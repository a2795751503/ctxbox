"""Claude Code adapter.

Format (verified against real sessions):
~/.claude/projects/<path-encoded-dir>/<sessionUuid>.jsonl

Line types:
  {"type":"user"|"assistant", "uuid":..., "parentUuid":..., "sessionId":...,
   "timestamp":..., "message":{"role":..., "content":[{"type":"text"|"tool_use"|"tool_result", ...}]}}
  {"type":"summary", "summary":..., "leafUuid":...}          -> session title
  {"type":"queue-operation", ...}                            -> non-conversational, skipped
Forks may rename line types — ALIASES below is the compatibility map.
"""

from __future__ import annotations

import json
import re
import uuid as uuidlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..model.schema import ContentPart, Role, Session, Turn
from ..normalize import read_jsonl_tolerant
from ..utils import as_dict, paths
from .base import BaseAdapter, register

# Community forks sometimes rename these; alias -> canonical
LINE_TYPE_ALIASES = {
    "user": "user",
    "human": "user",
    "assistant": "assistant",
    "ai": "assistant",
    "model": "assistant",
    "summary": "summary",
    "system": "system",
    "queue-operation": "meta",
    "file-history-snapshot": "meta",
    "progress": "meta",
    "hook": "meta",
}

SKIP_TYPES = {"meta"}
_ROLE_MAP = {"user": Role.USER, "assistant": Role.ASSISTANT, "system": Role.SYSTEM}


def _encode_project_dir(project_dir: str) -> str:
    """Claude encodes the cwd into a directory name (non-alphanumerics -> '-')."""
    return re.sub(r"[^A-Za-z0-9]", "-", project_dir)


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _content_to_parts(content: Any, raw: dict[str, Any]) -> list[ContentPart]:
    parts: list[ContentPart] = []
    if isinstance(content, str):
        return [ContentPart(kind="text", text=content, raw=raw)]
    if not isinstance(content, list):
        return [ContentPart(kind="raw", text=json.dumps(content, ensure_ascii=False), raw=raw)]
    for block in content:
        if not isinstance(block, dict):
            parts.append(ContentPart(kind="raw", text=str(block), raw=raw))
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append(ContentPart(kind="text", text=block.get("text", ""), raw=block))
        elif btype == "thinking":
            parts.append(ContentPart(kind="thinking", text=block.get("thinking", ""), raw=block))
        elif btype == "tool_use":
            parts.append(
                ContentPart(
                    kind="tool_call",
                    tool_name=block.get("name"),
                    tool_args=block.get("input") if isinstance(block.get("input"), dict) else None,
                    text=json.dumps(block.get("input"), ensure_ascii=False)
                    if block.get("input") is not None
                    else None,
                    raw=block,
                )
            )
        elif btype == "tool_result":
            inner = block.get("content")
            text = inner if isinstance(inner, str) else json.dumps(inner, ensure_ascii=False)
            parts.append(
                ContentPart(
                    kind="tool_result", tool_name=block.get("tool_use_id"), text=text, raw=block
                )
            )
        else:
            parts.append(
                ContentPart(kind="raw", text=json.dumps(block, ensure_ascii=False), raw=block)
            )
    return parts


@register
class ClaudeCodeAdapter(BaseAdapter):
    name = "claude-code"
    display_name = "Claude Code"

    def sessions_root(self) -> Path:
        return paths.dotdir(".claude") / "projects"

    def detect(self) -> list[Path]:
        root = self.sessions_root()
        if not root.is_dir():
            return []
        return sorted(root.glob("*/*.jsonl"))

    def parse(self, path: Path) -> Session:
        result = read_jsonl_tolerant(path)
        session_id = path.stem
        call_names: dict[str, str] = {}  # tool_use id -> 工具名
        turns: list[Turn] = []
        title = ""
        skipped = 0
        for line in result.lines:
            if line.data is None:
                turns.append(
                    Turn(
                        role=Role.UNKNOWN,
                        parts=[ContentPart(kind="raw", text=line.raw_text)],
                        meta={"unparseable": True, "lineno": line.lineno},
                    )
                )
                continue
            obj = line.data
            ltype = LINE_TYPE_ALIASES.get(str(obj.get("type", "")), "meta")
            if ltype in SKIP_TYPES:
                skipped += 1
                continue
            if ltype == "summary":
                title = str(obj.get("summary", "")) or title
                continue
            msg = as_dict(obj.get("message"))
            role = _ROLE_MAP.get(msg.get("role") or ltype, Role.UNKNOWN)
            usage = as_dict(msg.get("usage"))
            parts = _content_to_parts(msg.get("content"), obj)
            # tool_use id -> 工具名, 回填 tool_result 的名字 (不再显示 id/'?')
            for p in parts:
                if p.kind == "tool_call" and p.raw and p.raw.get("id") and p.tool_name:
                    call_names[str(p.raw["id"])] = str(p.tool_name)
                elif p.kind == "tool_result" and p.tool_name:
                    p.tool_name = call_names.get(p.tool_name, p.tool_name)
            turns.append(
                Turn(
                    id=str(obj.get("uuid", "")),
                    role=role,
                    parts=parts,
                    timestamp=_parse_ts(obj.get("timestamp")),
                    model=msg.get("model") if isinstance(msg.get("model"), str) else None,
                    tokens_in=usage.get("input_tokens"),
                    tokens_out=usage.get("output_tokens"),
                    parent_id=obj.get("parentUuid")
                    if isinstance(obj.get("parentUuid"), str)
                    else None,
                    meta={
                        "sessionId": obj.get("sessionId"),
                        "type": obj.get("type"),
                        "isSidechain": obj.get("isSidechain"),
                        "cwd": obj.get("cwd"),
                    },
                )
            )
        project = path.parent.name
        warnings = list(result.warnings)
        if skipped:
            warnings.append(f"{skipped} non-conversational meta lines skipped")
        return Session(
            id=session_id,
            source_tool=self.name,
            source_path=path,
            project_dir=project,
            title=title,
            turns=turns,
            created_at=turns[0].timestamp if turns else None,
            updated_at=turns[-1].timestamp if turns else None,
            parse_warnings=warnings,
            meta={"encoding": result.encoding},
        )

    # ---- write side ----

    def _turn_to_line(
        self, turn: Turn, session_id: str, parent_uuid: str | None, cwd: str | None
    ) -> dict[str, Any]:
        # preserve the turn's uuid when valid: turn ids stay stable across
        # save/re-parse round-trips (the GUI relies on this for turn actions)
        try:
            new_uuid = str(uuidlib.UUID(turn.id))
        except (ValueError, AttributeError):
            new_uuid = str(uuidlib.uuid4())
        ltype = "user" if turn.role in (Role.USER, Role.TOOL) else "assistant"
        content: list[dict[str, Any]] = []
        for p in turn.parts:
            # reuse original block only if it came from a CLAUDE parse;
            # cross-tool parts carry foreign blocks that must be converted
            if (
                p.raw
                and p.kind != "raw"
                and p.raw.get("type") in ("text", "thinking", "tool_use", "tool_result")
            ):
                content.append(p.raw)  # untouched part: round-trip original block
            elif p.kind == "text":
                content.append({"type": "text", "text": p.text or ""})
            elif p.kind == "thinking":
                content.append({"type": "thinking", "thinking": p.text or ""})
            elif p.kind == "tool_call":
                content.append(
                    {
                        "type": "tool_use",
                        "id": f"toolu_{uuidlib.uuid4().hex[:20]}",
                        "name": p.tool_name or "unknown",
                        "input": p.tool_args or {},
                    }
                )
            elif p.kind == "tool_result":
                content.append({"type": "tool_result", "content": p.text or ""})
            else:
                content.append({"type": "text", "text": p.text or ""})
        ts = (turn.timestamp or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")
        line: dict[str, Any] = {
            "parentUuid": parent_uuid,
            "isSidechain": False,
            "type": ltype,
            "uuid": new_uuid,
            "timestamp": ts,
            "sessionId": session_id,
            "message": {"role": "user" if ltype == "user" else "assistant", "content": content},
        }
        if cwd:
            line["cwd"] = cwd
        if turn.model and ltype == "assistant":
            line["message"]["model"] = turn.model
        return line

    def serialize(self, session: Session) -> bytes:
        lines: list[str] = []
        parent: str | None = None
        for turn in session.turns:
            if turn.meta.get("unparseable") and turn.parts:
                lines.append(turn.parts[0].text or "")  # keep broken lines verbatim
                continue
            line = self._turn_to_line(turn, session.id, parent, session.project_dir)
            parent = line["uuid"]
            lines.append(json.dumps(line, ensure_ascii=False))
        return ("\n".join(lines) + "\n").encode("utf-8")

    def inject(self, session: Session, target_dir: Path | None = None) -> Path:
        """Write as a brand-new session (fresh sessionId + uuid chain)."""
        new = session.model_copy(deep=True)
        new.id = str(uuidlib.uuid4())
        root = target_dir
        if root is None:
            proj = session.project_dir or "ctxbox-imported"
            root = self.sessions_root() / _encode_project_dir(proj)
        root.mkdir(parents=True, exist_ok=True)
        dest = root / f"{new.id}.jsonl"
        from ..utils import atomic_write

        atomic_write(dest, self.serialize(new))
        return dest

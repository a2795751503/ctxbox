"""Pi (pi.dev coding agent) adapter.

Format (verified against a live install, @earendil-works/pi-coding-agent):
~/.pi/agent/sessions/<slug(cwd)>/<ISO-ts>_<uuid>.jsonl

Line types:
  {"type":"session","version":3,"id":...,"timestamp":...,"cwd":...}   header
  {"type":"model_change","provider":...,"modelId":...,"parentId":...}
  {"type":"thinking_level_change",...}
  {"type":"message","id":...,"parentId":...,"timestamp":...,
   "message":{"role":"system"|"user"|"assistant"|"toolResult",
              "content": str | [{"type":"text"|"thinking"|"toolCall", ...}],
              "toolCallId"/"toolName" (toolResult),
              "provider"/"model"/"usage" (assistant)}}
  {"type":"context_edit","targetId":...,"replacement": null|{...}}
      post-hoc edits: replacement=null means the target message was deleted

Directory slug (verified): "--C--Users-105--" for C:\\Users\\105, i.e.
prepend "--", replace ":" with "--", path separators with "-", append "--".

Injection writes a brand-new session file; Pi's session browser picks it up.
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
from ..utils import as_dict, atomic_write, paths
from .base import BaseAdapter, register

_ROLE_MAP = {
    "user": Role.USER,
    "assistant": Role.ASSISTANT,
    "system": Role.SYSTEM,
    "toolResult": Role.TOOL,
}
_SKIP_TYPES = {"model_change", "thinking_level_change", "compaction", "label"}


def _slug(cwd: str) -> str:
    """Pi's session dir slug, verified on Windows installs:
    C:\\Users\\105 -> --C--Users-105--  (prepend/append '--', ':' and
    path separators become '-')."""
    s = re.sub(r"[:\\/]", "-", cwd)
    return "--" + s.strip("-") + "--"


def _ts(v: Any) -> datetime | None:
    if isinstance(v, str):
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    if isinstance(v, (int, float)) and v > 0:
        try:
            return datetime.fromtimestamp(v / 1000).astimezone()
        except (OSError, OverflowError):
            return None
    return None


def _iso(ts: datetime | None) -> str:
    return (ts or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z")


def _content_to_parts(content: Any, raw: dict[str, Any]) -> list[ContentPart]:
    if isinstance(content, str):
        return [ContentPart(kind="text", text=content, raw=raw)] if content else []
    parts: list[ContentPart] = []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        bt = b.get("type")
        if bt == "text":
            parts.append(ContentPart(kind="text", text=b.get("text", ""), raw=b))
        elif bt == "thinking":
            parts.append(ContentPart(kind="thinking", text=b.get("thinking", ""), raw=b))
        elif bt == "toolCall":
            parts.append(
                ContentPart(
                    kind="tool_call",
                    tool_name=b.get("name"),
                    tool_args=b.get("arguments") if isinstance(b.get("arguments"), dict) else None,
                    text=json.dumps(b.get("arguments"), ensure_ascii=False),
                    raw=b,
                )
            )
        else:
            parts.append(ContentPart(kind="raw", text=json.dumps(b, ensure_ascii=False), raw=b))
    return parts


@register
class PiAdapter(BaseAdapter):
    name = "pi"
    display_name = "Pi"

    def sessions_root(self) -> Path:
        return paths.dotdir(".pi") / "agent" / "sessions"

    def detect(self) -> list[Path]:
        root = self.sessions_root()
        if not root.is_dir():
            return []
        return sorted(root.glob("*/*.jsonl"))

    def parse(self, path: Path) -> Session:
        result = read_jsonl_tolerant(path)
        header: dict[str, Any] = {}
        model: str | None = None
        turns: list[Turn] = []
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
            otype = obj.get("type")
            if otype == "session":
                header = obj
                continue
            if otype == "model_change":
                model = obj.get("modelId") or model
                continue
            if otype == "context_edit":
                # replacement=None deletes the target message
                target = obj.get("targetId")
                if obj.get("replacement") is None and target:
                    turns = [t for t in turns if t.meta.get("pi_id") != target]
                skipped += 1
                continue
            if otype != "message":
                skipped += 1
                continue
            msg = as_dict(obj.get("message"))
            role = _ROLE_MAP.get(str(msg.get("role") or ""), Role.UNKNOWN)
            if role == Role.TOOL:
                parts = _content_to_parts(msg.get("content"), msg)
                for p in parts:
                    p.kind = "tool_result"
                    p.tool_name = msg.get("toolName")
            else:
                parts = _content_to_parts(msg.get("content"), msg)
            usage = as_dict(msg.get("usage"))
            turns.append(
                Turn(
                    role=role,
                    parts=parts,
                    timestamp=_ts(obj.get("timestamp")) or _ts(msg.get("timestamp")),
                    model=msg.get("model") if isinstance(msg.get("model"), str) else None,
                    tokens_in=usage.get("input"),
                    tokens_out=usage.get("output"),
                    parent_id=obj.get("parentId") if isinstance(obj.get("parentId"), str) else None,
                    meta={"raw": obj, "pi_id": obj.get("id"), "stopReason": msg.get("stopReason")},
                )
            )
        warnings = list(result.warnings)
        if skipped:
            warnings.append(f"{skipped} bookkeeping/edit records skipped")
        return Session(
            id=str(header.get("id") or path.stem.rsplit("_", 1)[-1]),
            source_tool=self.name,
            source_path=path,
            source_version=str(header.get("version", "")),
            project_dir=header.get("cwd"),
            turns=turns,
            created_at=_ts(header.get("timestamp")) or (turns[0].timestamp if turns else None),
            updated_at=turns[-1].timestamp if turns else None,
            parse_warnings=warnings,
            meta={"model": model, "encoding": result.encoding},
        )

    # ---- write side ----

    def _turn_to_lines(
        self, turn: Turn, parent_id: str | None, model: str | None
    ) -> list[dict[str, Any]]:
        lines: list[dict[str, Any]] = []
        ts = _iso(turn.timestamp)
        if turn.role == Role.TOOL or (turn.parts and turn.parts[0].kind == "tool_result"):
            lines.append(
                {
                    "type": "message",
                    "id": uuidlib.uuid4().hex[:8],
                    "parentId": parent_id,
                    "timestamp": ts,
                    "message": {
                        "role": "toolResult",
                        "toolCallId": f"call_{uuidlib.uuid4().hex}",
                        "toolName": turn.parts[0].tool_name if turn.parts else "tool",
                        "content": [{"type": "text", "text": turn.text()}],
                    },
                }
            )
            return lines
        if turn.role == Role.USER:
            role = "user"
            content: Any = [{"type": "text", "text": turn.text()}]
        elif turn.role == Role.SYSTEM:
            role = "system"
            content = turn.text()
        else:
            role = "assistant"
            content = []
            for p in turn.parts:
                if p.kind == "thinking":
                    content.append({"type": "thinking", "thinking": p.text or ""})
                elif p.kind == "tool_call":
                    content.append(
                        {
                            "type": "toolCall",
                            "id": f"call_{uuidlib.uuid4().hex}",
                            "name": p.tool_name or "tool",
                            "arguments": p.tool_args or {},
                        }
                    )
                else:
                    content.append({"type": "text", "text": p.text or ""})
        msg: dict[str, Any] = {"role": role, "content": content}
        if role == "assistant" and model:
            msg["model"] = model
        lines.append(
            {
                "type": "message",
                "id": uuidlib.uuid4().hex[:8],
                "parentId": parent_id,
                "timestamp": ts,
                "message": msg,
            }
        )
        return lines

    def serialize(self, session: Session) -> bytes:
        now = datetime.now(timezone.utc)
        model = session.meta.get("model")
        out: list[str] = [
            json.dumps(
                {
                    "type": "session",
                    "version": 3,
                    "id": session.id,
                    "timestamp": _iso(session.created_at or now),
                    "cwd": session.project_dir or str(Path.home()),
                },
                ensure_ascii=False,
            )
        ]
        parent: str | None = None
        if model:
            out.append(
                json.dumps(
                    {
                        "type": "model_change",
                        "id": uuidlib.uuid4().hex[:8],
                        "parentId": None,
                        "timestamp": _iso(session.created_at or now),
                        "provider": "ctxbox",
                        "modelId": model,
                    },
                    ensure_ascii=False,
                )
            )
            parent = json.loads(out[-1])["id"]
        for turn in session.turns:
            if turn.meta.get("unparseable") and turn.parts:
                out.append(turn.parts[0].text or "")
                continue
            raw = turn.meta.get("raw")
            # raw round-trip only for lines that came from a PI parse —
            # cross-tool sessions carry foreign raw payloads we must convert
            if raw and not turn.meta.get("_edited") and turn.meta.get("pi_id"):
                out.append(json.dumps(raw, ensure_ascii=False))
                parent = raw.get("id", parent)
                continue
            for line in self._turn_to_lines(turn, parent, model):
                parent = line["id"]
                out.append(json.dumps(line, ensure_ascii=False))
        return ("\n".join(out) + "\n").encode("utf-8")

    def inject(self, session: Session, target_dir: Path | None = None) -> Path:
        """Write as a brand-new Pi session file (fresh id)."""
        new = session.model_copy(deep=True)
        new.id = str(uuidlib.uuid4())
        cwd = session.project_dir or str(Path.home())
        root = target_dir or (self.sessions_root() / _slug(cwd))
        root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S-000Z")
        dest = root / f"{stamp}_{new.id}.jsonl"
        atomic_write(dest, self.serialize(new))
        return dest

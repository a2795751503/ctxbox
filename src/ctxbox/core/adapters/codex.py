"""Codex CLI / Codex Desktop adapter.

Format (verified against real sessions):
~/.codex/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl   (active)
~/.codex/archived_sessions/rollout-*.jsonl               (archived)

Line 0: {"timestamp":..., "type":"session_meta", "payload":{"session_id":..., "cwd":...,
         "cli_version":..., "forked_from_id":...|null, ...}}
Later : {"timestamp":..., "type":"response_item", "payload":{"type":"message",
         "role":"user"|"assistant", "content":[{"type":"input_text"|"output_text", ...}]}}
        {"type":"event_msg", ...} / turn_context / compaction records — kept as meta.
"""

from __future__ import annotations

import contextlib
import json
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
    "developer": Role.SYSTEM,
}

# payload types that carry conversation content
_MESSAGE_TYPES = {"message"}
_REASONING_TYPES = {"reasoning"}
_TOOL_CALL_TYPES = {"function_call", "local_shell_call", "custom_tool_call", "web_search_call"}
_TOOL_OUT_TYPES = {"function_call_output", "custom_tool_call_output"}


def _parse_ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _payload_to_turn(
    payload: dict[str, Any], ts: datetime | None, raw: dict[str, Any]
) -> Turn | None:
    ptype = payload.get("type")
    if ptype in _MESSAGE_TYPES:
        role = _ROLE_MAP.get(str(payload.get("role") or ""), Role.UNKNOWN)
        parts: list[ContentPart] = []
        for block in payload.get("content") or []:
            if isinstance(block, dict):
                parts.append(ContentPart(kind="text", text=block.get("text", ""), raw=block))
            else:
                parts.append(ContentPart(kind="text", text=str(block)))
        return Turn(role=role, parts=parts, timestamp=ts, meta={"payload_type": ptype, "raw": raw})
    if ptype in _REASONING_TYPES:
        summary = payload.get("summary") or []
        text = "\n".join(s.get("text", "") for s in summary if isinstance(s, dict))
        return Turn(
            role=Role.ASSISTANT,
            timestamp=ts,
            parts=[ContentPart(kind="thinking", text=text)],
            meta={"payload_type": ptype, "raw": raw},
        )
    if ptype in _TOOL_CALL_TYPES:
        name = payload.get("name") or ptype
        args_raw = payload.get("arguments") or payload.get("input")
        args = None
        if isinstance(args_raw, str):
            with contextlib.suppress(json.JSONDecodeError):
                args = json.loads(args_raw)
        elif isinstance(args_raw, dict):
            args = args_raw
        return Turn(
            role=Role.ASSISTANT,
            timestamp=ts,
            parts=[
                ContentPart(
                    kind="tool_call",
                    tool_name=name,
                    tool_args=args,
                    text=args_raw if isinstance(args_raw, str) else None,
                )
            ],
            meta={"payload_type": ptype, "raw": raw},
        )
    if ptype in _TOOL_OUT_TYPES:
        out = payload.get("output")
        return Turn(
            role=Role.TOOL,
            timestamp=ts,
            parts=[
                ContentPart(
                    kind="tool_result",
                    text=out if isinstance(out, str) else json.dumps(out, ensure_ascii=False),
                )
            ],
            meta={"payload_type": ptype, "raw": raw},
        )
    return None  # non-conversational payload


@register
class CodexAdapter(BaseAdapter):
    name = "codex"
    display_name = "Codex CLI / Desktop"

    def sessions_root(self) -> Path:
        return paths.dotdir(".codex") / "sessions"

    def detect(self) -> list[Path]:
        root = paths.dotdir(".codex")
        found: list[Path] = []
        for sub in (root / "sessions", root / "archived_sessions"):
            if sub.is_dir():
                found.extend(sub.rglob("rollout-*.jsonl"))
        return sorted(found)

    def parse(self, path: Path) -> Session:
        result = read_jsonl_tolerant(path)
        meta_payload: dict[str, Any] = {}
        call_names: dict[str, str] = {}  # call_id -> 工具名 (回填 output 块)
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
            ts = _parse_ts(obj.get("timestamp"))
            payload = as_dict(obj.get("payload"))
            if obj.get("type") == "session_meta":
                meta_payload = payload
                continue
            ptype = payload.get("type")
            if ptype in _TOOL_CALL_TYPES:
                cid, name = payload.get("call_id"), payload.get("name") or ptype
                if cid:
                    call_names[str(cid)] = str(name)
            turn = _payload_to_turn(payload, ts, obj)
            if turn is None:
                skipped += 1
                continue
            # function_call_output 回填真实工具名 (不再显示 '?')
            for p in turn.parts:
                if p.kind == "tool_result" and not p.tool_name:
                    p.tool_name = call_names.get(str(payload.get("call_id") or ""))
            turns.append(turn)
        session_id = str(meta_payload.get("session_id") or path.stem)
        warnings = list(result.warnings)
        if skipped:
            warnings.append(f"{skipped} non-message records skipped")
        return Session(
            id=session_id,
            source_tool=self.name,
            source_path=path,
            source_version=meta_payload.get("cli_version"),
            project_dir=meta_payload.get("cwd"),
            turns=turns,
            created_at=turns[0].timestamp if turns else None,
            updated_at=turns[-1].timestamp if turns else None,
            parse_warnings=warnings,
            meta={
                "session_meta": meta_payload,
                "encoding": result.encoding,
                "archived": "archived_sessions" in str(path),
            },
        )

    # ---- write side ----

    def serialize(self, session: Session) -> bytes:
        now = datetime.now(timezone.utc)
        meta = dict(session.meta.get("session_meta") or {})
        meta.update(
            {
                "session_id": session.id,
                "id": session.id,
                "timestamp": now.isoformat().replace("+00:00", "Z"),
                "cwd": session.project_dir or meta.get("cwd") or str(Path.home()),
                "originator": meta.get("originator") or "ctxbox",
                "cli_version": session.source_version or meta.get("cli_version") or "unknown",
                "source": meta.get("source") or "cli",
            }
        )
        lines = [
            json.dumps(
                {"timestamp": meta["timestamp"], "type": "session_meta", "payload": meta},
                ensure_ascii=False,
            )
        ]
        for turn in session.turns:
            if turn.meta.get("unparseable") and turn.parts:
                lines.append(turn.parts[0].text or "")
                continue
            ts = (turn.timestamp or now).isoformat().replace("+00:00", "Z")
            raw = turn.meta.get("raw")
            ptype = turn.meta.get("payload_type")
            if raw and ptype and not turn.meta.get("_edited"):
                lines.append(json.dumps(raw, ensure_ascii=False))
                continue
            if ptype in _TOOL_CALL_TYPES or (turn.parts and turn.parts[0].kind == "tool_call"):
                p = turn.parts[0]
                payload: dict[str, Any] = {
                    "type": "function_call",
                    "name": p.tool_name or "unknown",
                    "arguments": p.text or json.dumps(p.tool_args or {}, ensure_ascii=False),
                    "call_id": f"call_{uuidlib.uuid4().hex[:16]}",
                }
            elif ptype in _TOOL_OUT_TYPES or (turn.parts and turn.parts[0].kind == "tool_result"):
                payload = {
                    "type": "function_call_output",
                    "call_id": f"call_{uuidlib.uuid4().hex[:16]}",
                    "output": turn.text(),
                }
            elif ptype in _REASONING_TYPES or (turn.parts and turn.parts[0].kind == "thinking"):
                payload = {
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": turn.text()}],
                }
            else:
                role = (
                    "user"
                    if turn.role == Role.USER
                    else ("assistant" if turn.role == Role.ASSISTANT else "user")
                )
                block_type = "input_text" if role == "user" else "output_text"
                payload = {
                    "type": "message",
                    "role": role,
                    "content": [{"type": block_type, "text": turn.text()}],
                }
            lines.append(
                json.dumps(
                    {"timestamp": ts, "type": "response_item", "payload": payload},
                    ensure_ascii=False,
                )
            )
        return ("\n".join(lines) + "\n").encode("utf-8")

    def inject(self, session: Session, target_dir: Path | None = None) -> Path:
        """Write as a brand-new rollout file with a fresh session id."""
        new = session.model_copy(deep=True)
        new.id = str(uuidlib.uuid4())
        now = datetime.now(timezone.utc)
        root = target_dir or (self.sessions_root() / f"{now:%Y}" / f"{now:%m}" / f"{now:%d}")
        root.mkdir(parents=True, exist_ok=True)
        fname = f"rollout-{now:%Y-%m-%dT%H-%M-%S}-{new.id}.jsonl"
        dest = root / fname
        atomic_write(dest, self.serialize(new))
        return dest

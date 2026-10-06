"""Gemini CLI adapter.

Format: ~/.gemini/tmp/<project_hash>/chats/session-*.json
File is either a JSON array of message objects, or an object with a
`history` array (checkpoint format). Message shape (drifts across versions):
  {"id":..., "type":"user"|"gemini"|"info"|"error"|"warning",
   "content": "..." | [{"text": "..."}],
   "functionCalls": [...], "functionResponse": ..., "timestamp": ...}
Unknown shapes degrade to raw parts — nothing is dropped.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..model.schema import ContentPart, Role, Session, Turn
from ..normalize import decode_tolerant
from ..utils import paths
from .base import BaseAdapter, register

_TYPE_ROLE = {
    "user": Role.USER,
    "human": Role.USER,
    "gemini": Role.ASSISTANT,
    "model": Role.ASSISTANT,
    "assistant": Role.ASSISTANT,
    "info": Role.SYSTEM,
    "warning": Role.SYSTEM,
    "error": Role.SYSTEM,
}


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


def _content(content: Any, raw: dict[str, Any]) -> list[ContentPart]:
    if isinstance(content, str):
        return [ContentPart(kind="text", text=content, raw=raw)]
    parts: list[ContentPart] = []
    for b in content or []:
        if isinstance(b, dict) and b.get("text"):
            parts.append(ContentPart(kind="text", text=b["text"], raw=b))
        elif isinstance(b, dict) and b.get("functionCall"):
            fc = b["functionCall"]
            parts.append(
                ContentPart(
                    kind="tool_call", tool_name=fc.get("name"), tool_args=fc.get("args"), raw=b
                )
            )
        elif isinstance(b, dict) and b.get("functionResponse"):
            fr = b["functionResponse"]
            parts.append(
                ContentPart(
                    kind="tool_result",
                    tool_name=fr.get("name"),
                    text=json.dumps(fr.get("response"), ensure_ascii=False),
                    raw=b,
                )
            )
        else:
            parts.append(ContentPart(kind="raw", text=json.dumps(b, ensure_ascii=False), raw=b))
    return parts or [ContentPart(kind="raw", text=json.dumps(content, ensure_ascii=False), raw=raw)]


@register
class GeminiCliAdapter(BaseAdapter):
    name = "gemini-cli"
    display_name = "Gemini CLI"

    def detect(self) -> list[Path]:
        root = paths.dotdir(".gemini") / "tmp"
        if not root.is_dir():
            return []
        return sorted(root.glob("*/chats/session-*.json"))

    def parse(self, path: Path) -> Session:
        text, enc, warnings = decode_tolerant(path.read_bytes())
        data = json.loads(text)
        if isinstance(data, dict):
            messages = data.get("history") or data.get("messages") or []
        elif isinstance(data, list):
            messages = data
        else:
            messages = []
        turns: list[Turn] = []
        for m in messages:
            if not isinstance(m, dict):
                continue
            role = _TYPE_ROLE.get(str(m.get("type", "")).lower(), Role.UNKNOWN)
            parts = _content(m.get("content"), m)
            if m.get("functionCalls"):
                for fc in m["functionCalls"] or []:
                    parts.append(
                        ContentPart(
                            kind="tool_call",
                            tool_name=fc.get("name"),
                            tool_args=fc.get("args"),
                            raw=fc,
                        )
                    )
            turns.append(
                Turn(
                    role=role,
                    parts=parts,
                    timestamp=_ts(m.get("timestamp") or m.get("time")),
                    model=m.get("model") if isinstance(m.get("model"), str) else None,
                    meta={"raw": m},
                )
            )
        return Session(
            id=path.stem,
            source_tool=self.name,
            source_path=path,
            project_dir=path.parent.parent.name,
            turns=turns,
            created_at=turns[0].timestamp if turns else None,
            updated_at=turns[-1].timestamp if turns else None,
            parse_warnings=warnings,
            meta={"encoding": enc},
        )

    def serialize(self, session: Session) -> bytes:
        out = []
        for t in session.turns:
            raw = t.meta.get("raw")
            if raw and not t.meta.get("_edited"):
                out.append(raw)
                continue
            out.append(
                {
                    "type": "user" if t.role == Role.USER else "gemini",
                    "content": t.text(),
                    "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                }
            )
        return json.dumps(out, ensure_ascii=False, indent=2).encode("utf-8")

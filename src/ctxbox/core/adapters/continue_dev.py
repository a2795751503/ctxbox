"""Continue.dev adapter.

Format: ~/.continue/sessions/<uuid>.json — a single JSON object with a
`history` array of { "message": {"role":..., "content": ...}, ... } entries
(format has drifted across versions; we accept both `message` wrappers and
bare {role, content} entries).
"""

from __future__ import annotations

import json
import uuid as uuidlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..model.schema import ContentPart, Role, Session, Turn
from ..normalize import decode_tolerant
from ..utils import atomic_write, paths
from .base import BaseAdapter, register

_ROLE_MAP = {
    "user": Role.USER,
    "assistant": Role.ASSISTANT,
    "system": Role.SYSTEM,
    "tool": Role.TOOL,
}


def _entry_to_turn(entry: dict[str, Any]) -> Turn:
    raw_msg = entry.get("message")
    msg: dict[str, Any] = raw_msg if isinstance(raw_msg, dict) else entry
    role = _ROLE_MAP.get(str(msg.get("role") or ""), Role.UNKNOWN)
    content = msg.get("content")
    if isinstance(content, str):
        parts = [ContentPart(kind="text", text=content, raw=entry)]
    elif isinstance(content, list):
        parts = [
            ContentPart(
                kind="text",
                text=b.get("text", "") if isinstance(b, dict) else str(b),
                raw=b if isinstance(b, dict) else None,
            )
            for b in content
        ]
    else:
        parts = [ContentPart(kind="raw", text=json.dumps(content, ensure_ascii=False), raw=entry)]
    return Turn(role=role, parts=parts, meta={"raw": entry})


@register
class ContinueDevAdapter(BaseAdapter):
    name = "continue"
    display_name = "Continue.dev"

    def sessions_root(self) -> Path:
        return paths.dotdir(".continue") / "sessions"

    def detect(self) -> list[Path]:
        root = self.sessions_root()
        if not root.is_dir():
            return []
        # sessions.json is continue.dev's own registry file, not a session
        return sorted(p for p in root.glob("*.json") if p.name != "sessions.json")

    def parse(self, path: Path) -> Session:
        text, enc, warnings = decode_tolerant(path.read_bytes())
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"{path}: unexpected continue.dev session shape")
        history = data.get("history") or []
        turns = [_entry_to_turn(e) for e in history if isinstance(e, dict)]
        return Session(
            id=str(data.get("session_id") or path.stem),
            source_tool=self.name,
            source_path=path,
            title=str(data.get("title") or ""),
            turns=turns,
            parse_warnings=warnings,
            meta={"encoding": enc, "raw_root_keys": sorted(data.keys())},
        )

    def serialize(self, session: Session) -> bytes:
        history = []
        for t in session.turns:
            raw = t.meta.get("raw")
            if raw and not t.meta.get("_edited"):
                history.append(raw)
                continue
            role = (
                "user"
                if t.role == Role.USER
                else ("assistant" if t.role == Role.ASSISTANT else "system")
            )
            history.append({"message": {"role": role, "content": t.text()}})
        payload = {
            "session_id": session.id,
            "title": session.title,
            "date_created": datetime.now(timezone.utc).isoformat(),
            "history": history,
        }
        return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")

    def inject(self, session: Session, target_dir: Path | None = None) -> Path:
        new = session.model_copy(deep=True)
        new.id = str(uuidlib.uuid4())
        root = target_dir or self.sessions_root()
        root.mkdir(parents=True, exist_ok=True)
        dest = root / f"{new.id}.json"
        atomic_write(dest, self.serialize(new))
        return dest

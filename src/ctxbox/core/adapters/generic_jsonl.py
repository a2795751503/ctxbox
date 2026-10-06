"""Generic JSONL fallback adapter.

Reads ANY jsonl session file (Kimi Code, OpenCode, hand-rolled tools, forks we
don't know yet). Heuristic role detection: look for common keys
(role/type/event) and common role spellings. What we can't classify becomes a
raw turn — visible, searchable, never lost.
"""

from __future__ import annotations

import json
import uuid as uuidlib
from pathlib import Path

from ..model.schema import ContentPart, Role, Session, Turn
from ..normalize import read_jsonl_tolerant
from ..utils import atomic_write, paths
from .base import BaseAdapter, register

_ROLE_KEYS = ("role", "speaker", "author")
_TYPE_KEYS = ("type", "event", "kind")
_USER_HINTS = {"user", "human", "input", "prompt"}
_ASSISTANT_HINTS = {"assistant", "ai", "model", "output", "completion", "response"}
_SYSTEM_HINTS = {"system", "developer"}
_TOOL_HINTS = {"tool", "tool_result", "function", "observation"}
_TEXT_KEYS = ("text", "content", "message", "prompt", "output")


def _detect_role(obj: dict) -> Role | None:
    values: list[str] = []
    for k in _ROLE_KEYS + _TYPE_KEYS:
        v = obj.get(k)
        if isinstance(v, str):
            values.append(v.lower())
    nested = obj.get("message")
    if isinstance(nested, dict) and isinstance(nested.get("role"), str):
        values.append(nested["role"].lower())
    for v in values:
        if v in _USER_HINTS:
            return Role.USER
        if v in _ASSISTANT_HINTS:
            return Role.ASSISTANT
        if v in _SYSTEM_HINTS:
            return Role.SYSTEM
        if v in _TOOL_HINTS:
            return Role.TOOL
    return None


def _extract_text(obj: dict) -> str:
    for k in _TEXT_KEYS:
        v = obj.get(k)
        if isinstance(v, str):
            return v
        if isinstance(v, dict) and isinstance(v.get("content"), str):
            return v["content"]
        if isinstance(v, list):
            texts = [b.get("text", "") for b in v if isinstance(b, dict) and b.get("text")]
            if texts:
                return "\n".join(texts)
    return json.dumps(obj, ensure_ascii=False)


@register
class GenericJsonlAdapter(BaseAdapter):
    name = "generic-jsonl"
    display_name = "Generic JSONL (fallback)"

    def detect(self) -> list[Path]:
        return []  # fallback: users point at files manually via CLI/import

    def can_handle(self, path: Path) -> bool:
        return path.suffix.lower() in (".jsonl", ".ndjson")

    def parse_file(self, path: Path, source_tool: str = "generic-jsonl") -> Session:
        return self.parse(path)

    def parse(self, path: Path) -> Session:
        result = read_jsonl_tolerant(path)
        turns: list[Turn] = []
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
            role = _detect_role(line.data) or Role.UNKNOWN
            turns.append(
                Turn(
                    role=role,
                    parts=[ContentPart(kind="text", text=_extract_text(line.data), raw=line.data)],
                    meta={"raw": line.data, "lineno": line.lineno},
                )
            )
        return Session(
            id=path.stem or str(uuidlib.uuid4()),
            source_tool=self.name,
            source_path=path,
            turns=turns,
            parse_warnings=result.warnings,
            meta={"encoding": result.encoding},
        )

    def serialize(self, session: Session) -> bytes:
        lines = []
        for t in session.turns:
            raw = t.meta.get("raw")
            if raw and not t.meta.get("_edited"):
                lines.append(json.dumps(raw, ensure_ascii=False))
            elif t.meta.get("unparseable") and t.parts:
                lines.append(t.parts[0].text or "")
            else:
                role = t.role.value
                lines.append(json.dumps({"role": role, "content": t.text()}, ensure_ascii=False))
        return ("\n".join(lines) + "\n").encode("utf-8")

    def inject(self, session: Session, target_dir: Path | None = None) -> Path:
        root = target_dir or (paths.ctxbox_data_dir() / "exports")
        root.mkdir(parents=True, exist_ok=True)
        dest = root / f"{session.title[:32] or session.id}.jsonl"
        atomic_write(dest, self.serialize(session))
        return dest

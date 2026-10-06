"""Aider adapter.

Format: .aider.chat.history.md (markdown, usually in the project dir or home).
Structure:
  # aider chat started at 2026-07-01 10:00:00
  > user message line 1
  > user message line 2
  assistant reply (plain lines)
  #### /command output
Blocks are separated by "# aider chat started" headers. Lines beginning with
"> " are user input; everything else is assistant output. Injection = append
is unsafe (aider treats the file as its own log), so this adapter is
read/export only.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..model.schema import ContentPart, Role, Session, Turn
from ..normalize import decode_tolerant
from ..utils import paths
from .base import BaseAdapter, register

_HEADER_RE = re.compile(r"^# aider chat", re.IGNORECASE)


@register
class AiderAdapter(BaseAdapter):
    name = "aider"
    display_name = "Aider"

    def detect(self) -> list[Path]:
        candidates = [paths.home() / ".aider.chat.history.md"]
        return [p for p in candidates if p.is_file()]

    def parse(self, path: Path) -> Session:
        text, enc, warnings = decode_tolerant(path.read_bytes())
        turns: list[Turn] = []
        buf_role: Role | None = None
        buf: list[str] = []

        def flush() -> None:
            nonlocal buf, buf_role
            if buf_role is not None and buf:
                turns.append(
                    Turn(
                        role=buf_role, parts=[ContentPart(kind="text", text="\n".join(buf).strip())]
                    )
                )
            buf, buf_role = [], None

        for line in text.splitlines():
            if _HEADER_RE.match(line):
                flush()
                continue
            if line.startswith(">"):
                if buf_role not in (None, Role.USER):
                    flush()
                buf_role = Role.USER
                buf.append(line.lstrip("> ").rstrip())
            elif not line.strip():
                flush()
            else:
                if buf_role not in (None, Role.ASSISTANT):
                    flush()
                buf_role = Role.ASSISTANT
                buf.append(line.rstrip())
        flush()
        return Session(
            id=path.stem.replace(".", "_"),
            source_tool=self.name,
            source_path=path,
            turns=turns,
            parse_warnings=warnings,
            meta={"encoding": enc},
        )

    def serialize(self, session: Session) -> bytes:
        lines: list[str] = []
        for t in session.turns:
            if t.role == Role.USER:
                lines.extend(f"> {ln}" for ln in t.text().splitlines())
            else:
                lines.append(t.text())
            lines.append("")
        return "\n".join(lines).encode("utf-8")

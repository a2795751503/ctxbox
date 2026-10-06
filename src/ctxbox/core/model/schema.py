"""Unified conversation model.

Every AI tool's session file is normalized into:
    Session -> Turn (role = user input / assistant output / system / tool)
             -> ContentPart (text, code, tool_call, tool_result, ...)

Design rules:
- Never lose data: unknown fields go to meta, unparseable content becomes
  ContentPart(kind="raw") with the original payload preserved.
- Lossless round-trip: ContentPart.raw / Turn.meta keep the original record
  so serialize() can write back untouched what the user didn't edit.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Role(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"
    UNKNOWN = "unknown"


PartKind = Literal[
    "text",
    "code",
    "thinking",
    "tool_call",
    "tool_result",
    "image",
    "file_ref",
    "diff",
    "error",
    "raw",
]


class ContentPart(BaseModel):
    """One piece of a turn's content."""

    model_config = ConfigDict(extra="allow")

    kind: PartKind = "text"
    text: str | None = None
    language: str | None = None  # for code parts
    tool_name: str | None = None  # for tool_call / tool_result
    tool_args: dict[str, Any] | None = None
    raw: dict[str, Any] | None = None  # original record, for lossless round-trip

    def display_text(self) -> str:
        if self.kind == "tool_call":
            return f"[tool_call: {self.tool_name}] {self.text or ''}"
        if self.kind == "tool_result":
            return f"[tool_result: {self.tool_name}] {self.text or ''}"
        return self.text or ""


class Turn(BaseModel):
    """One turn of the conversation: a single input or output message."""

    model_config = ConfigDict(extra="allow")

    id: str = ""
    role: Role = Role.UNKNOWN
    parts: list[ContentPart] = Field(default_factory=list)
    timestamp: datetime | None = None
    model: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    parent_id: str | None = None
    meta: dict[str, Any] = Field(default_factory=dict)

    def text(self) -> str:
        return "\n".join(p.display_text() for p in self.parts if p.display_text())

    @staticmethod
    def make_id(session_id: str, ordinal: int) -> str:
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"ctxbox://{session_id}/{ordinal}"))


class Session(BaseModel):
    """A full conversation, normalized from one tool's native file."""

    model_config = ConfigDict(extra="allow")

    id: str
    source_tool: str
    source_path: Path | None = None
    source_version: str | None = None
    project_dir: str | None = None
    title: str = ""
    turns: list[Turn] = Field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None
    parse_warnings: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def model_post_init(self, __context: Any, /) -> None:
        if not self.title:
            for t in self.turns:
                if t.role == Role.USER and t.text().strip():
                    self.title = t.text().strip().splitlines()[0][:60]
                    break
        for i, t in enumerate(self.turns):
            if not t.id:
                t.id = Turn.make_id(self.id, i)

    # ---- CRUD helpers (GUI/CLI operate through these) ----
    def get_turn(self, turn_id: str) -> Turn | None:
        return next((t for t in self.turns if t.id == turn_id), None)

    def insert_turn(self, turn: Turn, index: int | None = None) -> Turn:
        if not turn.id:
            turn.id = str(uuid.uuid4())
        if index is None:
            self.turns.append(turn)
        else:
            self.turns.insert(index, turn)
        return turn

    def delete_turn(self, turn_id: str) -> bool:
        before = len(self.turns)
        self.turns = [t for t in self.turns if t.id != turn_id]
        return len(self.turns) != before

    def clone_turn(self, turn_id: str) -> Turn | None:
        src = self.get_turn(turn_id)
        if src is None:
            return None
        dup = src.model_copy(deep=True)
        dup.id = str(uuid.uuid4())
        idx = self.turns.index(src)
        self.turns.insert(idx + 1, dup)
        return dup

    def move_turn(self, turn_id: str, new_index: int) -> bool:
        src = self.get_turn(turn_id)
        if src is None:
            return False
        self.turns.remove(src)
        self.turns.insert(max(0, min(new_index, len(self.turns))), src)
        return True

    def merge_turns(self, first_id: str, second_id: str) -> bool:
        a, b = self.get_turn(first_id), self.get_turn(second_id)
        if a is None or b is None or a.role != b.role:
            return False
        a.parts.extend(b.parts)
        self.turns.remove(b)
        return True

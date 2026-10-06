"""OpenCode adapter.

Current OpenCode (>=1.2) stores ALL sessions in one SQLite database:
    ~/.local/share/opencode/opencode.db        (macOS/Linux)
    %USERPROFILE%\\.local\\share\\opencode\\opencode.db  (Windows)

Tables (schema per opencode source + community docs):
  session(id, project_id, parent_id, directory, title, version, agent, model,
          tokens_*, time_created, time_updated, time_archived, ...)
  message(id, session_id, time_created, data)   -- data: JSON {role, tokens, time, modelID}
  part(id, message_id, session_id, time_created, data)
      -- data: JSON discriminated by type:
         {"type":"text","text":...} / {"type":"reasoning","text":...}
         {"type":"tool","tool":...,"state":{"status","input","output","title"}}

We open the DB READ-ONLY (mode=ro) — opencode owns the live WAL file.
One DB -> many sessions, so this adapter overrides iter_sessions().
Injection is not supported (would require writing into opencode's live DB).
Legacy pre-SQLite `storage/` JSON files are not parsed (documented, not built).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

from ..model.schema import ContentPart, Role, Session, Turn
from ..utils import as_dict, paths
from .base import BaseAdapter, register


def _ts(ms: Any) -> datetime | None:
    if isinstance(ms, (int, float)) and ms > 0:
        try:
            return datetime.fromtimestamp(ms / 1000).astimezone()
        except (OSError, OverflowError):
            return None
    return None


def _j(raw: Any) -> dict[str, Any]:
    if isinstance(raw, str):
        try:
            obj = json.loads(raw)
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}
    return raw if isinstance(raw, dict) else {}


def _part_to_turn(data: dict[str, Any], ts: datetime | None) -> Turn | None:
    ptype = data.get("type")
    if ptype == "text":
        return Turn(
            role=Role.ASSISTANT,
            timestamp=ts,
            parts=[ContentPart(kind="text", text=data.get("text", ""))],
            meta={"raw": data},
        )
    if ptype == "reasoning":
        return Turn(
            role=Role.ASSISTANT,
            timestamp=ts,
            parts=[ContentPart(kind="thinking", text=data.get("text", ""))],
            meta={"raw": data},
        )
    if ptype == "tool":
        state = data.get("state") or {}
        out = state.get("output")
        return Turn(
            role=Role.TOOL,
            timestamp=ts,
            parts=[
                ContentPart(
                    kind="tool_result",
                    tool_name=data.get("tool"),
                    text=out if isinstance(out, str) else json.dumps(out, ensure_ascii=False),
                )
            ],
            meta={
                "raw": data,
                "tool_input": state.get("input"),
                "tool_status": state.get("status"),
            },
        )
    return None  # step-start / step-finish / patch etc: skip


@register
class OpenCodeAdapter(BaseAdapter):
    name = "opencode"
    display_name = "OpenCode"

    def db_path(self) -> Path:
        return paths.home() / ".local" / "share" / "opencode" / "opencode.db"

    def detect(self) -> list[Path]:
        db = self.db_path()
        return [db] if db.is_file() else []

    # -- one DB holds many sessions --
    def iter_sessions(self, path: Path) -> Iterator[Session]:
        uri = f"file:{path.as_posix()}?mode=ro"
        conn = sqlite3.connect(uri, uri=True)
        conn.row_factory = sqlite3.Row
        try:
            sessions = conn.execute("SELECT * FROM session ORDER BY time_updated DESC").fetchall()
            for srow in sessions:
                yield self._build_session(conn, srow, path)
        finally:
            conn.close()

    def _build_session(self, conn: sqlite3.Connection, srow: sqlite3.Row, db_path: Path) -> Session:
        sid = srow["id"]
        turns: list[Turn] = []
        msgs = conn.execute(
            "SELECT id, time_created, data FROM message WHERE session_id=? "
            "ORDER BY time_created ASC",
            (sid,),
        ).fetchall()
        parts_by_msg: dict[str, list[sqlite3.Row]] = {}
        for prow in conn.execute(
            "SELECT message_id, time_created, data FROM part WHERE session_id=? "
            "ORDER BY time_created ASC",
            (sid,),
        ).fetchall():
            parts_by_msg.setdefault(prow["message_id"], []).append(prow)
        for mrow in msgs:
            mdata = _j(mrow["data"])
            role = Role.USER if mdata.get("role") == "user" else Role.ASSISTANT
            mts = _ts(mrow["time_created"]) or _ts((mdata.get("time") or {}).get("created"))
            tokens = as_dict(mdata.get("tokens"))
            # user text lives in parts; assistant text/reasoning/tool too
            msg_parts: list[ContentPart] = []
            for prow in parts_by_msg.get(mrow["id"], []):
                pdata = _j(prow["data"])
                ptype = pdata.get("type")
                ts = _ts(prow["time_created"]) or mts
                if role == Role.USER and ptype == "text":
                    msg_parts.append(
                        ContentPart(kind="text", text=pdata.get("text", ""), raw=pdata)
                    )
                    continue
                turn = _part_to_turn(pdata, ts)
                if turn is not None:
                    turn.role = role if ptype in ("text", "reasoning") else turn.role
                    turn.tokens_in = tokens.get("input")
                    turn.tokens_out = tokens.get("output")
                    turn.model = mdata.get("modelID")
                    turns.append(turn)
            if role == Role.USER and msg_parts:
                turns.append(
                    Turn(role=Role.USER, timestamp=mts, parts=msg_parts, meta={"raw": mdata})
                )
        cols = set(srow.keys())  # sqlite3.Row: membership test needs the key set
        model_json = _j(srow["model"]) if "model" in cols else {}
        return Session(
            id=sid,
            source_tool=self.name,
            source_path=db_path,
            source_version=srow["version"] if "version" in cols else None,
            project_dir=srow["directory"] if "directory" in cols else None,
            title=srow["title"] or "",
            turns=turns,
            created_at=_ts(srow["time_created"]),
            updated_at=_ts(srow["time_updated"]),
            meta={
                "parent_id": srow["parent_id"] if "parent_id" in cols else None,
                "agent": srow["agent"] if "agent" in cols else None,
                "model": model_json.get("id"),
            },
        )

    def parse(self, path: Path) -> Session:
        """Contract method: returns the most recent session. Use
        iter_sessions() for the full list."""
        for session in self.iter_sessions(path):
            return session
        raise ValueError(f"no sessions found in {path}")

    def serialize(self, session: Session) -> bytes:
        # portable JSON export; writing into opencode's live DB is unsupported
        return session.model_dump_json(indent=2).encode("utf-8")

"""SQLite index + FTS5 full-text search over all discovered sessions.

Original session files are never moved or modified by the index — we store
parse metadata plus a mtime fingerprint, and re-parse incrementally when the
source file changes.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..adapters.base import all_adapters, get_adapter
from ..model.schema import Session
from ..utils import ctxbox_data_dir, make_backup

_CJK = re.compile(r"[一-鿿぀-ヿ가-힯]+")


def _cjk_bigrams(text: str) -> str:
    """FTS5's unicode61 treats a whole CJK run as ONE token, so searching
    '补天' never matches '补天白帽'. Fix: index/search overlapping bigrams."""
    grams: list[str] = []
    for m in _CJK.finditer(text):
        run = m.group(0)
        if len(run) == 1:
            grams.append(run)
        else:
            grams.extend(run[i : i + 2] for i in range(len(run) - 1))
    return text + " " + " ".join(grams) if grams else text


_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT NOT NULL,               -- tool-native session id (may repeat across snapshots)
    source_tool TEXT NOT NULL,
    title TEXT,
    project_dir TEXT,
    source_path TEXT NOT NULL,
    source_mtime REAL,
    turn_count INTEGER,
    created_at TEXT,
    updated_at TEXT,
    warnings TEXT,
    PRIMARY KEY (source_tool, source_path)   -- one row per FILE; ids can repeat
);
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    session_key UNINDEXED, role, text, tokenize='unicode61'
);
"""


class SessionIndex:
    def __init__(self, db_path: Path | None = None) -> None:
        db_path = db_path or (ctxbox_data_dir() / "index.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(db_path))
        self.db.row_factory = sqlite3.Row
        self.db.executescript(_SCHEMA)
        self.db.execute("PRAGMA journal_mode=WAL")

    def close(self) -> None:
        self.db.close()

    # ---- scanning ----

    def rescan(self, progress_cb: Callable[[str, int, int], None] | None = None) -> int:
        """Discover and (re)parse sessions from every adapter. Returns count."""
        total = 0
        adapters = all_adapters()
        files: list[tuple[str, Path]] = []
        for ad in adapters:
            for p in ad.detect():
                files.append((ad.name, p))
        for i, (tool, path) in enumerate(files, start=1):
            if progress_cb:
                progress_cb(f"{tool}: {path.name}", i, len(files))
            try:
                self._upsert_file(tool, path)
                total += 1
            except Exception as exc:  # a broken file must never kill the scan
                self._record_error(tool, path, str(exc))
        self.db.commit()
        return total

    def _upsert_file(self, tool: str, path: Path) -> None:
        mtime = path.stat().st_mtime
        row = self.db.execute(
            "SELECT source_mtime FROM sessions WHERE source_tool=? AND source_path=?",
            (tool, str(path)),
        ).fetchone()
        if row and row["source_mtime"] == mtime:
            return  # unchanged; incremental scan
        session = get_adapter(tool).parse(path)
        self.upsert_session(session)

    def upsert_session(self, session: Session) -> None:
        # FTS key is per-FILE (ids repeat across snapshots of one conversation)
        key = f"{session.source_tool}::{session.source_path}"
        self.db.execute(
            """INSERT OR REPLACE INTO sessions
               (id, source_tool, title, project_dir, source_path, source_mtime,
                turn_count, created_at, updated_at, warnings)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                session.id,
                session.source_tool,
                session.title,
                session.project_dir,
                str(session.source_path) if session.source_path else "",
                session.source_path.stat().st_mtime
                if session.source_path and session.source_path.exists()
                else 0,
                len(session.turns),
                session.created_at.isoformat() if session.created_at else None,
                session.updated_at.isoformat() if session.updated_at else None,
                "\n".join(session.parse_warnings),
            ),
        )
        self.db.execute("DELETE FROM turns_fts WHERE session_key=?", (key,))
        self.db.executemany(
            "INSERT INTO turns_fts (session_key, role, text) VALUES (?,?,?)",
            [
                (key, t.role.value, _cjk_bigrams(t.text()))
                for t in session.turns
                if t.text().strip()
            ],
        )

    def _record_error(self, tool: str, path: Path, error: str) -> None:
        self.db.execute(
            """INSERT OR REPLACE INTO sessions
               (id, source_tool, title, source_path, source_mtime, turn_count, warnings)
               VALUES (?,?,?,?,?,?,?)""",
            (
                path.stem,
                tool,
                f"[parse error] {path.name}",
                str(path),
                path.stat().st_mtime if path.exists() else 0,
                0,
                error,
            ),
        )

    # ---- queries ----

    def sessions(self, tool: str | None = None, dedupe: bool = True) -> list[dict[str, Any]]:
        """List sessions. dedupe=True collapses per-id snapshots to the newest file."""
        if dedupe:
            sql = """SELECT s.* FROM sessions s
                     JOIN (SELECT source_tool, id, MAX(source_mtime) AS m
                           FROM sessions GROUP BY source_tool, id) g
                     ON s.source_tool=g.source_tool AND s.id=g.id AND s.source_mtime=g.m"""
        else:
            sql = "SELECT * FROM sessions"
        params: list[Any] = []
        if tool:
            sql += " WHERE s.source_tool=?" if dedupe else " WHERE source_tool=?"
            params.append(tool)
        sql += " ORDER BY updated_at DESC"
        rows = self.db.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def tools_summary(self) -> list[tuple[str, int]]:
        rows = self.db.execute(
            "SELECT source_tool, COUNT(*) c FROM sessions GROUP BY source_tool ORDER BY c DESC"
        ).fetchall()
        return [(r["source_tool"], r["c"]) for r in rows]

    def load_session(self, session_id: str, tool: str | None = None) -> Session:
        """Re-parse the source file for a full-fidelity Session.
        When several snapshots share one session id, the newest file wins."""
        if tool:
            row = self.db.execute(
                """SELECT * FROM sessions WHERE id=? AND source_tool=?
                   ORDER BY source_mtime DESC LIMIT 1""",
                (session_id, tool),
            ).fetchone()
        else:
            row = self.db.execute(
                """SELECT * FROM sessions WHERE id=?
                   ORDER BY source_mtime DESC LIMIT 1""",
                (session_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"session not found in index: {session_id}")
        path = Path(row["source_path"])
        return get_adapter(row["source_tool"]).parse(path)

    def search(self, query: str, limit: int = 50) -> list[dict[str, Any]]:
        """FTS5 full-text search. Returns sessions with a matching snippet.
        CJK queries are expanded to bigram tokens (AND semantics)."""
        q = query.strip()
        if _CJK.search(q):
            grams = _cjk_bigrams(q).split()
            grams = [g for g in grams if _CJK.search(g)]  # keep only bigram tokens
            if grams:
                q = " ".join(f'"{g}"' for g in grams)
        rows = self.db.execute(
            """SELECT session_key, role, snippet(turns_fts, 2, '[', ']', '…', 12) AS snip
               FROM turns_fts WHERE turns_fts MATCH ? ORDER BY rank LIMIT ?""",
            (q, limit),
        ).fetchall()
        out = []
        for r in rows:
            tool, _, path = r["session_key"].partition("::")
            meta = self.db.execute(
                "SELECT * FROM sessions WHERE source_path=? AND source_tool=?", (path, tool)
            ).fetchone()
            if meta:
                d = dict(meta)
                d["snippet"] = r["snip"]
                out.append(d)
        return out

    def remove_session(self, session_id: str, tool: str) -> None:
        """Remove from index only (all snapshots) — source files are never deleted."""
        rows = self.db.execute(
            "SELECT source_path FROM sessions WHERE id=? AND source_tool=?", (session_id, tool)
        ).fetchall()
        for r in rows:
            self.db.execute(
                "DELETE FROM turns_fts WHERE session_key=?", (f"{tool}::{r['source_path']}",)
            )
        self.db.execute("DELETE FROM sessions WHERE id=? AND source_tool=?", (session_id, tool))
        self.db.commit()

    # ---- backups ----

    def backup_file(self, path: Path) -> Path:
        return make_backup(path, ctxbox_data_dir() / "backups")

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


def _bigrams(text: str) -> str:
    """Overlapping CJK bigrams — FTS5's unicode61 treats a whole CJK run as
    ONE token, so searching '补天' would never match '补天白帽' without this."""
    grams: list[str] = []
    for m in _CJK.finditer(text):
        run = m.group(0)
        if len(run) == 1:
            grams.append(run)
        else:
            grams.extend(run[i : i + 2] for i in range(len(run) - 1))
    return " ".join(grams)


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
    PRIMARY KEY (source_tool, source_path, id)
    -- one row per (file, conversation): codex splits a conversation into
    -- snapshot files; opencode packs many conversations into one DB file
);
CREATE VIRTUAL TABLE IF NOT EXISTS turns_fts USING fts5(
    session_key UNINDEXED, role, text, grams, tokenize='unicode61'
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
        self._migrate_schema()
        self._migrate_fts()

    def _migrate_schema(self) -> None:
        """v0.2.x -> v0.3.0: sessions PK gained `id` (multi-session files like
        opencode's DB). Rebuild the index from scratch if the old PK is found."""
        info = list(self.db.execute("PRAGMA table_info(sessions)"))
        if info:
            pk_cols = [r["name"] for r in info if r["pk"]]
            if set(pk_cols) != {"source_tool", "source_path", "id"}:
                self.db.execute("DROP TABLE sessions")
                self.db.execute("DROP TABLE IF EXISTS turns_fts")
                self.db.executescript(_SCHEMA)
                self.db.commit()
                self.rescan()  # full rebuild, one-time

    def _migrate_fts(self) -> None:
        """v0.1.0 -> v0.1.1: turns_fts gained a `grams` column. Rebuild FTS."""
        cols = {r["name"] for r in self.db.execute("PRAGMA table_info(turns_fts)")}
        if cols and "grams" not in cols:
            self.db.execute("DROP TABLE turns_fts")
            self.db.execute(
                "CREATE VIRTUAL TABLE turns_fts USING fts5("
                "session_key UNINDEXED, role, text, grams, tokenize='unicode61')"
            )
            rows = self.db.execute("SELECT source_tool, source_path FROM sessions").fetchall()
            for r in rows:
                try:
                    session = get_adapter(r["source_tool"]).parse(Path(r["source_path"]))
                    self.upsert_session(session)  # force: repopulate FTS
                except Exception:
                    continue  # file may be gone; next scan cleans up
            self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---- scanning ----

    def rescan(
        self,
        progress_cb: Callable[[str, int, int], None] | None = None,
        tool: str | None = None,
    ) -> int:
        """Discover and (re)parse sessions. tool=None scans every adapter;
        pass an adapter name to rescan only that tool's directories."""
        total = 0
        adapters = all_adapters()
        if tool:
            adapters = [a for a in adapters if a.name == tool]
        files: list[tuple[str, Path]] = []
        for ad in adapters:
            for p in ad.detect():
                files.append((ad.name, p))
        for i, (t, path) in enumerate(files, start=1):
            if progress_cb:
                progress_cb(f"{t}: {path.name}", i, len(files))
            try:
                self._upsert_file(t, path)
                total += 1
            except Exception as exc:  # a broken file must never kill the scan
                self._record_error(t, path, str(exc))
        self.prune(tool=tool)
        self.db.commit()
        return total

    def prune(self, tool: str | None = None) -> int:
        """Drop index rows whose source file no longer exists (scoped to
        `tool` when given). Keeps the index honest after files are deleted."""
        sql = "SELECT source_tool, source_path, id FROM sessions"
        params: tuple = ()
        if tool:
            sql += " WHERE source_tool=?"
            params = (tool,)
        stale = [
            (t, p, i)
            for t, p, i in self.db.execute(sql, params).fetchall()
            if p and not Path(p).exists()
        ]
        for t, p, i in stale:
            self.db.execute(
                "DELETE FROM sessions WHERE source_tool=? AND source_path=? AND id=?",
                (t, p, i),
            )
            self.db.execute("DELETE FROM turns_fts WHERE session_key=?", (f"{t}::{i}::{p}",))
        return len(stale)

    def _upsert_file(self, tool: str, path: Path) -> None:
        mtime = path.stat().st_mtime
        row = self.db.execute(
            "SELECT source_mtime FROM sessions WHERE source_tool=? AND source_path=?",
            (tool, str(path)),
        ).fetchone()
        if row and row["source_mtime"] == mtime:
            return  # unchanged; incremental scan
        adapter = get_adapter(tool)
        for session in adapter.iter_sessions(path):  # one file may hold many
            self.upsert_session(session)

    def upsert_session(self, session: Session) -> None:
        # FTS key carries the id too: one file may hold many conversations
        key = f"{session.source_tool}::{session.id}::{session.source_path}"
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
            "INSERT INTO turns_fts (session_key, role, text, grams) VALUES (?,?,?,?)",
            [
                (key, t.role.value, t.text(), _bigrams(t.text()))
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
            # window function: exactly one row per (tool, id) even on mtime ties
            sql = """SELECT * FROM (
                        SELECT s.*, g.c AS snapshot_count,
                               ROW_NUMBER() OVER (
                                   PARTITION BY s.source_tool, s.id
                                   ORDER BY s.source_mtime DESC, s.source_path DESC
                               ) AS rn
                        FROM sessions s
                        JOIN (SELECT source_tool, id, COUNT(*) AS c
                              FROM sessions GROUP BY source_tool, id) g
                        ON s.source_tool=g.source_tool AND s.id=g.id
                     ) WHERE rn=1"""
        else:
            sql = "SELECT * FROM sessions"
        params: list[Any] = []
        if tool:
            sql += " AND source_tool=?" if dedupe else " WHERE source_tool=?"
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
        """FTS5 full-text search, deduplicated per conversation.

        - CJK queries expand to quoted bigrams matched against the `grams`
          column (clean `text` column stays bigram-free for snippets)
        - one row per conversation: best snippet + total hit count
        """
        q = query.strip()
        if _CJK.search(q):
            grams = [g for g in _bigrams(q).split() if _CJK.search(g)]
            if grams:
                q = " OR ".join(f'"{g}"' for g in grams)
                q = f"grams:({q})"
        # over-fetch, then dedupe per conversation
        rows = self.db.execute(
            """SELECT session_key, role, snippet(turns_fts, 2, '[', ']', '…', 12) AS snip
               FROM turns_fts WHERE turns_fts MATCH ? ORDER BY rank LIMIT ?""",
            (q, limit * 4),
        ).fetchall()
        best: dict[tuple[str, str], dict[str, Any]] = {}
        for r in rows:
            tool, sid, path = (r["session_key"].split("::", 2) + ["", ""])[:3]
            meta = self.db.execute(
                "SELECT * FROM sessions WHERE source_path=? AND source_tool=?", (path, tool)
            ).fetchone()
            if not meta:
                continue
            conv = (tool, meta["id"])
            if conv not in best:
                d = dict(meta)
                d["snippet"] = r["snip"]
                d["hit_count"] = 1
                best[conv] = d
            else:
                best[conv]["hit_count"] += 1
        return list(best.values())[:limit]

    def remove_session(self, session_id: str, tool: str) -> None:
        """Remove from index only (all snapshots) — source files are never deleted."""
        self.remove_sessions_bulk([(tool, session_id)])

    def remove_sessions_bulk(self, pairs: list[tuple[str, str]]) -> int:
        """Remove many sessions from the index (all snapshots + FTS rows).
        pairs = [(source_tool, session_id), ...]. Source files untouched.
        Returns number of session rows removed."""
        removed = 0
        for tool, session_id in pairs:
            rows = self.db.execute(
                "SELECT source_path FROM sessions WHERE id=? AND source_tool=?", (session_id, tool)
            ).fetchall()
            for r in rows:
                self.db.execute(
                    "DELETE FROM turns_fts WHERE session_key=?",
                    (f"{tool}::{session_id}::{r['source_path']}",),
                )
            cur = self.db.execute(
                "DELETE FROM sessions WHERE id=? AND source_tool=?", (session_id, tool)
            )
            removed += cur.rowcount
        self.db.commit()
        return removed

    def project_files(self, tool: str | None, project_dir: str) -> list[dict[str, Any]]:
        """All index rows (all snapshots) belonging to one project."""
        sql = "SELECT * FROM sessions WHERE project_dir=?"
        params: list[Any] = [project_dir]
        if tool:
            sql += " AND source_tool=?"
            params.append(tool)
        return [dict(r) for r in self.db.execute(sql, params).fetchall()]

    # ---- backups ----

    def backup_file(self, path: Path) -> Path:
        return make_backup(path, ctxbox_data_dir() / "backups")

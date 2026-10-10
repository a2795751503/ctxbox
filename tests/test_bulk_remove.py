"""Bulk index removal + project file listing."""

import shutil
from pathlib import Path

from ctxbox.core.adapters.base import get_adapter
from ctxbox.core.store.db import SessionIndex

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE = FIXTURES / "claude_code" / "sample.jsonl"


def _seed(idx: SessionIndex, tmp: Path) -> None:
    ad = get_adapter("claude-code")
    for i in range(3):
        p = tmp / f"c{i}.jsonl"
        shutil.copy(CLAUDE, p)
        s = ad.parse(p)
        s.id = f"conv-{i}"
        s.project_dir = "proj-a" if i < 2 else "proj-b"
        idx.upsert_session(s)
    idx.db.commit()


def test_bulk_remove(tmp_path):
    idx = SessionIndex(db_path=tmp_path / "i.db")
    _seed(idx, tmp_path)
    removed = idx.remove_sessions_bulk([("claude-code", "conv-0"), ("claude-code", "conv-1")])
    assert removed == 2
    assert {r["id"] for r in idx.sessions(dedupe=False)} == {"conv-2"}
    # FTS 也清干净: 命中里只剩 conv-2
    assert {r["id"] for r in idx.search("401")} == {"conv-2"}
    idx.close()


def test_remove_session_delegates_to_bulk(tmp_path):
    idx = SessionIndex(db_path=tmp_path / "i.db")
    _seed(idx, tmp_path)
    idx.remove_session("conv-2", "claude-code")
    assert len(idx.sessions(dedupe=False)) == 2
    idx.close()


def test_project_files(tmp_path):
    idx = SessionIndex(db_path=tmp_path / "i.db")
    _seed(idx, tmp_path)
    rows = idx.project_files(None, "proj-a")
    assert len(rows) == 2
    rows_tool = idx.project_files("codex", "proj-a")
    assert rows_tool == []
    idx.close()

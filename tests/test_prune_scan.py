"""Per-tool rescan + stale-row pruning."""

import shutil
from pathlib import Path

from ctxbox.core.adapters.base import get_adapter
from ctxbox.core.store.db import SessionIndex

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE = FIXTURES / "claude_code" / "sample.jsonl"


def _seed(idx: SessionIndex, tmp: Path) -> None:
    ad = get_adapter("claude-code")
    for i in range(2):
        p = tmp / f"c{i}.jsonl"
        shutil.copy(CLAUDE, p)
        s = ad.parse(p)
        s.id = f"conv-{i}"
        idx.upsert_session(s)
    idx.db.commit()


def test_prune_removes_missing_files(tmp_path):
    idx = SessionIndex(db_path=tmp_path / "i.db")
    _seed(idx, tmp_path)
    (tmp_path / "c0.jsonl").unlink()
    removed = idx.prune()
    assert removed == 1
    remaining = {r["id"] for r in idx.sessions(dedupe=False)}
    assert remaining == {"conv-1"}
    idx.close()


def test_prune_scoped_to_tool(tmp_path):
    idx = SessionIndex(db_path=tmp_path / "i.db")
    _seed(idx, tmp_path)
    (tmp_path / "c0.jsonl").unlink()
    removed = idx.prune(tool="codex")  # different tool: nothing pruned
    assert removed == 0
    assert len(idx.sessions(dedupe=False)) == 2
    idx.close()

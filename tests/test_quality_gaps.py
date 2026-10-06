"""Coverage gap tests: db migrations/branches, error paths, adapter edges."""

import json
import sqlite3
from pathlib import Path

import pytest

from ctxbox.core.adapters.base import get_adapter
from ctxbox.core.inject.engine import inject_session
from ctxbox.core.store.db import SessionIndex

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE_SAMPLE = FIXTURES / "claude_code" / "sample.jsonl"


@pytest.fixture
def idx(tmp_path):
    i = SessionIndex(db_path=tmp_path / "index.db")
    yield i
    i.close()


class TestDbBranches:
    def test_load_missing_raises(self, idx):
        with pytest.raises(KeyError):
            idx.load_session("nope")

    def test_sessions_all_and_nondedupe(self, idx, tmp_path):
        ad = get_adapter("claude-code")
        for i in range(2):
            p = tmp_path / f"s{i}.jsonl"
            p.write_bytes(CLAUDE_SAMPLE.read_bytes())
            s = ad.parse(p)
            s.id = "shared-id"  # same conversation, two snapshots
            idx.upsert_session(s)
        idx.db.commit()
        assert len(idx.sessions()) == 1
        assert len(idx.sessions(dedupe=False)) == 2
        assert idx.tools_summary() == [("claude-code", 2)]

    def test_remove_session(self, idx, tmp_path):
        ad = get_adapter("claude-code")
        p = tmp_path / "x.jsonl"
        p.write_bytes(CLAUDE_SAMPLE.read_bytes())
        s = ad.parse(p)
        idx.upsert_session(s)
        idx.db.commit()
        idx.remove_session(s.id, "claude-code")
        assert idx.sessions() == []
        assert p.exists()  # source file never deleted

    def test_rescan_records_parse_error(self, idx, tmp_path, monkeypatch):
        ad = get_adapter("continue")
        bad = tmp_path / "broken.json"
        bad.write_text("[1,2,3]", encoding="utf-8")  # valid JSON, wrong shape
        monkeypatch.setattr(ad, "sessions_root", lambda: tmp_path)
        # force rescan path via _upsert_file
        with pytest.raises(ValueError):
            idx._upsert_file("continue", bad)

    def test_fts_migration_from_v010(self, tmp_path):
        """Old turns_fts without grams column must be rebuilt automatically."""
        db = tmp_path / "old.db"
        conn = sqlite3.connect(db)
        path_sql = str(CLAUDE_SAMPLE).replace("'", "''")
        conn.executescript(
            "CREATE TABLE sessions (id TEXT NOT NULL, source_tool TEXT NOT NULL,"
            " title TEXT, project_dir TEXT, source_path TEXT NOT NULL,"
            " source_mtime REAL, turn_count INTEGER, created_at TEXT,"
            " updated_at TEXT, warnings TEXT, PRIMARY KEY (source_tool, source_path));"
            "CREATE VIRTUAL TABLE turns_fts USING fts5(session_key UNINDEXED, role, text);"
            f"INSERT INTO sessions VALUES ('s1','claude-code','t',NULL,'{path_sql}',1,1,NULL,NULL,'');"
        )
        conn.commit()
        conn.close()
        idx2 = SessionIndex(db_path=db)  # should trigger both migrations
        cols = {r["name"] for r in idx2.db.execute("PRAGMA table_info(turns_fts)")}
        assert "grams" in cols
        idx2.close()


class TestInjectEngineFailures:
    def test_unknown_adapter(self):
        from ctxbox.core.adapters.base import get_adapter as ga

        s = ga("claude-code").parse(CLAUDE_SAMPLE)
        r = inject_session(s, "no-such-tool")
        assert not r.ok and "Unknown adapter" in (r.error or "")

    def test_inject_into_unwritable_dir(self, tmp_path):
        s = get_adapter("claude-code").parse(CLAUDE_SAMPLE)
        bad = tmp_path / "no" / "such" / "deep" / "dir"
        bad.parent.mkdir(parents=True)
        (bad.parent / "dir").mkdir()
        import os

        os.chmod(bad.parent, 0o444)
        try:
            r = inject_session(s, "claude-code", target_dir=bad / "x")
            assert not r.ok or r.path  # platform-dependent; must not raise
        finally:
            os.chmod(bad.parent, 0o755)


class TestGenericJsonlEdges:
    def test_role_hints_and_serialize(self, tmp_path):
        ad = get_adapter("generic-jsonl")
        p = tmp_path / "t.jsonl"
        p.write_text(
            '{"role":"human","content":"q1"}\n'
            '{"speaker":"model","text":"a1"}\n'
            '{"type":"tool","message":"obs"}\n',
            encoding="utf-8",
        )
        from ctxbox.core.model.schema import Role

        s = ad.parse(p)
        assert [t.role for t in s.turns] == [Role.USER, Role.ASSISTANT, Role.TOOL]
        out = ad.inject(s, target_dir=tmp_path)
        assert out.exists()

    def test_non_object_json_lines_wrapped(self, tmp_path):
        ad = get_adapter("generic-jsonl")
        p = tmp_path / "t.jsonl"
        p.write_text('[1,2,3]\n"just a string"\n', encoding="utf-8")
        s = ad.parse(p)
        assert len(s.turns) == 2


class TestGeminiEdges:
    def test_checkpoint_format_and_serialize(self, tmp_path):
        ad = get_adapter("gemini-cli")
        p = tmp_path / "session-cp.json"
        p.write_text(
            json.dumps({"history": [{"type": "user", "content": "hi"}]}),
            encoding="utf-8",
        )
        s = ad.parse(p)
        assert s.turns[0].text() == "hi"
        out = json.loads(ad.serialize(s))
        assert out[0]["type"] == "user"


class TestContinueEdges:
    def test_inject_new_file(self, tmp_path):
        ad = get_adapter("continue")
        s = ad.parse(FIXTURES / "continue" / "cont-1234.json")
        dest = ad.inject(s, target_dir=tmp_path)
        assert dest.exists() and dest.name != "cont-1234.json"
        again = ad.parse(dest)
        assert len(again.turns) == len(s.turns)


class TestAtomicEdges:
    def test_atomic_write_creates_parents(self, tmp_path):
        from ctxbox.core.utils import atomic_write

        p = tmp_path / "a" / "b" / "c.txt"
        atomic_write(p, b"hello")
        assert p.read_bytes() == b"hello"

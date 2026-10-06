from pathlib import Path

from ctxbox.core.adapters.base import get_adapter
from ctxbox.core.exporter import export_session
from ctxbox.core.inject.engine import inject_session
from ctxbox.core.store.db import SessionIndex

FIXTURES = Path(__file__).parent / "fixtures"
CLAUDE_SAMPLE = FIXTURES / "claude_code" / "sample.jsonl"


def _indexed(tmp_path) -> SessionIndex:
    idx = SessionIndex(db_path=tmp_path / "index.db")
    session = get_adapter("claude-code").parse(CLAUDE_SAMPLE)
    idx.upsert_session(session)
    idx.db.commit()
    return idx


def test_upsert_and_list(tmp_path):
    idx = _indexed(tmp_path)
    rows = idx.sessions(tool="claude-code")
    assert len(rows) == 1
    assert rows[0]["turn_count"] == 3
    idx.close()


def test_fts_search(tmp_path):
    idx = _indexed(tmp_path)
    hits = idx.search("401")
    assert hits and hits[0]["source_tool"] == "claude-code"
    assert hits[0]["snippet"]
    idx.close()


def test_load_session_roundtrip(tmp_path):
    idx = _indexed(tmp_path)
    s = idx.load_session("sample", tool="claude-code")
    assert len(s.turns) == 3
    idx.close()


def test_backup_created(tmp_path):
    idx = SessionIndex(db_path=tmp_path / "i.db")
    target = tmp_path / "some.jsonl"
    target.write_text("{}\n", encoding="utf-8")
    bak = idx.backup_file(target)
    assert bak.exists() and bak.read_bytes() == target.read_bytes()
    idx.close()


def test_inject_verifies(tmp_path):
    session = get_adapter("claude-code").parse(CLAUDE_SAMPLE)
    r = inject_session(session, "claude-code", target_dir=tmp_path)
    assert r.ok and r.path and r.turns_verified == r.turns_written


def test_inject_cross_tool(tmp_path):
    session = get_adapter("claude-code").parse(CLAUDE_SAMPLE)
    r = inject_session(session, "codex", target_dir=tmp_path)
    assert r.ok and r.path.name.startswith("rollout-")
    assert any("Cross-tool" in w for w in r.warnings)


def test_export_markdown_and_redact(tmp_path):
    session = get_adapter("claude-code").parse(CLAUDE_SAMPLE)
    md = export_session(session, "md")
    assert "🧑 User" in md and "🤖 Assistant" in md
    s2 = session.model_copy(deep=True)
    s2.turns[0].parts[0].text = "my key is sk-ant-abcdefghijklmnopqrstuvwxyz mail me@x.com"
    out = export_session(s2, "md", redact=True)
    assert "sk-ant-abcdef" not in out and "me@x.com" not in out


def test_export_json_jsonl(tmp_path):
    session = get_adapter("claude-code").parse(CLAUDE_SAMPLE)
    import json

    data = json.loads(export_session(session, "json"))
    assert data["source_tool"] == "claude-code"
    lines = export_session(session, "jsonl").strip().splitlines()
    assert len(lines) == len(session.turns)

"""Turn id stability across save/re-parse (GUI turn actions depend on it)."""

from pathlib import Path

from ctxbox.core.adapters.base import get_adapter

FIXTURES = Path(__file__).parent / "fixtures"


def test_claude_turn_ids_stable_after_roundtrip(tmp_path):
    ad = get_adapter("claude-code")
    s = ad.parse(FIXTURES / "claude_code" / "sample.jsonl")
    # real Claude files carry valid uuids; normalize the synthetic fixture
    import uuid as u

    for t in s.turns:
        t.id = str(u.uuid4())
    ids_before = [t.id for t in s.turns]
    # simulate an edit + save + re-parse
    s.turns[1].meta["_edited"] = True
    out = tmp_path / "rt.jsonl"
    out.write_bytes(ad.serialize(s))
    again = ad.parse(out)
    assert [t.id for t in again.turns] == ids_before


def test_claude_non_uuid_ids_get_replaced(tmp_path):
    ad = get_adapter("claude-code")
    s = ad.parse(FIXTURES / "claude_code" / "sample.jsonl")
    s.turns[0].id = "not-a-uuid"
    out = tmp_path / "rt.jsonl"
    out.write_bytes(ad.serialize(s))  # must not crash on invalid uuid
    again = ad.parse(out)
    assert again.turns[0].id != "not-a-uuid"

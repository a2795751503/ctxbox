"""P0 fixes: smart titles, noise folding, search dedupe, clean snippets."""

from pathlib import Path

from ctxbox.core.adapters.base import get_adapter
from ctxbox.core.exporter import export_session
from ctxbox.core.model.schema import ContentPart, Role, Session, Turn, is_noise_text
from ctxbox.core.store.db import SessionIndex

FIXTURES = Path(__file__).parent / "fixtures"
CODEX_SAMPLE = (
    FIXTURES / "codex" / "rollout-2026-06-17T19-51-50-019ed723-d13c-7530-a708-796c64a71938.jsonl"
)


def _noisy_session() -> Session:
    """Mimic a real Codex session: giant env-context first, real question later."""
    return Session(
        id="noisy-1",
        source_tool="codex",
        turns=[
            Turn(
                role=Role.USER,
                parts=[
                    ContentPart(
                        kind="text",
                        text="<environment_context>\n<cwd>D:\\x</cwd>\n</environment_context>",
                    )
                ],
            ),
            Turn(role=Role.USER, parts=[ContentPart(kind="text", text="为什么登录返回 401？")]),
            Turn(role=Role.ASSISTANT, parts=[ContentPart(kind="text", text="token 过期了。")]),
        ],
    )


def test_noise_detected_and_title_skips_it():
    s = _noisy_session()
    assert s.turns[0].meta.get("noise") is True
    assert s.turns[1].meta.get("noise") is None
    assert s.title == "为什么登录返回 401？"
    assert s.noise_count == 1


def test_is_noise_text():
    assert is_noise_text("<environment_context>x")
    assert is_noise_text("  <app-context>y")
    assert not is_noise_text("正常问题")


def test_export_skips_noise_by_default():
    s = _noisy_session()
    md = export_session(s, "md")
    assert "environment_context" not in md
    assert "为什么登录返回 401" in md
    assert "omitted" in md  # note about skipped turns
    md_full = export_session(s, "md", include_system=True)
    assert "environment_context" in md_full


def test_export_jsonl_skips_noise():
    s = _noisy_session()
    lines = export_session(s, "jsonl").strip().splitlines()
    assert len(lines) == 2  # noise turn dropped


def test_real_codex_fixture_title_is_real_question():
    s = get_adapter("codex").parse(CODEX_SAMPLE)
    assert s.title == "fix the flaky test in tests/test_api.py"


class TestSearchDedupeAndSnapshots:
    def setup_method(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.idx = SessionIndex(db_path=Path(self.tmp.name) / "i.db")
        ad = get_adapter("codex")
        # two snapshot files of the SAME conversation id
        for i in range(2):
            p = Path(self.tmp.name) / f"snap{i}.jsonl"
            p.write_bytes(CODEX_SAMPLE.read_bytes())
            self.idx.upsert_session(ad.parse(p))
        self.idx.db.commit()

    def teardown_method(self):
        self.idx.close()
        self.tmp.cleanup()

    def test_sessions_dedupe_with_snapshot_count(self):
        rows = self.idx.sessions(tool="codex")
        assert len(rows) == 1
        assert rows[0]["snapshot_count"] == 2

    def test_search_dedupes_and_counts_hits(self):
        hits = self.idx.search("flaky")
        assert len(hits) == 1
        assert hits[0]["hit_count"] >= 1

    def test_snippet_has_no_bigram_junk(self):
        p = Path(self.tmp.name) / "noisy_src.jsonl"
        p.write_bytes(CODEX_SAMPLE.read_bytes())
        s = _noisy_session()
        s.source_path = p
        s.turns.append(
            Turn(role=Role.USER, parts=[ContentPart(kind="text", text="在小红书app里抓包")])
        )
        self.idx.upsert_session(s)
        self.idx.db.commit()
        hits = self.idx.search("小红书")
        assert hits
        assert "[小红]" not in hits[0]["snippet"]

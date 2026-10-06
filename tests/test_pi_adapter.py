from pathlib import Path

from ctxbox.core.adapters.base import get_adapter
from ctxbox.core.inject.engine import inject_session
from ctxbox.core.model.schema import Role

FIXTURES = Path(__file__).parent / "fixtures"
PI_SAMPLE = FIXTURES / "pi" / "2026-10-06T19-30-40-051Z_01a112b2-test-73fa-a868-af48b160cdaf.jsonl"


class TestPi:
    def setup_method(self):
        self.adapter = get_adapter("pi")
        self.session = self.adapter.parse(PI_SAMPLE)

    def test_header_and_model(self):
        assert self.session.project_dir == "C:\\proj\\demo"
        assert self.session.meta.get("model") == "claude-opus-5-5"

    def test_roles_and_parts(self):
        roles = [t.role for t in self.session.turns]
        assert roles == [Role.SYSTEM, Role.USER, Role.ASSISTANT, Role.ASSISTANT]
        kinds = [p.kind for t in self.session.turns for p in t.parts]
        assert "thinking" in kinds and "tool_call" in kinds

    def test_context_edit_deletes_target(self):
        # the toolResult message m1000005 was deleted by context_edit
        assert not any(t.role == Role.TOOL for t in self.session.turns)

    def test_title(self):
        assert "pi切换上下文" in self.session.title

    def test_slug(self):
        from ctxbox.core.adapters.pi import _slug

        assert _slug("C:\\Users\\105") == "--C--Users-105--"
        assert _slug("C:\\Windows\\System32") == "--C--Windows-System32--"

    def test_roundtrip(self, tmp_path):
        dest = self.adapter.inject(self.session, target_dir=tmp_path)
        again = self.adapter.parse(dest)
        assert [t.role for t in again.turns] == [t.role for t in self.session.turns]
        assert again.title == self.session.title


class TestCrossToolPi:
    def test_codex_to_pi(self, tmp_path):
        codex = get_adapter("codex")
        cs = codex.parse(
            FIXTURES
            / "codex"
            / "rollout-2026-06-17T19-51-50-019ed723-d13c-7530-a708-796c64a71938.jsonl"
        )
        r = inject_session(cs, "pi", target_dir=tmp_path)
        assert r.ok and r.turns_verified == r.turns_written
        # the injected file is a valid pi session
        pi = get_adapter("pi")
        ps = pi.parse(r.path)
        assert ps.turns[0].role == Role.USER

    def test_pi_to_codex(self, tmp_path):
        pi = get_adapter("pi")
        ps = pi.parse(PI_SAMPLE)
        r = inject_session(ps, "codex", target_dir=tmp_path)
        assert r.ok and r.turns_verified == r.turns_written

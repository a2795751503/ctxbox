from pathlib import Path

from ctxbox.core.adapters.base import all_adapters, get_adapter
from ctxbox.core.model.schema import Role

FIXTURES = Path(__file__).parent / "fixtures"


def test_registry_discovers_adapters():
    names = {a.name for a in all_adapters()}
    assert {"claude-code", "codex", "continue", "generic-jsonl"} <= names


class TestClaudeCode:
    def setup_method(self):
        self.adapter = get_adapter("claude-code")
        self.session = self.adapter.parse(FIXTURES / "claude_code" / "sample.jsonl")

    def test_roles_classified(self):
        roles = [t.role for t in self.session.turns]
        assert Role.USER in roles and Role.ASSISTANT in roles
        assert roles.count(Role.USER) == 2  # second user turn carries tool_result

    def test_title_from_summary(self):
        assert self.session.title == "Fix auth bug in login flow"

    def test_tool_parts(self):
        kinds = [p.kind for t in self.session.turns for p in t.parts]
        assert "tool_call" in kinds and "tool_result" in kinds and "thinking" in kinds

    def test_meta_lines_skipped(self):
        assert not any(t.meta.get("type") == "queue-operation" for t in self.session.turns)

    def test_roundtrip(self, tmp_path):
        data = self.adapter.serialize(self.session)
        out = tmp_path / "rt.jsonl"
        out.write_bytes(data)
        again = self.adapter.parse(out)
        assert [t.role for t in again.turns] == [t.role for t in self.session.turns]
        assert again.turns[0].text() == self.session.turns[0].text()

    def test_inject_creates_new_file(self, tmp_path):
        dest = self.adapter.inject(self.session, target_dir=tmp_path)
        assert dest.exists() and dest.name.endswith(".jsonl")
        assert dest != self.session.source_path
        reread = self.adapter.parse(dest)
        assert len(reread.turns) == len(self.session.turns)


class TestCodex:
    def setup_method(self):
        self.adapter = get_adapter("codex")
        self.session = self.adapter.parse(
            FIXTURES
            / "codex"
            / "rollout-2026-06-17T19-51-50-019ed723-d13c-7530-a708-796c64a71938.jsonl"
        )

    def test_session_meta_extracted(self):
        assert self.session.id == "019ed723-d13c-7530-a708-796c64a71938"
        assert self.session.project_dir == "D:\\proj\\demo"
        assert self.session.source_version == "0.140.0-alpha.2"

    def test_roles_and_tools(self):
        roles = [t.role for t in self.session.turns]
        assert roles == [Role.USER, Role.ASSISTANT, Role.ASSISTANT, Role.TOOL, Role.ASSISTANT]

    def test_roundtrip(self, tmp_path):
        data = self.adapter.serialize(self.session)
        out = tmp_path / "rollout-rt.jsonl"
        out.write_bytes(data)
        again = self.adapter.parse(out)
        assert [t.role for t in again.turns] == [t.role for t in self.session.turns]

    def test_inject_writes_rollout_name(self, tmp_path):
        dest = self.adapter.inject(self.session, target_dir=tmp_path)
        assert dest.name.startswith("rollout-") and dest.exists()
        reread = self.adapter.parse(dest)
        assert len(reread.turns) == len(self.session.turns)


class TestContinue:
    def test_parse_and_roundtrip(self, tmp_path):
        adapter = get_adapter("continue")
        s = adapter.parse(FIXTURES / "continue" / "cont-1234.json")
        assert s.id == "cont-1234"
        assert [t.role for t in s.turns] == [Role.USER, Role.ASSISTANT]
        out = tmp_path / "rt.json"
        out.write_bytes(adapter.serialize(s))
        again = adapter.parse(out)
        assert [t.text() for t in again.turns] == [t.text() for t in s.turns]


class TestGenericDirty:
    def test_dirty_file_loses_nothing(self):
        adapter = get_adapter("generic-jsonl")
        s = adapter.parse(FIXTURES / "generic" / "dirty.jsonl")
        # 5 non-empty lines in fixture; every one must appear as a turn
        assert len(s.turns) == 5
        assert any(t.meta.get("unparseable") for t in s.turns)
        assert s.parse_warnings


class TestSessionCrud:
    def test_crud_ops(self):
        adapter = get_adapter("claude-code")
        s = adapter.parse(FIXTURES / "claude_code" / "sample.jsonl")
        first = s.turns[0]
        dup = s.clone_turn(first.id)
        assert dup is not None and dup.id != first.id
        assert s.delete_turn(dup.id)
        assert s.move_turn(s.turns[-1].id, 0)
        assert s.merge_turns(s.turns[1].id, s.turns[2].id) in (True, False)  # role-dependent

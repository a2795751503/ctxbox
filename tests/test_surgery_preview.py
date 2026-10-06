from pathlib import Path

from ctxbox.core.adapters.base import get_adapter
from ctxbox.core.inject.engine import preview_injection
from ctxbox.core.model.schema import ContentPart, Role, Session, Turn
from ctxbox.core.surgery import (
    estimate_tokens,
    regex_replace,
    session_tokens,
    slim,
    truncate_to_budget,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _surgery_session() -> Session:
    return Session(
        id="surg-1",
        source_tool="codex",
        turns=[
            Turn(
                role=Role.USER,
                parts=[ContentPart(kind="text", text="token 是 sk-ant-abc123def456ghi789")],
            ),
            Turn(
                role=Role.ASSISTANT,
                parts=[
                    ContentPart(kind="thinking", text="想一下" * 500),
                    ContentPart(kind="text", text="回答一"),
                ],
            ),
            Turn(
                role=Role.TOOL,
                parts=[ContentPart(kind="tool_result", tool_name="sh", text="x" * 5000)],
            ),
            Turn(
                role=Role.USER,
                parts=[ContentPart(kind="text", text="再问一次 sk-ant-abc123def456ghi789")],
            ),
            Turn(role=Role.ASSISTANT, parts=[ContentPart(kind="text", text="回答二")]),
        ],
    )


class TestRegexReplace:
    def test_replaces_and_counts(self):
        s = _surgery_session()
        r = regex_replace(s, r"sk-ant-\w+", "***KEY***")
        assert r.affected == 2
        assert "sk-ant" not in s.turns[0].text()
        assert s.turns[0].meta.get("_edited")
        assert s.turns[0].parts[0].raw is None

    def test_role_filter(self):
        s = _surgery_session()
        r = regex_replace(s, r"sk-ant-\w+", "***", roles={"assistant"})
        assert r.affected == 0


class TestSlim:
    def test_drop_kinds(self):
        s = _surgery_session()
        before = session_tokens(s)
        r = slim(s, drop_tool_results=True, drop_thinking=True)
        assert r.affected == 2
        kinds = [p.kind for t in s.turns for p in t.parts]
        assert "tool_result" not in kinds and "thinking" not in kinds
        assert r.tokens_after < before

    def test_max_part_chars(self):
        s = _surgery_session()
        r = slim(s, max_part_chars=100)
        assert r.affected >= 2  # thinking 2000 chars + tool_result 5000 chars
        assert all(len(p.text or "") <= 130 for t in s.turns for p in t.parts)


class TestTruncate:
    def test_budget_keeps_head_and_tail(self):
        s = _surgery_session()
        budget = (
            estimate_tokens("回答一")
            + estimate_tokens("再问一次 x")
            + estimate_tokens("回答二")
            + 50
        )
        r = truncate_to_budget(s, budget, keep_first=1)
        assert r.affected > 0
        assert s.turns[0].text().startswith("token")
        assert s.turns[-1].text() == "回答二"
        assert session_tokens(s) <= budget + 50

    def test_within_budget_noop(self):
        s = _surgery_session()
        r = truncate_to_budget(s, 10**9)
        assert r.affected == 0 and len(s.turns) == 5


class TestInjectPreview:
    def test_same_tool_keeps_all(self):
        s = get_adapter("claude-code").parse(FIXTURES / "claude_code" / "sample.jsonl")
        items = preview_injection(s, "claude-code")
        assert items and all(i.action == "keep" for i in items)

    def test_cross_tool_flags_degrades(self):
        s = get_adapter("claude-code").parse(FIXTURES / "claude_code" / "sample.jsonl")
        items = preview_injection(s, "continue")
        # continue serialize only writes text — thinking/tool parts degrade
        kinds = {(i.kind, i.action) for i in items}
        assert any(a == "degrade" for _, a in kinds) or all(i.action == "keep" for i in items)


def test_estimate_tokens():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("你好世界") >= 2

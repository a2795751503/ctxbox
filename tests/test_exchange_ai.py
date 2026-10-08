"""Exchange grouping + AI client (mocked HTTP)."""

import json
from pathlib import Path
from unittest import mock

import pytest

from ctxbox.core.adapters.base import get_adapter
from ctxbox.core.ai_client import PROMPTS, AiClient, AiConfig, AiError
from ctxbox.core.exchange import group_exchanges
from ctxbox.core.model.schema import ContentPart, Role, Turn

FIXTURES = Path(__file__).parent / "fixtures"


def _turn(role, text, kind="text", noise=False):
    meta = {"noise": True} if noise else {}
    return Turn(role=role, parts=[ContentPart(kind=kind, text=text)], meta=meta)


class TestGroupExchanges:
    def test_basic_qa_pairs(self):
        turns = [
            _turn(Role.USER, "问题1"),
            _turn(Role.ASSISTANT, "回答1"),
            _turn(Role.USER, "问题2"),
            _turn(Role.ASSISTANT, "回答2a"),
            _turn(Role.ASSISTANT, "回答2b"),
        ]
        exs = group_exchanges(turns)
        assert len(exs) == 2
        assert exs[0].input_text == "问题1"
        assert exs[0].output_text == "回答1"
        assert exs[1].output_text == "回答2a\n\n回答2b"

    def test_leading_system_becomes_opening(self):
        turns = [_turn(Role.SYSTEM, "sys"), _turn(Role.USER, "q"), _turn(Role.ASSISTANT, "a")]
        exs = group_exchanges(turns)
        assert exs[0].input is None  # 开场组
        assert exs[1].input_text == "q"

    def test_tool_result_user_turn_is_not_new_exchange(self):
        turns = [
            _turn(Role.USER, "q"),
            _turn(Role.ASSISTANT, "", kind="tool_call"),
            _turn(Role.USER, "结果", kind="tool_result"),  # claude 风格
            _turn(Role.ASSISTANT, "a"),
        ]
        exs = group_exchanges(turns)
        assert len(exs) == 1
        assert len(exs[0].output) == 3

    def test_noise_turns_grouped_not_own_exchange(self):
        turns = [
            _turn(Role.USER, "<environment_context>x", noise=True),
            _turn(Role.USER, "真问题"),
            _turn(Role.ASSISTANT, "a"),
            _turn(Role.USER, "<app-context>y", noise=True),
        ]
        exs = group_exchanges(turns)
        assert len(exs) == 1
        assert exs[0].input_text == "真问题"

    def test_real_sessions_all_adapters(self):
        samples = {
            "claude-code": FIXTURES / "claude_code" / "sample.jsonl",
            "codex": FIXTURES
            / "codex"
            / "rollout-2026-06-17T19-51-50-019ed723-d13c-7530-a708-796c64a71938.jsonl",
            "kimi-code": FIXTURES / "kimi_code" / "session_test" / "agents" / "main" / "wire.jsonl",
        }
        for tool, path in samples.items():
            s = get_adapter(tool).parse(path)
            exs = group_exchanges(s.turns)
            # 每个 turn 都必须归属某个 Exchange, 不丢
            total = sum(len(ex.turns()) for ex in exs)
            assert total == len(s.turns), tool
            assert any(ex.input is not None for ex in exs), tool


class TestAiClient:
    def test_disabled_without_key(self):
        c = AiClient(AiConfig(api_key=""))
        with pytest.raises(AiError, match="未配置"):
            c.complete("optimize_input", "x")

    def test_complete_calls_api(self):
        payload = json.dumps({"choices": [{"message": {"content": "优化后的文本"}}]}).encode()

        class FakeResp:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        with mock.patch("urllib.request.urlopen", return_value=FakeResp()) as m:
            c = AiClient(AiConfig(api_key="k", base_url="https://x.test/v1", model="m"))
            out = c.complete("optimize_input", "帮我搞下那个东西")
            assert out == "优化后的文本"
            req = m.call_args[0][0]
            assert req.full_url == "https://x.test/v1/chat/completions"
            assert req.headers["Authorization"] == "Bearer k"
            body = json.loads(req.data)
            assert body["model"] == "m"
            assert "帮我搞下那个东西" in body["messages"][0]["content"]

    def test_all_prompt_keys_have_templates_and_labels(self):
        from ctxbox.core.ai_client import PROMPT_LABELS

        for key in ("optimize_input", "optimize_output", "make_title", "compress_tool_output"):
            assert "{content}" in PROMPTS[key]
            assert key in PROMPT_LABELS

    def test_http_error_wrapped(self):
        import io
        import urllib.error

        err = urllib.error.HTTPError("u", 401, "unauthorized", {}, io.BytesIO(b"bad key"))
        with mock.patch("urllib.request.urlopen", side_effect=err):
            c = AiClient(AiConfig(api_key="k", base_url="https://x.test/v1"))
            with pytest.raises(AiError, match="401"):
                c.complete("optimize_input", "x")

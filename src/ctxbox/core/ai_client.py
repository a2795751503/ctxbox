"""OpenAI-compatible AI client for ctxbox's AI-assist features.

This is ctxbox's ONLY network feature: it is disabled until the user
configures an endpoint + key in Settings, and it sends only the content the
user explicitly reviews in the AI-optimize preview dialog.

Prompts are Chinese-first, user-editable in Settings.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class AiConfig:
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    model: str = "gpt-4o-mini"
    timeout: int = 60

    @property
    def enabled(self) -> bool:
        return bool(self.base_url.strip() and self.api_key.strip())


class AiError(Exception):
    pass


PROMPTS: dict[str, str] = {
    "optimize_input": (
        "你是提示词工程师。把用户给出的粗糙提问改写为高质量提示词:\n"
        "1) 完整保留原意和全部约束, 不新增事实;\n"
        "2) 补齐必要背景、明确任务目标、指定期望的输出形式;\n"
        "3) 语言清晰直接, 中文输出;\n"
        "4) 只返回改写后的文本, 不要任何解释。\n\n"
        "粗糙提问:\n{content}"
    ),
    "optimize_output": (
        "你是技术文档编辑。改进这段 AI 回答的表达:\n"
        "1) 先结论后展开, 分点编号, 代码块标注语言;\n"
        "2) 不改变任何技术结论, 不增删事实和代码;\n"
        "3) 中文输出, 只返回改进后的正文, 不要解释。\n\n"
        "原文:\n{content}"
    ),
    "make_title": (
        "用不超过12个字概括下面这段对话要完成的任务, 动词开头, 不带标点,"
        "只返回标题本身。\n\n对话:\n{content}"
    ),
    "compress_tool_output": (
        "把下面这段超长工具输出压缩为不超过200字的要点摘要,"
        "保留关键路径、错误码、数值结论, 中文输出, 只返回摘要。\n\n"
        "工具输出:\n{content}"
    ),
}

PROMPT_LABELS = {
    "optimize_input": "✨ 优化提问",
    "optimize_output": "✨ 优化输出",
    "make_title": "🏷 生成标题",
    "compress_tool_output": "🗜 压缩工具输出",
}


class AiClient:
    """Minimal /chat/completions caller (urllib only, no SDK)."""

    def __init__(self, config: AiConfig) -> None:
        self.config = config

    def complete(self, prompt_key: str, content: str, *, max_chars: int = 12000) -> str:
        if not self.config.enabled:
            raise AiError("未配置 AI 服务 (设置 → AI 服务 填写 Base URL 和 Key)")
        prompt = PROMPTS[prompt_key].format(content=content[:max_chars])
        url = self.config.base_url.rstrip("/") + "/chat/completions"
        payload = json.dumps(
            {
                "model": self.config.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
            }
        ).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.config.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.config.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")[:300]
            raise AiError(f"API 返回 {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise AiError(f"无法连接 {self.config.base_url}: {exc.reason}") from exc
        except TimeoutError as exc:
            raise AiError(f"请求超时 ({self.config.timeout}s)") from exc
        try:
            return data["choices"][0]["message"]["content"].strip()
        except (KeyError, IndexError, TypeError) as exc:
            raise AiError(f"API 响应格式异常: {str(data)[:300]}") from exc

    def test_connection(self) -> str:
        """Quick connectivity check. Returns model name on success."""
        return self.complete("make_title", "用户: 你好\n助手: 你好, 有什么可以帮你?")

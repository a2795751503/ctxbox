"""Exchange（问答对）分组。

Turn 是物理存储单位（单条消息）；用户认知的"一轮对话"是 Exchange：
一条用户输入 + 其后的全部助手输出（正文/思考/工具活动），直到下一条用户输入。

规则：
- 每个 user 轮开启一个新 Exchange（noise 环境注入不单独成轮，归到当前 Exchange）
- user 之前的 system/tool 前缀轮归入 "开场" Exchange（input 为空）
- assistant/tool 轮归入当前 Exchange 的 output
- unknown/无法解析轮归入当前 Exchange 的 output（不丢）
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model.schema import Role, Turn


@dataclass
class Exchange:
    index: int  # 第几轮 (0-based)
    input: Turn | None = None  # 用户输入轮 (开场组可能为 None)
    output: list[Turn] = field(default_factory=list)

    @property
    def title(self) -> str:
        if self.input is None:
            return "开场"
        text = (self.input.text() or "").strip().splitlines()
        return (text[0] if text else "(空输入)")[:40]

    @property
    def input_text(self) -> str:
        return self.input.text() if self.input else ""

    @property
    def output_text(self) -> str:
        """助手正文（仅 text part，思考/工具不混入编辑视图）。"""
        chunks = []
        for t in self.output:
            if t.role == Role.ASSISTANT:
                for p in t.parts:
                    if p.kind == "text" and p.text:
                        chunks.append(p.text)
        return "\n\n".join(chunks)

    def turns(self) -> list[Turn]:
        return ([self.input] if self.input else []) + self.output

    def stats(self) -> dict[str, int]:
        thinking = sum(1 for t in self.output for p in t.parts if p.kind == "thinking")
        tools = sum(1 for t in self.output for p in t.parts if p.kind == "tool_call")
        return {"thinking": thinking, "tool_calls": tools, "output_turns": len(self.output)}


def group_exchanges(turns: list[Turn]) -> list[Exchange]:
    """把扁平 Turn 列表折叠成 Exchange（问答对）列表。"""
    exchanges: list[Exchange] = []
    current = Exchange(index=0)
    pending_noise: list[Turn] = []  # 第一条真实输入之前的环境注入, 归到该输入的 Exchange

    def flush() -> None:
        nonlocal current
        if current.input is not None or current.output:
            exchanges.append(current)
        current = Exchange(index=len(exchanges))

    for turn in turns:
        if turn.role == Role.USER and not turn.meta.get("noise"):
            # 纯工具结果的"用户"轮不算新输入 (claude 格式)
            if turn.parts and all(p.kind == "tool_result" for p in turn.parts):
                current.output.append(turn)
                continue
            if current.input is None and not current.output and pending_noise:
                # 首条真实输入: flush 是空操作, 环境注入并入新 Exchange
                current.input = turn
                current.output = pending_noise
                pending_noise.clear()
                continue
            flush()
            current.input = turn
            continue
        if (
            turn.role == Role.USER
            and turn.meta.get("noise")
            and current.input is None
            and not current.output
        ):
            pending_noise.append(turn)
            continue
        if turn.role == Role.USER and turn.meta.get("noise"):
            # 会话中途的环境注入: 归到当前 Exchange
            current.output.append(turn)
            continue
        current.output.append(turn)
    # 没有真实输入的会话: pending 也作为一个组
    if pending_noise and current.input is None and not current.output:
        current.output = pending_noise + current.output
        pending_noise.clear()
    flush()
    # 重新编号
    for i, ex in enumerate(exchanges):
        ex.index = i
    return exchanges

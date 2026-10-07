"""工具活动行: 把 assistant 轮的 tool_call 与其后紧邻 tool 轮的 tool_result
在**渲染层**配对归并成一条可展开的活动行 (不动 Session 数据)。

归并规则 (build_render_nodes):
- assistant 轮只含 tool_call → 整条变活动行 (slim, 无气泡)
- assistant 轮同时含 text/thinking 和 tool_call → text/thinking 留在气泡,
  每个 tool_call 抽成一条活动行附在气泡内
- 结果按顺序依次分配给各 call; 只消费 parts 全部为 tool_result 的紧邻 tool 轮,
  且该轮的结果数不超过剩余未配对 call 数 (否则整轮留作未配对)
- meta.noise 轮不参与归并/被消费; 未配对的 tool_result 轮按瘦行渲染
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QPlainTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ctxbox.core.model.schema import ContentPart, Role, Turn

from ..theme import MONO_FAMILY, tokens

RESULT_TRUNCATE = 8000


# ------------------------------------------------------------- 数据模型 --
@dataclass
class ActivityNode:
    """一条工具活动: 调用 part + 可选的配对结果。"""

    call_turn: Turn
    call_part: ContentPart
    result_turn: Turn | None = None
    result_part: ContentPart | None = None


@dataclass
class RenderNode:
    """时间线的一个渲染单元。"""

    turn: Turn  # slim=True 时是 call 轮或未配对 result 轮
    activities: list[ActivityNode] = field(default_factory=list)
    slim: bool = False  # True: 无气泡 chrome 的瘦行渲染


def _is_pure_result_turn(turn: Turn) -> bool:
    return (
        turn.role == Role.TOOL
        and bool(turn.parts)
        and all(p.kind == "tool_result" for p in turn.parts)
        and not turn.meta.get("noise")
    )


def build_render_nodes(turns: list[Turn]) -> tuple[list[RenderNode], int]:
    """返回 (渲染节点列表, 被归并吃掉的结果轮数)。"""
    nodes: list[RenderNode] = []
    consumed = 0
    i, n = 0, len(turns)
    while i < n:
        turn = turns[i]
        if turn.role == Role.ASSISTANT and not turn.meta.get("noise"):
            calls = [p for p in turn.parts if p.kind == "tool_call"]
            others = [p for p in turn.parts if p.kind != "tool_call"]
            if calls:
                activities = [ActivityNode(turn, p) for p in calls]
                # 依次消费紧邻的纯 tool_result 轮, 按顺序分配结果
                j = i + 1
                pending = len(activities)
                while j < n and pending > 0 and _is_pure_result_turn(turns[j]):
                    result_turn = turns[j]
                    if len(result_turn.parts) > pending:
                        break  # 结果多于剩余 call: 整轮留作未配对, 不丢渲染
                    for rp in result_turn.parts:
                        slot = activities[len(activities) - pending]
                        slot.result_turn = result_turn
                        slot.result_part = rp
                        pending -= 1
                    consumed += 1
                    j += 1
                nodes.append(RenderNode(turn, activities, slim=not others))
                i = j
                continue
        nodes.append(RenderNode(turn, [], slim=_is_pure_result_turn(turn)))
        i += 1
    return nodes, consumed


# ------------------------------------------------------------- 摘要工具 --
def arg_summary(part: ContentPart, limit: int = 60) -> str:
    """tool_call 的第一个参数摘要: path/command 优先, 截断 limit 字符。"""
    args = part.tool_args
    if not args and part.text:
        try:
            parsed = json.loads(part.text)
            if isinstance(parsed, dict):
                args = parsed
        except (ValueError, TypeError):
            pass
    if isinstance(args, dict) and args:
        value = None
        for key in ("path", "file_path", "command", "cmd"):
            if args.get(key):
                value = args[key]
                break
        if value is None:
            value = next(iter(args.values()))
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    else:
        text = part.text or ""
    text = " ".join(text.split())  # 压成一行
    return text[:limit] + ("…" if len(text) > limit else "")


def text_preview(text: str, limit: int = 60) -> str:
    text = " ".join((text or "").split())
    return text[:limit] + ("…" if len(text) > limit else "")


def tool_label(part: ContentPart) -> str:
    return part.tool_name or "工具"


def pretty_args(part: ContentPart) -> str:
    if part.tool_args:
        return json.dumps(part.tool_args, ensure_ascii=False, indent=2)
    text = part.text or ""
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except (ValueError, TypeError):
        return text or "(无参数)"


def truncate_result(text: str) -> tuple[str, bool]:
    if len(text) > RESULT_TRUNCATE:
        return text[:RESULT_TRUNCATE], True
    return text, False


class FullTextDialog(QDialog):
    """双击结果区查看完整文本 (只读)。"""

    def __init__(self, title: str, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 540)
        lay = QVBoxLayout(self)
        view = QPlainTextEdit(text)
        view.setReadOnly(True)
        view.setStyleSheet(f"font-family: {MONO_FAMILY};")
        lay.addWidget(view, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(lambda _b: self.reject())
        lay.addWidget(buttons)


class ToolActivityRow(QFrame):
    """一条工具活动行: "⚡ Bash — `python emu.py unpack`", 可展开看参数+结果。"""

    toggled = Signal(bool)
    editRequested = Signal()
    contextAction = Signal(str)  # "edit" | "delete_pair" | "copy_text"

    def __init__(self, node: ActivityNode, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.node = node
        t = tokens()
        self.setObjectName("toolActivityRow")
        self.setStyleSheet(
            f"#toolActivityRow {{ background: {t['bubble_tool_bg']};"
            f" border: 1px solid {t['border']}; border-radius: 6px; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 3, 8, 3)
        lay.setSpacing(2)

        call = node.call_part
        name = tool_label(call)
        summary = arg_summary(call)
        title = f"⚡ {name}"
        if summary:
            title += f" — `{summary}`"
        self.btn = QToolButton()
        self.btn.setText(f"▶ {title}")
        self.btn.setCheckable(True)
        self.btn.setChecked(False)
        self.btn.setStyleSheet(
            f"QToolButton {{ color: {t['text_secondary']}; border: none;"
            " padding: 2px; font-size: 12px; text-align: left; }"
        )
        self.btn.toggled.connect(self._toggle)
        lay.addWidget(self.btn)

        # 展开体: 参数 + 结果
        self.body = QWidget()
        body_lay = QVBoxLayout(self.body)
        body_lay.setContentsMargins(16, 0, 0, 0)
        body_lay.setSpacing(3)
        body_lay.addWidget(self._block("参数", pretty_args(call), f"参数 — {name}"))
        if node.result_part is not None:
            result_text, truncated = truncate_result(node.result_part.text or "")
            if truncated:
                result_text += "\n…[已截断, 双击查看全部]"
            rname = tool_label(node.result_part)
            block = self._block("结果", result_text or "(空结果)", f"结果 — {rname}")
            if truncated:
                block.setCursor(Qt.CursorShape.PointingHandCursor)
                block.mouseDoubleClickEvent = lambda _e: FullTextDialog(
                    f"结果 — {rname}", node.result_part.text or "", self
                ).exec()
            body_lay.addWidget(block)
        else:
            no_result = QLabel("结果: (未配对到结果)")
            no_result.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px;")
            body_lay.addWidget(no_result)
        self.body.setVisible(False)
        lay.addWidget(self.body)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _block(self, caption: str, text: str, _title: str) -> QLabel:
        t = tokens()
        lab = QLabel(f"{caption}:\n{text}")
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lab.setStyleSheet(
            f"background: {t['code_bg']}; border: 1px solid {t['code_border']};"
            f" border-radius: 4px; padding: 6px; color: {t['code_text']};"
            f" font-family: {MONO_FAMILY}; font-size: 12px;"
        )
        return lab

    def _toggle(self, checked: bool) -> None:
        self.body.setVisible(checked)
        self.btn.setText(self.btn.text().replace("▶" if checked else "▼", "▼" if checked else "▶"))
        self.toggled.emit(checked)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.editRequested.emit()
        super().mouseDoubleClickEvent(event)

    def _menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        has_result = self.node.result_turn is not None
        menu = QMenu(self)
        act_edit = menu.addAction("编辑此调用")
        act_copy = menu.addAction("复制调用文本")
        act_del = menu.addAction("删除此调用 (含结果)" if has_result else "删除此调用")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_edit:
            self.contextAction.emit("edit")
        elif chosen is act_copy:
            self.contextAction.emit("copy_text")
        elif chosen is act_del:
            self.contextAction.emit("delete_pair")


def copy_to_clipboard(text: str) -> None:
    QApplication.clipboard().setText(text)

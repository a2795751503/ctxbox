"""右栏: 对话时间线。

user 气泡右对齐绿色系, assistant 左对齐蓝色系, tool/system 灰色小字块;
kind="thinking" / "tool_call" / "tool_result" 默认折叠; kind="raw" 黄色警告样式;
代码块等宽字体。双击某轮 -> 编辑; 右键 -> 轮级 CRUD 菜单。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ctxbox.core.model.schema import Role, Turn

ROLE_LABELS = {
    Role.USER: "用户",
    Role.ASSISTANT: "助手",
    Role.SYSTEM: "系统",
    Role.TOOL: "工具",
    Role.UNKNOWN: "未知",
}


def role_label(role) -> str:
    """role 可能是 Role 枚举或纯字符串。"""
    if isinstance(role, Role):
        return ROLE_LABELS.get(role, role.value)
    try:
        return ROLE_LABELS.get(Role(role), str(role))
    except ValueError:
        return str(role)


# 气泡配色: (背景, 边框)
BUBBLE_COLORS = {
    Role.USER: ("#1e3d2b", "#2f6b45"),
    Role.ASSISTANT: ("#1f3550", "#3a5a8a"),
    Role.SYSTEM: ("#2a2b30", "#3a3c44"),
    Role.TOOL: ("#2a2b30", "#3a3c44"),
    Role.UNKNOWN: ("#2a2b30", "#3a3c44"),
}

CODE_FONT = QFont("Consolas")
CODE_FONT.setStyleHint(QFont.StyleHint.Monospace)


def _mono_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setFont(CODE_FONT)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return lab


def _text_label(text: str, small: bool = False) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if small:
        lab.setStyleSheet("color: #9aa0aa; font-size: 12px;")
    return lab


class Collapsible(QFrame):
    """可折叠区块: 标题按钮 + 正文, 默认折叠。"""

    def __init__(self, title: str, content: QWidget, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.btn = QToolButton()
        self.btn.setText(f"▶ {title}")
        self.btn.setCheckable(True)
        self.btn.setChecked(False)
        self.btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn.setStyleSheet(
            "QToolButton { color: #8fa3c7; border: none; padding: 2px; font-size: 12px; }"
        )
        self.content = content
        self.content.setVisible(False)
        self.btn.toggled.connect(self._toggle)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.btn)
        lay.addWidget(self.content)

    def _toggle(self, checked: bool) -> None:
        self.content.setVisible(checked)
        self.btn.setText(self.btn.text().replace("▶" if checked else "▼", "▼" if checked else "▶"))


class TurnBubble(QFrame):
    """单轮气泡, 渲染一个 Turn 的所有 ContentPart。"""

    doubleClicked = Signal()

    def __init__(self, turn: Turn, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.turn = turn
        bg, border = BUBBLE_COLORS.get(turn.role, BUBBLE_COLORS[Role.UNKNOWN])
        self.setStyleSheet(
            f"TurnBubble {{ background: {bg}; border: 1px solid {border}; border-radius: 8px; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)

        # 头部: 角色 + 时间 + 模型 + token + 已编辑标记
        header_bits = [role_label(turn.role)]
        if turn.timestamp:
            header_bits.append(turn.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        if turn.model:
            header_bits.append(turn.model)
        if turn.tokens_in is not None or turn.tokens_out is not None:
            header_bits.append(f"tokens {turn.tokens_in or 0}/{turn.tokens_out or 0}")
        if turn.meta.get("_edited"):
            header_bits.append("✎已编辑")
        if turn.meta.get("noise"):
            header_bits.append("⚙️环境/系统上下文")
        header = QLabel(" · ".join(header_bits))
        header.setStyleSheet("color: #9aa0aa; font-size: 11px;")
        lay.addWidget(header)

        if turn.meta.get("noise"):
            # 噪音轮(工具注入的环境/系统上下文)默认整体折叠, 不再淹没时间线
            inner = QFrame()
            inner_lay = QVBoxLayout(inner)
            inner_lay.setContentsMargins(0, 0, 0, 0)
            for part in turn.parts:
                inner_lay.addWidget(self._render_part(part))
            preview = (turn.text() or "").strip().splitlines()[0][:60] if turn.text() else ""
            lay.addWidget(Collapsible(f"⚙️ 环境/系统上下文 · {preview}…", inner))
            return

        for part in turn.parts:
            lay.addWidget(self._render_part(part))

    def _render_part(self, part) -> QWidget:
        kind, text = part.kind, part.text or ""
        if kind == "thinking":
            return Collapsible("思考过程", _text_label(text, small=True))
        if kind in ("tool_call", "tool_result"):
            title = f"{'🔧 调用工具' if kind == 'tool_call' else '📥 工具结果'}: {part.tool_name or '?'}"
            return Collapsible(title, _mono_label(text or "(无内容)"))
        if kind == "code":
            body = _mono_label(text)
            body.setStyleSheet(
                "background: #141518; border: 1px solid #3a3c44; border-radius: 4px;"
                " padding: 6px; color: #cfe3ff;"
            )
            return body
        if kind == "raw":
            lab = _text_label(f"⚠ 无法解析的原始数据:\n{text[:2000]}", small=True)
            lab.setStyleSheet(
                "background: #4a3d1e; border: 1px solid #8a6d2f; border-radius: 4px;"
                " padding: 6px; color: #e8c96a; font-size: 12px;"
            )
            return lab
        if kind in ("image", "file_ref"):
            return _text_label(f"📎 [{kind}] {part.tool_name or text}", small=True)
        if kind == "error":
            lab = _text_label(f"❌ {text}", small=True)
            lab.setStyleSheet("color: #e06c75;")
            return lab
        # text / diff / 其他: 普通正文
        if not text.strip():
            text = f"[{kind}]"
        return _text_label(text)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class TimelineWidget(QListWidget):
    """对话时间线列表。"""

    editRequested = Signal(str)  # turn_id
    contextAction = Signal(str, str)  # (action_key, turn_id)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSpacing(8)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.itemDoubleClicked.connect(
            lambda item: self.editRequested.emit(item.data(Qt.ItemDataRole.UserRole))
        )

    def set_turns(self, turns: list[Turn]) -> None:
        self.clear()
        for turn in turns:
            bubble = TurnBubble(turn)
            # user 右对齐, assistant/tool/system 左对齐
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(4, 0, 4, 0)
            bubble.setMinimumWidth(180)
            if turn.role == Role.USER:
                hl.addStretch(1)
                hl.addWidget(bubble, 3)
            elif turn.role in (Role.TOOL, Role.SYSTEM):
                hl.addStretch(1)
                hl.addWidget(bubble, 6)
                hl.addStretch(1)
            else:
                hl.addWidget(bubble, 3)
                hl.addStretch(1)
            row.adjustSize()
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, turn.id)
            item.setSizeHint(row.sizeHint())
            self.addItem(item)
            self.setItemWidget(item, row)
            bubble.doubleClicked.connect(lambda tid=turn.id: self.editRequested.emit(tid))

    def _on_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        self.setCurrentItem(item)
        tid = item.data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        actions = [
            ("insert_above", "在此轮上方插入新轮"),
            ("insert_below", "在此轮下方插入新轮"),
            ("edit", "编辑此轮"),
            ("delete", "删除此轮"),
            ("copy_text", "复制此轮文本"),
            ("clone_turn", "克隆此轮"),
            ("move_up", "上移"),
            ("move_down", "下移"),
            ("merge_next", "与下一轮合并"),
        ]
        for key, label in actions:
            act = menu.addAction(label)
            act.triggered.connect(lambda _c=False, k=key, t=tid: self.contextAction.emit(k, t))
        menu.exec(self.viewport().mapToGlobal(pos))

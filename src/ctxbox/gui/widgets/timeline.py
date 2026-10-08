"""右栏: 对话时间线 (参考 Claude.ai / ChatGPT / open-webui 的对话设计)。

- user 右对齐蓝底白字, assistant 左对齐白卡, tool/system 居中浅灰虚线框
- tool_call 与紧邻 tool_result 在渲染层归并为「工具活动行」(见 tool_rows.py)
- 只有工具调用的助手轮/未配对的结果轮: 无气泡 chrome 的瘦行渲染
- thinking/tool 折叠块标题全部带内容预览; 代码块带复制按钮
- 双击编辑, 右键轮级 CRUD; 行高重测覆盖折叠块与活动行展开
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ctxbox.core.model.schema import Role, Turn

from ..theme import MONO_FAMILY, tokens
from .tool_rows import (
    ActivityNode,
    RenderNode,
    ToolActivityRow,
    arg_summary,
    build_render_nodes,
    copy_to_clipboard,
    text_preview,
    tool_label,
    truncate_result,
)

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


CODE_FONT = QFont("Cascadia Code")
CODE_FONT.setStyleHint(QFont.StyleHint.Monospace)


def _mono_label(text: str, color: str = "") -> QLabel:
    lab = QLabel(text)
    lab.setFont(CODE_FONT)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    if color:
        lab.setStyleSheet(f"color: {color};")
    return lab


def _text_label(text: str, color: str = "", size: int = 13) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    style = f"font-size: {size}px; padding: 4px 0px;"
    if color:
        style += f" color: {color};"
    lab.setStyleSheet(style)
    return lab


class Collapsible(QFrame):
    """可折叠区块: 标题按钮 + 正文, 默认折叠。

    well=True 时正文包一层"内容井"底色 (well_bg/well_border/well_text),
    颜色由调用方按气泡深浅传入, 杜绝气泡里白底白字/深底深字。
    """

    def __init__(
        self,
        title: str,
        content: QWidget,
        parent: QWidget | None = None,
        *,
        well_bg: str = "",
        well_border: str = "",
        well_text: str = "",
        btn_color: str = "",
    ) -> None:
        super().__init__(parent)
        t = tokens()
        # 折叠块自身透明, 露出所属气泡的底色 (否则浅色全局底会盖住蓝气泡)
        self.setStyleSheet("Collapsible { background: transparent; border: none; }")
        self.btn = QToolButton()
        self.btn.setText(f"▶ {title}")
        self.btn.setCheckable(True)
        self.btn.setChecked(False)
        self.btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn.setStyleSheet(
            f"QToolButton {{ color: {btn_color or t['text_secondary']}; border: none;"
            " padding: 2px; font-size: 12px; }"
        )
        self.content = content
        if well_bg:
            # 内容井: 显式底/边/字三色, 与所属气泡成深浅对比
            # (合并到内容已有样式上, 保留字体/字号设置)
            self.content.setStyleSheet(
                self.content.styleSheet()
                + f" background: {well_bg}; border: 1px solid {well_border};"
                f" border-radius: 6px; padding: 8px; color: {well_text};"
            )
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


class CodeBlock(QFrame):
    """代码块: mono 正文 + 右上角复制小按钮。"""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        t = tokens()
        self.setStyleSheet(
            f"CodeBlock {{ background: {t['code_bg']}; border: 1px solid {t['code_border']};"
            " border-radius: 6px; }}"
        )
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 4, 6)
        body = _mono_label(text, color=t["code_text"])
        body.setStyleSheet(f"font-family: {MONO_FAMILY}; color: {t['code_text']};")
        lay.addWidget(body, 1)

        btn = QToolButton()
        btn.setText("📋")
        btn.setToolTip("复制代码")
        btn.setFixedSize(24, 24)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet("QToolButton { border: none; font-size: 12px; }")

        def _copy() -> None:
            copy_to_clipboard(text)
            btn.setText("✓")
            QTimer.singleShot(1000, lambda: btn.setText("📋"))

        btn.clicked.connect(_copy)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignTop)


def _find_timeline(widget: QWidget) -> TimelineWidget | None:
    w = widget.parent()
    while w is not None and not isinstance(w, TimelineWidget):
        w = w.parent()
    return w


class _ActivityForwarder:
    """把活动行的 edit/delete/copy 信号转发到 TimelineWidget 的统一信号。"""

    def _forward_edit(self, turn_id: str) -> None:
        tl = _find_timeline(self)
        if tl is not None:
            tl.editRequested.emit(turn_id)

    def _forward_action(self, key: str, act: ActivityNode) -> None:
        tl = _find_timeline(self)
        if tl is None:
            return
        if key == "delete_pair":
            payload = act.call_turn.id
            if act.result_turn is not None:
                payload += "|" + act.result_turn.id
            tl.contextAction.emit("delete_pair", payload)
        elif key == "edit":
            tl.editRequested.emit(act.call_turn.id)
        else:
            tl.contextAction.emit(key, act.call_turn.id)


class TurnBubble(_ActivityForwarder, QFrame):
    """单轮气泡, 渲染一个 Turn 的正文 parts + 抽出的工具活动行。"""

    doubleClicked = Signal()

    def __init__(
        self,
        turn: Turn,
        activities: list[ActivityNode] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.turn = turn
        t = tokens()
        is_noise = bool(turn.meta.get("noise"))

        # 气泡配色: 浅色蓝白对话感, 深色走 DARK 令牌
        if is_noise:
            style = (
                f"background: {t['noise_bg']}; border: 1px dashed {t['noise_border']};"
                " border-radius: 14px;"
            )
            self._text_color = t["text_secondary"]
            header_color = t["text_muted"]
        elif turn.role == Role.USER:
            style = (
                f"background: {t['bubble_user_bg']}; border: none;"
                " border-radius: 14px; border-bottom-right-radius: 4px;"
            )
            self._text_color = t["bubble_user_text"]
            header_color = t["bubble_user_header"]
        elif turn.role in (Role.TOOL, Role.SYSTEM):
            style = (
                f"background: {t['bubble_tool_bg']}; border: 1px dashed {t['bubble_tool_border']};"
                " border-radius: 14px;"
            )
            self._text_color = t["bubble_tool_text"]
            header_color = t["text_muted"]
        else:  # assistant / unknown: 白卡
            style = (
                f"background: {t['bubble_assistant_bg']};"
                f" border: 1px solid {t['bubble_assistant_border']};"
                " border-radius: 14px; border-bottom-left-radius: 4px;"
            )
            self._text_color = t["bubble_assistant_text"]
            header_color = t["text_muted"]
        # 内容井配色: 用户蓝气泡用深蓝井, 其余浅色/深色卡用对应井色
        if turn.role == Role.USER:
            self._well = (t["well_user_bg"], t["well_user_border"], t["well_user_text"])
        else:
            self._well = (t["well_bg"], t["well_border"], t["well_text"])
        # 气泡级兜底颜色: 即使某个子标签忘了设色, 也继承到与背景相配的前景色,
        # 杜绝任何"白底白字/黑底黑字"组合
        self.setStyleSheet(f"TurnBubble {{ {style} color: {self._text_color}; }}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(5)

        # 头部: 角色 · 时间 · 模型 · tokens · 标记 (11px 浅灰)
        lay.addWidget(self._make_header(turn, header_color, is_noise))

        if is_noise:
            # 噪音轮(工具注入的环境/系统上下文)默认整体折叠, 不再淹没时间线
            inner = QFrame()
            inner_lay = QVBoxLayout(inner)
            inner_lay.setContentsMargins(0, 0, 0, 0)
            for part in turn.parts:
                inner_lay.addWidget(self._render_part(part))
            preview = text_preview(turn.text() or "")
            lay.addWidget(self._well_collapsible(f"⚙️ 环境/系统上下文 — {preview}", inner))
            return

        for part in turn.parts:
            lay.addWidget(self._render_part(part))

        # 抽出的工具活动行: 缩进附在气泡正文之下
        for act in activities or []:
            row = ToolActivityRow(act)
            row.editRequested.connect(lambda tid=act.call_turn.id: self._forward_edit(tid))
            row.contextAction.connect(lambda key, a=act: self._forward_action(key, a))
            lay.addWidget(row)

    def _make_header(self, turn: Turn, color: str, is_noise: bool) -> QLabel:
        header_bits = [role_label(turn.role)]
        if turn.timestamp:
            header_bits.append(turn.timestamp.strftime("%Y-%m-%d %H:%M:%S"))
        if turn.model:
            header_bits.append(turn.model)
        if turn.tokens_in is not None or turn.tokens_out is not None:
            header_bits.append(f"tokens {turn.tokens_in or 0}/{turn.tokens_out or 0}")
        if turn.meta.get("_edited"):
            header_bits.append("✎已编辑")
        if is_noise:
            header_bits.append("⚙️环境/系统上下文")
        header = QLabel(" · ".join(header_bits))
        header.setStyleSheet(f"color: {color}; font-size: 11px;")
        return header

    def _well_collapsible(self, title: str, content: QWidget) -> Collapsible:
        """折叠块带"内容井"配色: 井底/井边/井字与所属气泡成深浅对比。"""
        bg, border, text = self._well
        return Collapsible(
            title,
            content,
            well_bg=bg,
            well_border=border,
            well_text=text,
            btn_color=text,
        )

    def _render_part(self, part) -> QWidget:
        t = tokens()
        kind, text = part.kind, part.text or ""
        if kind == "thinking":
            title = f"💭 思考过程 — {text_preview(text)}" if text.strip() else "💭 思考过程"
            return self._well_collapsible(title, _text_label(text, color=self._well[2], size=12))
        if kind == "tool_call":  # 噪音轮内等未抽出的调用
            return self._well_collapsible(
                f"🔧 {tool_label(part)} — {arg_summary(part)}",
                _mono_label(text or "(无内容)", color=self._well[2]),
            )
        if kind == "tool_result":
            return self._well_collapsible(
                f"📥 {tool_label(part)} ✓",
                _mono_label(text or "(无内容)", color=self._well[2]),
            )
        if kind == "code":
            return CodeBlock(text)
        if kind == "raw":
            lab = _text_label(f"⚠ 无法解析的原始数据:\n{text[:2000]}", size=12)
            lab.setStyleSheet(
                f"background: {t['raw_bg']}; border: 1px solid {t['raw_border']};"
                f" border-radius: 6px; padding: 8px; color: {t['raw_text']}; font-size: 12px;"
            )
            return lab
        if kind in ("image", "file_ref"):
            return _text_label(
                f"📎 [{kind}] {part.tool_name or text}", color=self._text_color, size=12
            )
        if kind == "error":
            return _text_label(f"❌ {text}", color=t["danger"], size=12)
        # text / diff / 其他: 普通正文
        if not text.strip():
            text = f"[{kind}]"
        mono = self.turn.role in (Role.TOOL, Role.SYSTEM)
        if mono:
            return _mono_label(text, color=self._text_color)
        return _text_label(text, color=self._text_color)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        self.doubleClicked.emit()
        super().mouseDoubleClickEvent(event)


class SlimActivityBlock(_ActivityForwarder, QFrame):
    """只有工具调用的助手轮: 无气泡 chrome, 一行小灰字头部 + 活动行。"""

    def __init__(self, node: RenderNode, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.node = node
        t = tokens()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 0, 0, 0)
        lay.setSpacing(3)

        turn = node.turn
        bits = ["助手"]
        if turn.timestamp:
            bits.append(turn.timestamp.strftime("%H:%M:%S"))
        if turn.model:
            bits.append(turn.model)
        header = QLabel(" · ".join(bits))
        header.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px;")
        lay.addWidget(header)

        for act in node.activities:
            row = ToolActivityRow(act)
            row.editRequested.connect(lambda tid=act.call_turn.id: self._forward_edit(tid))
            row.contextAction.connect(lambda key, a=act: self._forward_action(key, a))
            lay.addWidget(row)


class SlimResultBlock(QFrame):
    """未配对的全 tool_result 轮: 瘦行 + 带工具名/预览的折叠块。"""

    def __init__(self, turn: Turn, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        t = tokens()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 0, 0, 0)
        lay.setSpacing(3)

        bits = ["工具"]
        if turn.timestamp:
            bits.append(turn.timestamp.strftime("%H:%M:%S"))
        header = QLabel(" · ".join(bits))
        header.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px;")
        lay.addWidget(header)

        for part in turn.parts:
            name = tool_label(part)
            text = part.text or ""
            result_text, truncated = truncate_result(text)
            if truncated:
                result_text += "\n…[已截断, 双击编辑查看全部]"
            preview = text_preview(text)
            title = f"📥 {name} — {preview}" if preview else f"📥 {name} ✓"
            body = _mono_label(result_text or "(空结果)", color=t["code_text"])
            body.setStyleSheet(
                f"background: {t['code_bg']}; border: 1px solid {t['code_border']};"
                f" border-radius: 4px; padding: 6px; color: {t['code_text']};"
                f" font-family: {MONO_FAMILY}; font-size: 12px;"
            )
            lay.addWidget(Collapsible(title, body))


class TimelineWidget(QListWidget):
    """对话时间线列表。"""

    editRequested = Signal(str)  # turn_id
    contextAction = Signal(str, str)  # (action_key, turn_id 或 "call|result")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setSpacing(10)
        self.setFrameShape(QFrame.Shape.NoFrame)
        # 关键: 按像素滚动。默认 ScrollPerItem 时, 单条消息比视口高
        # (如超长 markdown 摘要)就永远滚不到中段, 表现为"显示不全+不能下滑"
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.itemDoubleClicked.connect(self._on_double_click)

        # 「回到底部」浮动小圆按钮: 内容超出视口且未近底时出现
        self.btn_bottom = QToolButton(self)
        self.btn_bottom.setText("↓")
        self.btn_bottom.setToolTip("回到底部")
        self.btn_bottom.setFixedSize(36, 36)
        self.btn_bottom.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_bottom.clicked.connect(self.scrollToBottom)
        self.btn_bottom.hide()
        self._restyle_bottom_btn()
        sb = self.verticalScrollBar()
        sb.valueChanged.connect(self._update_bottom_btn)
        sb.rangeChanged.connect(self._update_bottom_btn)

        # 归并统计 (调试用): (渲染节点数, 被吃掉的结果轮数)
        self.merge_stats = (0, 0)
        # 虚拟化状态
        self._last_turns: list[Turn] | None = None
        self._last_len = -1
        self._nodes: list = []
        self._window_start = 0

    def _restyle_bottom_btn(self) -> None:
        t = tokens()
        self.btn_bottom.setStyleSheet(
            f"QToolButton {{ background: {t['accent']}; color: #ffffff; border: none;"
            " border-radius: 18px; font-size: 16px; font-weight: 700; }"
            f" QToolButton:hover {{ background: {t['accent_hover']}; }}"
        )

    def retheme(self) -> None:
        """主题切换后刷新浮动按钮配色 (气泡由主窗口重建)。"""
        self._restyle_bottom_btn()

    def _update_bottom_btn(self, *_args) -> None:
        sb = self.verticalScrollBar()
        show = sb.maximum() > 0 and sb.value() < sb.maximum() - 40
        self.btn_bottom.setVisible(show)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.btn_bottom.move(self.viewport().width() - 48, self.viewport().height() - 48)

    # ------------------------------------------------------------ 渲染 --
    WINDOW = 200  # 渲染窗口: 只实例化末尾 N 个节点

    def set_turns(
        self,
        turns: list[Turn],
        *,
        force: bool = False,
        focus_turn_index: int | None = None,
        keep_window: bool = False,
    ) -> None:
        # 同一 turns 对象且长度未变: refresh 触发的重复调用直接跳过
        if not force and turns is self._last_turns and len(turns) == self._last_len:
            return
        self._last_turns = turns
        self._last_len = len(turns)

        nodes, consumed = build_render_nodes(turns)
        self.merge_stats = (len(nodes), consumed)
        self._nodes = nodes
        self.clear()

        # 窗口起点: 默认末尾; focus 时包住目标节点; keep_window 时尽量保持
        if focus_turn_index is not None:
            target = self._node_index_for_turn(turns, focus_turn_index)
            self._window_start = (
                max(0, target - self.WINDOW + 1)
                if target is not None
                else max(0, len(nodes) - self.WINDOW)
            )
        elif keep_window and 0 <= self._window_start <= max(0, len(nodes) - self.WINDOW):
            pass  # 保持现有窗口
        else:
            self._window_start = max(0, len(nodes) - self.WINDOW)

        self._add_more_button_if_needed()
        for node in nodes[self._window_start :]:
            self._add_item(*self._build_row(node))

        if focus_turn_index is not None:
            row_idx = (
                self.count() - 1 - (len(nodes) - 1 - (target or 0)) if target is not None else -1
            )
            if 0 <= row_idx < self.count():
                item = self.item(row_idx)
                QTimer.singleShot(
                    0,
                    lambda: self.scrollToItem(item, QAbstractItemView.ScrollHint.PositionAtCenter),
                )
        else:
            # 打开会话直接定位到最新消息
            QTimer.singleShot(0, self.scrollToBottom)
        QTimer.singleShot(0, self._update_bottom_btn)

    def _node_index_for_turn(self, turns: list[Turn], turn_index: int) -> int | None:
        """turns 下标 -> 渲染节点下标 (节点含该轮或其配对结果轮)。"""
        if not (0 <= turn_index < len(turns)):
            return None
        tid = turns[turn_index].id
        for i, node in enumerate(self._nodes):
            if node.turn.id == tid:
                return i
            for act in node.activities:
                if act.result_turn is not None and act.result_turn.id == tid:
                    return i
        return None

    # ---------------------------------------------------- 加载更早 (分页) --
    def _add_more_button_if_needed(self) -> None:
        """顶部"加载更早"按钮项: 还有未渲染的更早节点时存在。"""
        if self._window_start <= 0:
            return
        t = tokens()
        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(18, 0, 0, 0)
        btn = QPushButton(f"⬆ 加载更早的 {self.WINDOW} 条 (还有 {self._window_start} 条)")
        btn.setProperty("kind", "secondary")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(btn.styleSheet() + f" color: {t['text_secondary']};")
        btn.clicked.connect(self.load_earlier)
        hl.addWidget(btn)
        hl.addStretch(1)
        row.adjustSize()
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, ("more", None))
        item.setSizeHint(row.sizeHint())
        item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # 不可选中
        self.addItem(item)
        self.setItemWidget(item, row)

    def load_earlier(self) -> None:
        """窗口向上扩展 WINDOW 个节点, 不重建已有项, 视口位置补偿不跳动。"""
        if self._window_start <= 0:
            return
        sb = self.verticalScrollBar()
        insert_pos = 1 if self.count() and self._is_more_item(self.item(0)) else 0
        # 锚点: 第一个已有内容项; 用它的视口相对位置做精确补偿
        anchor = self.item(insert_pos) if insert_pos < self.count() else None
        old_top = self.visualItemRect(anchor).top() if anchor is not None else None

        new_start = max(0, self._window_start - self.WINDOW)
        for offset, node in enumerate(self._nodes[new_start : self._window_start]):
            row, marker = self._build_row(node)
            row.adjustSize()
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, marker)
            item.setSizeHint(row.sizeHint())
            self.insertItem(insert_pos + offset, item)
            self.setItemWidget(item, row)
            self._hook_relayout(item, row)
        self._window_start = new_start
        # 更新或移除顶部按钮
        if self.count() and self._is_more_item(self.item(0)):
            if new_start > 0:
                btn = self.itemWidget(self.item(0)).findChildren(QPushButton)[0]
                btn.setText(f"⬆ 加载更早的 {self.WINDOW} 条 (还有 {new_start} 条)")
            else:
                self.takeItem(0)

        # 视口补偿: 保持锚点的视口相对位置不变
        # (sizeHint 与实际布局高度可能有误差, 直接按几何差值修正)
        def _compensate() -> None:
            if anchor is not None and old_top is not None:
                new_top = self.visualItemRect(anchor).top()
                delta = new_top - old_top
                if delta:
                    sb.setValue(sb.value() + delta)

        QTimer.singleShot(0, _compensate)

    @staticmethod
    def _is_more_item(item: QListWidgetItem) -> bool:
        marker = item.data(Qt.ItemDataRole.UserRole)
        return isinstance(marker, tuple) and marker[0] == "more"

    # ------------------------------------------------------------ 行构建 --
    def _build_row(self, node: RenderNode) -> tuple[QWidget, tuple]:
        """把一个渲染节点构建成 (行 widget, item 标记), 不加入列表。"""
        if node.slim and node.activities:
            block = SlimActivityBlock(node)
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(6, 0, 6, 0)
            hl.addWidget(block, 3)
            hl.addStretch(1)
            return row, ("turn", node.turn.id)
        if node.slim:
            block = SlimResultBlock(node.turn)
            row = QWidget()
            hl = QHBoxLayout(row)
            hl.setContentsMargins(6, 0, 6, 0)
            hl.addWidget(block, 3)
            hl.addStretch(1)
            return row, ("turn", node.turn.id)
        turn = node.turn
        display = turn
        if node.activities:
            # text/thinking 留在气泡, tool_call 已抽成活动行
            display = turn.model_copy(
                update={"parts": [p for p in turn.parts if p.kind != "tool_call"]}
            )
        bubble = TurnBubble(display, activities=node.activities)
        bubble.doubleClicked.connect(lambda tid=turn.id: self.editRequested.emit(tid))

        row = QWidget()
        hl = QHBoxLayout(row)
        hl.setContentsMargins(6, 0, 6, 0)
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
        return row, ("turn", turn.id)

    def _add_item(self, row: QWidget, marker) -> QListWidgetItem:
        row.adjustSize()
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, marker)
        item.setSizeHint(row.sizeHint())
        self.addItem(item)
        self.setItemWidget(item, row)
        self._hook_relayout(item, row)
        return item

    def _hook_relayout(self, item: QListWidgetItem, row: QWidget) -> None:
        # 展开/收起折叠块/活动行后, 重新测量并更新行高
        for coll in row.findChildren(Collapsible):
            coll.btn.toggled.connect(lambda *_a, it=item, rw=row: self._relayout(it, rw))
        for act_row in row.findChildren(ToolActivityRow):
            act_row.toggled.connect(lambda *_a, it=item, rw=row: self._relayout(it, rw))

    def _relayout(self, item: QListWidgetItem, row: QWidget) -> None:
        QTimer.singleShot(0, lambda: (row.adjustSize(), item.setSizeHint(row.sizeHint())))

    # ------------------------------------------------------------ 交互 --
    def _on_double_click(self, item: QListWidgetItem) -> None:
        marker = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(marker, tuple) and marker[0] == "turn":
            self.editRequested.emit(marker[1])

    def _on_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        self.setCurrentItem(item)
        marker = item.data(Qt.ItemDataRole.UserRole)
        if not (isinstance(marker, tuple) and marker[0] == "turn"):
            return
        tid = marker[1]
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

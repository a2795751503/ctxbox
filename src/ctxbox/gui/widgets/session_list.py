"""中栏: 会话卡片列表 (cc-switch 风格白卡 + pill 徽章 + hover 阴影)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

from ..theme import TOOL_COLORS, tokens

CARD_HEIGHT = 92
CARD_HEIGHT_SEARCH = 112


def fmt_dt(value: Any) -> str:
    """updated_at 可能是 datetime / ISO 字符串 / None。"""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, str) and value:
        return value.replace("T", " ")[:16]
    return "—"


def _elide(text: str, limit: int = 72) -> str:
    """粗略的中部省略, 防止超长路径撑破卡片。"""
    if len(text) <= limit:
        return text
    half = (limit - 1) // 2
    return text[:half] + "…" + text[-(limit - half - 1) :]


class SessionCard(QFrame):
    """一张会话卡片: 标题+pill / 元信息 / 项目路径 [/ 搜索片段]."""

    clicked = Signal()

    def __init__(self, row: dict, display_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.row = row
        self._hover = False
        self._selected = False
        self.setObjectName("sessionCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        t = tokens()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(14, 10, 14, 10)
        lay.setSpacing(4)

        # 第一行: 标题 (14px 半粗) + 右侧工具 pill
        row1 = QHBoxLayout()
        title = QLabel(_elide(row.get("title") or "(无标题)", 60))
        title.setStyleSheet(f"font-weight: 600; font-size: 14px; color: {t['text']};")
        row1.addWidget(title, 1)

        brand = TOOL_COLORS.get(row.get("source_tool", ""), "#6b7280")
        pill = QLabel(display_name)
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill.setStyleSheet(
            f"background: {brand}; color: #ffffff; font-size: 10px;"
            " border-radius: 9px; padding: 2px 8px; font-weight: 600;"
        )
        row1.addWidget(pill, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(row1)

        # 第二行: 元信息 (12px 灰): 轮数 · 更新时间 · 📷快照 · 🔍命中
        meta_bits = [f"{row.get('turn_count', '?')} 轮", fmt_dt(row.get("updated_at"))]
        snapshots = row.get("snapshot_count") or 1
        if snapshots > 1:
            meta_bits.append(f"📷 {snapshots} 个快照")
        hits = row.get("hit_count") or 0
        if hits > 1:
            meta_bits.append(f"🔍 {hits} 处命中")
        meta = QLabel(" · ".join(meta_bits))
        meta.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px;")
        lay.addWidget(meta)

        # 第三行: 项目路径 (11px 浅灰, 省略过长)
        proj = QLabel(_elide(row.get("project_dir") or row.get("source_path") or ""))
        proj.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px;")
        lay.addWidget(proj)

        snippet = row.get("snippet")
        if snippet:
            snip = QLabel(f"🔍 {_elide(snippet, 90)}")
            snip.setStyleSheet(f"color: {t['snippet']}; font-size: 12px;")
            lay.addWidget(snip)

        self._refresh_style()

    # ---------------------------------------------------------- 状态样式 --
    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._refresh_style()

    def _refresh_style(self) -> None:
        t = tokens()
        if self._selected:
            bg, border, width = t["accent_soft"], t["accent"], 2
        elif self._hover:
            bg, border, width = t["card"], t["accent_soft_border"], 1
        else:
            bg, border, width = t["card"], t["border"], 1
        self.setStyleSheet(
            f"#sessionCard {{ background: {bg}; border: {width}px solid {border};"
            " border-radius: 12px; }"
        )
        # hover 时加深阴影, 其余时候无 (阴影在浅色主题下才有意义)
        if self._hover and not self._selected:
            shadow = QGraphicsDropShadowEffect(self)
            shadow.setBlurRadius(16)
            shadow.setXOffset(0)
            shadow.setYOffset(2)
            shadow.setColor(QColor(17, 24, 39, 25))
            self.setGraphicsEffect(shadow)
        else:
            self.setGraphicsEffect(None)

    def enterEvent(self, event) -> None:  # noqa: N802
        self._hover = True
        self._refresh_style()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self._hover = False
        self._refresh_style()
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        self.clicked.emit()
        super().mousePressEvent(event)


class SessionListWidget(QListWidget):
    """会话卡片列表。rows 为 SessionIndex.sessions()/search() 返回的 dict。"""

    openRequested = Signal(str)  # session_id
    contextAction = Signal(str, str)  # (action_key, session_id)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setUniformItemSizes(True)
        self.setSpacing(8)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.itemDoubleClicked.connect(self._on_double_clicked)
        # ↑/↓ 方向键移动 currentItem 时同步卡片选中样式
        self.currentItemChanged.connect(lambda _cur, _prev: self._restyle_selection())
        self._tool_display: dict[str, str] = {}

    def set_tool_display_names(self, mapping: dict[str, str]) -> None:
        self._tool_display = mapping

    def set_rows(self, rows: list[dict], search_mode: bool = False) -> None:
        self.clear()
        for row in rows:
            card = SessionCard(row, self._tool_display.get(row["source_tool"], row["source_tool"]))
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, row)
            h = CARD_HEIGHT_SEARCH if (search_mode and row.get("snippet")) else CARD_HEIGHT
            item.setSizeHint(QSize(200, h))
            self.addItem(item)
            self.setItemWidget(item, card)
            card.clicked.connect(lambda it=item: self._select_item(it))

    def _select_item(self, item: QListWidgetItem) -> None:
        self.setCurrentItem(item)
        self._restyle_selection()

    def _restyle_selection(self) -> None:
        cur = self.currentItem()
        for i in range(self.count()):
            w = self.itemWidget(self.item(i))
            if isinstance(w, SessionCard):
                w.set_selected(self.item(i) is cur)

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        row = item.data(Qt.ItemDataRole.UserRole)
        if row:
            self.openRequested.emit(row["id"])

    def current_session_id(self) -> str | None:
        item = self.currentItem()
        row = item.data(Qt.ItemDataRole.UserRole) if item else None
        return row["id"] if row else None

    def _on_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        self._select_item(item)
        row = item.data(Qt.ItemDataRole.UserRole)
        sid = row["id"]
        menu = QMenu(self)
        actions = [
            ("open", "打开"),
            ("copy", "复制全文"),
            ("clone", "克隆会话"),
            ("delete", "删除会话 (仅删索引)"),
            ("delete_file", "🗑 删除上下文 (可选放入回收站)"),
            ("export_md", "导出 Markdown"),
            ("inject", "注入到…"),
            ("surgery", "🩺 上下文手术室…"),
        ]
        snapshots = row.get("snapshot_count") or 1
        if snapshots > 1:
            actions.append(("snapshots", f"📷 查看 {snapshots} 个快照"))
        for key, label in actions:
            act = menu.addAction(label)
            act.triggered.connect(
                lambda _checked=False, k=key, s=sid: self.contextAction.emit(k, s)
            )
        menu.exec(self.viewport().mapToGlobal(pos))

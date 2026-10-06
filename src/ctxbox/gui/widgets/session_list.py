"""中栏: 会话卡片列表 (QListWidget + 自定义卡片 widget + 右键菜单)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QVBoxLayout,
    QWidget,
)

CARD_HEIGHT = 88
CARD_HEIGHT_SEARCH = 108


def fmt_dt(value: Any) -> str:
    """updated_at 可能是 datetime / ISO 字符串 / None。"""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, str) and value:
        return value.replace("T", " ")[:16]
    return "—"


class SessionCard(QFrame):
    """一张会话卡片: 标题 / 工具·轮数·时间 / 项目路径 [/ 搜索片段]."""

    clicked = Signal()

    def __init__(self, row: dict, display_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.row = row
        self.setObjectName("sessionCard")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_style(False)

        title = QLabel(row.get("title") or "(无标题)")
        title.setStyleSheet("font-weight: 600; font-size: 13px;")
        title.setWordWrap(False)

        meta = QLabel(
            f"{display_name} · {row.get('turn_count', '?')} 轮 · {fmt_dt(row.get('updated_at'))}"
        )
        meta.setStyleSheet("color: #9aa0aa; font-size: 12px;")

        proj = QLabel(row.get("project_dir") or row.get("source_path") or "")
        proj.setStyleSheet("color: #6f747e; font-size: 11px;")
        proj.setWordWrap(False)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(3)
        lay.addWidget(title)
        lay.addWidget(meta)
        lay.addWidget(proj)

        snippet = row.get("snippet")
        if snippet:
            snip = QLabel(f"🔍 {snippet}")
            snip.setStyleSheet("color: #d9b45c; font-size: 12px;")
            snip.setWordWrap(False)
            lay.addWidget(snip)

    def set_selected(self, selected: bool) -> None:
        self._refresh_style(selected)

    def _refresh_style(self, selected: bool) -> None:
        border = "#4f7bdd" if selected else "#2e3038"
        bg = "#262b38" if selected else "#22232a"
        self.setStyleSheet(
            f"#sessionCard {{ background: {bg}; border: 1px solid {border}; border-radius: 6px; }}"
        )

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
        self.setSpacing(6)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._on_context_menu)
        self.itemDoubleClicked.connect(self._on_double_clicked)
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
        for i in range(self.count()):
            w = self.itemWidget(self.item(i))
            if isinstance(w, SessionCard):
                w.set_selected(self.item(i) is item)

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
            ("export_md", "导出 Markdown"),
            ("inject", "注入到…"),
        ]
        for key, label in actions:
            act = menu.addAction(label)
            act.triggered.connect(
                lambda _checked=False, k=key, s=sid: self.contextAction.emit(k, s)
            )
        menu.exec(self.viewport().mapToGlobal(pos))

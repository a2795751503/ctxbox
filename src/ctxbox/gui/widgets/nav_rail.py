"""左侧窄导航栏 (cc-switch icon rail 风格)。

纵向工具切换项: 图标 + 名称 + 会话数; 选中项有左侧 3px 蓝色指示条 + 浅蓝圆角背景。
第一项固定为 "📋 全部"; 底部放设置入口。
"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import tokens


class NavItem(QFrame):
    """单个导航项: [指示条] 图标 名称 … 数量。"""

    clicked = Signal()

    def __init__(self, icon: str, name: str, count: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("navItem")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._selected = False

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 0, 8, 0)
        lay.setSpacing(6)

        self.indicator = QFrame()
        self.indicator.setFixedWidth(3)
        self.indicator.setFixedHeight(18)
        lay.addWidget(self.indicator, 0, Qt.AlignmentFlag.AlignVCenter)

        label = QLabel(f"{icon} {name}")
        label.setStyleSheet("font-size: 13px;")
        lay.addWidget(label, 1)

        self.count_label = QLabel(str(count))
        lay.addWidget(self.count_label, 0)

        self._refresh_style()

    def set_selected(self, selected: bool) -> None:
        self._selected = selected
        self._refresh_style()

    def _refresh_style(self) -> None:
        t = tokens()
        if self._selected:
            self.setStyleSheet(
                f"#navItem {{ background: {t['accent_soft']}; border-radius: 8px; }}"
            )
            self.indicator.setStyleSheet(f"background: {t['accent']}; border-radius: 1px;")
            self.count_label.setStyleSheet(
                f"color: {t['accent']}; font-size: 12px; font-weight: 600;"
            )
        else:
            self.setStyleSheet("#navItem { background: transparent; border-radius: 8px; }")
            self.indicator.setStyleSheet("background: transparent;")
            self.count_label.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px;")

    def enterEvent(self, event) -> None:  # noqa: N802
        if not self._selected:
            t = tokens()
            self.setStyleSheet(
                f"#navItem {{ background: {t['accent_soft']}; border-radius: 8px; }}"
            )
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        if not self._selected:
            self.setStyleSheet("#navItem { background: transparent; border-radius: 8px; }")
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)


class NavRail(QWidget):
    """窄导航栏: 工具列表 + 底部设置按钮。"""

    filterChanged = Signal(object)  # source_tool (str) 或 None = 全部
    settingsRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedWidth(150)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 12, 8, 12)
        lay.setSpacing(6)

        self.listw = QListWidget()
        self.listw.setSpacing(2)
        self.listw.setFrameShape(QFrame.Shape.NoFrame)
        lay.addWidget(self.listw, 1)

        btn_settings = QPushButton("⚙️ 设置")
        btn_settings.setProperty("kind", "secondary")
        btn_settings.setToolTip("主题 / 备份目录 / 快捷键")
        btn_settings.clicked.connect(self.settingsRequested.emit)
        lay.addWidget(btn_settings)

    def set_tools(
        self,
        items: list[tuple[str | None, str, str, int]],
        current: str | None,
    ) -> None:
        """items: [(source_tool|None, icon, display_name, count)]; 保留当前选中项。"""
        self.listw.clear()
        for tool, icon, name, count in items:
            nav = NavItem(icon, name, count)
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, tool)
            item.setSizeHint(QSize(140, 34))
            self.listw.addItem(item)
            self.listw.setItemWidget(item, nav)
            nav.set_selected(tool == current)
            if tool == current:
                self.listw.setCurrentItem(item)
            nav.clicked.connect(lambda it=item: self._select(it))

    def _select(self, item: QListWidgetItem) -> None:
        self.listw.setCurrentItem(item)
        tool = item.data(Qt.ItemDataRole.UserRole)
        for i in range(self.listw.count()):
            w = self.listw.itemWidget(self.listw.item(i))
            if isinstance(w, NavItem):
                w.set_selected(self.listw.item(i) is item)
        self.filterChanged.emit(tool)

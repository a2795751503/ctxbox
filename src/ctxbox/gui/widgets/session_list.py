"""中栏: 会话卡片列表 — 项目分组(可折叠) + 批量勾选 + 平铺/搜索模式。

SessionCard 保持不动; 分组头/批量包装都是外层容器。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..theme import TOOL_COLORS, tokens

CARD_HEIGHT = 92
CARD_HEIGHT_SEARCH = 112
GROUP_HEADER_HEIGHT = 36
UNGROUPED = "未分组"


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


def _sort_key(row: dict) -> str:
    v = row.get("updated_at")
    return v.isoformat() if isinstance(v, datetime) else str(v or "")


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
            " border-radius: 12px; }}"
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


class GroupHeaderWidget(QFrame):
    """项目分组头: [勾选框?] 📁 项目名 · N 个会话 · M 轮 … chevron。"""

    collapseToggled = Signal(str, bool)  # project_dir, collapsed
    checkClicked = Signal(str, bool)  # project_dir, checked
    deleteRequested = Signal(str)
    copyPathRequested = Signal(str)

    def __init__(
        self,
        project_dir: str,
        count: int,
        turns: int,
        collapsed: bool,
        batch_mode: bool,
        check_state: Qt.CheckState,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.project_dir = project_dir
        self.collapsed = collapsed
        self.setObjectName("groupHeader")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        t = tokens()
        self._base = (
            f"#groupHeader {{ background: {t['bubble_tool_bg']};"
            f" border: 1px solid {t['border']}; border-radius: 8px; }}"
        )
        self._hover = (
            f"#groupHeader {{ background: {t['accent_soft']};"
            f" border: 1px solid {t['accent_soft_border']}; border-radius: 8px; }}"
        )
        self.setStyleSheet(self._base)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 4, 10, 4)
        lay.setSpacing(8)

        self.chk = QCheckBox()
        self.chk.setTristate(True)
        self.chk.setCheckState(check_state)
        self.chk.setVisible(batch_mode)
        self.chk.clicked.connect(
            lambda: self.checkClicked.emit(self.project_dir, self.chk.isChecked())
        )
        lay.addWidget(self.chk)

        name = project_dir.split("/")[-1].split("\\")[-1] or project_dir
        label = QLabel(f"📁 {name} · {count} 个会话 · {turns} 轮")
        label.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px; font-weight: 600;")
        label.setToolTip(project_dir)
        lay.addWidget(label, 1)

        self.chevron = QLabel("▼" if not collapsed else "▶")
        self.chevron.setStyleSheet(f"color: {t['text_muted']}; font-size: 11px;")
        lay.addWidget(self.chevron)

        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.collapseToggled.emit(self.project_dir, not self.collapsed)
        super().mousePressEvent(event)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.setStyleSheet(self._hover)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.setStyleSheet(self._base)
        super().leaveEvent(event)

    def _menu(self, pos) -> None:
        menu = QMenu(self)
        act_del = menu.addAction("🗑 删除该项目")
        act_copy = menu.addAction("📂 复制项目路径")
        chosen = menu.exec(self.mapToGlobal(pos))
        if chosen is act_del:
            self.deleteRequested.emit(self.project_dir)
        elif chosen is act_copy:
            self.copyPathRequested.emit(self.project_dir)


class BatchBar(QFrame):
    """批量模式底部浮动操作栏。"""

    selectAllClicked = Signal()
    invertClicked = Signal()
    deleteClicked = Signal()
    exitClicked = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        t = tokens()
        self.setObjectName("batchBar")
        self.setStyleSheet(
            f"#batchBar {{ background: {t['card']}; border: 1px solid {t['accent']};"
            " border-radius: 10px; }}"
        )
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(16)
        shadow.setXOffset(0)
        shadow.setYOffset(2)
        shadow.setColor(QColor(17, 24, 39, 40))
        self.setGraphicsEffect(shadow)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 6, 12, 6)
        lay.setSpacing(8)
        self.count_label = QLabel("已选 0 项")
        self.count_label.setStyleSheet(f"font-weight: 600; color: {t['accent']};")
        lay.addWidget(self.count_label)
        for text, slot, tip in [
            ("全选", self.selectAllClicked.emit, "选中当前列表全部会话"),
            ("反选", self.invertClicked.emit, "反转选中状态"),
            ("🗑 删除", self.deleteClicked.emit, "删除选中的会话 (可选放入回收站)"),
            ("✕ 退出", self.exitClicked.emit, "退出批量模式 (Esc)"),
        ]:
            btn = QPushButton(text)
            btn.setProperty("kind", "secondary")
            btn.setToolTip(tip)
            btn.clicked.connect(slot)
            lay.addWidget(btn)

    def set_count(self, n: int) -> None:
        self.count_label.setText(f"已选 {n} 项")


class SessionListWidget(QListWidget):
    """会话卡片列表 (项目分组 / 平铺 / 搜索) + 批量勾选。

    rows 为 SessionIndex.sessions()/search() 返回的 dict。
    """

    openRequested = Signal(str)  # session_id
    contextAction = Signal(str, str)  # (action_key, session_id)
    projectDeleteRequested = Signal(str)  # project_dir
    batchDeleteRequested = Signal(list)  # [(source_tool, session_id), ...]
    batchModeChanged = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
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

        self._rows_cache: list[dict] = []
        self._search_mode = False
        self._grouped = True
        self._batch_mode = False
        self._checked: set[str] = set()
        self._group_ids: dict[str, list[str]] = {}  # project_dir -> [session_id]

        # 批量浮动操作栏
        self.batch_bar = BatchBar(self)
        self.batch_bar.hide()
        self.batch_bar.selectAllClicked.connect(self._select_all)
        self.batch_bar.invertClicked.connect(self._invert_selection)
        self.batch_bar.deleteClicked.connect(self._emit_batch_delete)
        self.batch_bar.exitClicked.connect(lambda: self.set_batch_mode(False))

        from PySide6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self._on_escape)

    # ---------------------------------------------------------- 外部接口 --
    def set_tool_display_names(self, mapping: dict[str, str]) -> None:
        self._tool_display = mapping

    def set_grouped(self, grouped: bool) -> None:
        if grouped != self._grouped:
            self._grouped = grouped
            self._rebuild()

    def set_batch_mode(self, enabled: bool) -> None:
        if enabled == self._batch_mode:
            return
        self._batch_mode = enabled
        if not enabled:
            self._checked.clear()
        self.batch_bar.setVisible(enabled)
        self._rebuild()
        self.batchModeChanged.emit(enabled)

    def set_rows(self, rows: list[dict], search_mode: bool = False) -> None:
        self._rows_cache = list(rows)
        self._search_mode = search_mode
        self._rebuild()

    # ---------------------------------------------------------- 重建 --
    def _rebuild(self) -> None:
        scroll = self.verticalScrollBar().value()
        self.clear()
        self._group_ids = {}
        flat = self._search_mode or not self._grouped
        # 分组/批量模式下条目高度不一, 关闭均匀尺寸优化
        self.setUniformItemSizes(flat and not self._batch_mode)

        if flat:
            for row in self._rows_cache:
                self._add_card_item(row)
        else:
            groups: dict[str, list[dict]] = {}
            for row in self._rows_cache:
                groups.setdefault(row.get("project_dir") or UNGROUPED, []).append(row)
            # 组按最新会话时间排序
            ordered = sorted(
                groups.items(), key=lambda kv: max(_sort_key(r) for r in kv[1]), reverse=True
            )
            for project_dir, rows in ordered:
                ids = [r["id"] for r in rows]
                self._group_ids[project_dir] = ids
                collapsed = self._is_collapsed(project_dir)
                turns = sum(int(r.get("turn_count") or 0) for r in rows)
                checked_n = sum(1 for i in ids if i in self._checked)
                state = (
                    Qt.CheckState.Checked
                    if checked_n == len(ids)
                    else (Qt.CheckState.PartiallyChecked if checked_n else Qt.CheckState.Unchecked)
                )
                header = GroupHeaderWidget(
                    project_dir, len(rows), turns, collapsed, self._batch_mode, state
                )
                header.collapseToggled.connect(self._on_collapse)
                header.checkClicked.connect(self._on_group_check)
                header.deleteRequested.connect(self.projectDeleteRequested.emit)
                header.copyPathRequested.connect(self._copy_project_path)
                item = QListWidgetItem()
                item.setData(Qt.ItemDataRole.UserRole, ("group", project_dir))
                item.setSizeHint(QSize(200, GROUP_HEADER_HEIGHT))
                item.setFlags(Qt.ItemFlag.ItemIsEnabled)  # 不可选中
                self.addItem(item)
                self.setItemWidget(item, header)
                if not collapsed:
                    for row in rows:
                        self._add_card_item(row)
        self.verticalScrollBar().setValue(scroll)
        self._update_batch_bar()

    def _add_card_item(self, row: dict) -> None:
        card = SessionCard(row, self._tool_display.get(row["source_tool"], row["source_tool"]))
        h = CARD_HEIGHT_SEARCH if (self._search_mode and row.get("snippet")) else CARD_HEIGHT
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, row)
        item.setSizeHint(QSize(200, h))
        self.addItem(item)
        if self._batch_mode:
            wrapper = QWidget()
            hl = QHBoxLayout(wrapper)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(4)
            chk = QCheckBox()
            chk.setChecked(row["id"] in self._checked)
            chk.setToolTip("勾选参与批量操作")
            chk.toggled.connect(lambda checked, rid=row["id"]: self._on_card_check(rid, checked))
            hl.addWidget(chk, 0, Qt.AlignmentFlag.AlignVCenter)
            hl.addWidget(card, 1)
            self.setItemWidget(item, wrapper)
            card.set_selected(row["id"] in self._checked)
        else:
            self.setItemWidget(item, card)
        card.clicked.connect(lambda it=item: self._select_item(it))

    # ---------------------------------------------------------- 折叠 --
    # QSettings.value 在 Windows 上是注册表读取 (~10ms/次), 重建时每组一次会卡,
    # 因此折叠状态一次性载入内存, 切换时写穿。
    _collapsed_cache: dict[str, bool] | None = None

    def _collapsed_map(self) -> dict[str, bool]:
        if self._collapsed_cache is None:
            s = QSettings("ctxbox", "ctxbox")
            s.beginGroup("collapsed")
            self._collapsed_cache = {k: s.value(k, False, type=bool) for k in s.childKeys()}
            s.endGroup()
        return self._collapsed_cache

    def _is_collapsed(self, project_dir: str) -> bool:
        return self._collapsed_map().get(project_dir, False)

    def _on_collapse(self, project_dir: str, collapsed: bool) -> None:
        QSettings("ctxbox", "ctxbox").setValue(f"collapsed/{project_dir}", collapsed)
        self._collapsed_map()[project_dir] = collapsed
        self._rebuild()

    @staticmethod
    def _copy_project_path(project_dir: str) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(project_dir)

    # ---------------------------------------------------------- 批量 --
    def _on_escape(self) -> None:
        if self._batch_mode:
            self.set_batch_mode(False)

    def _on_card_check(self, session_id: str, checked: bool) -> None:
        if checked:
            self._checked.add(session_id)
        else:
            self._checked.discard(session_id)
        self._refresh_checks_visual()

    def _on_group_check(self, project_dir: str, checked: bool) -> None:
        ids = self._group_ids.get(project_dir, [])
        if checked:
            self._checked.update(ids)
        else:
            self._checked.difference_update(ids)
        self._rebuild()  # 整组状态变化大, 重建最省心

    def _select_all(self) -> None:
        self._checked = {r["id"] for r in self._rows_cache}
        self._refresh_checks_visual()

    def _invert_selection(self) -> None:
        all_ids = {r["id"] for r in self._rows_cache}
        self._checked = all_ids - self._checked
        self._refresh_checks_visual()

    def _emit_batch_delete(self) -> None:
        if not self._checked:
            return
        pairs = sorted(
            {(r["source_tool"], r["id"]) for r in self._rows_cache if r["id"] in self._checked}
        )
        self.batchDeleteRequested.emit(pairs)

    def _refresh_checks_visual(self) -> None:
        """同步卡片勾选样式 + 组头三态 + 计数 (不重建)。"""
        checked_in_group: dict[str, int] = {}
        for i in range(self.count()):
            w = self.itemWidget(self.item(i))
            if w is None:
                continue
            card = w.findChild(SessionCard)
            if card is not None:
                card.set_selected(card.row["id"] in self._checked)
                chk = w.findChild(QCheckBox)
                if chk is not None:
                    chk.blockSignals(True)
                    chk.setChecked(card.row["id"] in self._checked)
                    chk.blockSignals(False)
            elif isinstance(w, GroupHeaderWidget):
                ids = self._group_ids.get(w.project_dir, [])
                n = sum(1 for x in ids if x in self._checked)
                checked_in_group[w.project_dir] = n
                w.chk.blockSignals(True)
                w.chk.setCheckState(
                    Qt.CheckState.Checked
                    if n == len(ids) and ids
                    else (Qt.CheckState.PartiallyChecked if n else Qt.CheckState.Unchecked)
                )
                w.chk.blockSignals(False)
        self._update_batch_bar()

    def _update_batch_bar(self) -> None:
        self.batch_bar.set_count(len(self._checked))

    # ---------------------------------------------------------- 选中/打开 --
    def _select_item(self, item: QListWidgetItem) -> None:
        self.setCurrentItem(item)
        self._restyle_selection()

    def _restyle_selection(self) -> None:
        if self._batch_mode:
            return  # 批量模式下蓝边由勾选驱动
        cur = self.currentItem()
        for i in range(self.count()):
            w = self.itemWidget(self.item(i))
            card = w.findChild(SessionCard) if w is not None else None
            if card is not None:
                card.set_selected(self.item(i) is cur)

    def _on_double_clicked(self, item: QListWidgetItem) -> None:
        row = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(row, dict):
            self.openRequested.emit(row["id"])

    def current_session_id(self) -> str | None:
        item = self.currentItem()
        row = item.data(Qt.ItemDataRole.UserRole) if item else None
        return row["id"] if isinstance(row, dict) else None

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self.batch_bar.adjustSize()
        x = max(8, (self.viewport().width() - self.batch_bar.width()) // 2)
        y = self.viewport().height() - self.batch_bar.height() - 12
        self.batch_bar.move(x, y)

    # ---------------------------------------------------------- 右键 --
    def _on_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        row = item.data(Qt.ItemDataRole.UserRole)
        if not isinstance(row, dict):
            return  # 分组头有自己的菜单
        self._select_item(item)
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

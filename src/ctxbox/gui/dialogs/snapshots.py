"""快照查看器: 列出同一会话 id 的全部快照文件, 可打开任意一个渲染。"""

from __future__ import annotations

import contextlib
from datetime import datetime
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from ..theme import tokens


def _fmt_mtime(value: Any) -> str:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, (int, float)) and value:
        return datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S")
    if isinstance(value, str) and value:
        return value.replace("T", " ")[:19]
    return "—"


class SnapshotsDialog(QDialog):
    """表格: 文件名 | 修改时间 | 轮数 | 大小; 选中后 [打开此快照]。"""

    openRequested = Signal(str)  # source_path

    def __init__(self, rows: list[dict], parent=None) -> None:
        super().__init__(parent)
        t = tokens()
        self.setWindowTitle(f"📷 快照查看器 ({len(rows)} 个快照)")
        self.resize(680, 420)
        lay = QVBoxLayout(self)

        tip = QLabel("同一会话的多个磁盘快照 (按修改时间倒序)。打开快照不影响当前索引。")
        tip.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px;")
        lay.addWidget(tip)

        self.table = QTableWidget(len(rows), 4)
        self.table.setHorizontalHeaderLabels(["文件名", "修改时间", "轮数", "大小"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._rows = sorted(rows, key=lambda r: str(r.get("source_mtime") or ""), reverse=True)
        for i, row in enumerate(self._rows):
            path = Path(row.get("source_path") or "")
            size = "—"
            with contextlib.suppress(OSError):
                size = f"{path.stat().st_size / 1024:.1f} KB"
            cells = [
                path.name,
                _fmt_mtime(row.get("source_mtime")),
                str(row.get("turn_count", "?")),
                size,
            ]
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col == 3:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self.table.setItem(i, col, item)
        if rows:
            self.table.selectRow(0)
        lay.addWidget(self.table, 1)

        btn_row = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btn_open = QPushButton("打开此快照")
        btn_open.setProperty("kind", "primary")
        btn_open.setToolTip("把选中的快照文件渲染到右侧时间线")
        btn_open.clicked.connect(self._open_selected)
        btn_row.addButton(btn_open, QDialogButtonBox.ButtonRole.AcceptRole)
        btn_row.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        btn_row.rejected.connect(self.reject)
        lay.addWidget(btn_row)

    def _open_selected(self) -> None:
        row_idx = self.table.currentRow()
        if row_idx < 0:
            return
        path = self._rows[row_idx].get("source_path")
        if path:
            self.openRequested.emit(str(path))
            self.accept()

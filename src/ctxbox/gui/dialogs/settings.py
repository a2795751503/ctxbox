"""设置页占位: 主题 / 语言 / 备份目录展示。"""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from ctxbox.core.utils.paths import ctxbox_data_dir


class SettingsDialog(QDialog):
    """设置对话框 (占位版): 展示为主, 暂无可持久化项。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(520, 260)
        lay = QVBoxLayout(self)

        form = QFormLayout()

        self.theme = QComboBox()
        self.theme.addItems(["深色 (默认)", "浅色 (未实现)"])
        self.theme.setEnabled(False)  # TODO: 浅色主题待实现
        form.addRow("主题", self.theme)

        self.lang = QComboBox()
        self.lang.addItems(["简体中文"])
        self.lang.setEnabled(False)  # TODO: i18n 待实现
        form.addRow("语言", self.lang)

        data_dir = ctxbox_data_dir()
        backup_dir = data_dir / "backups"

        dir_row = QHBoxLayout()
        dir_lab = QLabel(str(backup_dir))
        dir_lab.setStyleSheet("color: #9aa0aa;")
        dir_row.addWidget(dir_lab, 1)
        btn_open = QPushButton("打开文件夹")
        btn_open.clicked.connect(lambda: self._open_dir(str(backup_dir)))
        dir_row.addWidget(btn_open)
        form.addRow("备份目录", dir_row)

        db_lab = QLabel(str(data_dir / "index.db"))
        db_lab.setStyleSheet("color: #9aa0aa;")
        form.addRow("索引数据库", db_lab)

        lay.addLayout(form)

        note = QLabel("提示: 每次写回会话文件前, ctxbox 都会先把原文件备份到上面的备份目录。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #6f747e; font-size: 12px;")
        lay.addWidget(note)
        lay.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(lambda _b: self.reject())
        lay.addWidget(buttons)

    @staticmethod
    def _open_dir(path: str) -> None:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')  # noqa: S605
        else:
            os.system(f'xdg-open "{path}"')  # noqa: S605

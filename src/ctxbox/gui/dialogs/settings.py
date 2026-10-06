"""设置页: 主题切换 (即时生效) / 语言占位 / 备份目录展示。"""

from __future__ import annotations

import os
import sys

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
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

from ..theme import apply_theme, current_theme, tokens

THEMES = [("light", "浅色"), ("dark", "深色")]


class SettingsDialog(QDialog):
    """设置对话框: 主题可切换, 其余为展示/占位。"""

    def __init__(self, parent=None, on_theme_changed=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(540, 480)
        self._on_theme_changed = on_theme_changed
        t = tokens()
        lay = QVBoxLayout(self)

        form = QFormLayout()

        self.theme = QComboBox()
        for key, label in THEMES:
            self.theme.addItem(label, key)
        self.theme.setCurrentIndex(0 if current_theme() == "light" else 1)
        self.theme.currentIndexChanged.connect(self._apply_theme)
        form.addRow("主题", self.theme)

        self.lang = QComboBox()
        self.lang.addItems(["简体中文"])
        self.lang.setEnabled(False)  # TODO: i18n 待实现
        form.addRow("语言", self.lang)

        from PySide6.QtCore import QSettings

        self.diff_confirm = QCheckBox("保存前显示 diff 确认")
        self.diff_confirm.setChecked(
            bool(QSettings("ctxbox", "ctxbox").value("diff_confirm", True, type=bool))
        )
        self.diff_confirm.toggled.connect(
            lambda checked: QSettings("ctxbox", "ctxbox").setValue("diff_confirm", bool(checked))
        )
        form.addRow("写回", self.diff_confirm)

        data_dir = ctxbox_data_dir()
        backup_dir = data_dir / "backups"

        dir_row = QHBoxLayout()
        dir_lab = QLabel(str(backup_dir))
        dir_lab.setStyleSheet(f"color: {t['text_secondary']};")
        dir_row.addWidget(dir_lab, 1)
        btn_open = QPushButton("打开文件夹")
        btn_open.setProperty("kind", "secondary")
        btn_open.clicked.connect(lambda: self._open_dir(str(backup_dir)))
        dir_row.addWidget(btn_open)
        form.addRow("备份目录", dir_row)

        db_lab = QLabel(str(data_dir / "index.db"))
        db_lab.setStyleSheet(f"color: {t['text_secondary']};")
        form.addRow("索引数据库", db_lab)

        lay.addLayout(form)

        # 快捷键一览 (静态展示)
        t_keys = tokens()
        group_title = QLabel("快捷键")
        group_title.setStyleSheet(f"font-weight: 600; color: {t_keys['text']};")
        lay.addWidget(group_title)
        shortcuts = [
            ("Ctrl+F", "聚焦全局搜索框"),
            ("Ctrl+R", "重新扫描本机会话"),
            ("Ctrl+E", "导出当前会话"),
            ("Ctrl+D", "克隆当前会话"),
            ("Delete", "删除当前会话 (会话列表聚焦时)"),
            ("↑ / ↓", "在会话列表中移动选择"),
        ]
        keys_grid = QFormLayout()
        for key, desc in shortcuts:
            key_lab = QLabel(key)
            key_lab.setStyleSheet(
                f"font-family: 'Cascadia Code', Consolas, monospace; color: {t_keys['accent']};"
                f" background: {t_keys['accent_soft']}; border-radius: 4px; padding: 1px 6px;"
            )
            keys_grid.addRow(key_lab, QLabel(desc))
        lay.addLayout(keys_grid)

        note = QLabel("提示: 每次写回会话文件前, ctxbox 都会先把原文件备份到上面的备份目录。")
        note.setWordWrap(True)
        note.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px;")
        lay.addWidget(note)
        lay.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        close_btn = buttons.button(QDialogButtonBox.StandardButton.Close)
        close_btn.setText("关闭")
        close_btn.setProperty("kind", "primary")
        close_btn.style().unpolish(close_btn)
        close_btn.style().polish(close_btn)
        buttons.rejected.connect(self.reject)
        buttons.clicked.connect(lambda _b: self.reject())
        lay.addWidget(buttons)

    def _apply_theme(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        apply_theme(app, self.theme.currentData())
        if callable(self._on_theme_changed):
            self._on_theme_changed()

    @staticmethod
    def _open_dir(path: str) -> None:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')  # noqa: S605
        else:
            os.system(f'xdg-open "{path}"')  # noqa: S605

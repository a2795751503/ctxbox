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
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from ctxbox.core.ai_client import PROMPT_LABELS, PROMPTS
from ctxbox.core.utils.paths import ctxbox_data_dir

from ..ai_support import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    AiWorker,
    load_ai_config,
    save_ai_config,
    start_ai_job,
)
from ..theme import apply_theme, current_theme, tokens

THEMES = [("dark", "深色 (VSCode Dark+)"), ("light", "浅色 (VSCode Light+)")]


class SettingsDialog(QDialog):
    """设置对话框: 主题可切换, 其余为展示/占位。"""

    def __init__(self, parent=None, on_theme_changed=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("设置")
        self.resize(620, 780)
        self._on_theme_changed = on_theme_changed
        t = tokens()
        lay = QVBoxLayout(self)

        form = QFormLayout()

        self.theme = QComboBox()
        for key, label in THEMES:
            self.theme.addItem(label, key)
        self.theme.setCurrentIndex(0 if current_theme() == "dark" else 1)
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

        # ---------------------------- AI 服务 ----------------------------
        ai_group = QGroupBox("AI 服务")
        ai_form = QFormLayout(ai_group)

        st = QSettings("ctxbox", "ctxbox")
        self.ai_base_url = QLineEdit(str(st.value("ai_base_url", DEFAULT_BASE_URL)))
        ai_form.addRow("Base URL", self.ai_base_url)
        self.ai_key = QLineEdit(str(st.value("ai_key", "")))
        self.ai_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ai_key.setPlaceholderText("仅存储在本机 QSettings")
        ai_form.addRow("API Key", self.ai_key)
        self.ai_model = QLineEdit(str(st.value("ai_model", DEFAULT_MODEL)))
        ai_form.addRow("Model", self.ai_model)

        test_row = QHBoxLayout()
        self.btn_ai_test = QPushButton("测试连接")
        self.btn_ai_test.setProperty("kind", "secondary")
        self.btn_ai_test.clicked.connect(self._test_ai)
        test_row.addWidget(self.btn_ai_test)
        self.ai_test_result = QLabel("")
        self.ai_test_result.setWordWrap(True)
        test_row.addWidget(self.ai_test_result, 1)
        ai_form.addRow("", test_row)

        for edit in (self.ai_base_url, self.ai_key, self.ai_model):
            edit.editingFinished.connect(self._save_ai_fields)

        ai_note = QLabel(
            "AI 服务为 ctxbox 唯一的联网功能，仅在你配置后、且只对预览确认的内容发送。"
            "Key 仅存储在本机。"
        )
        ai_note.setWordWrap(True)
        ai_note.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px;")
        ai_form.addRow("", ai_note)

        # 提示词查看
        prompt_row = QHBoxLayout()
        prompt_row.addWidget(QLabel("提示词"))
        self.prompt_combo = QComboBox()
        for key, label in PROMPT_LABELS.items():
            self.prompt_combo.addItem(label, key)
        prompt_row.addWidget(self.prompt_combo, 1)
        ai_form.addRow("", prompt_row)
        self.prompt_view = QPlainTextEdit()
        self.prompt_view.setReadOnly(True)
        self.prompt_view.setMaximumHeight(110)
        self.prompt_view.setStyleSheet("font-size: 12px;")
        self.prompt_combo.currentIndexChanged.connect(self._show_prompt)
        self._show_prompt()
        ai_form.addRow("", self.prompt_view)

        lay.addWidget(ai_group)

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

    # ------------------------------------------------------------- AI --
    def _save_ai_fields(self) -> None:
        save_ai_config(self.ai_base_url.text(), self.ai_key.text(), self.ai_model.text())

    def _show_prompt(self) -> None:
        key = self.prompt_combo.currentData()
        self.prompt_view.setPlainText(PROMPTS.get(key, ""))

    def _test_ai(self) -> None:
        self._save_ai_fields()  # 先持久化当前表单再测
        cfg = load_ai_config()
        if not cfg.enabled:
            self.ai_test_result.setStyleSheet(f"color: {tokens()['danger']};")
            self.ai_test_result.setText("请先填写 API Key")
            return
        self.btn_ai_test.setEnabled(False)
        self.btn_ai_test.setText("测试中…")
        self.ai_test_result.setStyleSheet(f"color: {tokens()['text_secondary']};")
        self.ai_test_result.setText("")

        def _done(result: str) -> None:
            self._ai_test_done()
            self.ai_test_result.setStyleSheet(f"color: {tokens()['success']};")
            self.ai_test_result.setText(f"✓ 连接成功: {result}")

        def _failed(detail: str) -> None:
            self._ai_test_done()
            self.ai_test_result.setStyleSheet(f"color: {tokens()['danger']};")
            self.ai_test_result.setText(f"✗ {detail}")

        worker = AiWorker(cfg, mode="test")
        start_ai_job(self, worker, _done, _failed)

    def _ai_test_done(self) -> None:
        self.btn_ai_test.setEnabled(True)
        self.btn_ai_test.setText("测试连接")

    @staticmethod
    def _open_dir(path: str) -> None:
        if sys.platform.startswith("win"):
            os.startfile(path)  # noqa: S606
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')  # noqa: S605
        else:
            os.system(f'xdg-open "{path}"')  # noqa: S605

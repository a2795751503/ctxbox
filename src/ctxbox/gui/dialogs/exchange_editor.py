"""Exchange 问答对编辑器: 一问一答为一个编辑单元 + AI 优化。

只改写文本 parts (thinking / tool_call / tool_result 一律不动),
保存经主窗口的 diff 确认 + 备份 + 原子写路径。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QToolButton,
    QVBoxLayout,
)

from ctxbox.core.ai_client import PROMPT_LABELS, PROMPTS
from ctxbox.core.exchange import Exchange

from ..ai_support import AiWorker, load_ai_config, start_ai_job
from ..theme import tokens


class PromptPreviewDialog(QDialog):
    """发送前预览: 显示提示词中文名 + 即将发送的完整 prompt。"""

    def __init__(self, prompt_key: str, prompt_text: str, parent=None) -> None:
        super().__init__(parent)
        t = tokens()
        self.setWindowTitle("发送预览")
        self.resize(640, 420)
        lay = QVBoxLayout(self)
        head = QLabel(
            f"{PROMPT_LABELS.get(prompt_key, prompt_key)} — 以下内容将发送到你配置的 AI 服务:"
        )
        head.setStyleSheet(f"font-weight: 600; color: {t['text']};")
        head.setWordWrap(True)
        lay.addWidget(head)
        view = QPlainTextEdit(prompt_text)
        view.setReadOnly(True)
        lay.addWidget(view, 1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("发送")
        ok.setProperty("kind", "primary")
        ok.style().unpolish(ok)
        ok.style().polish(ok)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


class TitleResultDialog(QDialog):
    """make_title 结果: 显示标题 + [应用到会话标题] [复制]。"""

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.title = title
        self.apply_requested = False
        lay = QVBoxLayout(self)
        head = QLabel("AI 生成的标题:")
        lay.addWidget(head)
        lab = QLabel(title)
        lab.setWordWrap(True)
        lab.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lab.setStyleSheet("font-size: 14px; font-weight: 600; padding: 8px;")
        lay.addWidget(lab)
        btn_row = QHBoxLayout()
        btn_apply = QPushButton("应用到会话标题")
        btn_apply.setProperty("kind", "primary")
        btn_apply.clicked.connect(self._apply)
        btn_row.addWidget(btn_apply)
        btn_copy = QPushButton("复制")
        btn_copy.setProperty("kind", "secondary")
        btn_copy.clicked.connect(self._copy)
        btn_row.addWidget(btn_copy)
        btn_close = QPushButton("关闭")
        btn_close.setProperty("kind", "secondary")
        btn_close.clicked.connect(self.reject)
        btn_row.addWidget(btn_close)
        lay.addLayout(btn_row)

    def _apply(self) -> None:
        self.apply_requested = True
        self.accept()

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.title)


class ExchangeEditorDialog(QDialog):
    """编辑一个 Exchange (一问一答)。"""

    def __init__(self, exchange: Exchange, on_apply_title=None, parent=None) -> None:
        super().__init__(parent)
        self.exchange = exchange
        self._on_apply_title = on_apply_title
        t = tokens()
        self.setWindowTitle(f"编辑第 {exchange.index} 轮")
        self.resize(720, 640)
        lay = QVBoxLayout(self)

        # 只读信息行
        stats = exchange.stats()
        info = QLabel(
            f"💭 思考 {stats['thinking']} 块 · ⚡ 工具调用 {stats['tool_calls']} 条"
            f" · 共 {stats['output_turns']} 条输出消息"
            "（这些内容不随编辑器改动）"
        )
        info.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px;")
        lay.addWidget(info)

        # 输入区
        in_title = QLabel("✏️ 输入（用户）")
        in_title.setStyleSheet(f"font-weight: 600; color: {t['text']};")
        lay.addWidget(in_title)
        self.input_edit = QPlainTextEdit(exchange.input_text)
        self.input_edit.setMinimumHeight(120)
        lay.addWidget(self.input_edit, 1)
        if exchange.input is None:
            self.input_edit.setEnabled(False)
            self.input_edit.setPlaceholderText("开场组无用户输入, 不可编辑")

        # 输出区
        out_title = QLabel("🤖 输出（助手）")
        out_title.setStyleSheet(f"font-weight: 600; color: {t['text']};")
        lay.addWidget(out_title)
        self.output_edit = QPlainTextEdit(exchange.output_text)
        self.output_edit.setMinimumHeight(160)
        lay.addWidget(self.output_edit, 2)

        # 底部按钮
        btn_row = QHBoxLayout()
        self.btn_ai = QToolButton()
        self.btn_ai.setText("✨ AI 优化 ▾")
        self.btn_ai.setToolTip("用你配置的 AI 服务优化内容 (发送前会先预览)")
        self.btn_ai.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self.btn_ai)
        for key, label in PROMPT_LABELS.items():
            act = menu.addAction(label)
            act.triggered.connect(lambda _c=False, k=key: self._ai_action(k))
        self.btn_ai.setMenu(menu)
        btn_row.addWidget(self.btn_ai)
        btn_row.addStretch(1)

        btn_cancel = QPushButton("取消")
        btn_cancel.setProperty("kind", "secondary")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        btn_save = QPushButton("保存")
        btn_save.setProperty("kind", "primary")
        btn_save.setDefault(True)
        btn_save.clicked.connect(self._save)
        btn_row.addWidget(btn_save)
        lay.addLayout(btn_row)

    def result_texts(self) -> tuple[str, str]:
        return self.input_edit.toPlainText(), self.output_edit.toPlainText()

    def _save(self) -> None:
        if self.exchange.input is None and not self.output_edit.toPlainText().strip():
            QMessageBox.information(self, "提示", "输出内容为空, 没有可保存的修改。")
            return
        self.accept()

    # ------------------------------------------------------------- AI --
    def _target_edit(self, prompt_key: str) -> QPlainTextEdit:
        return self.input_edit if prompt_key == "optimize_input" else self.output_edit

    def _ai_action(self, prompt_key: str) -> None:
        cfg = load_ai_config()
        if not cfg.enabled:
            QMessageBox.information(
                self,
                "尚未配置 AI 服务",
                "请先在「设置 → AI 服务」里填写 Base URL / API Key / Model。\n\n"
                "AI 服务为 ctxbox 唯一的联网功能, 仅对你预览确认的内容发送。",
            )
            return
        content = self._target_edit(prompt_key).toPlainText().strip()
        if not content:
            QMessageBox.information(self, "提示", "对应编辑框是空的, 没有可发送的内容。")
            return
        prompt_text = PROMPTS[prompt_key].format(content=content)
        preview = PromptPreviewDialog(prompt_key, prompt_text, self)
        if preview.exec() != QDialog.DialogCode.Accepted:
            return
        self._run_ai(cfg, prompt_key, content)

    def _run_ai(self, cfg, prompt_key: str, content: str) -> None:
        self.btn_ai.setEnabled(False)
        self.btn_ai.setText("AI 处理中…")

        def _done(result: str) -> None:
            self._ai_done()
            if prompt_key == "make_title":
                dlg = TitleResultDialog(result.strip(), self)
                dlg.exec()
                if dlg.apply_requested and callable(self._on_apply_title):
                    self._on_apply_title(result.strip())
            else:
                self._target_edit(prompt_key).setPlainText(result)

        def _failed(detail: str) -> None:
            self._ai_done()
            QMessageBox.warning(self, "AI 服务错误", detail)

        worker = AiWorker(cfg, mode="complete", prompt_key=prompt_key, content=content)
        start_ai_job(self, worker, _done, _failed)

    def _ai_done(self) -> None:
        self.btn_ai.setEnabled(True)
        self.btn_ai.setText("✨ AI 优化 ▾")

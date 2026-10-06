"""上下文手术室: 在内存副本上试跑批量操作, 预览影响后再真正写回。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from ctxbox.core.model.schema import Session
from ctxbox.core.surgery import (
    SurgeryReport,
    regex_replace,
    session_tokens,
    slim,
    truncate_to_budget,
)

from ..theme import MONO_FAMILY, tokens

ROLE_FILTER = [("全部", None), ("仅用户", {"user"}), ("仅助手", {"assistant"})]


class SurgeryDialog(QDialog):
    """四个操作卡组: 正则替换 / 瘦身 / 超长截断 / Token 预算。

    每次点[执行]都在 deep copy 上试跑并刷新预览; [应用更改]才把
    试跑结果交给主窗口写回 (走 diff 确认 + 备份 + 原子写路径)。
    """

    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        if parent is None or not hasattr(parent, "apply_surgery_result"):
            raise TypeError("SurgeryDialog 需要带 apply_surgery_result 的 MainWindow 作为 parent")
        self._source = session
        self._trial: Session | None = None  # 最近一次试跑结果
        self._reports: list[SurgeryReport] = []

        t = tokens()
        self.setWindowTitle("🩺 上下文手术室")
        self.resize(680, 640)
        lay = QVBoxLayout(self)

        # 会话信息
        self.info = QLabel(
            f"{session.title or session.id} · {len(session.turns)} 轮"
            f" · 估算 {session_tokens(session):,} tokens"
        )
        self.info.setStyleSheet(f"font-weight: 600; color: {t['text']};")
        lay.addWidget(self.info)

        # 预览
        self.preview = QLabel("尚未执行任何操作 — 点卡组里的「执行」试跑")
        self.preview.setStyleSheet(
            f"color: {t['accent']}; background: {t['accent_soft']};"
            " border-radius: 6px; padding: 6px 10px;"
        )
        lay.addWidget(self.preview)

        # 1) 正则替换
        g1 = QGroupBox("正则替换")
        f1 = QFormLayout(g1)
        self.rx_pattern = QLineEdit()
        self.rx_pattern.setPlaceholderText("例如 sk-[A-Za-z0-9-]+")
        f1.addRow("模式", self.rx_pattern)
        row1 = QHBoxLayout()
        self.rx_repl = QLineEdit()
        self.rx_repl.setPlaceholderText("替换为, 例如 ***REDACTED***")
        row1.addWidget(self.rx_repl, 1)
        self.rx_roles = QComboBox()
        for label, roles in ROLE_FILTER:
            self.rx_roles.addItem(label, roles)
        row1.addWidget(self.rx_roles)
        btn1 = QPushButton("执行")
        btn1.setProperty("kind", "secondary")
        btn1.clicked.connect(self._run_regex)
        row1.addWidget(btn1)
        f1.addRow("替换/角色", row1)
        lay.addWidget(g1)

        # 2) 瘦身
        g2 = QGroupBox("瘦身 (删除大块内容)")
        f2 = QFormLayout(g2)
        self.ck_results = QCheckBox("删除所有工具结果 (tool_result)")
        self.ck_thinking = QCheckBox("删除所有思考块 (thinking)")
        self.ck_calls = QCheckBox("删除所有工具调用 (tool_call)")
        f2.addRow(self.ck_results)
        f2.addRow(self.ck_thinking)
        f2.addRow(self.ck_calls)
        btn2 = QPushButton("执行")
        btn2.setProperty("kind", "secondary")
        btn2.clicked.connect(self._run_slim)
        f2.addRow("", btn2)
        lay.addWidget(g2)

        # 3) 超长截断
        g3 = QGroupBox("超长截断 (钳制单个 part 的最大字符数)")
        f3 = QFormLayout(g3)
        row3 = QHBoxLayout()
        self.sp_chars = QSpinBox()
        self.sp_chars.setRange(100, 1_000_000)
        self.sp_chars.setValue(4000)
        self.sp_chars.setSingleStep(500)
        row3.addWidget(self.sp_chars, 1)
        btn3 = QPushButton("执行")
        btn3.setProperty("kind", "secondary")
        btn3.clicked.connect(self._run_clamp)
        row3.addWidget(btn3)
        f3.addRow("最大字符数", row3)
        lay.addWidget(g3)

        # 4) Token 预算
        g4 = QGroupBox("Token 预算 (保留开头 1 轮 + 最新的若干轮)")
        f4 = QFormLayout(g4)
        row4 = QHBoxLayout()
        self.sp_budget = QSpinBox()
        self.sp_budget.setRange(100, 10_000_000)
        self.sp_budget.setValue(100000)
        self.sp_budget.setSingleStep(10000)
        row4.addWidget(self.sp_budget, 1)
        btn4 = QPushButton("执行")
        btn4.setProperty("kind", "secondary")
        btn4.clicked.connect(self._run_budget)
        row4.addWidget(btn4)
        f4.addRow("预算", row4)
        lay.addWidget(g4)

        # 日志区
        log_title = QLabel("操作日志")
        log_title.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px;")
        lay.addWidget(log_title)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setStyleSheet(f"font-family: {MONO_FAMILY}; font-size: 12px;")
        self.log.setMaximumBlockCount(500)
        lay.addWidget(self.log, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Close
        )
        self.btn_apply = buttons.button(QDialogButtonBox.StandardButton.Apply)
        self.btn_apply.setText("应用更改")
        self.btn_apply.setProperty("kind", "primary")
        self.btn_apply.style().unpolish(self.btn_apply)
        self.btn_apply.style().polish(self.btn_apply)
        self.btn_apply.setEnabled(False)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.clicked.connect(self._on_button)
        lay.addWidget(buttons)

    # ------------------------------------------------------------- 试跑 --
    def _trial_session(self) -> Session:
        """在 (上一次试跑结果 or 源会话) 的深拷贝上继续试跑, 支持叠加。"""
        base = self._trial if self._trial is not None else self._source
        return base.model_copy(deep=True)

    def _report(self, trial: Session, report: SurgeryReport) -> None:
        self._trial = trial
        self._reports.append(report)
        pct = (
            f"(-{100 - report.tokens_after * 100 // report.tokens_before}%)"
            if report.tokens_before
            else ""
        )
        self.preview.setText(
            f"将影响 {report.affected} 处 · token {report.tokens_before:,} → "
            f"{report.tokens_after:,} {pct}"
        )
        self.log.appendPlainText(f"[{report.action}] " + "; ".join(report.details))
        self.btn_apply.setEnabled(True)
        self.info.setText(
            f"{self._source.title or self._source.id} · {len(trial.turns)} 轮"
            f" · 估算 {session_tokens(trial):,} tokens (试跑中)"
        )

    def _run_regex(self) -> None:
        pattern = self.rx_pattern.text()
        if not pattern:
            QMessageBox.information(self, "提示", "请先输入正则模式。")
            return
        try:
            trial = self._trial_session()
            report = regex_replace(
                trial, pattern, self.rx_repl.text(), roles=self.rx_roles.currentData()
            )
        except Exception as exc:  # noqa: BLE001 - 无效正则等
            QMessageBox.warning(self, "执行失败", str(exc))
            return
        self._report(trial, report)

    def _run_slim(self) -> None:
        if not (
            self.ck_results.isChecked() or self.ck_thinking.isChecked() or self.ck_calls.isChecked()
        ):
            QMessageBox.information(self, "提示", "请至少勾选一个要删除的内容类型。")
            return
        trial = self._trial_session()
        report = slim(
            trial,
            drop_tool_results=self.ck_results.isChecked(),
            drop_thinking=self.ck_thinking.isChecked(),
            drop_tool_calls=self.ck_calls.isChecked(),
        )
        self._report(trial, report)

    def _run_clamp(self) -> None:
        trial = self._trial_session()
        report = slim(trial, max_part_chars=self.sp_chars.value())
        self._report(trial, report)

    def _run_budget(self) -> None:
        trial = self._trial_session()
        report = truncate_to_budget(trial, self.sp_budget.value())
        self._report(trial, report)

    # ------------------------------------------------------------- 应用 --
    def _on_button(self, btn) -> None:
        if btn is self.btn_apply:
            if self._trial is None:
                return
            # 交给主窗口: diff 确认 -> 备份 -> 原子写 -> 重载
            if self.parent().apply_surgery_result(self._trial):
                self.log.appendPlainText("[applied] 已写回磁盘")
                self._source = self._trial
                self._trial = None
                self.btn_apply.setEnabled(False)
                self.info.setText(
                    f"{self._source.title or self._source.id} · {len(self._source.turns)} 轮"
                    f" · 估算 {session_tokens(self._source):,} tokens"
                )
        else:
            self.reject()

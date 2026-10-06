"""注入向导: 选目标适配器 -> 预览映射 -> 执行 -> 显示 InjectResult。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from ctxbox.core.adapters.base import all_adapters
from ctxbox.core.model.schema import Role, Session

from .._compat import inject_session

ROLE_CN = {
    Role.USER: "用户",
    Role.ASSISTANT: "助手",
    Role.SYSTEM: "系统",
    Role.TOOL: "工具",
    Role.UNKNOWN: "未知",
}


def role_cn(role) -> str:
    """role 可能是 Role 枚举或纯字符串。"""
    if isinstance(role, Role):
        return ROLE_CN.get(role, role.value)
    return ROLE_CN.get(Role(role)) if role in Role._value2member_map_ else str(role)


class TargetPage(QWizardPage):
    """第 1 步: 选目标适配器 (仅列出 supported_features 含 inject 的) + 目标目录。"""

    def __init__(self) -> None:
        super().__init__()
        self.setTitle("选择目标工具")
        self.setSubTitle("只列出支持注入 (inject) 的适配器。")
        lay = QVBoxLayout(self)

        self.adapters = [a for a in all_adapters() if "inject" in a.supported_features()]
        self.listw = QListWidget()
        for a in self.adapters:
            item = QListWidgetItem(f"{a.display_name}  ({a.name})")
            item.setData(0x0100, a.name)  # Qt.UserRole
            self.listw.addItem(item)
        if self.adapters:
            self.listw.setCurrentRow(0)
        lay.addWidget(self.listw)

        dir_row = QHBoxLayout()
        dir_row.addWidget(QLabel("目标目录 (可留空, 使用默认):"))
        self.dir_edit = QLineEdit()
        self.dir_edit.setPlaceholderText("留空则写入该工具的默认会话目录")
        dir_row.addWidget(self.dir_edit, 1)
        btn = QPushButton("浏览…")
        btn.clicked.connect(self._browse)
        dir_row.addWidget(btn)
        lay.addLayout(dir_row)

    def _browse(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择目标目录")
        if d:
            self.dir_edit.setText(d)

    def selected_adapter_name(self) -> str | None:
        item = self.listw.currentItem()
        return item.data(0x0100) if item else None

    def target_dir(self) -> Path | None:
        text = self.dir_edit.text().strip()
        return Path(text) if text else None


class PreviewPage(QWizardPage):
    """第 2 步: 预览映射 + 降级明细 (core.preview_injection)。"""

    def __init__(self, wizard: InjectWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("预览映射")
        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self.info)
        self.stats = QLabel()
        self.stats.setStyleSheet("font-weight: 600;")
        lay.addWidget(self.stats)
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["轮次", "类型", "处置", "说明", "预览"])
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        lay.addWidget(self.table, 1)

    def initializePage(self) -> None:  # noqa: N802
        from ctxbox.core.inject.engine import preview_injection

        from ..theme import tokens

        t = tokens()
        s: Session = self._wizard.session
        target = self._wizard.target_page.selected_adapter_name()
        target_disp = target or "(未选择)"
        for a in self._wizard.target_page.adapters:
            if a.name == target:
                target_disp = a.display_name
                break
        counts: dict[str, int] = {}
        for turn in s.turns:
            label = role_cn(turn.role)
            counts[label] = counts.get(label, 0) + 1
        role_txt = " / ".join(f"{k} {v}" for k, v in counts.items())
        self.info.setText(
            f"源会话: {s.title or s.id} ({s.source_tool}, {len(s.turns)} 轮 — {role_txt})\n"
            f"目标工具: {target_disp} · 目标目录: {self._wizard.target_page.target_dir() or '(默认)'}"
        )

        try:
            items = preview_injection(s, target)
        except Exception as exc:  # noqa: BLE001
            self.stats.setText(f"⚠ 降级预览失败: {exc}")
            self.table.setRowCount(0)
            return
        n_keep = sum(1 for it in items if it.action == "keep")
        n_degrade = sum(1 for it in items if it.action == "degrade")
        n_drop = sum(1 for it in items if it.action == "drop")
        if n_keep == len(items):
            self.stats.setText(f"共 {len(items)} 块 · 全部原生保留 ✅")
        else:
            self.stats.setText(
                f"共 {len(items)} 块 · 保留 {n_keep} · 降级 {n_degrade} · 丢弃 {n_drop}"
            )
        colors = {"keep": t["success"], "degrade": t["warning"], "drop": t["danger"]}
        labels = {"keep": "保留", "degrade": "降级", "drop": "丢弃"}
        self.table.setRowCount(len(items))
        for i, it in enumerate(items):
            cells = [
                str(it.turn_index + 1),
                it.kind,
                labels.get(it.action, it.action),
                it.note,
                (it.preview or "").replace("\n", " "),
            ]
            for col, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if col == 2:
                    cell.setForeground(QColor(colors.get(it.action, t["text"])))
                self.table.setItem(i, col, cell)

    def isComplete(self) -> bool:  # noqa: N802
        return self._wizard.target_page.selected_adapter_name() is not None


class ResultPage(QWizardPage):
    """第 3 步: 执行注入并显示 InjectResult。"""

    def __init__(self, wizard: InjectWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("执行注入")
        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self.info)
        lay.addStretch(1)
        self._ran = False

    def initializePage(self) -> None:  # noqa: N802
        if self._ran:
            return
        self._ran = True
        s = self._wizard.session
        target = self._wizard.target_page.selected_adapter_name()
        self.info.setText("正在注入…")
        try:
            result = inject_session(s, target, self._wizard.target_page.target_dir())
        except Exception as exc:  # noqa: BLE001
            self.info.setText(f"❌ 注入过程发生异常:\n{exc}")
            return
        if result.ok:
            lines = ["✅ 注入成功!", "", f"新会话文件: {result.path}"]
            written = getattr(result, "turns_written", None)
            if written is not None:
                lines.append(f"写入轮数: {written}")
            for w in result.warnings or []:
                lines.append(f"⚠ {w}")
            lines += ["", "提示: 重新扫描后可在列表中看到注入的新会话。"]
            self.info.setText("\n".join(lines))
        else:
            self.info.setText(f"❌ 注入失败:\n{result.error or '未知错误'}")

    def isComplete(self) -> bool:  # noqa: N802
        return True


class InjectWizard(QWizard):
    """注入向导主窗口。"""

    def __init__(self, session: Session, parent=None) -> None:
        super().__init__(parent)
        self.session = session
        self.setWindowTitle("注入会话到目标工具")
        self.resize(560, 460)
        self.target_page = TargetPage()
        self.preview_page = PreviewPage(self)
        self.result_page = ResultPage(self)
        self.addPage(self.target_page)
        self.addPage(self.preview_page)
        self.addPage(self.result_page)
        self.setButtonText(QWizard.WizardButton.NextButton, "下一步 >")
        self.setButtonText(QWizard.WizardButton.BackButton, "< 上一步")
        self.setButtonText(QWizard.WizardButton.FinishButton, "完成")
        self.setButtonText(QWizard.WizardButton.CancelButton, "取消")

"""注入向导: 选目标适配器 -> 预览映射 -> 执行 -> 显示 InjectResult。"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
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
    """第 2 步: 预览映射。"""

    def __init__(self, wizard: InjectWizard) -> None:
        super().__init__()
        self._wizard = wizard
        self.setTitle("预览映射")
        lay = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.PlainText)
        lay.addWidget(self.info)
        lay.addStretch(1)

    def initializePage(self) -> None:  # noqa: N802
        s: Session = self._wizard.session
        target = self._wizard.target_page.selected_adapter_name()
        counts: dict[str, int] = {}
        kinds: dict[str, int] = {}
        for t in s.turns:
            label = role_cn(t.role)
            counts[label] = counts.get(label, 0) + 1
            for p in t.parts:
                kinds[p.kind] = kinds.get(p.kind, 0) + 1
        role_txt = " / ".join(f"{k} {v}" for k, v in counts.items())
        kind_txt = ", ".join(f"{k}×{v}" for k, v in sorted(kinds.items()))
        target_disp = target or "(未选择)"
        for a in self._wizard.target_page.adapters:
            if a.name == target:
                target_disp = a.display_name
                break
        lines = [
            f"源会话: {s.title or s.id}",
            f"来源工具: {s.source_tool}",
            f"源文件: {s.source_path or '—'}",
            "",
            f"目标工具: {target_disp}",
            f"目标目录: {self._wizard.target_page.target_dir() or '(默认)'}",
            "",
            f"共 {len(s.turns)} 轮 ({role_txt})",
            f"内容类型: {kind_txt or '无'}",
            "",
            "映射说明: 每轮将按目标工具的格式转换; 目标不支持的内容类型会尽量降级为文本,",
            "原始数据保留在 raw/meta 中, 不会丢失。",
        ]
        if s.parse_warnings:
            lines.append("")
            lines.append(f"⚠ 解析警告 {len(s.parse_warnings)} 条 (详情见会话 meta)")
        self.info.setText("\n".join(lines))

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

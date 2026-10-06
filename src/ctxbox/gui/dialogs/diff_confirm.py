"""写回前的 Diff 确认对话框。

对 (磁盘上的旧会话, 内存中的新会话) 逐轮文本生成 unified diff,
+行绿底 / -行红底 高亮; 取消则完全不动磁盘。
"""

from __future__ import annotations

import difflib
from pathlib import Path

from PySide6.QtCore import QSettings
from PySide6.QtGui import QFont, QTextCharFormat, QTextFormat
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QTextEdit,
    QVBoxLayout,
)

from ctxbox.core.model.schema import Session

from ..theme import MONO_FAMILY, tokens


def diff_confirm_enabled() -> bool:
    """设置开关: 保存前显示 diff 确认 (默认开)。"""
    return bool(QSettings("ctxbox", "ctxbox").value("diff_confirm", True, type=bool))


def session_to_lines(session: Session) -> list[str]:
    """会话 -> 逐轮 'role: text' 行, 用于 diff。"""
    lines = []
    for i, turn in enumerate(session.turns):
        text = (turn.text() or "").replace("\n", " ⏎ ")
        lines.append(f"[{i + 1}] {turn.role.value}: {text}")
    return lines


def make_diff(old: Session, new: Session) -> tuple[str, int]:
    """返回 (diff 文本, 变更轮数)。变更轮数按 +/- 行估算。"""
    diff_lines = list(
        difflib.unified_diff(
            session_to_lines(old),
            session_to_lines(new),
            fromfile="磁盘现况",
            tofile="修改后",
            lineterm="",
            n=1,
        )
    )
    changed = sum(
        1
        for ln in diff_lines
        if (ln.startswith("+") or ln.startswith("-")) and not ln.startswith(("+++", "---"))
    )
    return "\n".join(diff_lines), changed


class DiffConfirmDialog(QDialog):
    """写回确认: 操作描述 + diff 视图 + 统计 + [取消][确认写入]。"""

    def __init__(
        self,
        old_session: Session,
        new_session: Session,
        description: str,
        target_path: Path,
        parent=None,
    ) -> None:
        super().__init__(parent)
        t = tokens()
        self.setWindowTitle("确认写回")
        self.resize(760, 560)
        lay = QVBoxLayout(self)

        desc = QLabel(f"{description} · 备份将自动创建")
        desc.setStyleSheet(f"font-weight: 600; color: {t['text']};")
        lay.addWidget(desc)

        diff_text, changed = make_diff(old_session, new_session)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        font = QFont("Cascadia Code")
        font.setStyleHint(QFont.StyleHint.Monospace)
        self.view.setFont(font)
        self.view.setStyleSheet(f"font-family: {MONO_FAMILY};")
        self.view.setPlainText(diff_text or "(无可视差异 — 仅元数据变化)")
        lay.addWidget(self.view, 1)

        # 逐行刷色: + 绿 / - 红 (全行背景)
        selections = []
        add_fmt = QTextCharFormat()
        add_fmt.setBackground(_rgba(t["success"], 0.14))
        add_fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)
        del_fmt = QTextCharFormat()
        del_fmt.setBackground(_rgba(t["danger"], 0.14))
        del_fmt.setProperty(QTextFormat.Property.FullWidthSelection, True)
        head_fmt = QTextCharFormat()
        head_fmt.setForeground(_rgba(t["accent"], 1.0))
        doc = self.view.document()
        block = doc.firstBlock()
        while block.isValid():
            ln = block.text()
            fmt = None
            if ln.startswith(("+++", "---", "@@")):
                fmt = head_fmt
            elif ln.startswith("+"):
                fmt = add_fmt
            elif ln.startswith("-"):
                fmt = del_fmt
            if fmt is not None:
                sel = QTextEdit.ExtraSelection()
                sel.format = fmt
                cursor = self.view.textCursor()
                cursor.setPosition(block.position())
                sel.cursor = cursor
                sel.cursor.clearSelection()
                selections.append(sel)
            block = block.next()
        self.view.setExtraSelections(selections)

        stats = QLabel(
            f"{max(changed // 2, 1) if diff_text else 0} 轮变更 · 将写入 {target_path.name}"
        )
        stats.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px;")
        lay.addWidget(stats)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setText("确认写入")
        ok_btn.setProperty("kind", "primary")
        ok_btn.style().unpolish(ok_btn)
        ok_btn.style().polish(ok_btn)
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)


def _rgba(hex_color: str, alpha: float):
    from PySide6.QtGui import QColor

    c = QColor(hex_color)
    c.setAlphaF(alpha)
    return c


def confirm_save(
    parent,
    old_session: Session,
    new_session: Session,
    description: str,
    target_path: Path,
) -> bool:
    """统一入口: 开关关 -> 直接 True; 开关开 -> 弹对话框, 确认才 True。"""
    if not diff_confirm_enabled():
        return True
    dlg = DiffConfirmDialog(old_session, new_session, description, target_path, parent)
    return dlg.exec() == QDialog.DialogCode.Accepted

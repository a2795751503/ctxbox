"""编辑单轮 Turn 的对话框: role 选择 + 多 part 文本编辑。"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ctxbox.core.model.schema import ContentPart, Role, Turn

PART_KINDS = [
    "text",
    "code",
    "thinking",
    "tool_call",
    "tool_result",
    "image",
    "file_ref",
    "diff",
    "error",
    "raw",
]
ROLE_ITEMS = [
    (Role.USER, "用户"),
    (Role.ASSISTANT, "助手"),
    (Role.SYSTEM, "系统"),
    (Role.TOOL, "工具"),
    (Role.UNKNOWN, "未知"),
]


class PartEditor(QFrame):
    """一个 ContentPart 的编辑行: kind + 语言/工具名 + 正文 + 删除。"""

    def __init__(self, part: ContentPart, on_remove, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            "PartEditor { background: #22232a; border: 1px solid #2e3038; border-radius: 6px; }"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(4)

        top = QHBoxLayout()
        top.addWidget(QLabel("类型"))
        self.kind = QComboBox()
        self.kind.addItems(PART_KINDS)
        idx = PART_KINDS.index(part.kind) if part.kind in PART_KINDS else 0
        self.kind.setCurrentIndex(idx)
        top.addWidget(self.kind)

        top.addWidget(QLabel("工具名"))
        self.tool_name = QLineEdit(part.tool_name or "")
        self.tool_name.setPlaceholderText("tool_call / tool_result 用")
        top.addWidget(self.tool_name, 1)

        top.addWidget(QLabel("语言"))
        self.language = QLineEdit(part.language or "")
        self.language.setPlaceholderText("code 用")
        self.language.setMaximumWidth(90)
        top.addWidget(self.language)

        btn_del = QPushButton("删除此 part")
        btn_del.clicked.connect(lambda: on_remove(self))
        top.addWidget(btn_del)
        lay.addLayout(top)

        self.text = QPlainTextEdit(part.text or "")
        self.text.setPlaceholderText("正文内容…")
        self.text.setMinimumHeight(80)
        lay.addWidget(self.text)

    def to_part(self, old: ContentPart | None = None) -> ContentPart:
        """生成新的 ContentPart。

        raw 是原工具的原始记录, 仅当用户没有改动任何字段时才保留
        (core 序列化器见到 raw 会原样回写, 改动过的 part 必须丢弃 raw 才能生效)。
        """
        kind = self.kind.currentText()
        text = self.text.toPlainText()
        tool_name = self.tool_name.text().strip() or None
        language = self.language.text().strip() or None
        unchanged = (
            old is not None
            and old.kind == kind
            and (old.text or "") == text
            and old.tool_name == tool_name
            and old.language == language
        )
        return ContentPart(
            kind=kind,
            text=text,
            tool_name=tool_name,
            language=language,
            raw=old.raw if unchanged else None,
        )


class TurnEditorDialog(QDialog):
    """编辑单轮: role 下拉 + part 编辑器列表。"""

    def __init__(self, turn: Turn, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑对话轮次")
        self.resize(640, 560)
        self._turn = turn
        self._editors: list[PartEditor] = []

        lay = QVBoxLayout(self)

        form = QFormLayout()
        self.role = QComboBox()
        for role, label in ROLE_ITEMS:
            self.role.addItem(label, role)
        cur = next((i for i, (r, _) in enumerate(ROLE_ITEMS) if r == turn.role), 4)
        self.role.setCurrentIndex(cur)
        form.addRow("角色", self.role)

        self.model = QLineEdit(turn.model or "")
        self.model.setPlaceholderText("模型名 (可留空)")
        form.addRow("模型", self.model)
        lay.addLayout(form)

        meta_bits = []
        if turn.timestamp:
            meta_bits.append(f"时间: {turn.timestamp.strftime('%Y-%m-%d %H:%M:%S')}")
        if turn.tokens_in is not None or turn.tokens_out is not None:
            meta_bits.append(f"tokens: {turn.tokens_in or 0} 入 / {turn.tokens_out or 0} 出")
        if meta_bits:
            info = QLabel(" · ".join(meta_bits))
            info.setStyleSheet("color: #9aa0aa; font-size: 12px;")
            lay.addWidget(info)

        # parts 滚动区
        self._parts_container = QWidget()
        self._parts_lay = QVBoxLayout(self._parts_container)
        self._parts_lay.setContentsMargins(0, 0, 0, 0)
        self._parts_lay.setSpacing(6)
        self._parts_lay.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._parts_container)
        lay.addWidget(scroll, 1)

        for part in turn.parts:
            self._add_editor(part)
        if not turn.parts:
            self._add_editor(ContentPart(kind="text", text=""))

        btn_add = QPushButton("＋ 添加 part")
        btn_add.clicked.connect(lambda: self._add_editor(ContentPart(kind="text", text="")))
        lay.addWidget(btn_add)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _add_editor(self, part: ContentPart) -> None:
        ed = PartEditor(part, self._remove_editor)
        self._editors.append(ed)
        self._parts_lay.insertWidget(self._parts_lay.count() - 1, ed)

    def _remove_editor(self, ed: PartEditor) -> None:
        if len(self._editors) <= 1:
            QMessageBox.information(self, "提示", "至少保留一个 part。")
            return
        self._editors.remove(ed)
        ed.setParent(None)
        ed.deleteLater()

    def _on_accept(self) -> None:
        if all(not ed.text.toPlainText().strip() for ed in self._editors):
            QMessageBox.warning(self, "无法保存", "所有 part 的正文均为空。")
            return
        self.accept()

    def apply_to(self, turn: Turn) -> None:
        """把编辑结果写回 Turn (就地修改), 并打上 _edited 标记。"""
        role = self.role.currentData()
        turn.role = role if isinstance(role, Role) else Role(role)
        turn.model = self.model.text().strip() or None
        old_parts = turn.parts
        new_parts: list[ContentPart] = []
        for i, ed in enumerate(self._editors):
            old = old_parts[i] if i < len(old_parts) else None
            new_parts.append(ed.to_part(old))
        turn.parts = new_parts
        turn.meta["_edited"] = True

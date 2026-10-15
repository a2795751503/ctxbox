"""供应商配置中心页 (CC Switch 风格): 预设卡片 + 一键切换 + 当前配置。

所有读写走 core.providers; 除「启用」外均为只读操作。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
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
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core import providers
from ...core.providers import PresetStore, ProviderPreset
from ..theme import TOOL_COLORS, tokens


class PresetEditorDialog(QDialog):
    """新建/编辑预设的表单弹窗。"""

    def __init__(self, tool: str, preset: ProviderPreset | None = None, parent=None) -> None:
        super().__init__(parent)
        self.tool = tool
        self.preset = preset or ProviderPreset(tool=tool, name="")
        self.setWindowTitle("编辑预设" if preset else "新建预设")
        self.setMinimumWidth(460)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.ed_name = QLineEdit(self.preset.name)
        self.ed_name.setPlaceholderText("例如: 中转A / 官方 / 本地 vLLM")
        form.addRow("预设名称 *", self.ed_name)

        self.ed_base = QLineEdit(self.preset.base_url)
        self.ed_base.setPlaceholderText(
            "https://api.anthropic.com" if tool == "claude-code" else "https://your-relay.com/v1"
        )
        form.addRow("Base URL *", self.ed_base)

        self.ed_key = QLineEdit(self.preset.api_key)
        self.ed_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.ed_key.setPlaceholderText("sk-…")
        form.addRow("API Key", self.ed_key)

        self.ed_model = QLineEdit(self.preset.model)
        self.ed_model.setPlaceholderText("claude-opus-4-8" if tool == "claude-code" else "gpt-6.1")
        form.addRow("模型", self.ed_model)

        if tool == "codex":
            self.ed_wire = QComboBox()
            self.ed_wire.addItems(["responses", "chat"])
            self.ed_wire.setCurrentText(self.preset.wire_api or "responses")
            form.addRow("Wire API", self.ed_wire)

        self.ed_notes = QLineEdit(self.preset.notes)
        self.ed_notes.setPlaceholderText("备注 (可选)")
        form.addRow("备注", self.ed_notes)
        lay.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)

    def _save(self) -> None:
        if not self.ed_name.text().strip() or not self.ed_base.text().strip():
            QMessageBox.warning(self, "缺少必填项", "预设名称和 Base URL 不能为空。")
            return
        p = self.preset
        p.name = self.ed_name.text().strip()
        p.base_url = self.ed_base.text().strip().rstrip("/")
        p.api_key = self.ed_key.text().strip()
        p.model = self.ed_model.text().strip()
        p.notes = self.ed_notes.text().strip()
        if self.tool == "codex":
            p.wire_api = self.ed_wire.currentText()
        self.accept()


class PresetCard(QFrame):
    """一张预设卡片: 名称+使用中徽章 / URL / 模型 / [启用][编辑][删除]。"""

    applyClicked = Signal(object)
    editClicked = Signal(object)
    deleteClicked = Signal(object)

    def __init__(self, preset: ProviderPreset, active: bool, parent=None) -> None:
        super().__init__(parent)
        self.preset = preset
        self.setObjectName("presetCard")
        t = tokens()
        brand = TOOL_COLORS.get(preset.tool, "#6b7280")
        border = t["accent"] if active else t["border"]
        self.setStyleSheet(
            f"#presetCard {{ background: {t['card']}; border: {'2' if active else '1'}px"
            f" solid {border}; border-radius: 12px; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)

        row1 = QHBoxLayout()
        name = QLabel(preset.name)
        name.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {t['text']};")
        row1.addWidget(name)
        if active:
            badge = QLabel("✓ 使用中")
            badge.setStyleSheet(
                f"background: {t['accent_soft']}; color: {t['accent']};"
                " border-radius: 8px; padding: 2px 8px; font-size: 11px; font-weight: 600;"
            )
            row1.addWidget(badge)
        row1.addStretch(1)
        tool_pill = QLabel(providers.TOOL_LABELS.get(preset.tool, preset.tool))
        tool_pill.setStyleSheet(
            f"background: {brand}; color: #ffffff; font-size: 10px;"
            " border-radius: 9px; padding: 2px 8px; font-weight: 600;"
        )
        row1.addWidget(tool_pill)
        lay.addLayout(row1)

        url = QLabel(preset.base_url)
        url.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px;")
        lay.addWidget(url)
        meta_bits = []
        if preset.model:
            meta_bits.append(f"模型: {preset.model}")
        if preset.tool == "codex":
            meta_bits.append(f"wire: {preset.wire_api}")
        meta_bits.append(f"Key: {preset.masked_key()}")
        if preset.notes:
            meta_bits.append(preset.notes)
        meta = QLabel(" · ".join(meta_bits))
        meta.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px;")
        lay.addWidget(meta)

        row3 = QHBoxLayout()
        btn_apply = QPushButton("⚡ 启用")
        btn_apply.setProperty("kind", "primary")
        btn_apply.setToolTip("写入该工具的真实配置文件 (自动备份) 并立即生效")
        btn_apply.clicked.connect(lambda: self.applyClicked.emit(self.preset))
        row3.addWidget(btn_apply)
        btn_edit = QPushButton("✏️ 编辑")
        btn_edit.setProperty("kind", "secondary")
        btn_edit.clicked.connect(lambda: self.editClicked.emit(self.preset))
        row3.addWidget(btn_edit)
        btn_del = QPushButton("🗑 删除")
        btn_del.setProperty("kind", "secondary")
        btn_del.setToolTip("只删除预设, 不影响工具当前配置")
        btn_del.clicked.connect(lambda: self.deleteClicked.emit(self.preset))
        row3.addWidget(btn_del)
        row3.addStretch(1)
        lay.addLayout(row3)


class ProvidersPage(QWidget):
    """供应商配置中心主页面。"""

    statusMessage = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.store = PresetStore()
        self.tool = "claude-code"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(12)

        # 顶部: 工具切换 + 新建
        top = QHBoxLayout()
        self.tool_buttons: dict[str, QPushButton] = {}
        for tool, label in providers.TOOL_LABELS.items():
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(tool == self.tool)
            btn.clicked.connect(lambda _=False, t=tool: self._switch_tool(t))
            self.tool_buttons[tool] = btn
            top.addWidget(btn)
        top.addStretch(1)
        btn_new = QPushButton("＋ 新建预设")
        btn_new.setProperty("kind", "primary")
        btn_new.clicked.connect(self._new_preset)
        top.addWidget(btn_new)
        lay.addLayout(top)

        # 当前生效配置面板
        self.current_panel = QLabel()
        self.current_panel.setWordWrap(True)
        self.current_panel.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        t = tokens()
        self.current_panel.setStyleSheet(
            f"background: {t['bubble_tool_bg']}; border: 1px solid {t['border']};"
            f" border-radius: 10px; padding: 12px; color: {t['text_secondary']};"
            " font-size: 12px;"
        )
        lay.addWidget(self.current_panel)

        # 快捷操作行: 存为预设 / 导出 / 导入
        quick = QHBoxLayout()
        btn_snapshot = QPushButton("💾 从当前配置存为预设")
        btn_snapshot.setProperty("kind", "secondary")
        btn_snapshot.setToolTip("把上面显示的真实配置直接保存成一个预设, 免手填")
        btn_snapshot.clicked.connect(self._save_current_as_preset)
        quick.addWidget(btn_snapshot)
        btn_export = QPushButton("📤 导出预设")
        btn_export.setProperty("kind", "secondary")
        btn_export.setToolTip("把当前工具的预设导出为 JSON, 可分享给别人")
        btn_export.clicked.connect(self._export_presets)
        quick.addWidget(btn_export)
        btn_import = QPushButton("📥 导入预设")
        btn_import.setProperty("kind", "secondary")
        btn_import.setToolTip("从 JSON 文件导入预设 (id 冲突自动换新, 不覆盖已有)")
        btn_import.clicked.connect(self._import_presets)
        quick.addWidget(btn_import)
        quick.addStretch(1)
        lay.addLayout(quick)

        # 预设卡片列表 (滚动区)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_container = QWidget()
        self._list_lay = QVBoxLayout(self._list_container)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(10)
        self._list_lay.addStretch(1)
        scroll.setWidget(self._list_container)
        lay.addWidget(scroll, 1)

        self.reload()

    def _switch_tool(self, tool: str) -> None:
        self.tool = tool
        for name, btn in self.tool_buttons.items():
            btn.setChecked(name == tool)
        self.reload()

    def reload(self) -> None:
        """重读当前配置 + 预设列表 (只读)。"""
        try:
            current = providers.read_current(self.tool)
            key = current.get("api_key") or ""
            masked = (
                f"{key[:4]}…{key[-4:]}" if len(key) > 8 else ("(未设置)" if not key else "****")
            )
            self.current_panel.setText(
                f"<b>当前生效配置</b> · {providers.TOOL_LABELS[self.tool]}<br>"
                f"Base URL: {current.get('base_url') or '(官方默认)'}<br>"
                f"模型: {current.get('model') or '(默认)'} · Key: {masked}<br>"
                f"<span style='opacity:0.7'>配置文件: {current.get('path')}</span>"
            )
        except Exception as exc:  # noqa: BLE001
            self.current_panel.setText(f"读取当前配置失败: {exc}")

        active_id = providers.active_preset_id(self.tool, self.store)
        while self._list_lay.count() > 1:  # 保留底部 stretch
            item = self._list_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        presets = self.store.list(self.tool)
        if not presets:
            t = tokens()
            empty = QLabel("还没有预设。点右上角「＋ 新建预设」添加一个供应商/中转站。")
            empty.setStyleSheet(f"color: {t['text_muted']}; padding: 20px;")
            self._list_lay.insertWidget(0, empty)
        for i, p in enumerate(presets):
            card = PresetCard(p, active=(p.id == active_id))
            card.applyClicked.connect(self._apply)
            card.editClicked.connect(self._edit)
            card.deleteClicked.connect(self._delete)
            self._list_lay.insertWidget(i, card)

    # ------------------------------------------------------------- 操作 --
    def _new_preset(self) -> None:
        dlg = PresetEditorDialog(self.tool, parent=self)
        if dlg.exec():
            self.store.upsert(dlg.preset)
            self.reload()
            self.statusMessage.emit(f"已保存预设「{dlg.preset.name}」")

    def _edit(self, preset: ProviderPreset) -> None:
        dlg = PresetEditorDialog(self.tool, preset=preset, parent=self)
        if dlg.exec():
            self.store.upsert(dlg.preset)
            self.reload()

    def _delete(self, preset: ProviderPreset) -> None:
        ret = QMessageBox.question(
            self,
            "删除预设",
            f"删除预设「{preset.name}」?\n只删除预设, 不会影响该工具当前生效的配置。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret == QMessageBox.StandardButton.Yes:
            self.store.delete(preset.id)
            self.reload()

    def _apply(self, preset: ProviderPreset) -> None:
        ret = QMessageBox.question(
            self,
            "启用供应商",
            f"将「{preset.name}」写入 {providers.TOOL_LABELS[preset.tool]} 的真实配置?\n\n"
            f"Base URL: {preset.base_url}\n模型: {preset.model or '(默认)'}\n\n"
            "写入前会自动备份原配置, 其余配置项保持不变。\n重启对应工具后完全生效。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        try:
            path = providers.apply_preset(preset)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "启用失败", str(exc))
            return
        self.reload()
        self.statusMessage.emit(f"已切换到「{preset.name}」 · 配置已备份 · {path}")

    # ------------------------------------------------- 存为预设/导入导出 --
    def _save_current_as_preset(self) -> None:
        preset = providers.preset_from_current(self.tool)
        dlg = PresetEditorDialog(self.tool, preset=preset, parent=self)
        dlg.setWindowTitle("从当前配置存为预设")
        if dlg.exec():
            self.store.upsert(dlg.preset)
            self.reload()
            self.statusMessage.emit(f"已把当前配置保存为预设「{dlg.preset.name}」")

    def _export_presets(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getSaveFileName(
            self, "导出预设", f"ctxbox-presets-{self.tool}.json", "JSON (*.json)"
        )
        if not path:
            return
        try:
            n = providers.export_presets(Path(path), self.store, self.tool)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "导出失败", str(exc))
            return
        self.statusMessage.emit(f"已导出 {n} 个预设到 {path}")

    def _import_presets(self) -> None:
        from pathlib import Path

        from PySide6.QtWidgets import QFileDialog

        path, _ = QFileDialog.getOpenFileName(self, "导入预设", "", "JSON (*.json)")
        if not path:
            return
        try:
            n = providers.import_presets(Path(path), self.store)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "导入失败", str(exc))
            return
        self.reload()
        self.statusMessage.emit(f"已导入 {n} 个预设 (id 冲突已自动换新)")

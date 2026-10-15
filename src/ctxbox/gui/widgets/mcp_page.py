"""MCP 服务器管理页: 列表 / 新建 / 编辑 / 删除 (Claude Code + Codex)。

读写全部走 core.mcp; 编辑弹窗里 args 每行一个参数, env 每行 KEY=VALUE。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
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

from ...core import mcp
from ...core.mcp import McpServer
from ...core.providers import TOOL_LABELS
from ..theme import TOOL_COLORS, tokens


def _parse_env(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"环境变量格式应为 KEY=VALUE: {line}")
        k, _, v = line.partition("=")
        env[k.strip()] = v
    return env


class McpEditorDialog(QDialog):
    def __init__(self, tool: str, server: McpServer | None = None, parent=None) -> None:
        super().__init__(parent)
        self.tool = tool
        self.server = server or McpServer(name="", tool=tool)
        self.setWindowTitle("编辑 MCP 服务器" if server else "新建 MCP 服务器")
        self.setMinimumWidth(520)
        lay = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.ed_name = QLineEdit(self.server.name)
        self.ed_name.setPlaceholderText("例如: filesystem / ida-pro-mcp")
        if server:
            self.ed_name.setReadOnly(True)  # 名称即主键, 编辑时不可改
        form.addRow("名称 *", self.ed_name)

        self.ed_command = QLineEdit(self.server.command)
        self.ed_command.setPlaceholderText("python / node / npx / 可执行文件绝对路径")
        form.addRow("启动命令 *", self.ed_command)

        self.ed_args = QPlainTextEdit("\n".join(self.server.args))
        self.ed_args.setPlaceholderText("每行一个参数, 例如:\nD:/tools/server.py\n--port\n8080")
        self.ed_args.setMaximumHeight(90)
        form.addRow("参数 (每行一个)", self.ed_args)

        env_text = "\n".join(f"{k}={v}" for k, v in self.server.env.items())
        self.ed_env = QPlainTextEdit(env_text)
        self.ed_env.setPlaceholderText("每行 KEY=VALUE (可留空)")
        self.ed_env.setMaximumHeight(70)
        form.addRow("环境变量", self.ed_env)

        if tool == "codex":
            self.ed_timeout = QLineEdit(
                ""
                if self.server.startup_timeout_sec is None
                else str(self.server.startup_timeout_sec)
            )
            self.ed_timeout.setPlaceholderText("启动超时秒数 (可留空)")
            form.addRow("启动超时 (秒)", self.ed_timeout)
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
        try:
            env = _parse_env(self.ed_env.toPlainText())
        except ValueError as exc:
            QMessageBox.warning(self, "环境变量格式错误", str(exc))
            return
        s = self.server
        s.name = self.ed_name.text().strip()
        s.command = self.ed_command.text().strip()
        s.args = [x.strip() for x in self.ed_args.toPlainText().splitlines() if x.strip()]
        s.env = env
        if self.tool == "codex":
            raw = self.ed_timeout.text().strip()
            try:
                s.startup_timeout_sec = float(raw) if raw else None
            except ValueError:
                QMessageBox.warning(self, "格式错误", "启动超时必须是数字。")
                return
        if not s.name or not s.command:
            QMessageBox.warning(self, "缺少必填项", "名称和启动命令不能为空。")
            return
        self.accept()


class McpCard(QFrame):
    editClicked = Signal(object)
    deleteClicked = Signal(object)

    def __init__(self, server: McpServer, parent=None) -> None:
        super().__init__(parent)
        self.server = server
        self.setObjectName("mcpCard")
        t = tokens()
        brand = TOOL_COLORS.get(server.tool, "#6b7280")
        self.setStyleSheet(
            f"#mcpCard {{ background: {t['card']}; border: 1px solid {t['border']};"
            " border-radius: 12px; }}"
        )
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 12, 16, 12)
        lay.setSpacing(6)

        row1 = QHBoxLayout()
        name = QLabel(f"🧩 {server.name}")
        name.setStyleSheet(f"font-size: 14px; font-weight: 600; color: {t['text']};")
        row1.addWidget(name)
        row1.addStretch(1)
        pill = QLabel(TOOL_LABELS.get(server.tool, server.tool))
        pill.setStyleSheet(
            f"background: {brand}; color: #ffffff; font-size: 10px;"
            " border-radius: 9px; padding: 2px 8px; font-weight: 600;"
        )
        row1.addWidget(pill)
        lay.addLayout(row1)

        cmd = QLabel(server.summary())
        cmd.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px;")
        cmd.setWordWrap(True)
        lay.addWidget(cmd)

        bits = [f"{len(server.args)} 个参数", f"{len(server.env)} 个环境变量"]
        if server.startup_timeout_sec is not None:
            bits.append(f"超时 {server.startup_timeout_sec:g}s")
        meta = QLabel(" · ".join(bits))
        meta.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px;")
        lay.addWidget(meta)

        row3 = QHBoxLayout()
        btn_edit = QPushButton("✏️ 编辑")
        btn_edit.setProperty("kind", "secondary")
        btn_edit.clicked.connect(lambda: self.editClicked.emit(self.server))
        row3.addWidget(btn_edit)
        btn_del = QPushButton("🗑 删除")
        btn_del.setProperty("kind", "secondary")
        btn_del.clicked.connect(lambda: self.deleteClicked.emit(self.server))
        row3.addWidget(btn_del)
        row3.addStretch(1)
        lay.addLayout(row3)


class McpPage(QWidget):
    statusMessage = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.tool = "claude-code"
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 12, 20, 12)
        lay.setSpacing(12)

        top = QHBoxLayout()
        self.tool_buttons: dict[str, QPushButton] = {}
        for tool, label in TOOL_LABELS.items():
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setChecked(tool == self.tool)
            btn.clicked.connect(lambda _=False, t=tool: self._switch_tool(t))
            self.tool_buttons[tool] = btn
            top.addWidget(btn)
        top.addStretch(1)
        btn_new = QPushButton("＋ 新建 MCP")
        btn_new.setProperty("kind", "primary")
        btn_new.clicked.connect(self._new_server)
        top.addWidget(btn_new)
        lay.addLayout(top)

        hint = QLabel("写入真实配置文件前自动备份; 重启对应工具后生效。")
        t = tokens()
        hint.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px;")
        lay.addWidget(hint)

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
        while self._list_lay.count() > 1:
            item = self._list_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        try:
            servers = mcp.list_servers(self.tool)
        except Exception as exc:  # noqa: BLE001
            self.statusMessage.emit(f"读取 MCP 配置失败: {exc}")
            servers = []
        if not servers:
            t = tokens()
            empty = QLabel("该工具还没有 MCP 服务器。点右上角「＋ 新建 MCP」添加。")
            empty.setStyleSheet(f"color: {t['text_muted']}; padding: 20px;")
            self._list_lay.insertWidget(0, empty)
        for i, s in enumerate(servers):
            card = McpCard(s)
            card.editClicked.connect(self._edit)
            card.deleteClicked.connect(self._delete)
            self._list_lay.insertWidget(i, card)

    def _new_server(self) -> None:
        dlg = McpEditorDialog(self.tool, parent=self)
        if dlg.exec():
            try:
                path = mcp.upsert_server(self.tool, dlg.server)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "保存失败", str(exc))
                return
            self.reload()
            self.statusMessage.emit(f"已保存 MCP「{dlg.server.name}」 · 已备份 · {path}")

    def _edit(self, server: McpServer) -> None:
        dlg = McpEditorDialog(self.tool, server=server, parent=self)
        if dlg.exec():
            try:
                mcp.upsert_server(self.tool, dlg.server)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.critical(self, "保存失败", str(exc))
                return
            self.reload()

    def _delete(self, server: McpServer) -> None:
        ret = QMessageBox.question(
            self,
            "删除 MCP 服务器",
            f"从 {TOOL_LABELS[self.tool]} 的配置中删除「{server.name}」?\n"
            "只删配置项, 不会删除服务器程序文件。原配置自动备份。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        try:
            mcp.delete_server(self.tool, server.name)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "删除失败", str(exc))
            return
        self.reload()
        self.statusMessage.emit(f"已删除 MCP「{server.name}」 · 已备份")

"""ctxbox 主窗口: 左窄导航栏 | 中(会话卡片列表) | 右(对话时间线)。"""

from __future__ import annotations

import contextlib
import traceback
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ctxbox.core.adapters.base import all_adapters, get_adapter
from ctxbox.core.model.schema import ContentPart, Role, Session, Turn
from ctxbox.core.utils.atomic import atomic_write
from ctxbox.core.utils.paths import ctxbox_data_dir

from ._compat import SessionIndex, export_session
from .dialogs.inject_wizard import InjectWizard
from .dialogs.settings import SettingsDialog
from .theme import TOOL_ICONS
from .widgets.dashboard import DashboardWidget
from .widgets.nav_rail import NavRail
from .widgets.session_list import SessionListWidget
from .widgets.timeline import TimelineWidget
from .widgets.turn_editor import TurnEditorDialog


# ------------------------------------------------------------ 后台扫描线程 --
class ScanWorker(QObject):
    """在后台线程里跑 SessionIndex.rescan, 不阻塞 UI。

    用独立的 SessionIndex 实例, 避免 sqlite 连接跨线程问题。
    """

    progress = Signal(int, int)  # done, total
    finished_ok = Signal(int)  # 会话总数
    failed = Signal(str)

    def run(self) -> None:
        idx = None
        try:
            idx = SessionIndex()
            # progress_cb 签名以 core 实现为准 (可能带 tool 名等额外参数),
            # 约定最后两个参数是 (done, total)
            n = idx.rescan(progress_cb=lambda *a: self.progress.emit(int(a[-2]), int(a[-1])))
            self.finished_ok.emit(n)
        except Exception:  # noqa: BLE001
            self.failed.emit(traceback.format_exc(limit=5))
        finally:
            if idx is not None:
                with contextlib.suppress(Exception):
                    idx.close()


# --------------------------------------------------------------- 导出对话框 --
class ExportDialog(QDialog):
    """导出选项: 格式 + 脱敏开关。"""

    FORMATS = [("md", "Markdown (*.md)"), ("json", "JSON (*.json)"), ("jsonl", "JSONL (*.jsonl)")]

    def __init__(self, title: str, parent=None, md_only: bool = False) -> None:
        super().__init__(parent)
        self.setWindowTitle("导出会话")
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.fmt = QComboBox()
        for key, label in self.FORMATS:
            self.fmt.addItem(label, key)
        if md_only:
            self.fmt.setCurrentIndex(0)
            self.fmt.setEnabled(False)
        form.addRow("格式", self.fmt)
        self.redact = QCheckBox("导出前脱敏 (token / 密钥 / 邮箱)")
        form.addRow("", self.redact)
        lay.addLayout(form)
        lab = QLabel(f"会话: {title}")
        lab.setStyleSheet("color: #9aa0aa;")
        lay.addWidget(lab)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("选择保存位置…")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        lay.addWidget(buttons)
        ok_btn = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok_btn.setProperty("kind", "primary")
        ok_btn.style().unpolish(ok_btn)
        ok_btn.style().polish(ok_btn)

    def chosen(self) -> tuple[str, bool]:
        return self.fmt.currentData(), self.redact.isChecked()


# ----------------------------------------------------------------- 主窗口 --
class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("ctxbox — AI 上下文管理器")
        self.resize(1280, 800)

        self.idx: SessionIndex | None = None
        self.current_session: Session | None = None
        self.current_tool_filter: str | None = None
        self._all_rows: list[dict] = []
        self._searching = False
        self._scan_thread: QThread | None = None
        self._scan_worker: ScanWorker | None = None

        self._build_ui()
        self._init_index()

    # ---------------------------------------------------------------- UI --
    def _build_ui(self) -> None:
        central = QWidget()
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶栏: 页面标题 -> 胶囊搜索框 -> [扫描][导出][注入]
        header = QWidget()
        header.setObjectName("pageHeader")
        hb = QHBoxLayout(header)
        hb.setContentsMargins(16, 10, 16, 10)
        hb.setSpacing(10)

        title = QLabel("会话")
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        hb.addWidget(title)

        self.search_edit = QLineEdit()
        self.search_edit.setObjectName("capsuleSearch")
        self.search_edit.setPlaceholderText("🔍 全局搜索 (回车搜索, 清空恢复)…")
        self.search_edit.setToolTip("全文搜索所有会话内容 (Ctrl+F)")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.returnPressed.connect(self._on_search)
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        hb.addWidget(self.search_edit, 1)

        self.btn_scan = QPushButton("🔄 扫描")
        self.btn_scan.setProperty("kind", "secondary")
        self.btn_scan.setToolTip("重新扫描本机所有 AI 工具的会话 (Ctrl+R)")
        self.btn_scan.clicked.connect(self.start_scan)
        hb.addWidget(self.btn_scan)

        btn_export = QPushButton("📤 导出")
        btn_export.setProperty("kind", "secondary")
        btn_export.setToolTip("导出当前会话为 Markdown / JSON / JSONL (Ctrl+E)")
        btn_export.clicked.connect(self._on_export_current)
        hb.addWidget(btn_export)

        btn_inject = QPushButton("💉 注入")
        btn_inject.setProperty("kind", "primary")
        btn_inject.setToolTip("把当前会话注入到另一个 AI 工具")
        btn_inject.clicked.connect(self._on_inject_current)
        hb.addWidget(btn_inject)
        root.addWidget(header)

        # 主体: 左窄导航栏 | 中列表 | 右时间线
        body = QHBoxLayout()
        body.setContentsMargins(8, 0, 0, 0)
        body.setSpacing(0)

        self.nav = NavRail()
        self.nav.filterChanged.connect(self._on_nav_filter)
        self.nav.settingsRequested.connect(self._on_settings)
        body.addWidget(self.nav)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        self.center_stack = QStackedWidget()
        self.center_empty = self._make_empty(
            "💬", "暂无会话\n\n点击顶部「扫描」发现本机 AI 工具的会话。"
        )
        self.session_list = SessionListWidget()
        self.session_list.openRequested.connect(self.open_session)
        self.session_list.contextAction.connect(self._on_session_action)
        self.center_stack.addWidget(self.center_empty)
        self.center_stack.addWidget(self.session_list)
        splitter.addWidget(self.center_stack)

        self.right_stack = QStackedWidget()
        self.dashboard = DashboardWidget()
        self.dashboard.openRequested.connect(self.open_session)
        self.dashboard.scanRequested.connect(self.start_scan)
        self.dashboard.searchRequested.connect(self.focus_search)
        self.right_loading = self._make_empty("⏳", "加载中…")
        self.timeline = TimelineWidget()
        self.timeline.editRequested.connect(self._edit_turn)
        self.timeline.contextAction.connect(self._on_turn_action)
        self.right_stack.addWidget(self.dashboard)
        self.right_stack.addWidget(self.right_loading)
        self.right_stack.addWidget(self.timeline)
        self.right_stack.setCurrentWidget(self.dashboard)
        splitter.addWidget(self.right_stack)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([430, 650])
        body.addWidget(splitter, 1)
        root.addLayout(body, 1)
        self.setCentralWidget(central)

        # 状态栏: 右侧灰色小字 = 总数 + 索引路径; 扫描时加不确定进度条
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 0)  # indeterminate
        self.scan_progress.setFixedWidth(140)
        self.scan_progress.setTextVisible(False)
        self.scan_progress.hide()
        self.statusBar().addPermanentWidget(self.scan_progress)
        db_path = ctxbox_data_dir() / "index.db"
        self.status_total = QLabel(f"共 0 个会话 · 索引: {db_path}")
        self.statusBar().addPermanentWidget(self.status_total)
        self.statusBar().showMessage("就绪")

        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        """全局快捷键 (挂在主窗口; Delete 只挂在会话列表上, 避免抢编辑器按键)。"""
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self.focus_search)
        QShortcut(QKeySequence("Ctrl+R"), self, activated=self.start_scan)
        QShortcut(QKeySequence("Ctrl+E"), self, activated=self._on_export_current)
        QShortcut(QKeySequence("Ctrl+D"), self, activated=self._on_clone_current)
        QShortcut(
            QKeySequence(Qt.Key.Key_Delete),
            self.session_list,
            activated=self._on_delete_current,
        )

    def focus_search(self) -> None:
        """Ctrl+F / 仪表盘「全局搜索」: 聚焦搜索框并全选。"""
        self.search_edit.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search_edit.selectAll()

    @staticmethod
    def _make_empty(emoji: str, text: str) -> QLabel:
        """空状态: 大号 emoji + 灰色提示文字, 居中。"""
        lab = QLabel(f"{emoji}\n\n{text}")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setStyleSheet("color: #9ca3af; font-size: 14px; line-height: 1.6;")
        return lab

    def _init_index(self) -> None:
        try:
            self.idx = SessionIndex()
            names = self._tool_display_names()
            self.session_list.set_tool_display_names(names)
            self.dashboard.set_tool_display_names(names)
            self.refresh()
        except Exception as exc:  # noqa: BLE001
            self._error("初始化索引失败", exc)

    # ------------------------------------------------------------- helpers --
    def _tool_display_names(self) -> dict[str, str]:
        try:
            # 导航栏/卡片 pill 用短名: "Codex CLI / Desktop" -> "Codex CLI"
            return {a.name: a.display_name.split(" / ")[0] for a in all_adapters()}
        except Exception:  # noqa: BLE001
            return {}

    def _error(self, title: str, exc: BaseException | str) -> None:
        QMessageBox.critical(self, title, str(exc))

    def _require_idx(self) -> SessionIndex:
        if self.idx is None:
            raise RuntimeError("索引未初始化")
        return self.idx

    def _visible_rows(self) -> list[dict]:
        if self.current_tool_filter:
            return [r for r in self._all_rows if r["source_tool"] == self.current_tool_filter]
        return list(self._all_rows)

    # ---------------------------------------------------------------- 刷新 --
    def refresh(self) -> None:
        """重新读取索引并重建导航栏 + 中栏。"""
        try:
            idx = self._require_idx()
            self._all_rows = idx.sessions()
        except Exception as exc:  # noqa: BLE001
            self._error("读取会话索引失败", exc)
            return

        # 左窄导航栏: "📋 全部" + 按 source_tool 分组计数
        disp = self._tool_display_names()
        counts: dict[str, int] = {}
        for r in self._all_rows:
            counts[r["source_tool"]] = counts.get(r["source_tool"], 0) + 1
        items: list[tuple[str | None, str, str, int]] = [(None, "📋", "全部", len(self._all_rows))]
        for tool in sorted(counts):
            items.append((tool, TOOL_ICONS.get(tool, "🗂️"), disp.get(tool, tool), counts[tool]))
        if self.current_tool_filter and self.current_tool_filter not in counts:
            self.current_tool_filter = None  # 当前过滤的工具已没有会话, 回退到全部
        self.nav.set_tools(items, self.current_tool_filter)

        if not self._searching:
            self._populate_center()
        self._update_status_total()
        with contextlib.suppress(Exception):
            self.dashboard.refresh_data(idx)  # 仪表盘统计同步刷新

    def _update_status_total(self) -> None:
        db_path = ctxbox_data_dir() / "index.db"
        self.status_total.setText(f"共 {len(self._all_rows)} 个会话 · 索引: {db_path}")

    def _populate_center(self) -> None:
        rows = self._visible_rows()
        if rows:
            self.session_list.set_rows(rows)
            self.center_stack.setCurrentWidget(self.session_list)
        else:
            self.center_stack.setCurrentWidget(self.center_empty)

    # ---------------------------------------------------------------- 扫描 --
    def start_scan(self) -> None:
        if self._scan_thread is not None:
            return  # 已在扫描
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("⏳ 扫描中…")
        self.scan_progress.show()
        self.statusBar().showMessage("正在扫描本机 AI 工具会话…")

        self._scan_thread = QThread(self)
        self._scan_worker = ScanWorker()
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.progress.connect(self._on_scan_progress)
        self._scan_worker.finished_ok.connect(self._on_scan_done)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.finished_ok.connect(self._scan_thread.quit)
        self._scan_worker.failed.connect(self._scan_thread.quit)
        self._scan_thread.finished.connect(self._scan_cleanup)
        self._scan_thread.start()

    def _on_scan_progress(self, done: int, total: int) -> None:
        self.statusBar().showMessage(f"正在扫描… {done}/{total}")

    def _on_scan_done(self, count: int) -> None:
        self.statusBar().showMessage(f"扫描完成, 共发现 {count} 个会话", 8000)
        try:
            if self.idx is not None:
                self.idx.close()
        except Exception:  # noqa: BLE001
            pass
        self.idx = None
        try:
            self.idx = SessionIndex()  # 重建索引连接, 读取最新数据
        except Exception as exc:  # noqa: BLE001
            self._error("重建索引失败", exc)
        self.refresh()

    def _on_scan_failed(self, detail: str) -> None:
        self.statusBar().showMessage("扫描失败", 8000)
        self._error("扫描失败", detail)

    def _scan_cleanup(self) -> None:
        self.btn_scan.setEnabled(True)
        self.btn_scan.setText("🔄 扫描")
        self.scan_progress.hide()
        if self._scan_worker is not None:
            self._scan_worker.deleteLater()
        if self._scan_thread is not None:
            self._scan_thread.deleteLater()
        self._scan_worker = None
        self._scan_thread = None

    # ---------------------------------------------------------------- 搜索 --
    def _on_search(self) -> None:
        query = self.search_edit.text().strip()
        if not query:
            self._clear_search()
            return
        try:
            rows = self._require_idx().search(query)
        except Exception as exc:  # noqa: BLE001
            self._error("搜索失败", exc)
            return
        self._searching = True
        if rows:
            self.session_list.set_rows(rows, search_mode=True)
            self.center_stack.setCurrentWidget(self.session_list)
        else:
            self.center_empty.setText(f"🔍\n\n没有找到匹配「{query}」的会话")
            self.center_stack.setCurrentWidget(self.center_empty)
        self.statusBar().showMessage(f"搜索「{query}」: 命中 {len(rows)} 条", 8000)

    def _on_search_text_changed(self, text: str) -> None:
        if not text.strip() and self._searching:
            self._clear_search()

    def _clear_search(self) -> None:
        self._searching = False
        self.center_empty.setText("💬\n\n暂无会话\n\n点击顶部「扫描」发现本机 AI 工具的会话。")
        self._populate_center()
        self.statusBar().showMessage("就绪")

    # ------------------------------------------------------------- 导航栏 --
    def _on_nav_filter(self, tool: str | None) -> None:
        self.current_tool_filter = tool
        if self._searching:
            return
        self._populate_center()

    # --------------------------------------------------------- 打开会话 --
    def open_session(self, session_id: str) -> None:
        """先显示加载占位, 下一拍再解析渲染 (大文件 parse 可能几百 ms)。"""
        self.right_stack.setCurrentWidget(self.right_loading)
        QTimer.singleShot(0, lambda: self._load_and_render(session_id))

    def _load_and_render(self, session_id: str) -> None:
        try:
            session = self._require_idx().load_session(session_id)
        except Exception as exc:  # noqa: BLE001
            self.right_stack.setCurrentWidget(self.dashboard)
            self._error("加载会话失败", exc)
            return
        self.current_session = session
        self.timeline.set_turns(session.turns)
        self.right_stack.setCurrentWidget(self.timeline)
        warns = len(session.parse_warnings or [])
        title = session.title or session.id
        msg = f"已打开: {title} ({len(session.turns)} 轮)"
        if warns:
            msg += f" · ⚠ {warns} 条解析警告"
        self.statusBar().showMessage(msg, 8000)

    # ------------------------------------------------------ 会话级右键动作 --
    def _on_session_action(self, action: str, session_id: str) -> None:
        try:
            if action == "open":
                self.open_session(session_id)
            elif action == "copy":
                self._copy_full(session_id)
            elif action == "clone":
                self._clone_session(session_id)
            elif action == "delete":
                self._delete_session(session_id)
            elif action == "export_md":
                self._export_session(session_id, md_only=True)
            elif action == "inject":
                self._inject_session(session_id)
        except Exception as exc:  # noqa: BLE001
            self._error("操作失败", exc)

    def _copy_full(self, session_id: str) -> None:
        session = self._require_idx().load_session(session_id)
        chunks = []
        for t in session.turns:
            text = t.text()
            if text.strip():
                chunks.append(f"[{t.role.value}]\n{text}")
        QApplication.clipboard().setText("\n\n".join(chunks))
        self.statusBar().showMessage("已复制会话全文到剪贴板", 5000)

    def _clone_session(self, session_id: str) -> None:
        session = self._require_idx().load_session(session_id)
        adapter = get_adapter(session.source_tool)
        if "inject" not in adapter.supported_features():
            QMessageBox.information(
                self, "无法克隆", f"{adapter.display_name} 暂不支持写回, 无法克隆。"
            )
            return
        session.title = (session.title or "会话") + "（副本）"
        dest = adapter.inject(session)
        QMessageBox.information(
            self, "克隆成功", f"已克隆为新会话文件:\n{dest}\n\n重新扫描后可见。"
        )
        self.start_scan()

    def _delete_session(self, session_id: str) -> None:
        row = next((r for r in self._all_rows if r["id"] == session_id), None)
        title = (row or {}).get("title") or session_id
        ret = QMessageBox.question(
            self,
            "删除会话",
            f"确定从索引中删除「{title}」吗?\n\n只会删除索引记录, 不会删除源文件。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ret != QMessageBox.StandardButton.Yes:
            return
        idx = self._require_idx()
        # TODO: core 的 SessionIndex 删除接口名以最终实现为准, 这里做兼容探测
        # 真实实现 remove_session(session_id, tool) 需要工具名; stub 的 delete_session 只需 id
        tool = (row or {}).get("source_tool")
        removed = False
        for name in ("delete_session", "remove_session", "delete"):
            deleter = getattr(idx, name, None)
            if deleter is None:
                continue
            try:
                deleter(session_id, tool) if tool else deleter(session_id)
            except TypeError:
                deleter(session_id)
            removed = True
            break
        if not removed:
            raise RuntimeError("core 的 SessionIndex 暂未提供删除接口 (TODO)")
        if self.current_session and self.current_session.id == session_id:
            self.current_session = None
            self.right_stack.setCurrentWidget(self.dashboard)
        self.statusBar().showMessage("已从索引删除 (源文件保留)", 5000)
        self.refresh()

    def _export_session(self, session_id: str, md_only: bool = False) -> None:
        session = self._require_idx().load_session(session_id)
        dlg = ExportDialog(session.title or session.id, self, md_only=md_only)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        fmt, redact = dlg.chosen()
        filt = {"md": "Markdown (*.md)", "json": "JSON (*.json)", "jsonl": "JSONL (*.jsonl)"}[fmt]
        path, _ = QFileDialog.getSaveFileName(
            self, "导出会话", f"ctxbox-{session.id[:8]}.{fmt}", filt
        )
        if not path:
            return
        if not path.lower().endswith(f".{fmt}"):
            path += f".{fmt}"
        text = export_session(session, fmt=fmt, redact=redact)
        atomic_write(Path(path), text.encode("utf-8"))
        self.statusBar().showMessage(f"已导出到 {path}", 8000)

    def _inject_session(self, session_id: str) -> None:
        session = self._require_idx().load_session(session_id)
        wizard = InjectWizard(session, self)
        wizard.exec()

    # ------------------------------------------------------------ 顶栏动作 --
    def _current_or_selected_session_id(self) -> str | None:
        if self.current_session is not None:
            return self.current_session.id
        return self.session_list.current_session_id()

    def _on_export_current(self) -> None:
        sid = self._current_or_selected_session_id()
        if not sid:
            self.statusBar().showMessage("请先在中间栏选择一个会话", 4000)
            return
        try:
            self._export_session(sid)
        except Exception as exc:  # noqa: BLE001
            self._error("导出失败", exc)

    def _on_clone_current(self) -> None:
        sid = self._current_or_selected_session_id()
        if not sid:
            self.statusBar().showMessage("请先在中间栏选择一个会话", 4000)
            return
        try:
            self._clone_session(sid)
        except Exception as exc:  # noqa: BLE001
            self._error("克隆失败", exc)

    def _on_delete_current(self) -> None:
        sid = self._current_or_selected_session_id()
        if not sid:
            self.statusBar().showMessage("请先在中间栏选择一个会话", 4000)
            return
        try:
            self._delete_session(sid)
        except Exception as exc:  # noqa: BLE001
            self._error("删除失败", exc)

    def _on_inject_current(self) -> None:
        sid = self._current_or_selected_session_id()
        if not sid:
            self.statusBar().showMessage("请先在中间栏选择一个会话", 4000)
            return
        try:
            self._inject_session(sid)
        except Exception as exc:  # noqa: BLE001
            self._error("注入失败", exc)

    def _on_settings(self) -> None:
        SettingsDialog(self, on_theme_changed=self._on_theme_changed).exec()

    def _on_theme_changed(self) -> None:
        """主题切换后: 卡片/气泡/仪表盘用的是构造时取色的内联样式, 需要重建。"""
        self.refresh()  # refresh 内部会重建导航栏/卡片并刷新仪表盘
        self.timeline.retheme()
        if self.current_session is not None:
            self.timeline.set_turns(self.current_session.turns)

    # ------------------------------------------------------------- 写回 --
    def _save_session(self) -> None:
        """统一保存路径: 备份源文件 -> adapter.serialize -> 原子写回。"""
        s = self.current_session
        if s is None:
            return
        if not s.source_path:
            raise RuntimeError("该会话没有源文件路径, 无法写回。")
        idx = self._require_idx()
        idx.backup_file(Path(s.source_path))
        adapter = get_adapter(s.source_tool)
        data = adapter.serialize(s)
        atomic_write(Path(s.source_path), data)
        self.statusBar().showMessage("已保存 (原文件已备份)", 5000)

    def _save_and_reload(self) -> None:
        self._save_session()
        sid = self.current_session.id
        self._load_and_render(sid)  # 同步重载, 保证后续操作立刻拿到最新 turn id
        self.refresh()  # 轮数/时间可能变化

    # -------------------------------------------------------- 轮级动作 --
    def _turn_index(self, turn_id: str) -> int:
        s = self.current_session
        for i, t in enumerate(s.turns):
            if t.id == turn_id:
                return i
        raise KeyError(f"找不到轮次 {turn_id}")

    def _edit_turn(self, turn_id: str) -> None:
        s = self.current_session
        if s is None:
            return
        turn = s.get_turn(turn_id)
        if turn is None:
            return
        dlg = TurnEditorDialog(turn, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            dlg.apply_to(turn)  # 就地修改 + meta["_edited"]=True
            self._save_and_reload()
        except Exception as exc:  # noqa: BLE001
            self._error("保存失败", exc)

    def _on_turn_action(self, action: str, turn_id: str) -> None:
        s = self.current_session
        if s is None:
            return
        try:
            self._do_turn_action(s, action, turn_id)
        except Exception as exc:  # noqa: BLE001
            self._error("操作失败", exc)

    def _do_turn_action(self, s: Session, action: str, turn_id: str) -> None:
        if action == "edit":
            self._edit_turn(turn_id)
            return
        if action == "copy_text":
            turn = s.get_turn(turn_id)
            if turn:
                QApplication.clipboard().setText(turn.text())
                self.statusBar().showMessage("已复制该轮文本", 4000)
            return

        idx = self._turn_index(turn_id)

        if action in ("insert_above", "insert_below"):
            at = idx if action == "insert_above" else idx + 1
            new_turn = Turn(
                id=str(uuid.uuid4()),
                role=Role.USER,
                parts=[ContentPart(kind="text", text="")],
            )
            s.insert_turn(new_turn, at)
            dlg = TurnEditorDialog(new_turn, self)
            if dlg.exec() == QDialog.DialogCode.Accepted:
                dlg.apply_to(new_turn)
                self._save_and_reload()
            else:
                s.delete_turn(new_turn.id)  # 取消则回滚, 不落盘
            return

        if action == "delete":
            turn = s.get_turn(turn_id)
            preview = (turn.text() or "")[:60] if turn else ""
            ret = QMessageBox.question(
                self,
                "删除此轮",
                f"确定删除该轮吗?\n{preview}…\n\n(保存前会自动备份源文件)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret == QMessageBox.StandardButton.Yes:
                s.delete_turn(turn_id)
                self._save_and_reload()
            return

        if action == "clone_turn":
            s.clone_turn(turn_id)
            self._save_and_reload()
            return

        if action == "move_up":
            if idx == 0:
                self.statusBar().showMessage("已经是第一轮", 3000)
                return
            s.move_turn(turn_id, idx - 1)
            self._save_and_reload()
            return

        if action == "move_down":
            if idx >= len(s.turns) - 1:
                self.statusBar().showMessage("已经是最后一轮", 3000)
                return
            s.move_turn(turn_id, idx + 1)
            self._save_and_reload()
            return

        if action == "merge_next":
            if idx >= len(s.turns) - 1:
                self.statusBar().showMessage("没有下一轮可合并", 3000)
                return
            nxt = s.turns[idx + 1]
            if not s.merge_turns(turn_id, nxt.id):
                QMessageBox.information(self, "无法合并", "只能合并角色相同的两轮。")
                return
            self._save_and_reload()
            return

    # ------------------------------------------------------------- 关闭 --
    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            if self._scan_thread is not None:
                self._scan_thread.quit()
                self._scan_thread.wait(3000)
            if self.idx is not None:
                self.idx.close()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)

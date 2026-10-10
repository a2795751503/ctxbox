"""ctxbox 主窗口: 左窄导航栏 | 中(会话卡片列表) | 右(对话时间线)。"""

from __future__ import annotations

import contextlib
import traceback
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QThread, Signal
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
from .dialogs.diff_confirm import confirm_save
from .dialogs.exchange_editor import ExchangeEditorDialog
from .dialogs.inject_wizard import InjectWizard
from .dialogs.settings import SettingsDialog
from .dialogs.snapshots import SnapshotsDialog
from .dialogs.surgery import SurgeryDialog
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

    def __init__(self, tool: str | None = None) -> None:
        super().__init__()
        self.tool = tool  # None=全盘; 传适配器名则只扫该底座

    def run(self) -> None:
        idx = None
        try:
            idx = SessionIndex()
            # progress_cb 签名以 core 实现为准 (可能带 tool 名等额外参数),
            # 约定最后两个参数是 (done, total)
            n = idx.rescan(
                progress_cb=lambda *a: self.progress.emit(int(a[-2]), int(a[-1])),
                tool=self.tool,
            )
            self.finished_ok.emit(n)
        except Exception:  # noqa: BLE001
            self.failed.emit(traceback.format_exc(limit=5))
        finally:
            if idx is not None:
                with contextlib.suppress(Exception):
                    idx.close()


# ------------------------------------------------------------ 后台解析线程 --
class ParseWorker(QObject):
    """后台线程 parse 会话 (大文件几秒), 完成把 Session 发回主线程。

    用独立的 SessionIndex 实例, 避免 sqlite 连接跨线程共享;
    pydantic Session 对象可跨线程传递。generation 用于丢弃过期结果。
    """

    loaded = Signal(int, object)  # generation, Session
    failed = Signal(int, str)  # generation, 错误详情

    def __init__(
        self,
        generation: int,
        *,
        session_id: str | None = None,
        file_path: str | None = None,
        tool: str | None = None,
    ) -> None:
        super().__init__()
        self.generation = generation
        self.session_id = session_id
        self.file_path = file_path
        self.tool = tool

    def run(self) -> None:
        idx = None
        try:
            if self.session_id is not None:
                idx = SessionIndex()
                session = idx.load_session(self.session_id)
            else:
                session = get_adapter(self.tool).parse(Path(self.file_path))
            self.loaded.emit(self.generation, session)
        except Exception:  # noqa: BLE001
            self.failed.emit(self.generation, traceback.format_exc(limit=5))
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
        self._load_gen = 0  # 加载代次: 丢弃过期的后台解析结果
        self._load_threads: list[QThread] = []
        self._load_workers: list[ParseWorker] = []  # 持引用防 GC
        self._pending_focus: int | None = None
        self._cursor_depth = 0

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
        self.btn_scan.setToolTip(
            "重新扫描本机所有 AI 工具的会话 (Ctrl+R)\n单独重扫某个底座: 左侧导航栏右键该工具"
        )
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
        self.nav.rescanRequested.connect(lambda tool: self.start_scan(tool))
        body.addWidget(self.nav)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 中栏: 工具条 ([☑ 批量] [🗂 按项目分组]) + 列表
        center_col = QWidget()
        center_lay = QVBoxLayout(center_col)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(4)

        self.center_toolbar = QWidget()
        ctb = QHBoxLayout(self.center_toolbar)
        ctb.setContentsMargins(8, 2, 8, 2)
        ctb.setSpacing(8)
        self.btn_batch = QPushButton("☑ 批量")
        self.btn_batch.setProperty("kind", "secondary")
        self.btn_batch.setCheckable(True)
        self.btn_batch.setToolTip("进入批量勾选模式, 可批量删除会话")
        self.btn_batch.toggled.connect(self._on_batch_toggled)
        ctb.addWidget(self.btn_batch)
        self.btn_group = QPushButton("🗂 按项目分组")
        self.btn_group.setProperty("kind", "primary")
        self.btn_group.setCheckable(True)
        self.btn_group.setChecked(True)
        self.btn_group.setToolTip("在项目分组视图和平铺列表之间切换")
        self.btn_group.toggled.connect(self._on_group_toggled)
        ctb.addWidget(self.btn_group)
        ctb.addStretch(1)
        center_lay.addWidget(self.center_toolbar)

        self.center_stack = QStackedWidget()
        self.center_empty = self._make_empty(
            "💬", "暂无会话\n\n点击顶部「扫描」发现本机 AI 工具的会话。"
        )
        self.session_list = SessionListWidget()
        self.session_list.openRequested.connect(self.open_session)
        self.session_list.contextAction.connect(self._on_session_action)
        self.session_list.projectDeleteRequested.connect(self._delete_project)
        self.session_list.batchDeleteRequested.connect(self._delete_batch)
        self.session_list.batchModeChanged.connect(self._sync_batch_button)
        self.center_stack.addWidget(self.center_empty)
        self.center_stack.addWidget(self.session_list)
        center_lay.addWidget(self.center_stack, 1)
        splitter.addWidget(center_col)

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
    def start_scan(self, tool: str | None = None) -> None:
        if self._scan_thread is not None:
            return  # 已在扫描
        label = f"「{tool}」" if tool else "全部底座"
        self.btn_scan.setEnabled(False)
        self.btn_scan.setText("⏳ 扫描中…")
        self.scan_progress.show()
        self._cursor_wait()
        self.statusBar().showMessage(f"正在扫描{label}…")

        self._scan_thread = QThread(self)
        self._scan_worker = ScanWorker(tool=tool)
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
        self._cursor_restore()
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
        # 搜索模式强制平铺, 隐藏分组/批量切换
        self.center_toolbar.hide()
        if self.btn_batch.isChecked():
            self.btn_batch.setChecked(False)
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
        self.center_toolbar.show()
        self.center_empty.setText("💬\n\n暂无会话\n\n点击顶部「扫描」发现本机 AI 工具的会话。")
        self._populate_center()
        self.statusBar().showMessage("就绪")

    # ------------------------------------------------------- 中栏工具条 --
    def _on_batch_toggled(self, checked: bool) -> None:
        self.session_list.set_batch_mode(checked)
        self._restyle_toggle(self.btn_batch, checked)

    def _on_group_toggled(self, checked: bool) -> None:
        self.session_list.set_grouped(checked)
        self._restyle_toggle(self.btn_group, checked)

    @staticmethod
    def _restyle_toggle(btn: QPushButton, active: bool) -> None:
        btn.setProperty("kind", "primary" if active else "secondary")
        btn.style().unpolish(btn)
        btn.style().polish(btn)

    def _sync_batch_button(self, enabled: bool) -> None:
        """session_list 内部退出批量 (Esc/✕) 时同步工具条按钮态。"""
        if self.btn_batch.isChecked() != enabled:
            self.btn_batch.setChecked(enabled)

    # ------------------------------------------------------------- 导航栏 --
    def _on_nav_filter(self, tool: str | None) -> None:
        self.current_tool_filter = tool
        if self._searching:
            return
        self._populate_center()

    # --------------------------------------------------------- 打开会话 --
    def open_session(self, session_id: str) -> None:
        """显示加载占位, 后台线程 parse 后回主线程渲染。"""
        self._start_load(session_id=session_id)

    def _start_load(
        self,
        *,
        session_id: str | None = None,
        file_path: str | None = None,
        tool: str | None = None,
        focus_turn_index: int | None = None,
    ) -> None:
        self._load_gen += 1
        gen = self._load_gen
        self._pending_focus = focus_turn_index
        self.right_stack.setCurrentWidget(self.right_loading)
        self._cursor_wait()

        thread = QThread(self)
        worker = ParseWorker(gen, session_id=session_id, file_path=file_path, tool=tool)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.loaded.connect(self._on_session_loaded)
        worker.failed.connect(self._on_load_failed)
        worker.loaded.connect(thread.quit)
        worker.failed.connect(thread.quit)
        # 关键: 主线程必须持有 worker 引用直到结束, 否则会被 GC 中途回收
        self._load_workers.append(worker)
        self._load_threads.append(thread)
        thread.finished.connect(lambda: self._load_threads.remove(thread))
        thread.finished.connect(lambda: self._load_workers.remove(worker))
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.start()

    def _on_session_loaded(self, gen: int, session: Session) -> None:
        if gen != self._load_gen:
            return  # 已有更新的加载请求, 丢弃过期结果
        self._cursor_restore()
        self.current_session = session
        self.timeline.set_turns(session.turns, focus_turn_index=self._pending_focus)
        self._pending_focus = None
        self.right_stack.setCurrentWidget(self.timeline)
        warns = len(session.parse_warnings or [])
        title = session.title or session.id
        msg = f"已打开: {title} ({len(session.turns)} 轮)"
        if warns:
            msg += f" · ⚠ {warns} 条解析警告"
        self.statusBar().showMessage(msg, 8000)

    def _on_load_failed(self, gen: int, detail: str) -> None:
        if gen != self._load_gen:
            return
        self._cursor_restore()
        self.right_stack.setCurrentWidget(self.dashboard)
        self._error("加载会话失败", detail)

    # ------------------------------------------------------- 等待光标管理 --
    def _cursor_wait(self) -> None:
        self._cursor_depth += 1
        if self._cursor_depth == 1:
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)

    def _cursor_restore(self) -> None:
        self._cursor_depth = max(0, self._cursor_depth - 1)
        if self._cursor_depth == 0:
            QApplication.restoreOverrideCursor()

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
            elif action == "delete_file":
                self._delete_context_file(session_id)
            elif action == "export_md":
                self._export_session(session_id, md_only=True)
            elif action == "inject":
                self._inject_session(session_id)
            elif action == "surgery":
                self._open_surgery(session_id)
            elif action == "snapshots":
                self._open_snapshots(session_id)
        except Exception as exc:  # noqa: BLE001
            self._error("操作失败", exc)

    def _open_surgery(self, session_id: str) -> None:
        """右键「上下文手术室」: 先确保当前会话已加载, 再打开手术室。"""
        if self.current_session is None or self.current_session.id != session_id:
            session = self._require_idx().load_session(session_id)
            self.current_session = session
            self.timeline.set_turns(session.turns)
            self.right_stack.setCurrentWidget(self.timeline)
        SurgeryDialog(self.current_session, self).exec()

    def _open_snapshots(self, session_id: str) -> None:
        idx = self._require_idx()
        rows = [r for r in idx.sessions(dedupe=False) if r["id"] == session_id]
        if not rows:
            self.statusBar().showMessage("该会话没有快照文件", 4000)
            return
        tool = rows[0]["source_tool"]
        dlg = SnapshotsDialog(rows, self)
        dlg.openRequested.connect(lambda p: self.open_session_file(p, tool))
        dlg.exec()

    def open_session_file(self, path: str, tool: str) -> None:
        """直接 parse 指定文件渲染到时间线 (不走索引, 快照查看器用)。

        注意: 之后对该会话的编辑会写回这个快照文件。
        """
        self._start_load(file_path=path, tool=tool)

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

    def _delete_context_file(self, session_id: str) -> None:
        """删除上下文: 连源文件一起删 (走共享删除流程)。"""
        row = next((r for r in self._all_rows if r["id"] == session_id), None)
        if row is None:
            return
        title = row.get("title") or session_id
        tool = row.get("source_tool")
        idx = self._require_idx()
        files = [
            r["source_path"]
            for r in idx.sessions(dedupe=False)
            if r["id"] == session_id and r["source_tool"] == tool and r.get("source_path")
        ]
        desc = f"确定删除「{title}」的上下文文件吗?"
        self._delete_files_and_index(files, [(tool, session_id)], desc, clear_current_id=session_id)

    def _delete_project(self, project_dir: str) -> None:
        """分组头「删除该项目」: 覆盖该项目全部工具的全部快照文件。"""
        idx = self._require_idx()
        rows = idx.project_files(None, project_dir)
        if not rows:
            self.statusBar().showMessage("该项目在索引中没有文件", 4000)
            return
        files = [r["source_path"] for r in rows if r.get("source_path")]
        pairs = sorted({(r["source_tool"], r["id"]) for r in rows})
        n_sessions = len({r["id"] for r in rows})
        name = project_dir.split("/")[-1].split("\\")[-1] or project_dir
        desc = f"项目「{name}」共有 {n_sessions} 个会话 · {len(files)} 个源文件, 将一并删除"
        self._delete_files_and_index(files, pairs, desc)

    def _delete_batch(self, pairs: list) -> None:
        """批量删除选中的会话 (含每个会话的全部快照文件)。"""
        if not pairs:
            return
        idx = self._require_idx()
        pairset = set(pairs)
        files = [
            r["source_path"]
            for r in idx.sessions(dedupe=False)
            if (r["source_tool"], r["id"]) in pairset and r.get("source_path")
        ]
        desc = f"选中的 {len(pairs)} 个会话 · {len(files)} 个源文件, 将一并删除"
        if self._delete_files_and_index(files, list(pairset), desc):
            self.session_list.set_batch_mode(False)  # 成功后退出批量模式

    def _delete_files_and_index(
        self,
        files: list[str],
        pairs: list,
        subject_desc: str,
        clear_current_id: str | None = None,
    ) -> bool:
        """共享删除流程: 确认(回收站可选) -> 删文件 -> 批量清索引 -> refresh。

        files: 源文件路径列表; pairs: [(source_tool, session_id)] 批量索引删除。
        被占用报错并中止 (返回 False)。
        """
        from pathlib import Path

        from PySide6.QtWidgets import QCheckBox

        idx = self._require_idx()
        files = list(dict.fromkeys(files))  # 去重保序
        box = QMessageBox(self)
        box.setWindowTitle("删除上下文")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"{subject_desc}\n\n将删除 {len(files)} 个源文件(含全部快照)。")
        chk = QCheckBox("放入系统回收站(可还原)")
        chk.setChecked(True)
        box.setCheckBox(chk)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        if box.exec() != QMessageBox.StandardButton.Yes:
            return False
        use_bin = chk.isChecked()
        if not use_bin:
            ret = QMessageBox.warning(
                self,
                "永久删除",
                f"未选择回收站, {len(files)} 个文件将被永久删除, 无法还原!\n确定继续吗?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return False

        from ctxbox.core.utils import move_to_recycle_bin

        deleted, note = 0, ""
        for f in files:
            p = Path(f)
            if not p.exists():
                continue
            try:
                if use_bin:
                    note = move_to_recycle_bin(p)
                else:
                    p.unlink()
                    note = "永久删除"
                deleted += 1
            except OSError as exc:
                self._error("删除失败", f"{p}\n{exc}\n(文件可能被对应工具占用, 请先关闭)")
                return False

        removed = idx.remove_sessions_bulk(pairs) if hasattr(idx, "remove_sessions_bulk") else 0
        if not removed:
            # 老接口回退: 逐个 remove_session
            for tool, sid in pairs:
                try:
                    idx.remove_session(sid, tool)
                    removed += 1
                except Exception:  # noqa: BLE001
                    pass
        if (
            (
                clear_current_id
                and self.current_session
                and self.current_session.id == clear_current_id
            )
            or self.current_session
            and any(sid == self.current_session.id for _tool, sid in pairs)
        ):
            self.current_session = None
            self.right_stack.setCurrentWidget(self.dashboard)
        tail = f"已放入{note}" if use_bin else "已永久删除"
        self.statusBar().showMessage(
            f"已删除 {deleted} 个上下文文件 · 索引移除 {removed} 条 · {tail}", 8000
        )
        self.refresh()
        return True

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
            # force 重建 (否则会被同对象跳过), 但保持当前窗口位置
            self.timeline.set_turns(self.current_session.turns, force=True, keep_window=True)

    # ------------------------------------------------------------- 写回 --
    def _save_session(self, op_desc: str = "修改会话") -> bool:
        """统一保存路径: diff 确认 -> 备份源文件 -> adapter.serialize -> 原子写回。

        返回 False 表示用户在 diff 对话框里取消 (磁盘未动)。
        """
        s = self.current_session
        if s is None:
            return False
        if not s.source_path:
            raise RuntimeError("该会话没有源文件路径, 无法写回。")
        idx = self._require_idx()
        adapter = get_adapter(s.source_tool)
        src = Path(s.source_path)
        try:
            old = adapter.parse(src)  # 磁盘现况, 用于 diff
        except Exception:  # noqa: BLE001 - 解析失败就不挡保存
            old = None
        if old is not None and not confirm_save(self, old, s, op_desc, src):
            return False
        idx.backup_file(src)
        data = adapter.serialize(s)
        atomic_write(src, data)
        self.statusBar().showMessage("已保存 (原文件已备份)", 5000)
        return True

    def _save_and_reload(
        self, op_desc: str = "修改会话", focus_turn_index: int | None = None
    ) -> bool:
        saved = self._save_session(op_desc)
        # 保存与取消都直接重解析刚写入的文件 (不依赖索引可见性:
        # 快照文件/未入库会话同样能正确重载; 后台线程 + 200 节点窗口)
        s = self.current_session
        self._start_load(
            file_path=str(s.source_path), tool=s.source_tool, focus_turn_index=focus_turn_index
        )
        if saved:
            self.refresh()  # 轮数/时间可能变化
        return saved

    def apply_surgery_result(self, trial: Session) -> bool:
        """手术室[应用更改]回调: 用试跑结果替换当前会话内容并写回。"""
        if self.current_session is None:
            return False
        self.current_session.turns = trial.turns
        self.current_session.meta.update(trial.meta)
        return self._save_and_reload("上下文手术室批量处理")

    # -------------------------------------------------------- 轮级动作 --
    def _turn_index(self, turn_id: str) -> int:
        s = self.current_session
        for i, t in enumerate(s.turns):
            if t.id == turn_id:
                return i
        # 保存后适配器可能重建 id: 界面持有的是旧 id — 同步从磁盘重解析一次再试
        fresh = get_adapter(s.source_tool).parse(Path(s.source_path))
        self.current_session = fresh
        self.timeline.set_turns(fresh.turns, force=True, keep_window=True)
        for i, t in enumerate(fresh.turns):
            if t.id == turn_id:
                return i
        raise KeyError(f"找不到轮次 {turn_id}(界面已自动刷新, 请重试该操作)")

    def _edit_turn(self, turn_id: str) -> None:
        s = self.current_session
        if s is None:
            return
        # 定位所属 Exchange (一问一答为一个编辑单元)
        from ctxbox.core.exchange import group_exchanges

        exchanges = group_exchanges(s.turns)
        target = None
        for ex in exchanges:
            if (ex.input is not None and ex.input.id == turn_id) or any(
                t.id == turn_id for t in ex.output
            ):
                target = ex
                break
        if target is None:
            self.statusBar().showMessage("该轮不在任何问答对中, 无法编辑", 4000)
            return
        dlg = ExchangeEditorDialog(target, on_apply_title=self.apply_session_title, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        input_text, output_text = dlg.result_texts()
        try:
            self._apply_exchange_edit(s, target, input_text, output_text)
            focus = None
            if target.input is not None and target.input in s.turns:
                focus = s.turns.index(target.input)
            elif target.output:
                focus = s.turns.index(target.output[0])
            self._save_and_reload(f"编辑第 {target.index} 轮", focus_turn_index=focus)
        except Exception as exc:  # noqa: BLE001
            self._error("保存失败", exc)

    @staticmethod
    def _apply_exchange_edit(s: Session, exchange, input_text: str, output_text: str) -> None:
        """把编辑器结果写回 Exchange: 只动 text parts, thinking/tool 一律保留。"""
        # 输入轮: 第一个 text part 替换, 其余 text part 删除; 没有就新建
        if exchange.input is not None:
            turn = exchange.input
            text_parts = [p for p in turn.parts if p.kind == "text"]
            if text_parts:
                text_parts[0].text = input_text
                text_parts[0].raw = None  # 已编辑: 不再原样回写旧块
                for p in text_parts[1:]:
                    turn.parts.remove(p)
            else:
                turn.parts.append(ContentPart(kind="text", text=input_text))
            turn.meta["_edited"] = True

        # 输出: 该 Exchange 内第一个 assistant text part 替换, 其余删除
        first: tuple | None = None
        for t in exchange.output:
            if t.role != Role.ASSISTANT:
                continue
            for p in t.parts:
                if p.kind == "text":
                    first = (t, p)
                    break
            if first:
                break
        if first is not None:
            t0, p0 = first
            p0.text = output_text
            p0.raw = None
            t0.meta["_edited"] = True
            for t in exchange.output:
                if t.role != Role.ASSISTANT:
                    continue
                for p in list(t.parts):
                    if p.kind == "text" and p is not p0:
                        t.parts.remove(p)
                        t.meta["_edited"] = True
        else:
            # 输出原本没有任何 text part: 在最后一个 assistant 轮新建
            assistants = [t for t in exchange.output if t.role == Role.ASSISTANT]
            if assistants and output_text.strip():
                assistants[-1].parts.append(ContentPart(kind="text", text=output_text))
                assistants[-1].meta["_edited"] = True

    def apply_session_title(self, title: str) -> None:
        """AI 生成标题后应用到当前会话并写回 (序列化器支持的格式会持久化)。"""
        if self.current_session is None or not title.strip():
            return
        self.current_session.title = title.strip()
        self._save_and_reload("AI 生成标题")

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
        if action == "delete_pair":
            # 工具活动行: 删除调用轮 + 配对的结果轮
            call_id, _, result_id = turn_id.partition("|")
            call_turn = s.get_turn(call_id)
            preview = (call_turn.text() or "")[:60] if call_turn else ""
            ret = QMessageBox.question(
                self,
                "删除工具调用",
                f"确定删除该工具调用及其结果吗?\n{preview}…\n\n(保存前会自动备份源文件)",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret == QMessageBox.StandardButton.Yes:
                call_idx = next((i for i, t in enumerate(s.turns) if t.id == call_id), 0)
                s.delete_turn(call_id)
                if result_id:
                    s.delete_turn(result_id)
                self._save_and_reload("删除工具调用及其结果", focus_turn_index=max(0, call_idx - 1))
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
                self._save_and_reload(f"在第 {at + 1} 位插入新轮", focus_turn_index=at)
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
                self._save_and_reload(f"删除第 {idx + 1} 轮", focus_turn_index=max(0, idx - 1))
            return

        if action == "clone_turn":
            s.clone_turn(turn_id)
            self._save_and_reload(f"克隆第 {idx + 1} 轮", focus_turn_index=idx + 1)
            return

        if action == "move_up":
            if idx == 0:
                self.statusBar().showMessage("已经是第一轮", 3000)
                return
            s.move_turn(turn_id, idx - 1)
            self._save_and_reload(f"上移第 {idx + 1} 轮", focus_turn_index=idx - 1)
            return

        if action == "move_down":
            if idx >= len(s.turns) - 1:
                self.statusBar().showMessage("已经是最后一轮", 3000)
                return
            s.move_turn(turn_id, idx + 1)
            self._save_and_reload(f"下移第 {idx + 1} 轮", focus_turn_index=idx + 1)
            return

        if action == "merge_next":
            if idx >= len(s.turns) - 1:
                self.statusBar().showMessage("没有下一轮可合并", 3000)
                return
            nxt = s.turns[idx + 1]
            if not s.merge_turns(turn_id, nxt.id):
                QMessageBox.information(self, "无法合并", "只能合并角色相同的两轮。")
                return
            self._save_and_reload(f"合并第 {idx + 1} 轮与第 {idx + 2} 轮", focus_turn_index=idx)
            return

    # ------------------------------------------------------------- 关闭 --
    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            if self._scan_thread is not None:
                self._scan_thread.quit()
                self._scan_thread.wait(3000)
            for thread in list(self._load_threads):
                thread.quit()
                thread.wait(3000)
            self.dashboard.shutdown()
            while self._cursor_depth > 0:
                self._cursor_restore()
            if self.idx is not None:
                self.idx.close()
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)

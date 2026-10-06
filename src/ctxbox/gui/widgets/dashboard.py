"""右栏默认首页: 仪表盘 (欢迎语 + 统计卡片 + 最近活跃 + 快捷操作)。

未选中会话时替代原来的占位页; 数据来自 SessionIndex 的只读查询。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..theme import TOOL_COLORS, TOOL_ICONS, tokens

README_URL = "https://github.com/a2795751503/ctxbox#readme"


def relative_time(value: Any) -> str:
    """updated_at (datetime / ISO 字符串 / None) -> '3 小时前' 风格相对时间。"""
    dt: datetime | None = None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return value[:16]
    if dt is None:
        return "—"
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    secs = int((now - dt).total_seconds())
    if secs < 60:
        return "刚刚"
    if secs < 3600:
        return f"{secs // 60} 分钟前"
    if secs < 86400:
        return f"{secs // 3600} 小时前"
    if secs < 86400 * 30:
        return f"{secs // 86400} 天前"
    return dt.strftime("%Y-%m-%d")


def _elide(text: str, limit: int = 36) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def fmt_tokens(value: int) -> str:
    """45123 -> '45.1k' / 1234567 -> '1.23M'。"""
    if value < 1000:
        return str(value)
    if value < 1_000_000:
        return f"{value / 1000:.1f}k"
    return f"{value / 1_000_000:.2f}M"


class StatCard(QFrame):
    """统计白卡: 大数字 + 图标标签。"""

    def __init__(self, icon: str, label: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("statCard")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(6)
        self.number = QLabel("—")
        self.number.setStyleSheet("font-size: 26px; font-weight: 700;")
        lab = QLabel(f"{icon} {label}")
        lab.setStyleSheet("font-size: 12px;")
        lay.addWidget(self.number)
        lay.addWidget(lab)
        self._lab = lab
        self.restyle()

    def restyle(self) -> None:
        t = tokens()
        self.setStyleSheet(
            f"#statCard {{ background: {t['card']}; border: 1px solid {t['border']};"
            " border-radius: 12px; }}"
        )
        self.number.setStyleSheet(f"font-size: 26px; font-weight: 700; color: {t['accent']};")
        self._lab.setStyleSheet(f"color: {t['text_secondary']}; font-size: 12px;")

    def set_value(self, value: int) -> None:
        self.number.setText(f"{value:,}")


class RecentRow(QFrame):
    """最近活跃列表的一行: 标题 + 工具 pill + 相对时间。"""

    clicked = Signal()

    def __init__(self, row: dict, display_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.session_id = row["id"]
        self.setObjectName("recentRow")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        t = tokens()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(8)

        icon = TOOL_ICONS.get(row.get("source_tool", ""), "🗂️")
        title = QLabel(f"{icon} {_elide(row.get('title') or '(无标题)')}")
        title.setStyleSheet(f"font-size: 13px; color: {t['text']};")
        lay.addWidget(title, 1)

        brand = TOOL_COLORS.get(row.get("source_tool", ""), "#6b7280")
        pill = QLabel(display_name)
        pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pill.setStyleSheet(
            f"background: {brand}; color: #ffffff; font-size: 10px;"
            " border-radius: 9px; padding: 2px 8px; font-weight: 600;"
        )
        lay.addWidget(pill)

        time_lab = QLabel(relative_time(row.get("updated_at")))
        time_lab.setStyleSheet(f"color: {t['text_muted']}; font-size: 12px;")
        time_lab.setMinimumWidth(70)
        time_lab.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(time_lab)

        self._base_style = (
            f"#recentRow {{ background: {t['card']}; border: 1px solid {t['border']};"
            " border-radius: 10px; }}"
        )
        self._hover_style = (
            f"#recentRow {{ background: {t['accent_soft']};"
            f" border: 1px solid {t['accent_soft_border']}; border-radius: 10px; }}"
        )
        self.setStyleSheet(self._base_style)

    def enterEvent(self, event) -> None:  # noqa: N802
        self.setStyleSheet(self._hover_style)
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:  # noqa: N802
        self.setStyleSheet(self._base_style)
        super().leaveEvent(event)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        self.clicked.emit()
        super().mousePressEvent(event)


class DashboardWidget(QScrollArea):
    """仪表盘首页 (右栏默认页)。"""

    openRequested = Signal(str)  # session_id
    scanRequested = Signal()
    searchRequested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self._tool_display: dict[str, str] = {}
        self._token_key: tuple | None = None  # token 统计缓存键

        container = QWidget()
        self.setWidget(container)
        lay = QVBoxLayout(container)
        lay.setContentsMargins(32, 28, 32, 28)
        lay.setSpacing(18)

        # 欢迎语
        t = tokens()
        hero = QLabel("你的 AI 上下文都在这里")
        hero.setStyleSheet(f"font-size: 22px; font-weight: 700; color: {t['text']};")
        lay.addWidget(hero)
        sub = QLabel("扫描 · 搜索 · 编辑 · 导出 · 注入 — 跨工具统一管理本机 AI 编程助手的会话")
        sub.setStyleSheet(f"color: {t['text_secondary']}; font-size: 13px;")
        lay.addWidget(sub)

        # 统计卡片区 (3+2)
        self.stat_sessions = StatCard("📚", "总会话数")
        self.stat_turns = StatCard("💬", "总轮数")
        self.stat_tools = StatCard("🤖", "接入工具数")
        self.stat_snapshots = StatCard("📷", "快照总数")
        self.stat_tokens = StatCard("🔤", "估算 token 总量")
        self.stat_tokens.setToolTip("基于最近 30 个会话采样估算 (依赖-free chars 启发式)")
        grid = QGridLayout()
        grid.setSpacing(12)
        grid.addWidget(self.stat_sessions, 0, 0)
        grid.addWidget(self.stat_turns, 0, 1)
        grid.addWidget(self.stat_tools, 0, 2)
        grid.addWidget(self.stat_snapshots, 1, 0)
        grid.addWidget(self.stat_tokens, 1, 1)
        lay.addLayout(grid)

        # Top 5 大会话 (按采样内估算 token 排序)
        t = tokens()
        top_title = QLabel("Top 5 大会话")
        top_title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {t['text']};")
        lay.addWidget(top_title)
        self._top_container = QWidget()
        self._top_lay = QVBoxLayout(self._top_container)
        self._top_lay.setContentsMargins(0, 0, 0, 0)
        self._top_lay.setSpacing(8)
        lay.addWidget(self._top_container)

        # 最近活跃
        recent_title = QLabel("最近活跃")
        recent_title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {t['text']};")
        lay.addWidget(recent_title)
        self._recent_container = QWidget()
        self._recent_lay = QVBoxLayout(self._recent_container)
        self._recent_lay.setContentsMargins(0, 0, 0, 0)
        self._recent_lay.setSpacing(8)
        lay.addWidget(self._recent_container)

        # 快捷操作
        actions_title = QLabel("快捷操作")
        actions_title.setStyleSheet(f"font-size: 15px; font-weight: 600; color: {t['text']};")
        lay.addWidget(actions_title)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)

        btn_scan = QPushButton("🔄 立即扫描")
        btn_scan.setProperty("kind", "primary")
        btn_scan.setToolTip("重新扫描本机所有 AI 工具的会话 (Ctrl+R)")
        btn_scan.clicked.connect(self.scanRequested.emit)
        btn_row.addWidget(btn_scan)

        btn_search = QPushButton("🔍 全局搜索")
        btn_search.setProperty("kind", "secondary")
        btn_search.setToolTip("聚焦顶部搜索框 (Ctrl+F)")
        btn_search.clicked.connect(self.searchRequested.emit)
        btn_row.addWidget(btn_search)

        btn_guide = QPushButton("📖 使用指南")
        btn_guide.setProperty("kind", "secondary")
        btn_guide.setToolTip("打开 GitHub 上的 README")
        btn_guide.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(README_URL)))
        btn_row.addWidget(btn_guide)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        lay.addStretch(1)

    def set_tool_display_names(self, mapping: dict[str, str]) -> None:
        self._tool_display = mapping

    def refresh_data(self, idx) -> None:
        """从 SessionIndex 重新拉取统计和最近会话 (只读查询, 不修改 db)。"""
        rows = idx.sessions()
        total_sessions = len(rows)
        try:
            total_turns = int(
                idx.db.execute("SELECT COALESCE(SUM(turn_count),0) FROM sessions").fetchone()[0]
            )
            total_snapshots = int(
                idx.db.execute(
                    "SELECT COALESCE(SUM(snapshot_count),0) FROM sessions WHERE snapshot_count > 1"
                ).fetchone()[0]
            )
        except Exception:  # noqa: BLE001 - db 属性/列名变化时退回内存计算
            total_turns = sum(int(r.get("turn_count") or 0) for r in rows)
            total_snapshots = sum(int(r.get("snapshot_count") or 0) for r in rows)
        try:
            total_tools = len(idx.tools_summary())
        except Exception:  # noqa: BLE001
            total_tools = len({r["source_tool"] for r in rows})

        for card in (
            self.stat_sessions,
            self.stat_turns,
            self.stat_tools,
            self.stat_snapshots,
            self.stat_tokens,
        ):
            card.restyle()
        self.stat_sessions.set_value(total_sessions)
        self.stat_turns.set_value(total_turns)
        self.stat_tools.set_value(total_tools)
        self.stat_snapshots.set_value(total_snapshots)

        # 最近活跃 5 条 (防御性按更新时间倒序)
        def sort_key(r: dict) -> str:
            v = r.get("updated_at")
            return v.isoformat() if isinstance(v, datetime) else str(v or "")

        recent = sorted(rows, key=sort_key, reverse=True)[:5]
        while self._recent_lay.count():
            item = self._recent_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        if not recent:
            t = tokens()
            empty = QLabel("还没有会话, 点击下方「立即扫描」开始。")
            empty.setStyleSheet(f"color: {t['text_muted']}; font-size: 13px;")
            self._recent_lay.addWidget(empty)
        for row in recent:
            disp = self._tool_display.get(row["source_tool"], row["source_tool"])
            rr = RecentRow(row, disp)
            rr.clicked.connect(lambda sid=row["id"]: self.openRequested.emit(sid))
            self._recent_lay.addWidget(rr)

        # token 采样统计较慢 (parse 最近 30 个会话), 延迟到下一拍且按数据变化缓存
        key = (total_sessions, sort_key(rows[0]) if rows else "")
        if key != self._token_key:
            self._token_key = key
            QTimer.singleShot(0, lambda: self._refresh_token_stats(idx))

    def _refresh_token_stats(self, idx) -> None:
        """采样最近 30 个会话, 估算 token 总量 + Top 5 大会话。"""
        from ctxbox.core.surgery import session_tokens

        def sort_key(r: dict) -> str:
            v = r.get("updated_at")
            return v.isoformat() if isinstance(v, datetime) else str(v or "")

        try:
            rows = sorted(idx.sessions(), key=sort_key, reverse=True)[:30]
        except Exception:  # noqa: BLE001
            return
        total = 0
        scored: list[tuple[int, dict]] = []
        for row in rows:
            try:
                n = session_tokens(idx.load_session(row["id"]))
            except Exception:  # noqa: BLE001 - 单个文件坏了不拖垮整页
                continue
            total += n
            scored.append((n, row))
        self.stat_tokens.set_value(total)

        t = tokens()
        while self._top_lay.count():
            item = self._top_lay.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for n, row in sorted(scored, reverse=True, key=lambda x: x[0])[:5]:
            line = QFrame()
            line.setStyleSheet(
                f"QFrame {{ background: {t['card']}; border: 1px solid {t['border']};"
                " border-radius: 10px; }}"
            )
            hl = QHBoxLayout(line)
            hl.setContentsMargins(12, 8, 12, 8)
            title = QLabel(_elide(row.get("title") or "(无标题)"))
            title.setStyleSheet(f"font-size: 13px; color: {t['text']};")
            hl.addWidget(title, 1)
            num = QLabel(fmt_tokens(n))
            num.setStyleSheet(f"color: {t['accent']}; font-weight: 600;")
            hl.addWidget(num)
            self._top_lay.addWidget(line)

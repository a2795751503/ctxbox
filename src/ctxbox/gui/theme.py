"""设计令牌与全局主题 (cc-switch 风格)。

集中定义 LIGHT/DARK 两套颜色令牌、间距、圆角、字体栈,
`apply_theme(app, theme)` 生成并应用全局 QSS。
主题选择持久化在 QSettings("ctxbox", "ctxbox") key="theme", 默认 "light"。
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

# ------------------------------------------------------------------ 字体 --
FONT_FAMILY = '"Microsoft YaHei UI", "PingFang SC", "Segoe UI", sans-serif'
MONO_FAMILY = '"Cascadia Code", Consolas, monospace'

# ------------------------------------------------------------------ 令牌 --
LIGHT: dict[str, str] = {
    "bg": "#f5f6f8",
    "card": "#ffffff",
    "border": "#e5e7eb",
    "text": "#111827",
    "text_secondary": "#6b7280",
    "text_muted": "#9ca3af",
    "accent": "#2563eb",
    "accent_hover": "#1d4ed8",
    "accent_soft": "#eff6ff",  # 选中态浅蓝底
    "accent_soft_border": "#93c5fd",  # hover 边框蓝
    "success": "#10b981",
    "warning": "#f59e0b",
    "danger": "#dc2626",
    "input_bg": "#ffffff",
    "input_border": "#d1d5db",
    "menu_bg": "#ffffff",
    "scroll_handle": "rgba(17, 24, 39, 0.25)",
    "scroll_handle_hover": "rgba(17, 24, 39, 0.40)",
    # 时间线气泡
    "bubble_user_bg": "#2563eb",
    "bubble_user_text": "#ffffff",
    "bubble_user_header": "#dbeafe",
    "bubble_assistant_bg": "#ffffff",
    "bubble_assistant_border": "#e5e7eb",
    "bubble_assistant_text": "#111827",
    "bubble_tool_bg": "#f3f4f6",
    "bubble_tool_border": "#d1d5db",
    "bubble_tool_text": "#4b5563",
    "code_bg": "#f3f4f6",
    "code_border": "#e5e7eb",
    "code_text": "#1f2937",
    "noise_bg": "#fffbeb",
    "noise_border": "#fbbf24",
    "raw_bg": "#fef3c7",
    "raw_border": "#fcd34d",
    "raw_text": "#92400e",
    "snippet": "#b45309",
}

DARK: dict[str, str] = {
    "bg": "#0f1115",
    "card": "#1a1d24",
    "border": "#2d333d",
    "text": "#e5e7eb",
    "text_secondary": "#9ca3af",
    "text_muted": "#6b7280",
    "accent": "#3b82f6",
    "accent_hover": "#2563eb",
    "accent_soft": "#1e293b",
    "accent_soft_border": "#2563eb",
    "success": "#10b981",
    "warning": "#f59e0b",
    "danger": "#ef4444",
    "input_bg": "#11141a",
    "input_border": "#374151",
    "menu_bg": "#1a1d24",
    "scroll_handle": "rgba(255, 255, 255, 0.20)",
    "scroll_handle_hover": "rgba(255, 255, 255, 0.35)",
    # 时间线气泡
    "bubble_user_bg": "#1d4ed8",
    "bubble_user_text": "#ffffff",
    "bubble_user_header": "#bfdbfe",
    "bubble_assistant_bg": "#1f2937",
    "bubble_assistant_border": "#374151",
    "bubble_assistant_text": "#e5e7eb",
    "bubble_tool_bg": "#111827",
    "bubble_tool_border": "#374151",
    "bubble_tool_text": "#9ca3af",
    "code_bg": "#111827",
    "code_border": "#374151",
    "code_text": "#d1d5db",
    "noise_bg": "#2c2614",
    "noise_border": "#a16207",
    "raw_bg": "#2c2614",
    "raw_border": "#a16207",
    "raw_text": "#fbbf24",
    "snippet": "#fbbf24",
}

THEMES = {"light": LIGHT, "dark": DARK}

# 工具品牌色 (pill 徽章)
TOOL_COLORS = {
    "claude-code": "#d97706",  # 琥珀
    "codex": "#10b981",  # 绿
    "continue": "#6366f1",  # 紫
    "kimi-code": "#0ea5e9",  # 天蓝
    "generic-jsonl": "#6b7280",  # 灰
}
TOOL_ICONS = {
    "claude-code": "🤖",
    "codex": "🌀",
    "continue": "🧩",
    "kimi-code": "🌙",
    "generic-jsonl": "📄",
}

RADIUS_CARD = 12
SPACING_CARD = 8


# ---------------------------------------------------------------- 持久化 --
def current_theme() -> str:
    name = str(QSettings("ctxbox", "ctxbox").value("theme", "light"))
    return name if name in THEMES else "light"


def set_theme(name: str) -> None:
    QSettings("ctxbox", "ctxbox").setValue("theme", name)


def tokens(theme: str | None = None) -> dict[str, str]:
    return THEMES[theme or current_theme()]


# ------------------------------------------------------------------- QSS --
def build_qss(theme: str | None = None) -> str:
    t = tokens(theme)
    return f"""
* {{ font-family: {FONT_FAMILY}; font-size: 13px; }}
QMainWindow, QDialog, QWidget {{ background: {t["bg"]}; color: {t["text"]}; }}

/* 输入框: 默认圆角 6px; objectName=capsuleSearch 为全圆角胶囊 */
QLineEdit, QPlainTextEdit, QTextEdit {{
    background: {t["input_bg"]}; color: {t["text"]};
    border: 1px solid {t["input_border"]}; border-radius: 6px;
    padding: 5px 8px; selection-background-color: {t["accent"]};
}}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {t["accent"]}; }}
QLineEdit#capsuleSearch {{
    border-radius: 16px; padding: 7px 14px; border: 1px solid {t["input_border"]};
    background: {t["input_bg"]};
}}
QLineEdit#capsuleSearch:focus {{ border-color: {t["accent"]}; }}

/* 按钮: 默认 / kind=secondary 描边 / kind=primary 实心蓝 */
QPushButton {{
    background: {t["card"]}; color: {t["text"]};
    border: 1px solid {t["input_border"]}; border-radius: 8px; padding: 7px 16px;
}}
QPushButton:hover {{ border-color: {t["accent_soft_border"]}; color: {t["accent"]}; }}
QPushButton:disabled {{ color: {t["text_muted"]}; border-color: {t["border"]}; }}
QPushButton[kind="primary"] {{
    background: {t["accent"]}; color: #ffffff; border: none;
}}
QPushButton[kind="primary"]:hover {{ background: {t["accent_hover"]}; color: #ffffff; }}
QPushButton[kind="primary"]:disabled {{ background: {t["border"]}; color: {t["text_muted"]}; }}
QPushButton[kind="secondary"] {{
    background: transparent; color: {t["text"]}; border: 1px solid {t["input_border"]};
}}
QPushButton[kind="secondary"]:hover {{ border-color: {t["accent"]}; color: {t["accent"]}; }}

QComboBox {{
    background: {t["input_bg"]}; color: {t["text"]};
    border: 1px solid {t["input_border"]}; border-radius: 6px;
    padding: 5px 8px; min-height: 24px;
}}
QComboBox:focus {{ border-color: {t["accent"]}; }}
QComboBox QAbstractItemView {{
    background: {t["menu_bg"]}; color: {t["text"]};
    border: 1px solid {t["border"]}; selection-background-color: {t["accent_soft"]};
    selection-color: {t["text"]};
}}
QCheckBox {{ spacing: 6px; }}

/* 列表: 透明底无框, 选中色由卡片自绘 */
QListWidget {{ background: transparent; border: none; outline: none; }}
QListWidget::item:selected {{ background: transparent; }}

QToolButton {{
    background: transparent; border: 1px solid transparent;
    border-radius: 6px; padding: 5px 10px; color: {t["text"]};
}}
QToolButton:hover {{ background: {t["accent_soft"]}; border-color: {t["border"]}; }}
QToolButton:disabled {{ color: {t["text_muted"]}; }}

QMenu {{
    background: {t["menu_bg"]}; color: {t["text"]};
    border: 1px solid {t["border"]}; border-radius: 8px; padding: 4px;
}}
QMenu::item {{ padding: 7px 24px; border-radius: 5px; }}
QMenu::item:selected {{ background: {t["accent_soft"]}; color: {t["accent"]}; }}

QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
QScrollBar::handle:vertical {{
    background: {t["scroll_handle"]}; border-radius: 4px; min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: {t["scroll_handle_hover"]}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 8px; margin: 2px; }}
QScrollBar::handle:horizontal {{
    background: {t["scroll_handle"]}; border-radius: 4px; min-width: 24px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

QSplitter::handle {{ background: {t["bg"]}; }}
QStatusBar {{ background: {t["bg"]}; color: {t["text_muted"]}; }}
QStatusBar QLabel {{ color: {t["text_muted"]}; font-size: 12px; }}

QToolTip {{
    background: {t["menu_bg"]}; color: {t["text"]}; border: 1px solid {t["border"]};
    padding: 4px 8px;
}}
QLabel {{ background: transparent; }}
QWizard {{ background: {t["bg"]}; }}
QWizard QLabel {{ color: {t["text"]}; }}
"""


def apply_theme(app, theme: str) -> None:
    """应用主题: Fusion 风格 + 调色板 + 全局 QSS, 并持久化到 QSettings。"""
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QStyleFactory

    if theme not in THEMES:
        theme = "light"
    t = THEMES[theme]
    app.setStyle(QStyleFactory.create("Fusion"))
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(t["bg"]))
    p.setColor(QPalette.ColorRole.WindowText, QColor(t["text"]))
    p.setColor(QPalette.ColorRole.Base, QColor(t["input_bg"]))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(t["card"]))
    p.setColor(QPalette.ColorRole.Text, QColor(t["text"]))
    p.setColor(QPalette.ColorRole.Button, QColor(t["card"]))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(t["text"]))
    p.setColor(QPalette.ColorRole.Highlight, QColor(t["accent"]))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(t["menu_bg"]))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(t["text"]))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(t["text_muted"]))
    app.setPalette(p)
    app.setStyleSheet(build_qss(theme))
    set_theme(theme)

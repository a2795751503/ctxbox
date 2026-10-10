"""设计令牌与全局主题 (VSCode IDE 配色)。

集中定义 VSCode Light+ / Dark+ 两套颜色令牌、间距、圆角、字体栈,
`apply_theme(app, theme)` 生成并应用全局 QSS。
主题选择持久化在 QSettings("ctxbox", "ctxbox") key="theme", 默认 "dark"。
所有前景/背景配对由 tests/test_theme_contrast.py 强制 WCAG 对比度 ≥ 4.5。
"""

from __future__ import annotations

from PySide6.QtCore import QSettings

# ------------------------------------------------------------------ 字体 --
FONT_FAMILY = '"Microsoft YaHei UI", "PingFang SC", "Segoe UI", sans-serif'
MONO_FAMILY = '"Cascadia Code", Consolas, monospace'

# ---------------------------------------------------- 令牌 (VSCode 配色) --
# Light+ 参考 VSCode Light+: 编辑器 #ffffff / 侧栏 #f3f3f3 / 主蓝 #0078d4
LIGHT: dict[str, str] = {
    "bg": "#f3f3f3",
    "card": "#ffffff",
    "border": "#e5e5e5",
    "text": "#1f1f1f",
    "text_secondary": "#424242",
    "text_muted": "#6e6e6e",
    "accent": "#0078d4",
    "accent_hover": "#106ebe",
    "accent_soft": "#e8f1fb",  # 选中态浅蓝底
    "accent_soft_border": "#7eb6ea",  # hover 边框蓝
    "success": "#16825d",
    "warning": "#bf8803",
    "danger": "#c72e0f",
    "input_bg": "#ffffff",
    "input_border": "#cecece",
    "menu_bg": "#ffffff",
    "scroll_handle": "rgba(31, 31, 31, 0.25)",
    "scroll_handle_hover": "rgba(31, 31, 31, 0.45)",
    # 时间线气泡
    "bubble_user_bg": "#005a9e",
    "bubble_user_text": "#ffffff",
    "bubble_user_header": "#cfe4f7",
    "bubble_assistant_bg": "#ffffff",
    "bubble_assistant_border": "#e5e5e5",
    "bubble_assistant_text": "#1f1f1f",
    "bubble_tool_bg": "#f3f3f3",
    "bubble_tool_border": "#cecece",
    "bubble_tool_text": "#383838",
    "code_bg": "#f5f5f5",
    "code_border": "#e0e0e0",
    "code_text": "#1f1f1f",
    # 气泡内"内容井"(折叠块展开区/代码/结果): 蓝气泡用深蓝井, 白卡用浅灰井
    "well_bg": "#f0f0f0",
    "well_border": "#e0e0e0",
    "well_text": "#1f1f1f",
    "well_user_bg": "#084a7e",
    "well_user_border": "#0b5d99",
    "well_user_text": "#dbeafe",
    "noise_bg": "#fff8e5",
    "noise_border": "#d7a900",
    "raw_bg": "#fff3d6",
    "raw_border": "#d7a900",
    "raw_text": "#6b4e00",
    "snippet": "#8a5a00",
}

# Dark+ 参考 VSCode Dark+: 编辑器 #1e1e1e / 侧栏 #252526 / 按钮蓝 #0e639c
DARK: dict[str, str] = {
    "bg": "#1e1e1e",
    "card": "#252526",
    "border": "#3c3c3c",
    "text": "#cccccc",
    "text_secondary": "#a6a6a6",
    "text_muted": "#8a8a8a",
    "accent": "#0e639c",
    "accent_hover": "#1177bb",
    "accent_soft": "#094771",  # 列表选中底
    "accent_soft_border": "#1177bb",
    "success": "#4ec9b0",
    "warning": "#dcdcaa",
    "danger": "#f48771",
    "input_bg": "#3c3c3c",
    "input_border": "#3c3c3c",
    "menu_bg": "#252526",
    "scroll_handle": "rgba(204, 204, 204, 0.20)",
    "scroll_handle_hover": "rgba(204, 204, 204, 0.40)",
    # 时间线气泡
    "bubble_user_bg": "#0e639c",
    "bubble_user_text": "#ffffff",
    "bubble_user_header": "#9fd0f0",
    "bubble_assistant_bg": "#252526",
    "bubble_assistant_border": "#3c3c3c",
    "bubble_assistant_text": "#cccccc",
    "bubble_tool_bg": "#1b1b1c",
    "bubble_tool_border": "#3c3c3c",
    "bubble_tool_text": "#a6a6a6",
    "code_bg": "#1b1b1c",
    "code_border": "#3c3c3c",
    "code_text": "#d4d4d4",
    # 气泡内"内容井": 深蓝气泡用更深井, 深灰卡用近黑井
    "well_bg": "#1b1b1c",
    "well_border": "#3c3c3c",
    "well_text": "#cccccc",
    "well_user_bg": "#0a4d78",
    "well_user_border": "#1177bb",
    "well_user_text": "#d0e8f8",
    "noise_bg": "#2e2a17",
    "noise_border": "#8a7b1e",
    "raw_bg": "#2e2a17",
    "raw_border": "#8a7b1e",
    "raw_text": "#dcdcaa",
    "snippet": "#d7b54a",
}

THEMES = {"light": LIGHT, "dark": DARK}
DEFAULT_THEME = "dark"

# 工具品牌色 (pill 徽章)
TOOL_COLORS = {
    "claude-code": "#d97706",  # 琥珀
    "codex": "#10b981",  # 绿
    "continue": "#6366f1",  # 紫
    "kimi-code": "#0ea5e9",  # 天蓝
    "pi": "#7c3aed",  # 紫罗兰
    "opencode": "#f97316",  # 橙
    "gemini-cli": "#4285f4",  # 谷歌蓝
    "aider": "#84cc16",  # 黄绿
    "generic-jsonl": "#6b7280",  # 灰
}
TOOL_ICONS = {
    "claude-code": "🤖",
    "codex": "🌀",
    "continue": "🧩",
    "kimi-code": "🌙",
    "pi": "🥧",
    "opencode": "🈳",
    "gemini-cli": "♊",
    "aider": "🛠",
    "generic-jsonl": "📄",
}

RADIUS_CARD = 12
SPACING_CARD = 8


# ---------------------------------------------------------------- 持久化 --
# QSettings.value 在 Windows 上是注册表读取 (~10ms/次), 列表重建会调用数百次,
# 必须内存缓存; set_theme 时写穿。
_theme_cache: str | None = None


def current_theme() -> str:
    global _theme_cache
    if _theme_cache is None:
        name = str(QSettings("ctxbox", "ctxbox").value("theme", DEFAULT_THEME))
        _theme_cache = name if name in THEMES else DEFAULT_THEME
    return _theme_cache


def set_theme(name: str) -> None:
    global _theme_cache
    QSettings("ctxbox", "ctxbox").setValue("theme", name)
    _theme_cache = name if name in THEMES else DEFAULT_THEME


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
        theme = DEFAULT_THEME
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

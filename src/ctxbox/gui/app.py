"""ctxbox GUI 入口: QApplication + 深色主题 (Fusion + 自写 QSS, 无第三方主题库)."""

from __future__ import annotations

import sys
import traceback

DARK_QSS = """
QMainWindow, QDialog, QWidget { background: #1e1f24; color: #d7dae0;
    font-family: "Microsoft YaHei", "Segoe UI", sans-serif; font-size: 13px; }
QToolBar { background: #26272d; border: none; spacing: 6px; padding: 4px; }
QToolButton { background: transparent; border: 1px solid transparent;
    border-radius: 4px; padding: 5px 10px; color: #d7dae0; }
QToolButton:hover { background: #33353d; border-color: #45474f; }
QToolButton:disabled { color: #6a6d75; }
QLineEdit, QPlainTextEdit, QTextEdit { background: #141518; color: #e3e5ea;
    border: 1px solid #3a3c44; border-radius: 4px; padding: 4px 6px;
    selection-background-color: #3d5a99; }
QLineEdit:focus, QPlainTextEdit:focus { border-color: #4f7bdd; }
QComboBox { background: #141518; border: 1px solid #3a3c44; border-radius: 4px;
    padding: 4px 8px; min-height: 22px; }
QComboBox QAbstractItemView { background: #26272d; border: 1px solid #3a3c44;
    selection-background-color: #3d5a99; }
QPushButton { background: #33353d; border: 1px solid #45474f; border-radius: 4px;
    padding: 5px 14px; }
QPushButton:hover { background: #3e4049; }
QPushButton:default { background: #3d5a99; border-color: #4f7bdd; }
QPushButton:disabled { color: #6a6d75; }
QListWidget, QTreeWidget { background: #191a1e; border: none; outline: none; }
QListWidget::item:selected, QTreeWidget::item:selected { background: transparent; }
QTreeWidget::item { padding: 4px; }
QTreeWidget::item:hover { background: #26272d; }
QSplitter::handle { background: #2a2b31; }
QStatusBar { background: #26272d; }
QScrollBar:vertical { background: #191a1e; width: 10px; }
QScrollBar::handle:vertical { background: #3a3c44; border-radius: 5px; min-height: 24px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QMenu { background: #26272d; border: 1px solid #3a3c44; }
QMenu::item { padding: 6px 24px; }
QMenu::item:selected { background: #3d5a99; }
QWizard { background: #1e1f24; }
QLabel { background: transparent; }
QToolTip { background: #26272d; color: #d7dae0; border: 1px solid #45474f; }
"""


def _apply_dark_theme(app) -> None:
    """Fusion 风格 + 深色 QSS。"""
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QStyleFactory

    app.setStyle(QStyleFactory.create("Fusion"))
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#1e1f24"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#d7dae0"))
    p.setColor(QPalette.ColorRole.Base, QColor("#141518"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#1e1f24"))
    p.setColor(QPalette.ColorRole.Text, QColor("#e3e5ea"))
    p.setColor(QPalette.ColorRole.Button, QColor("#33353d"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#d7dae0"))
    p.setColor(QPalette.ColorRole.Highlight, QColor("#3d5a99"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#26272d"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#d7dae0"))
    app.setPalette(p)
    app.setStyleSheet(DARK_QSS)


def _excepthook(exc_type, exc, tb) -> None:
    """兜底: 任何未捕获异常弹窗而不是崩溃。"""
    from PySide6.QtWidgets import QMessageBox

    detail = "".join(traceback.format_exception(exc_type, exc, tb))
    QMessageBox.critical(None, "未捕获异常", f"{exc}\n\n{detail[-1500:]}")


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    app.setApplicationName("ctxbox")
    app.setOrganizationName("ctxbox")
    app.setApplicationDisplayName("ctxbox — AI 上下文管理器")
    _apply_dark_theme(app)
    sys.excepthook = _excepthook

    from .main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

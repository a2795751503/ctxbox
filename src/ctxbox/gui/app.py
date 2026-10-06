"""ctxbox GUI 入口: QApplication + cc-switch 风格主题 (见 gui/theme.py)."""

from __future__ import annotations

import sys
import traceback


def _excepthook(exc_type, exc, tb) -> None:
    """兜底: 任何未捕获异常弹窗而不是崩溃。"""
    from PySide6.QtWidgets import QMessageBox

    detail = "".join(traceback.format_exception(exc_type, exc, tb))
    QMessageBox.critical(None, "未捕获异常", f"{exc}\n\n{detail[-1500:]}")


def main() -> int:
    from PySide6.QtWidgets import QApplication

    from .theme import apply_theme, current_theme

    app = QApplication(sys.argv)
    app.setApplicationName("ctxbox")
    app.setOrganizationName("ctxbox")
    app.setApplicationDisplayName("ctxbox — AI 上下文管理器")
    apply_theme(app, current_theme())
    sys.excepthook = _excepthook

    from .main_window import MainWindow

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

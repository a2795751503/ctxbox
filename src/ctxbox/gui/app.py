"""ctxbox GUI 入口: QApplication + cc-switch 风格主题 (见 gui/theme.py)."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def _find_icon() -> Path | None:
    """找应用图标: PyInstaller 冻结后从 sys._MEIPASS 找, 开发模式从仓库根找。"""
    candidates: list[Path] = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "packaging" / "icons" / "ctxbox.png")
        candidates.append(Path(meipass) / "icons" / "ctxbox.png")
    repo_root = Path(__file__).resolve().parents[3]  # gui/app.py -> ctxbox -> src -> 仓库根
    candidates.append(repo_root / "packaging" / "icons" / "ctxbox.png")
    for p in candidates:
        if p.is_file():
            return p
    return None


def _excepthook(exc_type, exc, tb) -> None:
    """兜底: 任何未捕获异常弹窗而不是崩溃。"""
    from PySide6.QtWidgets import QMessageBox

    detail = "".join(traceback.format_exception(exc_type, exc, tb))
    QMessageBox.critical(None, "未捕获异常", f"{exc}\n\n{detail[-1500:]}")


def main() -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from .theme import apply_theme, current_theme

    app = QApplication(sys.argv)
    app.setApplicationName("ctxbox")
    app.setOrganizationName("ctxbox")
    app.setApplicationDisplayName("ctxbox — AI 上下文管理器")
    apply_theme(app, current_theme())
    sys.excepthook = _excepthook

    icon_path = _find_icon()
    icon = QIcon(str(icon_path)) if icon_path else None
    if icon is not None:
        app.setWindowIcon(icon)

    from .main_window import MainWindow

    win = MainWindow()
    if icon is not None:
        win.setWindowIcon(icon)
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

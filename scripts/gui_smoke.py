"""Offscreen GUI smoke test for CI.

Creates the real MainWindow with a synthetic index, exercises the main flows,
and exits non-zero on any failure. Run with QT_QPA_PLATFORM=offscreen.
"""

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from ctxbox.core.adapters.base import get_adapter
from ctxbox.core.store.db import SessionIndex

FIXTURE = Path(__file__).parent.parent / "tests/fixtures/claude_code/sample.jsonl"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="ctxbox-smoke-"))
    idx = SessionIndex(db_path=tmp / "index.db")
    idx.upsert_session(get_adapter("claude-code").parse(FIXTURE))
    idx.db.commit()

    app = QApplication(sys.argv)

    import ctxbox.gui.main_window as mw_mod

    # point the GUI at our synthetic index
    mw_mod.SessionIndex = lambda *a, **k: idx  # type: ignore[misc]

    window = mw_mod.MainWindow()
    window.show()
    app.processEvents()

    rows = window._visible_rows()
    assert rows, "no sessions visible"
    print(f"smoke: {len(rows)} session(s) listed ok")

    window.open_session(rows[0]["id"])
    app.processEvents()
    print("smoke: session opened ok")

    window.close()
    print("GUI SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

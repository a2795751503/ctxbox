"""Move files to the OS-native recycle bin / trash.

- Windows: SHFileOperationW with FOF_ALLOWUNDO (recoverable from 回收站)
- macOS:   Finder delete via osascript (moves to Trash)
- Linux:   freedesktop.org Trash spec (~/.local/share/Trash)

Falls back to permanent deletion ONLY if the platform path fails AND
`fallback_to_unlink` is True; otherwise raises. Recoverability is a core
safety guarantee of ctxbox — callers should surface failures, not swallow.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _trash_windows(path: Path) -> None:
    import ctypes
    from ctypes import wintypes

    FO_DELETE = 3
    FOF_ALLOWUNDO = 0x40
    FOF_NOCONFIRMATION = 0x10
    FOF_NOERRORUI = 0x400
    FOF_SILENT = 0x4

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("wFunc", wintypes.UINT),
            ("pFrom", wintypes.LPCWSTR),
            ("pTo", wintypes.LPCWSTR),
            ("fFlags", wintypes.USHORT),
            ("fAnyOperationsAborted", wintypes.BOOL),
            ("hNameMappings", wintypes.LPVOID),
            ("lpszProgressTitle", wintypes.LPCWSTR),
        ]

    op = SHFILEOPSTRUCTW()
    op.wFunc = FO_DELETE
    # double-null-terminated source path (required by the API)
    op.pFrom = str(path) + "\0"
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_NOERRORUI | FOF_SILENT
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))  # type: ignore[attr-defined]
    if rc != 0:
        raise OSError(f"SHFileOperationW failed (code {rc}) for {path}")
    if op.fAnyOperationsAborted:
        raise OSError(f"回收站操作被中止: {path}")


def _trash_macos(path: Path) -> None:
    script = f'tell application "Finder" to delete POSIX file "{path}"'
    subprocess.run(["osascript", "-e", script], check=True, capture_output=True, text=True)


def _trash_linux(path: Path) -> None:
    trash = Path.home() / ".local" / "share" / "Trash"
    files_dir, info_dir = trash / "files", trash / "info"
    files_dir.mkdir(parents=True, exist_ok=True)
    info_dir.mkdir(parents=True, exist_ok=True)
    dest = files_dir / path.name
    n = 1
    while dest.exists():
        dest = files_dir / f"{path.stem}.{n}{path.suffix}"
        n += 1
    shutil.move(str(path), dest)
    info = (
        f"[Trash Info]\nPath={path.resolve()}\nDeletionDate={time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
    )
    (info_dir / f"{dest.name}.trashinfo").write_text(info, encoding="utf-8")


def move_to_recycle_bin(path: Path, *, fallback_to_unlink: bool = False) -> str:
    """Move path to the OS recycle bin. Returns a human description of what
    happened ('回收站' / 'Trash' / '永久删除(回退)').

    Raises OSError when recycling is impossible and fallback is disabled.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(path)
    try:
        if sys.platform == "win32":
            _trash_windows(path)
        elif sys.platform == "darwin":
            _trash_macos(path)
        else:
            _trash_linux(path)
        return "回收站" if sys.platform == "win32" else "Trash"
    except Exception:
        if not fallback_to_unlink:
            raise
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            os.unlink(path)
        return "永久删除(回收站不可用,已回退直删)"

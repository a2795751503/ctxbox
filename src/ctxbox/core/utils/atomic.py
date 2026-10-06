"""Atomic file writes and backup helpers. We never half-write a user's file."""

from __future__ import annotations

import contextlib
import os
import shutil
import stat
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

_REPLACE_RETRIES = 6
_REPLACE_DELAY = 0.25  # seconds; handles AV/indexer/tool transient locks


class FileLockedError(PermissionError):
    """The target file is held open by another process (e.g. the AI tool
    itself is running and has the session file open)."""


def _clear_readonly(path: Path) -> None:
    with contextlib.suppress(OSError):
        os.chmod(path, stat.S_IWRITE | stat.S_IREAD)


def atomic_write(path: Path, data: bytes) -> None:
    """Write data to path atomically: temp file in same dir + os.replace.

    Windows hardening: os.replace fails with WinError 5 when the target is
    read-only or momentarily locked (antivirus, search indexer, or the AI
    tool itself holding the session open). We clear the read-only flag and
    retry with backoff; if the file is still locked after retries we raise
    FileLockedError with an actionable message.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        _clear_readonly(path)
        last_exc: OSError | None = None
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(tmp, path)
                return
            except PermissionError as exc:
                last_exc = exc
                if attempt < _REPLACE_RETRIES - 1:
                    time.sleep(_REPLACE_DELAY)
        raise FileLockedError(
            f"文件被占用, 无法写入: {path}\n"
            "可能对应的 AI 工具(Codex/Claude 等)正开着这个会话, "
            "请先在原工具中关闭该会话或退出工具后重试。"
        ) from last_exc
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def make_backup(path: Path, backup_root: Path) -> Path:
    """Copy path into backup_root before any modification. Returns backup path."""
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe = str(path).replace(":", "").replace("\\", "_").replace("/", "_").strip("_")
    dest = backup_root / f"{stamp}_{safe}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    return dest

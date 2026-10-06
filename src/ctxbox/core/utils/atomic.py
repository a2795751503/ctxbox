"""Atomic file writes and backup helpers. We never half-write a user's file."""

from __future__ import annotations

import contextlib
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def atomic_write(path: Path, data: bytes) -> None:
    """Write data to path atomically: temp file in same dir + os.replace."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
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

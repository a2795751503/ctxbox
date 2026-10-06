"""Cross-platform path helpers. Never hardcode C:\\ or /Users in adapters."""

from __future__ import annotations

from pathlib import Path

from platformdirs import user_config_dir, user_data_dir


def home() -> Path:
    return Path.home()


def dotdir(name: str) -> Path:
    """A dot-directory in the user's home: ~/.claude, ~/.codex, ..."""
    return home() / name


def roaming_app_dir(app: str) -> Path:
    """%APPDATA%/<app> on Windows, ~/Library/Application Support/<app> on macOS,
    ~/.config/<app> on Linux."""
    return Path(user_config_dir(app, roaming=True))


def local_data_dir(app: str) -> Path:
    return Path(user_data_dir(app))


def ctxbox_data_dir() -> Path:
    """Where ctxbox keeps its index db and backups."""
    d = local_data_dir("ctxbox")
    (d / "backups").mkdir(parents=True, exist_ok=True)
    return d

"""Tiny typing helpers for JSON-shaped data."""

from __future__ import annotations

from typing import Any


def as_dict(value: Any) -> dict[str, Any]:
    """Return value if it is a dict, else an empty dict.

    JSON parsing yields Any; this both narrows for type checkers and
    guarantees a safe .get() target for malformed records.
    """
    return value if isinstance(value, dict) else {}

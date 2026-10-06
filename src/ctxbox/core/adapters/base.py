"""Adapter plugin system. Each AI tool = one BaseAdapter subclass."""

from __future__ import annotations

import importlib
import pkgutil
from abc import ABC, abstractmethod
from collections.abc import Iterator
from pathlib import Path
from typing import ClassVar

from ..model.schema import Session

_REGISTRY: dict[str, type[BaseAdapter]] = {}
_discovered = False


def register(cls: type[BaseAdapter]) -> type[BaseAdapter]:
    """Class decorator: register an adapter by its unique name."""
    _REGISTRY[cls.name] = cls
    return cls


class BaseAdapter(ABC):
    """Contract between ctxbox and one AI tool's session format."""

    name: ClassVar[str] = "base"
    display_name: ClassVar[str] = "Base"

    @abstractmethod
    def detect(self) -> list[Path]:
        """Find this tool's session files on the local machine."""

    @abstractmethod
    def parse(self, path: Path) -> Session:
        """Native file -> unified Session model."""

    def iter_sessions(self, path: Path) -> Iterator[Session]:
        """Yield sessions found in path. Most tools store one session per
        file (default below); DB-backed tools (opencode) override this to
        yield many sessions from one database file."""
        yield self.parse(path)

    @abstractmethod
    def serialize(self, session: Session) -> bytes:
        """Unified model -> native file bytes (for export/injection)."""

    def inject(self, session: Session, target_dir: Path | None = None) -> Path:
        """Write session as a NEW native session file the tool will pick up.
        Default: unsupported."""
        raise NotImplementedError(f"{self.display_name} does not support injection yet")

    @classmethod
    def supported_features(cls) -> set[str]:
        feats = {"read"}
        if cls.serialize is not BaseAdapter.serialize:
            feats.add("export")
        if cls.inject is not BaseAdapter.inject:
            feats.add("inject")
        return feats


def discover_adapters() -> list[type[BaseAdapter]]:
    """Import every module in this package so @register runs."""
    global _discovered
    if not _discovered:
        pkg_dir = Path(__file__).parent
        for mod in pkgutil.iter_modules([str(pkg_dir)]):
            if not mod.name.startswith("_") and mod.name != "base":
                importlib.import_module(f"{__package__}.{mod.name}")
        _discovered = True
    return list(_REGISTRY.values())


def get_adapter(name: str) -> BaseAdapter:
    discover_adapters()
    if name not in _REGISTRY:
        raise KeyError(f"Unknown adapter {name!r}. Available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]()


def all_adapters() -> list[BaseAdapter]:
    return [cls() for cls in discover_adapters()]

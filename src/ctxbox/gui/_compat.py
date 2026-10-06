# TODO(compat): 临时兼容层。
# core 的 store.db / inject.engine / exporter / utils.redact 模块由主线并行开发中。
# 本文件优先 import 真实实现；真实模块就绪后下方 stub 自动失效，届时可整体删除 stub 部分。
# stub 仅供 GUI 界面联调使用，不是 core 功能实现，请勿在 core 中引用。
"""Import real core modules when available; fall back to minimal demo stubs."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ctxbox.core.adapters.base import all_adapters, get_adapter
from ctxbox.core.model.schema import Session
from ctxbox.core.utils.paths import ctxbox_data_dir

# ---------------------------------------------------------------- redact ----
try:
    from ctxbox.core.utils.redact import redact_text  # noqa: F401
except ImportError:  # TODO: 待 core.utils.redact 就绪后删除
    _RE_SECRET = re.compile(
        r"(sk-[A-Za-z0-9_-]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{8,}"
        r"|[\w.+-]+@[\w-]+\.[\w.]+)"
    )

    def redact_text(text: str) -> str:
        """Stub: 简单正则脱敏 token/邮箱。"""
        return _RE_SECRET.sub("***REDACTED***", text)


# --------------------------------------------------------------- exporter ---
try:
    from ctxbox.core.exporter import export_session  # noqa: F401
except ImportError:  # TODO: 待 core.exporter 就绪后删除

    def export_session(session: Session, fmt: str = "md", redact: bool = False) -> str:
        """Stub: 最小 md / json / jsonl 导出。"""

        def maybe_redact(s: str) -> str:
            return redact_text(s) if redact else s

        if fmt == "json":
            data = session.model_dump(mode="json")
            return maybe_redact(json.dumps(data, ensure_ascii=False, indent=2))
        if fmt == "jsonl":
            lines = [
                json.dumps(t.model_dump(mode="json"), ensure_ascii=False) for t in session.turns
            ]
            return maybe_redact("\n".join(lines) + "\n")
        if fmt == "md":
            out = [f"# {session.title or session.id}", ""]
            for t in session.turns:
                out.append(f"## [{t.role.value}]")
                out.append(t.text())
                out.append("")
            return maybe_redact("\n".join(out))
        raise ValueError(f"unknown export format: {fmt}")


# ---------------------------------------------------------------- inject ----
try:
    from ctxbox.core.inject.engine import InjectResult, inject_session  # noqa: F401
except ImportError:  # TODO: 待 core.inject.engine 就绪后删除

    @dataclass
    class InjectResult:
        ok: bool
        path: Path | None = None
        warnings: list[str] = field(default_factory=list)
        error: str | None = None

    def inject_session(
        session: Session, target_adapter_name: str, target_dir: Path | None = None
    ) -> InjectResult:
        """Stub: 直接调用目标 adapter.inject。"""
        try:
            adapter = get_adapter(target_adapter_name)
            dest = adapter.inject(session, Path(target_dir) if target_dir else None)
            return InjectResult(ok=True, path=dest)
        except Exception as exc:  # noqa: BLE001
            return InjectResult(ok=False, error=str(exc))


# ------------------------------------------------------------------ store ---
try:
    from ctxbox.core.store.db import SessionIndex  # noqa: F401
except ImportError:  # TODO: 待 core.store.db 就绪后删除

    class SessionIndex:
        """Stub: 纯内存索引（每次启动全量 detect+parse），仅供界面联调。"""

        def __init__(self) -> None:
            self._rows: dict[str, dict] = {}
            self._cache: dict[str, Session] = {}
            self.rescan()

        def rescan(self, progress_cb=None) -> int:
            self._rows.clear()
            self._cache.clear()
            jobs: list[tuple] = []
            for adapter in all_adapters():
                try:
                    for p in adapter.detect():
                        jobs.append((adapter, p))
                except Exception:  # noqa: BLE001
                    continue
            for i, (adapter, path) in enumerate(jobs):
                try:
                    s = adapter.parse(path)
                except Exception:  # noqa: BLE001
                    continue
                self._cache[s.id] = s
                self._rows[s.id] = {
                    "id": s.id,
                    "source_tool": s.source_tool,
                    "title": s.title,
                    "project_dir": s.project_dir,
                    "source_path": str(s.source_path) if s.source_path else "",
                    "turn_count": len(s.turns),
                    "updated_at": s.updated_at,
                }
                if progress_cb:
                    progress_cb(i + 1, len(jobs))
            return len(self._rows)

        def sessions(self, tool: str | None = None, query: str | None = None) -> list[dict]:
            rows = list(self._rows.values())
            if tool:
                rows = [r for r in rows if r["source_tool"] == tool]
            if query:
                q = query.lower()
                rows = [r for r in rows if q in (r["title"] or "").lower()]
            return sorted(rows, key=lambda r: str(r.get("updated_at") or ""), reverse=True)

        def load_session(self, session_id: str) -> Session:
            return self._cache[session_id]

        def search(self, query: str) -> list[dict]:
            results: list[dict] = []
            q = query.lower()
            for sid, row in self._rows.items():
                s = self._cache[sid]
                for t in s.turns:
                    text = t.text()
                    pos = text.lower().find(q)
                    if pos >= 0:
                        start = max(0, pos - 40)
                        snippet = ("…" if start else "") + text[start : pos + 80] + "…"
                        results.append({**row, "snippet": snippet.replace("\n", " ")})
                        break
            return results

        def backup_file(self, path: Path) -> Path:
            from ctxbox.core.utils.atomic import make_backup

            return make_backup(Path(path), ctxbox_data_dir() / "backups")

        def delete_session(self, session_id: str) -> bool:
            """仅删索引，不删源文件。"""
            existed = session_id in self._rows
            self._rows.pop(session_id, None)
            self._cache.pop(session_id, None)
            return existed

        def close(self) -> None:
            pass

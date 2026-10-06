"""Injection engine: write a Session back as a NEW native session file.

Safety contract:
- never overwrite an existing file (fresh id + fresh filename)
- after writing, re-parse our own output and verify the turns survive
  (>=99% of turns must round-trip, or we report failure and keep the backup)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..adapters.base import get_adapter
from ..model.schema import Session


@dataclass
class InjectResult:
    ok: bool
    path: Path | None = None
    warnings: list[str] = field(default_factory=list)
    error: str | None = None
    turns_written: int = 0
    turns_verified: int = 0


@dataclass
class PreviewItem:
    turn_index: int
    kind: str  # part kind: text / tool_call / tool_result / thinking / raw …
    action: str  # "keep" | "degrade" | "drop"
    note: str  # human-readable explanation
    preview: str  # first ~80 chars of the part


# part kinds every injectable adapter understands natively
_NATIVE_KINDS = {"text", "thinking", "tool_call", "tool_result", "code"}


def preview_injection(session: Session, target_adapter_name: str) -> list[PreviewItem]:
    """List how every part of the session will land in the target format.

    Same-tool injection keeps everything; cross-tool degrades non-native
    kinds (thinking/raw/image/file_ref) to marked text blocks.
    """
    cross_tool = session.source_tool != target_adapter_name
    items: list[PreviewItem] = []
    for i, turn in enumerate(session.turns):
        for part in turn.parts:
            kind = part.kind
            if not cross_tool:
                action = "keep"
                note = (
                    "损坏行原文保留"
                    if (kind == "raw" and turn.meta.get("unparseable"))
                    else "原生保留"
                )
            elif kind in _NATIVE_KINDS:
                action, note = "keep", "映射为等效块"
            elif kind == "thinking":
                action, note = "degrade", "目标不支持思考块 → 转为 [thinking] 文本"
            elif kind in ("image", "file_ref"):
                action, note = "degrade", f"目标不支持 {kind} → 转为占位文本"
            else:
                action, note = "degrade", "未识别结构 → 转为原文文本"
            items.append(
                PreviewItem(
                    turn_index=i,
                    kind=kind,
                    action=action,
                    note=note,
                    preview=(part.text or "")[:80],
                )
            )
    return items


def inject_session(
    session: Session, target_adapter_name: str, target_dir: Path | None = None
) -> InjectResult:
    """Inject session into target tool's native format as a NEW session.

    Same-tool injection preserves native structures; cross-tool injection maps
    through the unified model and degrades unsupported parts to marked text.
    """
    result = InjectResult(ok=False)
    try:
        adapter = get_adapter(target_adapter_name)
    except KeyError as exc:
        result.error = str(exc)
        return result

    cross_tool = session.source_tool != target_adapter_name
    if cross_tool:
        result.warnings.append(
            f"Cross-tool injection {session.source_tool} -> {target_adapter_name}: "
            "unsupported blocks degrade to marked text"
        )

    work = session.model_copy(deep=True)
    work.source_tool = target_adapter_name  # serialize speaks the target's format
    try:
        path = adapter.inject(work, target_dir=target_dir)
    except Exception as exc:
        result.error = f"inject failed: {exc}"
        return result

    result.turns_written = len(work.turns)
    # post-write verification: re-parse what we just wrote
    try:
        reread = adapter.parse(path)
        result.turns_verified = len(reread.turns)
        threshold = max(1, int(result.turns_written * 0.99))
        if result.turns_verified < threshold:
            result.error = (
                f"verification failed: wrote {result.turns_written} turns, "
                f"only {result.turns_verified} readable back"
            )
            return result
    except Exception as exc:
        result.error = f"verification re-parse failed: {exc}"
        return result

    result.ok = True
    result.path = path
    result.warnings.extend(reread.parse_warnings)
    return result

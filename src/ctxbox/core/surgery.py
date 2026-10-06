"""Context surgery: bulk operations on a Session before saving or injecting.

- regex_replace: global find & replace across all text parts (with match count)
- slim: drop bulky part kinds (tool_result / thinking / tool_call) to shrink context
- truncate_to_budget: keep the newest turns that fit a token budget
- estimate_tokens: dependency-free token estimate (chars/4 heuristic,
  CJK-adjusted) — good enough for budgets and stats
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model.schema import Session


def estimate_tokens(text: str) -> int:
    """Rough token count. Latin ~4 chars/token; CJK ~1.5 chars/token."""
    if not text:
        return 0
    cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
    other = len(text) - cjk
    return max(1, int(cjk / 1.5 + other / 4))


def session_tokens(session: Session) -> int:
    return sum(estimate_tokens(t.text()) for t in session.turns)


@dataclass
class SurgeryReport:
    action: str
    affected: int = 0
    details: list[str] = field(default_factory=list)
    tokens_before: int = 0
    tokens_after: int = 0


def regex_replace(
    session: Session, pattern: str, replacement: str, *, roles: set[str] | None = None
) -> SurgeryReport:
    """Replace pattern in every text part. Returns report with match count."""
    rx = re.compile(pattern, re.DOTALL)
    report = SurgeryReport(action="regex_replace", tokens_before=session_tokens(session))
    for turn in session.turns:
        if roles and turn.role.value not in roles:
            continue
        for part in turn.parts:
            if part.text is None:
                continue
            new_text, n = rx.subn(replacement, part.text)
            if n:
                part.text = new_text
                part.raw = None  # edited: don't round-trip the stale original
                turn.meta["_edited"] = True
                report.affected += n
    report.details.append(f"replaced {report.affected} occurrence(s) of /{pattern}/")
    report.tokens_after = session_tokens(session)
    return report


def slim(
    session: Session,
    *,
    drop_tool_results: bool = False,
    drop_thinking: bool = False,
    drop_tool_calls: bool = False,
    max_part_chars: int | None = None,
) -> SurgeryReport:
    """Remove bulky parts / clamp oversized parts to shrink the context."""
    report = SurgeryReport(action="slim", tokens_before=session_tokens(session))
    drop_kinds: set[str] = set()
    if drop_tool_results:
        drop_kinds.add("tool_result")
    if drop_thinking:
        drop_kinds.add("thinking")
    if drop_tool_calls:
        drop_kinds.add("tool_call")
    for turn in session.turns:
        before = len(turn.parts)
        if drop_kinds:
            turn.parts = [p for p in turn.parts if p.kind not in drop_kinds]
            dropped = before - len(turn.parts)
            if dropped:
                turn.meta["_edited"] = True
                report.affected += dropped
        if max_part_chars:
            for part in turn.parts:
                if part.text and len(part.text) > max_part_chars:
                    part.text = part.text[:max_part_chars] + "\n…[ctxbox: truncated]"
                    part.raw = None
                    turn.meta["_edited"] = True
                    report.affected += 1
    report.details.append(
        f"removed/clamped {report.affected} part(s)"
        + (f" (kinds: {', '.join(sorted(drop_kinds))})" if drop_kinds else "")
    )
    report.tokens_after = session_tokens(session)
    return report


def truncate_to_budget(
    session: Session, token_budget: int, *, keep_first: int = 1
) -> SurgeryReport:
    """Keep `keep_first` opening turns + the newest turns that fit the budget."""
    report = SurgeryReport(action="truncate", tokens_before=session_tokens(session))
    if session_tokens(session) <= token_budget:
        report.details.append("already within budget")
        report.tokens_after = report.tokens_before
        return report
    head = session.turns[:keep_first]
    tail: list = []
    used = sum(estimate_tokens(t.text()) for t in head)
    for turn in reversed(session.turns[keep_first:]):
        cost = estimate_tokens(turn.text())
        if used + cost > token_budget:
            continue
        tail.insert(0, turn)
        used += cost
    removed = len(session.turns) - len(head) - len(tail)
    session.turns = head + tail
    session.meta["_ctxbox_truncated"] = removed
    report.affected = removed
    report.details.append(f"dropped {removed} middle turn(s), kept {len(head)}+{len(tail)}")
    report.tokens_after = session_tokens(session)
    return report

"""Kimi Code adapter.

Format (verified against live ~/.kimi-code sessions):
~/.kimi-code/sessions/<wd_*>/session_<uuid>/agents/main/wire.jsonl

wire.jsonl is an event log; conversation reconstruction:
  {"type":"context.append_message","message":{"role":"user","content":[{"type":"text",...}]}}
      -> user input turns
  {"type":"context.append_loop_event","event":{"type":"content.part","part":{"type":"think"|"text",...}}}
      -> assistant thinking / text output
  {"type":"context.append_loop_event","event":{"type":"tool.call","name":...,"args":...}}
      -> assistant tool calls
  {"type":"context.append_loop_event","event":{"type":"tool.result","result":{"output":...}}}
      -> tool results
  {"type":"llm.request","modelAlias":...} -> model info
Everything else (metadata, config.update, usage.record, llm.*, step.begin/end,
turn.*, file_history.*, token_counting.*) is session bookkeeping — skipped.

Injection is intentionally NOT supported: wire.jsonl is Kimi Code's live
runtime log, writing a fake one would not produce a resumable session.
Export (md/json/jsonl) works through the standard exporter.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from ..model.schema import ContentPart, Role, Session, Turn
from ..normalize import read_jsonl_tolerant
from ..utils import paths
from .base import BaseAdapter, register

_BOOKKEEPING_PREFIXES = (
    "metadata",
    "config.",
    "tools.",
    "permission.",
    "mcp.",
    "llm.",
    "usage.",
    "turn.steer",
    "turn.ended",
    "turn.result",
    "turn.end",
    "agent.",
    "prompt.",
    "file_history.",
    "token_counting.",
    "context.append_loop_event_meta",
)


def _ts(ms: Any) -> datetime | None:
    if isinstance(ms, (int, float)):
        try:
            return datetime.fromtimestamp(ms / 1000).astimezone()
        except (OSError, OverflowError):
            return None
    return None


def _content_parts(content: Any, raw: dict[str, Any]) -> list[ContentPart]:
    parts: list[ContentPart] = []
    if isinstance(content, str):
        return [ContentPart(kind="text", text=content, raw=raw)]
    for block in content or []:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            parts.append(ContentPart(kind="text", text=block.get("text", ""), raw=block))
        else:
            parts.append(
                ContentPart(kind="raw", text=json.dumps(block, ensure_ascii=False), raw=block)
            )
    return parts


def _loop_event_to_turn(ev: dict[str, Any], ts: datetime | None, model: str | None) -> Turn | None:
    etype = ev.get("type")
    if etype == "content.part":
        part = ev.get("part") or {}
        ptype = part.get("type")
        if ptype == "think":
            return Turn(
                role=Role.ASSISTANT,
                timestamp=ts,
                model=model,
                parts=[ContentPart(kind="thinking", text=part.get("think", ""))],
                meta={"raw": ev, "kimi_type": etype},
            )
        text = part.get("text") or part.get("content") or ""
        return Turn(
            role=Role.ASSISTANT,
            timestamp=ts,
            model=model,
            parts=[ContentPart(kind="text", text=str(text))],
            meta={"raw": ev, "kimi_type": etype},
        )
    if etype == "tool.call":
        return Turn(
            role=Role.ASSISTANT,
            timestamp=ts,
            model=model,
            parts=[
                ContentPart(
                    kind="tool_call",
                    tool_name=ev.get("name"),
                    tool_args=ev.get("args") if isinstance(ev.get("args"), dict) else None,
                    text=json.dumps(ev.get("args"), ensure_ascii=False),
                )
            ],
            meta={"raw": ev, "kimi_type": etype},
        )
    if etype == "tool.result":
        result = ev.get("result")
        out = result.get("output") if isinstance(result, dict) else result
        return Turn(
            role=Role.TOOL,
            timestamp=ts,
            parts=[
                ContentPart(
                    kind="tool_result",
                    text=out if isinstance(out, str) else json.dumps(out, ensure_ascii=False),
                )
            ],
            meta={"raw": ev, "kimi_type": etype},
        )
    return None


@register
class KimiCodeAdapter(BaseAdapter):
    name = "kimi-code"
    display_name = "Kimi Code"

    def sessions_root(self) -> Path:
        return paths.dotdir(".kimi-code") / "sessions"

    def detect(self) -> list[Path]:
        root = self.sessions_root()
        if not root.is_dir():
            return []
        return sorted(root.glob("*/session_*/agents/main/wire.jsonl"))

    def parse(self, path: Path) -> Session:
        result = read_jsonl_tolerant(path)
        # .../sessions/<wd_*>/session_<uuid>/agents/main/wire.jsonl
        session_id = path.parents[2].name
        model: str | None = None
        turns: list[Turn] = []
        skipped = 0
        for line in result.lines:
            if line.data is None:
                turns.append(
                    Turn(
                        role=Role.UNKNOWN,
                        parts=[ContentPart(kind="raw", text=line.raw_text)],
                        meta={"unparseable": True, "lineno": line.lineno},
                    )
                )
                continue
            obj = line.data
            otype = str(obj.get("type", ""))
            ts = _ts(obj.get("time") or obj.get("created_at"))
            if otype == "llm.request" and not model:
                model = obj.get("modelAlias") or obj.get("model")
                continue
            if otype in ("context.append_message", "turn.prompt"):
                msg = obj.get("message") if isinstance(obj.get("message"), dict) else obj
                role = Role.USER if msg.get("role") == "user" else Role.UNKNOWN
                origin = (msg.get("origin") or {}).get("kind")
                turns.append(
                    Turn(
                        role=role,
                        timestamp=ts,
                        parts=_content_parts(msg.get("content") or msg.get("input"), obj),
                        meta={"raw": obj, "origin": origin},
                    )
                )
                continue
            if otype == "context.append_loop_event":
                ev = obj.get("event") or {}
                turn = _loop_event_to_turn(ev, ts, model)
                if turn is None:
                    skipped += 1
                    continue
                turns.append(turn)
                continue
            if any(otype.startswith(p) for p in _BOOKKEEPING_PREFIXES):
                skipped += 1
                continue
            skipped += 1  # unknown future event types: ignore but count
        # workspace dir: wd_<name>_<hash>
        project = path.parents[3].name if len(path.parents) > 3 else ""
        m = re.match(r"wd_(.+?)_[0-9a-f]{8,}$", project)
        project = m.group(1) if m else project
        warnings = list(result.warnings)
        if skipped:
            warnings.append(f"{skipped} bookkeeping events skipped")
        return Session(
            id=session_id,
            source_tool=self.name,
            source_path=path,
            project_dir=project,
            turns=turns,
            created_at=turns[0].timestamp if turns else None,
            updated_at=turns[-1].timestamp if turns else None,
            parse_warnings=warnings,
            meta={"encoding": result.encoding, "model": model},
        )

    def serialize(self, session: Session) -> bytes:
        """Best-effort wire.jsonl export (user prompts + assistant/tool events)."""
        lines = [
            json.dumps(
                {"type": "metadata", "protocol_version": "1.4", "exported_by": "ctxbox"},
                ensure_ascii=False,
            )
        ]
        for turn in session.turns:
            ts = int(turn.timestamp.timestamp() * 1000) if turn.timestamp else None
            if turn.role == Role.USER:
                lines.append(
                    json.dumps(
                        {
                            "type": "context.append_message",
                            "time": ts,
                            "message": {
                                "role": "user",
                                "content": [{"type": "text", "text": turn.text()}],
                                "origin": {"kind": "user"},
                            },
                        },
                        ensure_ascii=False,
                    )
                )
                continue
            for p in turn.parts:
                if p.kind == "thinking":
                    ev = {"type": "content.part", "part": {"type": "think", "think": p.text or ""}}
                elif p.kind == "tool_call":
                    ev = {
                        "type": "tool.call",
                        "name": p.tool_name or "unknown",
                        "args": p.tool_args or {},
                    }
                elif p.kind == "tool_result":
                    ev = {"type": "tool.result", "result": {"output": p.text or ""}}
                else:
                    ev = {"type": "content.part", "part": {"type": "text", "text": p.text or ""}}
                lines.append(
                    json.dumps(
                        {"type": "context.append_loop_event", "time": ts, "event": ev},
                        ensure_ascii=False,
                    )
                )
        return ("\n".join(lines) + "\n").encode("utf-8")

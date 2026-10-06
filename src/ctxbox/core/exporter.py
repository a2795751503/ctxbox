"""Export a Session to shareable formats: Markdown / JSON / JSONL."""

from __future__ import annotations

import json

from .model.schema import Role, Session
from .utils.redact import redact_text

_ROLE_LABEL = {
    Role.USER: "🧑 User",
    Role.ASSISTANT: "🤖 Assistant",
    Role.SYSTEM: "⚙️ System",
    Role.TOOL: "🔧 Tool",
    Role.UNKNOWN: "❓ Unknown",
}


def export_session(
    session: Session, fmt: str = "md", redact: bool = False, include_system: bool = False
) -> str:
    fmt = fmt.lower()
    if fmt in ("md", "markdown"):
        return _to_markdown(session, redact, include_system)
    if fmt == "json":
        return _to_json(session, redact, include_system)
    if fmt == "jsonl":
        return _to_jsonl(session, redact, include_system)
    raise ValueError(f"unsupported export format: {fmt}")


def _visible_turns(session: Session, include_system: bool) -> tuple[list, int]:
    """Split turns into (exportable, skipped_noise_count)."""
    if include_system:
        return session.turns, 0
    visible = [t for t in session.turns if not t.meta.get("noise")]
    return visible, len(session.turns) - len(visible)


def _maybe_redact(text: str, redact: bool) -> str:
    return redact_text(text) if redact else text


def _to_markdown(session: Session, redact: bool, include_system: bool = False) -> str:
    turns, skipped = _visible_turns(session, include_system)
    lines = [
        f"# {session.title or session.id}",
        "",
        f"- Source: `{session.source_tool}`",
        f"- Project: `{session.project_dir or '-'}`",
        f"- Turns: {len(turns)}",
    ]
    if skipped:
        lines.append(
            f"- _{skipped} system/environment turns omitted "
            f"(export with --include-system to keep them)_"
        )
    lines += ["", "---", ""]
    for t in turns:
        label = _ROLE_LABEL.get(t.role, t.role.value)
        ts = f" · {t.timestamp:%Y-%m-%d %H:%M}" if t.timestamp else ""
        lines.append(f"## {label}{ts}")
        lines.append("")
        for p in t.parts:
            body = _maybe_redact(p.display_text(), redact)
            if p.kind == "thinking":
                lines.append(f"<details><summary>thinking</summary>\n\n{body}\n</details>")
            elif p.kind == "tool_call":
                lines.append(f"**🔧 call `{p.tool_name}`**\n```json\n{body}\n```")
            elif p.kind == "tool_result":
                lines.append(f"**🔧 result**\n```\n{body[:4000]}\n```")
            else:
                lines.append(body)
            lines.append("")
    return "\n".join(lines)


def _to_json(session: Session, redact: bool, include_system: bool = False) -> str:
    turns, _ = _visible_turns(session, include_system)
    data = json.loads(session.model_dump_json())
    keep = {t.id for t in turns}
    data["turns"] = [t for t in data.get("turns", []) if t.get("id") in keep]
    if redact:
        for t in data.get("turns", []):
            for p in t.get("parts", []):
                if p.get("text"):
                    p["text"] = redact_text(p["text"])
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _to_jsonl(session: Session, redact: bool, include_system: bool = False) -> str:
    turns, _ = _visible_turns(session, include_system)
    lines = []
    for t in turns:
        text = _maybe_redact(t.text(), redact)
        lines.append(
            json.dumps(
                {
                    "id": t.id,
                    "role": t.role.value,
                    "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                    "text": text,
                },
                ensure_ascii=False,
            )
        )
    return "\n".join(lines) + "\n"

"""ctxbox command line interface.

Every GUI feature has a CLI equivalent:
  ctxbox scan                       discover & index all sessions
  ctxbox list [--tool X]            list indexed sessions
  ctxbox show <id> [--tool X]       print a conversation
  ctxbox search <query>             full-text search
  ctxbox export <id> --format md -o out.md [--redact]
  ctxbox inject <id> --to codex     write as a new native session
  ctxbox adapters                   list available adapters
  ctxbox gui                        launch the desktop app
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .core.adapters.base import all_adapters
from .core.exporter import export_session
from .core.inject.engine import inject_session
from .core.store.db import SessionIndex


def _print_progress(msg: str, i: int, total: int) -> None:
    print(f"\r[{i}/{total}] {msg[:70]:<70}", end="", flush=True)


def cmd_scan(args: argparse.Namespace) -> int:
    idx = SessionIndex()
    n = idx.rescan(progress_cb=_print_progress)
    print(f"\nScanned {n} sessions.")
    for tool, count in idx.tools_summary():
        print(f"  {tool:<15} {count}")
    idx.close()
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    idx = SessionIndex()
    for s in idx.sessions(tool=args.tool):
        print(
            f"{s['source_tool']:<14} {s['id'][:38]:<38} "
            f"turns={s['turn_count'] or 0:<4} {s['title'] or ''}"
        )
    idx.close()
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    idx = SessionIndex()
    session = idx.load_session(args.id, tool=args.tool)
    print(f"# {session.title or session.id}  [{session.source_tool}]\n")
    for t in session.turns:
        print(f"--- {t.role.value} {'-' * 40}")
        print(t.text()[: args.max_chars])
    idx.close()
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    idx = SessionIndex()
    for r in idx.search(args.query):
        hits = f" ({r['hit_count']} hits)" if r.get("hit_count", 1) > 1 else ""
        snaps = f" [📷 {r['snapshot_count']} snapshots]" if r.get("snapshot_count", 1) > 1 else ""
        print(f"{r['source_tool']:<14} {r['id'][:38]:<38} {r['title'] or ''}{hits}{snaps}")
        print(f"    …{r['snippet']}…")
    idx.close()
    return 0


def cmd_export(args: argparse.Namespace) -> int:
    idx = SessionIndex()
    session = idx.load_session(args.id, tool=args.tool)
    text = export_session(
        session, fmt=args.format, redact=args.redact, include_system=args.include_system
    )
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"Exported -> {args.output}")
    else:
        print(text)
    idx.close()
    return 0


def cmd_inject(args: argparse.Namespace) -> int:
    idx = SessionIndex()
    session = idx.load_session(args.id, tool=args.tool)
    result = inject_session(
        session, args.to, target_dir=Path(args.target_dir) if args.target_dir else None
    )
    for w in result.warnings:
        print(f"warning: {w}")
    if result.ok:
        print(f"Injected {result.turns_written} turns -> {result.path}")
        print("Open the target tool to continue this conversation.")
        return 0
    print(f"Injection failed: {result.error}", file=sys.stderr)
    return 1


def cmd_adapters(args: argparse.Namespace) -> int:
    for ad in all_adapters():
        feats = ",".join(sorted(ad.supported_features()))
        print(f"{ad.name:<16} {ad.display_name:<24} [{feats}]")
    return 0


def _save_session(idx: SessionIndex, session) -> None:
    """Backup + atomic write + reindex after a mutation."""
    from .core.adapters.base import get_adapter
    from .core.utils import atomic_write

    assert session.source_path is not None
    backup = idx.backup_file(session.source_path)
    adapter = get_adapter(session.source_tool)
    atomic_write(session.source_path, adapter.serialize(session))
    idx.upsert_session(session)
    idx.db.commit()
    print(f"saved (backup: {backup})")


def cmd_replace(args: argparse.Namespace) -> int:
    from .core.surgery import regex_replace

    idx = SessionIndex()
    session = idx.load_session(args.id, tool=args.tool)
    roles = set(args.roles.split(",")) if args.roles else None
    report = regex_replace(session, args.pattern, args.replacement, roles=roles)
    if report.affected == 0:
        print("no matches")
        return 0
    if not args.yes:
        print(f"will replace {report.affected} occurrence(s); rerun with --yes to apply")
        return 0
    _save_session(idx, session)
    print(
        f"replaced {report.affected} occurrence(s) · tokens {report.tokens_before} -> {report.tokens_after}"
    )
    idx.close()
    return 0


def cmd_slim(args: argparse.Namespace) -> int:
    from .core.surgery import slim, truncate_to_budget

    idx = SessionIndex()
    session = idx.load_session(args.id, tool=args.tool)
    if args.budget:
        report = truncate_to_budget(session, args.budget, keep_first=args.keep_first)
    else:
        report = slim(
            session,
            drop_tool_results=args.drop_tool_results,
            drop_thinking=args.drop_thinking,
            drop_tool_calls=args.drop_tool_calls,
            max_part_chars=args.max_part_chars,
        )
    print(f"{'; '.join(report.details)} · tokens {report.tokens_before} -> {report.tokens_after}")
    if report.affected == 0:
        return 0
    if not args.yes:
        print("dry-run; rerun with --yes to apply")
        return 0
    _save_session(idx, session)
    idx.close()
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    from .gui.app import main as gui_main

    return gui_main()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ctxbox", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--version", action="version", version=f"ctxbox {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("scan", help="discover & index all sessions")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("list", help="list indexed sessions")
    s.add_argument("--tool")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("show", help="print a conversation")
    s.add_argument("id")
    s.add_argument("--tool")
    s.add_argument("--max-chars", type=int, default=2000)
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("search", help="full-text search")
    s.add_argument("query")
    s.set_defaults(func=cmd_search)

    s = sub.add_parser("export", help="export a session")
    s.add_argument("id")
    s.add_argument("--tool")
    s.add_argument("--format", default="md", choices=["md", "json", "jsonl"])
    s.add_argument("--redact", action="store_true", help="scrub secrets/emails")
    s.add_argument(
        "--include-system",
        action="store_true",
        help="keep system/environment turns (skipped by default)",
    )
    s.add_argument("-o", "--output")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("inject", help="write a session as a new native session")
    s.add_argument("id")
    s.add_argument("--tool", help="source tool (if id is ambiguous)")
    s.add_argument("--to", required=True, help="target adapter name")
    s.add_argument("--target-dir")
    s.set_defaults(func=cmd_inject)

    s = sub.add_parser("adapters", help="list available adapters")
    s.set_defaults(func=cmd_adapters)

    s = sub.add_parser("replace", help="regex find & replace inside a session")
    s.add_argument("id")
    s.add_argument("pattern")
    s.add_argument("replacement")
    s.add_argument("--tool")
    s.add_argument("--roles", help="comma-separated: user,assistant,tool,system")
    s.add_argument("--yes", action="store_true", help="apply (default: dry-run)")
    s.set_defaults(func=cmd_replace)

    s = sub.add_parser("slim", help="shrink a session (drop bulky parts / budget)")
    s.add_argument("id")
    s.add_argument("--tool")
    s.add_argument("--drop-tool-results", action="store_true")
    s.add_argument("--drop-thinking", action="store_true")
    s.add_argument("--drop-tool-calls", action="store_true")
    s.add_argument("--max-part-chars", type=int)
    s.add_argument("--budget", type=int, help="token budget (keeps newest turns)")
    s.add_argument("--keep-first", type=int, default=1)
    s.add_argument("--yes", action="store_true", help="apply (default: dry-run)")
    s.set_defaults(func=cmd_slim)

    s = sub.add_parser("gui", help="launch the desktop app")
    s.set_defaults(func=cmd_gui)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0] - 2026-10-07

### Added
- **Dashboard home page**: welcome hero, stat cards (sessions / turns / tools /
  snapshots), recent activity with one-click open, quick actions
- **Keyboard shortcuts**: Ctrl+F search, Ctrl+R rescan, Ctrl+E export,
  Ctrl+D clone, Delete remove — listed in Settings → 快捷键
- Loading states: async session open with placeholder, scanning indicator
  with progress bar, empty-search placeholder
- Floating "back to bottom" button on long timelines
- App window icon (dev + PyInstaller paths)
- Kimi Code brand color/icon in the nav rail
- SECURITY.md, ROADMAP.md; README hero (logo, badges, real screenshots)

### Engineering
- mypy is now **clean and blocking** for `core/` (19 errors fixed via `as_dict`)
- Core coverage raised 80% → **89%**; CI runs pytest-cov and an offscreen
  GUI smoke test (`scripts/gui_smoke.py`)

## [0.3.0] - 2026-10-06

### Added
- **Kimi Code adapter**: parses `wire.jsonl` event logs (user prompts,
  thinking/text parts, tool calls/results, model info) — read + export
- **OpenCode adapter**: read-only SQLite (`opencode.db`), many sessions per
  DB via new `BaseAdapter.iter_sessions()` contract
- **Gemini CLI adapter**: `~/.gemini/tmp/*/chats/session-*.json`, array and
  checkpoint formats
- **Aider adapter**: `.aider.chat.history.md` markdown logs
- Index schema migration: primary key `(source_tool, source_path, id)`
  supports multi-session files; one-time automatic rebuild

## [0.2.1] - 2026-10-06

### Fixed
- **Timeline couldn't scroll through long messages**: QListWidget scrolled
  per-item, so a single turn taller than the viewport (long markdown
  summaries) was unreachable — switched timeline and session list to
  per-pixel scrolling
- Disabled horizontal scrollbars (labels word-wrap anyway)
- Nav rail/pill display name shortened ("Codex CLI / Desktop" → "Codex CLI")

## [0.2.0] - 2026-10-06

### Changed
- **GUI redesign, cc-switch inspired**: light theme by default (soft gray
  canvas, white rounded cards, blue accent), left icon nav rail with tool
  badges, capsule search box, primary/secondary button hierarchy
- Session cards: brand-colored tool pills, hover shadow + blue border,
  elided project paths, snapshot/hit-count pills
- Timeline: blue right-aligned user bubbles, white assistant cards, dashed
  tool/system blocks, amber noise-fold blocks
- Theme system (`gui/theme.py`): light/dark token sets, instant switching in
  Settings, persisted via QSettings

## [0.1.2] - 2026-10-06

### Fixed
- **Timeline collapsibles squashed**: expanding a thinking/tool/noise block
  now re-measures the row and updates the list item height — before, the row
  height was frozen at creation time so expanded content rendered as an
  empty box

## [0.1.1] - 2026-10-06

### Fixed
- **Smart titles**: session titles skip tool-injected context (`<environment_context>`, `<app-context>`, system reminders, file-mention blocks) and use the first real human question — no more every-session-named-`<environment_context>`
- **Noise folding**: environment/system turns are marked `meta.noise` and collapsed by default in the GUI timeline; exports skip them unless `--include-system` is passed
- **Search dedupe**: results are one row per conversation (was: one per snapshot × hit), with a total hit count
- **Clean snippets**: CJK bigrams moved to a separate FTS column — snippets no longer leak `[小红] [红书]` tokenization junk
- **Snapshot badge**: session cards and CLI search show `📷 N snapshots` when a conversation has multiple snapshot files

### Added
- `ctxbox export --include-system` flag
- Automatic FTS index migration from v0.1.0 databases

## [0.1.0] - 2026-01-01

### Added
- Initial release
- Unified conversation model (Session / Turn / ContentPart) with lossless `raw` round-trip
- Tolerant normalization engine: encoding detection, dirty JSONL recovery, schema version sniffing, line-type alias maps
- Adapters: Claude Code, Codex CLI/Desktop, Continue.dev, generic JSONL fallback
- SQLite index with FTS5 full-text search, incremental re-parse, file watching
- PySide6 GUI: dashboard, session browser, chat timeline, turn editor (add/edit/delete/copy/clone/reorder/merge), diff view
- Injection engine: write sessions back as new native files for Claude Code and Codex, with post-write verification
- Export/import: Markdown, JSON, JSONL, clipboard; secret redaction
- CLI: `ctxbox scan|list|show|export|inject`
- PyInstaller packaging for Windows / macOS / Linux via GitHub Actions

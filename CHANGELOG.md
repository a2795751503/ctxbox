# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

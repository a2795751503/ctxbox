# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

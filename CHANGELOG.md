# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.8.0] - 2026-10-07

### Added
- **Exchange-level editing**: a "round" is now a real Q&A pair (user input +
  all assistant output incl. thinking/tool activity), not a single message.
  The editor shows input and output separately; thinking and tool calls are
  preserved untouched on save
- **AI assist (opt-in)**: configure any OpenAI-compatible endpoint in
  Settings → AI 服务, then "✨ AI 优化" in the editor: optimize the question,
  optimize the answer, generate a title, or compress tool output. Four
  Chinese-first prompt templates ship editable. Every send is previewed and
  confirmed; keys stay on your machine — this is ctxbox's only network
  feature and it's disabled until you configure it
- `core/exchange.py` (`group_exchanges`) and `core/ai_client.py` (urllib-only
  `/chat/completions` client) with full tests

### Fixed
- Saving a session opened via the snapshot viewer now reloads the same file
  (was: "加载会话失败")

## [0.7.0] - 2026-10-07

### Changed
- **Conversation view rebuilt like the major LLM chat UIs** (Claude / ChatGPT /
  Codex / open-webui):
  - Tool calls and their results merge into single slim "⚡ Tool — args"
    activity rows (expandable: pretty-printed args + truncated result,
    full text on double-click) — timelines shrink ~26% on tool-heavy sessions
  - Tool-only assistant turns lose the bubble chrome (slim rows), collapsible
    blocks now carry content previews ("💭 思考过程 — 先检查 token…",
    "🔧 Read — auth.py"), code blocks get a copy button
  - Deleting an activity row removes both the call and its paired result
    through the standard diff-confirm + backup path

### Fixed
- Tool results no longer show "?" — adapters resolve the real tool name back
  from call ids (kimi-code, claude-code, codex)
- Cross-tool raw round-trip restricted to same-tool blocks

## [0.6.2] - 2026-10-07

### Changed
- **Theme rebuilt on the VSCode IDE palette**: Dark+ (editor #1e1e1e, sidebar
  #252526, button blue #0e639c) and Light+ (#ffffff / #f3f3f3 / #0078d4);
  dark is now the default theme
- Chat bubbles carry a bubble-level fallback text color — no unstyled label
  can ever inherit a mismatched foreground again

### Added
- **WCAG contrast guard test**: every foreground/background token pair in both
  themes is enforced ≥ 4.5 (3.0 for de-emphasized text) — the
  "white-on-white" class of bugs is now impossible to reintroduce
- Brand colors/icons for Pi, OpenCode, Gemini CLI, Aider

### Fixed
- Timeline readability bug reported as white text on white background

## [0.6.0] - 2026-10-07

### Added
- **Pi (pi.dev) adapter**: full read + inject. Parses session JSONL with
  `context_edit` semantics (post-hoc message deletions applied), verified
  against a live install; injection writes a brand-new session Pi picks up.
  Verified both directions on real data: codex→pi and pi→codex (35/35 and
  10/10 turns round-trip)

### Fixed
- Cross-tool raw round-trip: serializers now only reuse original blocks when
  they came from the same tool's parser — foreign payloads are converted
  instead of being dumped verbatim into the target format
- Stable turn ids across save/re-parse (Claude uuid preservation) and GUI
  auto-recovery from stale turn ids (0.5.1)

## [0.5.0] - 2026-10-07

### Added
- **Context Surgery** (🩺): regex find & replace with role filter, slim
  (drop tool results / thinking / tool calls), oversized-part clamping,
  token-budget truncation — every operation dry-runs on a copy and previews
  "N affected · tokens a → b" before applying. GUI panel + CLI
  `ctxbox replace` / `ctxbox slim`
- **Diff confirmation before save**: unified diff of the session is shown
  (colored +/- lines) before any write; cancellable, toggleable in Settings
- **Injection downgrade preview**: wizard now lists every block with
  keep/degrade/drop and explains the mapping before injecting
- **Snapshot viewer**: browse all snapshots of a conversation (mtime, turns,
  size) and open any of them directly
- **Token stats**: dashboard card with estimated total + Top-5 largest
  sessions; dependency-free `estimate_tokens` in core
- CLI parity: `ctxbox replace`, `ctxbox slim`

### Fixed
- **Windows file-lock failures on save**: atomic writes now clear the
  read-only flag and retry with backoff; persistent locks raise a
  FileLockedError telling you to close the AI tool holding the session
- Deterministic snapshot dedupe on low-resolution filesystems (ROW_NUMBER)

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

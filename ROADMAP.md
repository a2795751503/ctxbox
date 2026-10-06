# Roadmap / 路线图

Legend: ✅ shipped · 🚧 in progress · 📋 planned · 💭 exploring

## v0.1 — Foundation ✅
- Unified conversation model (Session/Turn/ContentPart), lossless raw round-trip
- Tolerant normalization: encoding detection, dirty JSONL repair, alias maps
- Adapters: Claude Code, Codex, Continue.dev, generic JSONL
- SQLite + FTS5 index, injection engine with verification, CLI, MIT open source

## v0.2 — Design system ✅
- cc-switch inspired GUI: theme tokens (light/dark), nav rail, card list, bubble timeline
- Smart titles, noise folding, search dedupe, CJK bigram search, snapshot badges

## v0.3 — Adapter breadth ✅
- Kimi Code (wire.jsonl), OpenCode (read-only SQLite, multi-session DB)
- Gemini CLI, Aider
- `iter_sessions()` contract for DB-backed tools

## v0.4 — Award-level polish 🚧
- Dashboard home page (stats, recent activity, quick actions)
- Keyboard shortcuts, loading states, back-to-bottom
- README hero (logo, badges, real screenshots), SECURITY.md
- Engineering: mypy tightening, coverage reporting, CI GUI smoke test

## v0.5 — Depth 📋
- Cursor adapter (`state.vscdb`, graceful degradation on encrypted fields)
- Cline / RooCode adapter (VS Code extension storage)
- Edit diff confirmation view before save
- Context surgery: global regex replace, token-budget trimming, bulk tool_result cleanup
- Injection downgrade preview (exact list of degraded blocks)

## v0.6 — Power features 📋
- Token statistics dashboard (tiktoken), per-tool/per-project charts
- Cross-tool injection mapping preview UI
- Session merge view for multi-snapshot conversations
- `ctxbox doctor` (health check of tool directories), `ctxbox open`

## v1.0 — Ecosystem 💭
- MCP server mode (`ctxbox mcp`): let any AI tool query your history
- Tray resident + global hotkey quick search
- Community adapter marketplace (external adapters as packages)
- Optional local embeddings search (offline, opt-in)
- Internationalization (zh-CN / en / ja)

## How priorities are set
1. Adapter requests from issues (vote with 👍)
2. Data-safety bugs always first
3. Everything is offline-capable — no feature may require network access

# ctxbox

[English](README.md) | [中文](README.zh-CN.md)

> One place for all your AI coding assistant contexts. Scan, search, edit, copy, and inject conversation history across Claude Code, Codex, Cursor, Continue, Gemini CLI, Aider and more — 100% local, open source, MIT licensed.

## Why ctxbox?

Your AI conversations are scattered across a dozen tools, each with its own opaque format (JSONL, SQLite, JSON, Markdown). ctxbox:

- **Discovers** every supported tool's sessions on your machine automatically
- **Normalizes** them into one clean conversation model — user inputs vs. assistant outputs, tool calls, thinking blocks — even when the format is dirty, half-broken, or a community fork's flavor
- **Lets you edit**: modify any turn, delete, insert, reorder, clone, merge, find & replace, redact secrets
- **Injects back**: write a session as a brand-new native session file so the original tool can resume it — or migrate a Claude Code debugging session into Codex and continue there
- **Never touches your originals**: atomic writes, automatic backups, one-click rollback

## Supported tools

| Tool | Read | Inject back | Notes |
|---|:---:|:---:|---|
| Claude Code | ✅ | ✅ | JSONL sessions, uuid chain rebuilt |
| Codex CLI / Desktop | ✅ | ✅ | rollout JSONL with `session_meta` |
| Continue.dev | ✅ | ✅ | |
| Generic JSONL (Kimi Code, OpenCode, …) | ✅ | ✅ | fallback adapter |
| Cursor / Gemini CLI / Aider / Cline / Copilot / Windsurf | v0.2 | — | [planned](docs/adapters.md), adapter PRs welcome |

Want your tool here? [Adding an adapter takes ~100 lines](CONTRIBUTING.md#adding-a-new-adapter). PRs welcome!

## Install

Download the latest build for your OS from [Releases](../../releases), or run from source:

```bash
git clone https://github.com/a2795751503/ctxbox.git
cd ctxbox
pip install -e ".[gui]"
ctxbox-gui          # launch the desktop app
```

## CLI

Every GUI feature has a CLI equivalent:

```bash
ctxbox scan                     # discover & index all sessions
ctxbox list --tool claude-code  # list sessions
ctxbox show <session-id>        # print a conversation
ctxbox export <id> --format md -o out.md
ctxbox inject <id> --to codex   # write as a new native session
```

## Privacy

ctxbox runs **entirely offline**. It never makes network requests with your data. Your conversations stay on your machine — the code is auditable, that's the point of open source.

## Roadmap

- [x] v0.1 — scan / search / edit / export / inject (Claude Code, Codex, Continue)
- [ ] v0.2 — cross-tool injection, Cursor/Gemini/Aider adapters, token stats
- [ ] v0.3 — MCP server mode, tray hotkey, adapter marketplace

## Contributing

We love contributions — especially new adapters! See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE) © a2795751503

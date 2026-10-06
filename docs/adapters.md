# Adapter support matrix / 适配器支持矩阵

| Adapter | Tool | Read | Inject | Session locations |
|---|---|---|---|---|
| `claude-code` | Claude Code | ✅ | ✅ | `~/.claude/projects/*/*.jsonl` |
| `codex` | Codex CLI / Desktop | ✅ | ✅ | `~/.codex/sessions/**/rollout-*.jsonl`, `~/.codex/archived_sessions/` |
| `continue` | Continue.dev | ✅ | ✅ | `~/.continue/sessions/*.json` |
| `kimi-code` | Kimi Code | ✅ | ⚠️ export | `~/.kimi-code/sessions/*/session_*/agents/main/wire.jsonl` |
| `pi` | Pi (pi.dev) | ✅ | ✅ | `~/.pi/agent/sessions/*/*.jsonl` |
| `opencode` | OpenCode | ✅ | ⚠️ export | `~/.local/share/opencode/opencode.db` (SQLite, read-only, multi-session) |
| `gemini-cli` | Gemini CLI | ✅ | ⚠️ export | `~/.gemini/tmp/*/chats/session-*.json` |
| `aider` | Aider | ✅ | ⚠️ export | `~/.aider.chat.history.md` |
| `generic-jsonl` | any JSONL tool | ✅ | ✅ | user-selected files |

## Planned / 计划中 (contributions welcome!)

| Tool | Status | Notes |
|---|---|---|
| Cursor | v0.4 | `state.vscdb` SQLite; encrypted fields degrade gracefully |
| Cline / RooCode | v0.4 | VS Code extension storage JSON |
| GitHub Copilot | v0.5 | read-only, workspaceStorage |
| Windsurf | v0.5 | |
| OpenCode legacy `storage/` JSON | — | pre-1.2 installs; SQLite is authoritative since 1.2 |

## Writing an adapter

See [CONTRIBUTING.md](../CONTRIBUTING.md#adding-a-new-adapter) — ~100 lines:

```python
@register
class MyToolAdapter(BaseAdapter):
    name = "my-tool"
    def detect(self) -> list[Path]: ...
    def parse(self, path) -> Session: ...
    def serialize(self, session) -> bytes: ...
    def inject(self, session, target_dir=None) -> Path: ...
```

# Adapter support matrix / 适配器支持矩阵

| Adapter | Tool | Read | Inject | Session locations |
|---|---|---|---|---|
| `claude-code` | Claude Code | ✅ | ✅ | `~/.claude/projects/*/*.jsonl` |
| `codex` | Codex CLI / Desktop | ✅ | ✅ | `~/.codex/sessions/**/rollout-*.jsonl`, `~/.codex/archived_sessions/` |
| `continue` | Continue.dev | ✅ | ✅ | `~/.continue/sessions/*.json` |
| `generic-jsonl` | any JSONL tool | ✅ | ✅ | user-selected files |

## Planned / 计划中 (contributions welcome!)

| Tool | Status | Notes |
|---|---|---|
| Cursor | v0.2 | `state.vscdb` SQLite; encrypted fields degrade gracefully |
| Gemini CLI | v0.2 | `~/.gemini/tmp/**/chats/*.json` |
| Aider | v0.2 | `.aider.chat.history.md` |
| Cline / RooCode | v0.2 | VS Code extension storage JSON |
| GitHub Copilot | v0.3 | read-only, workspaceStorage |
| Windsurf | v0.3 | |

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

# ctxbox architecture / 架构

## Layers / 分层

```
gui/      PySide6 desktop app (never imported by core)
cli.py    argparse CLI — every GUI feature has a CLI equivalent
core/
  model/      unified Session/Turn/ContentPart schema (pydantic)
  adapters/   one plugin per AI tool: detect / parse / serialize / inject
  normalize/  tolerant parsing: encoding detection, dirty JSONL repair,
              schema sniffing, alias maps — never lose data
  store/      SQLite index + FTS5 search (CJK bigram tokenizer) + backups
  inject/     injection engine with post-write verification
  utils/      cross-platform paths, atomic writes, secret redaction
```

## Design rules / 设计原则

1. **core never imports PySide6** — core is reusable as a library.
2. **Never overwrite user originals** — injection always writes a NEW session
   file (fresh id), edits go through backup + atomic write.
3. **Never lose data** — unparseable records become `raw` parts with warnings.
4. **Adapters are plugins** — drop a file into `core/adapters/`, decorate with
   `@register`, done. See CONTRIBUTING.md.

## Why per-file index keys / 为什么索引按文件而不是会话 ID

Codex splits one conversation across many rollout-*.jsonl snapshot files that
share the same session id. The index keys on `(source_tool, source_path)` and
dedupes at query time (newest snapshot wins).

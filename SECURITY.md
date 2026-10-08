# Security Policy

## Supported Versions

| Version | Supported |
|---|---|
| latest release | ✅ |
| older releases | ❌ |

## Privacy model / 隐私模型

ctxbox is **local-first and offline by default**: it reads AI tool session files on your
machine, builds a local SQLite index, and never sends your data anywhere.
There are no accounts, no telemetry, no analytics, no update checks that
carry user content.

**One opt-in exception**: the AI-assist features ("✨ AI 优化", v0.8+)
call an OpenAI-compatible `/chat/completions` endpoint that **you configure
yourself** (Base URL + API Key + Model in Settings). It is disabled until you
configure it, sends only the specific content shown in the send-preview
dialog you confirm, and your key is stored only on your machine (QSettings,
never in the repository or logs).

ctxbox 完全离线运行：只读取本机 AI 工具的会话文件、建立本地索引，
不会携带你的任何数据发起网络请求。无账号、无遥测、无分析。

**唯一的可选例外**：v0.8 的「✨ AI 优化」功能会调用**你自己配置**的
OpenAI 兼容端点。未配置时完全禁用；每次发送前都有预览确认框，只发送
你确认的那段内容；Key 只存在你自己电脑上。

## Write safety / 写入安全

- ctxbox **never overwrites original session files in place without a
  backup**; edits and injections go through atomic writes
  (temp file + `os.replace`) and automatic snapshots under the ctxbox data
  directory.
- Injection always creates a **new** session file — it never modifies an
  existing conversation.

## Reporting a Vulnerability

Please **do not** open a public issue for security reports — especially
anything involving private conversation data, path traversal in adapters,
or secret leakage in exports.

Instead, contact the maintainer privately via GitHub:
[@a2795751503](https://github.com/a2795751503) (use a private channel such
as GitHub's private vulnerability reporting on the Security tab).

请通过 GitHub 仓库 Security 页面的私密漏洞报告渠道联系我们，
**不要**开公开 issue 报告安全问题。

We aim to acknowledge within 72 hours and ship a fix or mitigation within
14 days for confirmed issues.

## Scope notes

- The **redaction** feature (`export --redact`) is best-effort pattern
  matching, not a guarantee. Always review exported content before sharing.
- ctxbox reads other applications' data directories by design; treat any
  crafted session file as untrusted input — if you find a parsing path that
  executes code or escapes the data dir, that is in scope and we want to
  hear about it.

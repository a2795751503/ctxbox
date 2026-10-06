"""Secret redaction: scrub tokens/keys/emails before exporting or sharing."""

from __future__ import annotations

import re

_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"sk-[A-Za-z0-9_\-]{16,}"), "sk-***REDACTED***"),  # OpenAI-style keys
    (re.compile(r"sk-ant-[A-Za-z0-9_\-]{10,}"), "sk-ant-***REDACTED***"),  # Anthropic keys
    (re.compile(r"ghp_[A-Za-z0-9]{20,}"), "ghp_***REDACTED***"),  # GitHub PAT
    (re.compile(r"gho_[A-Za-z0-9]{20,}"), "gho_***REDACTED***"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AKIA***REDACTED***"),  # AWS access key
    (
        re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,}"),
        "***JWT-REDACTED***",
    ),  # JWTs
    (
        re.compile(r"(?i)(api[_-]?key|token|secret|password|passwd)\s*[:=]\s*['\"]?[\w\-]{8,}"),
        r"\1=***REDACTED***",
    ),
    (re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"), "***EMAIL-REDACTED***"),
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{16,}"), r"\1***REDACTED***"),
    (re.compile(r"\b1[3-9]\d{9}\b"), "***PHONE-REDACTED***"),  # CN mobile numbers
]


def redact_text(text: str) -> str:
    for pat, repl in _PATTERNS:
        text = pat.sub(repl, text)
    return text

"""Tolerant normalization engine.

This is ctxbox's answer to "各种魔改、格式不支持":
- encoding detection (utf-8/16/gbk, BOM, bad bytes -> replacement + warning)
- dirty JSONL recovery (truncated lines, trailing commas, ANSI escapes)
- unknown record types degrade to raw payloads instead of crashing
- line-type alias maps so community forks keep parsing
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from charset_normalizer import from_bytes

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

# high-frequency hanzi for CJK decode tie-breaking
COMMON_CJK = "的一是不了在人有我他这中大来上国个到说们为子和你地出道也时年得就那要下以生会自着去之过家学对可她里后小么心多天而能好都然没日于起还发成事只作当想看文无开手十用主行方又如前所本见经头面公同三已老从动两"


@dataclass
class JsonlLine:
    """One line of a JSONL file, parsed as far as possible."""

    lineno: int
    data: dict[str, Any] | None  # parsed object, None if unrecoverable
    raw_text: str  # original line text
    warning: str | None = None  # set when the line needed repair or failed


@dataclass
class JsonlResult:
    lines: list[JsonlLine] = field(default_factory=list)
    encoding: str = "utf-8"
    warnings: list[str] = field(default_factory=list)

    @property
    def objects(self) -> Iterator[dict[str, Any]]:
        for ln in self.lines:
            if ln.data is not None:
                yield ln.data

    @property
    def bad_lines(self) -> list[JsonlLine]:
        return [ln for ln in self.lines if ln.data is None]


def decode_tolerant(raw: bytes) -> tuple[str, str, list[str]]:
    """Decode bytes with best-effort encoding detection.

    Returns (text, encoding, warnings). Never raises.
    """
    warnings: list[str] = []
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace"), "utf-8-sig", warnings
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        warnings.append("UTF-16 BOM detected; converted to str")
        return raw.decode("utf-16", errors="replace"), "utf-16", warnings
    try:
        return raw.decode("utf-8"), "utf-8", warnings
    except UnicodeDecodeError:
        pass
    best = from_bytes(raw).best()
    candidates: list[tuple[str, str]] = []
    if best is not None and best.encoding:
        candidates.append((best.encoding, str(best)))
    # charset_normalizer can misdetect CJK on short inputs; try the common ones
    for enc in ("gb18030", "big5", "shift_jis", "euc-kr"):
        try:
            candidates.append((enc, raw.decode(enc)))
        except (UnicodeDecodeError, LookupError):
            continue
    if candidates:
        # Short CJK samples are ambiguous across encodings (gb18030 vs big5
        # can BOTH decode without errors). Tie-break with a frequency
        # heuristic: the correct decode lands on common characters, a wrong
        # decode lands on rare ones. COMMON_CJK holds high-frequency hanzi.
        def _score(c):
            text = c[1]
            freq = sum(1 for ch in text if ch in COMMON_CJK)
            return (text.count("\ufffd"), -freq)

        enc, text = min(candidates, key=_score)
        warnings.append(f"Non-UTF-8 encoding detected ({enc}); decoded with it")
        return text, enc, warnings
    warnings.append("Encoding detection failed; fell back to utf-8 with replacement")
    return raw.decode("utf-8", errors="replace"), "utf-8", warnings


def _repair_json_line(text: str) -> str | None:
    """Try to make a dirty JSON line parseable. Returns repaired text or None."""
    t = _ANSI_RE.sub("", text).strip().rstrip(",")
    if not t:
        return None
    # truncated object/array: balance brackets by appending closers
    for opener, closer in (("{", "}"), ("[", "]")):
        missing = t.count(opener) - t.count(closer)
        if missing > 0:
            t += closer * missing
    # cut trailing garbage after the last closing brace
    last = t.rfind("}")
    if last > 0 and t[last + 1 :].strip():
        t = t[: last + 1]
    return t


def parse_jsonl_text(text: str) -> JsonlResult:
    """Parse JSONL text line by line. Broken lines are kept as raw_text with
    a warning instead of raising — we never drop data silently."""
    result = JsonlResult()
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict):
                result.lines.append(JsonlLine(lineno, obj, stripped))
            else:  # valid JSON but not an object (array/scalar): keep as raw wrapper
                result.lines.append(
                    JsonlLine(
                        lineno,
                        {"_ctxbox_raw_value": obj},
                        stripped,
                        "JSON value is not an object; wrapped",
                    )
                )
            continue
        except json.JSONDecodeError:
            pass
        repaired = _repair_json_line(stripped)
        if repaired is not None:
            try:
                obj = json.loads(repaired)
                if isinstance(obj, dict):
                    result.lines.append(
                        JsonlLine(lineno, obj, stripped, f"line {lineno}: repaired dirty JSON")
                    )
                    result.warnings.append(f"line {lineno}: repaired dirty JSON")
                    continue
            except json.JSONDecodeError:
                pass
        result.lines.append(
            JsonlLine(lineno, None, stripped, f"line {lineno}: unparseable, kept as raw text")
        )
        result.warnings.append(f"line {lineno}: unparseable JSONL line preserved as raw text")
    return result


def read_jsonl_tolerant(path: Path | str) -> JsonlResult:
    """Read a JSONL file tolerantly. This is the adapter's front door."""
    raw = Path(path).read_bytes()
    text, enc, warnings = decode_tolerant(raw)
    result = parse_jsonl_text(text)
    result.encoding = enc
    result.warnings = warnings + result.warnings
    return result


def sniff_schema_version(sample: dict[str, Any], markers: dict[str, list[str]]) -> str | None:
    """Pick the first version whose marker fields are all present in sample."""
    keys = set(sample.keys())
    for version, fields in markers.items():
        if all(f in keys for f in fields):
            return version
    return None

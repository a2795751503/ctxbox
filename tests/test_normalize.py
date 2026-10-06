"""Tolerant normalization engine tests: encoding, dirty lines, repair."""

from ctxbox.core.normalize import decode_tolerant, parse_jsonl_text


def test_parse_clean_jsonl():
    r = parse_jsonl_text('{"a":1}\n{"b":2}\n')
    assert len(r.lines) == 2
    assert not r.bad_lines


def test_dirty_line_kept_not_dropped():
    text = '{"ok":true}\nthis is not json\n{"also":"ok"}\n'
    r = parse_jsonl_text(text)
    assert len(r.lines) == 3
    assert len(r.bad_lines) == 1
    assert "not json" in r.bad_lines[0].raw_text  # data preserved


def test_truncated_line_repaired():
    r = parse_jsonl_text('{"a": {"b": 1}\n')
    assert r.lines[0].data == {"a": {"b": 1}}
    assert r.warnings  # repair was recorded


def test_trailing_garbage_repaired():
    r = parse_jsonl_text('{"a":1}  <<<STREAM CUT>>>')
    assert r.lines[0].data == {"a": 1}


def test_decode_utf16():
    raw = '{"x":"héllo"}'.encode("utf-16")
    text, enc, warnings = decode_tolerant(raw)
    assert "héllo" in text
    assert enc == "utf-16"


def test_decode_gbk_fallback():
    raw = '{"x":"中文"}\n'.encode("gbk")
    text, enc, _ = decode_tolerant(raw)
    assert "中文" in text


def test_never_raises_on_garbage():
    r = parse_jsonl_text("\x00\xff\n\n{bad\n{'single': 'quotes'}\n")
    assert isinstance(r.lines, list)

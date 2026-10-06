import os
import stat

from ctxbox.core.utils.atomic import atomic_write


def test_atomic_write_over_readonly(tmp_path):
    p = tmp_path / "ro.jsonl"
    p.write_text("old", encoding="utf-8")
    os.chmod(p, stat.S_IREAD)  # read-only: replace must still succeed
    try:
        atomic_write(p, b"new")
        assert p.read_bytes() == b"new"
    finally:
        os.chmod(p, stat.S_IWRITE | stat.S_IREAD)


def test_atomic_write_leaves_no_tmp_on_success(tmp_path):
    p = tmp_path / "f.txt"
    atomic_write(p, b"x")
    assert list(tmp_path.glob("*.tmp")) == []

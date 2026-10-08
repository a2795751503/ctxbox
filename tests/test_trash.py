"""OS recycle bin integration."""

import pytest

from ctxbox.core.utils import move_to_recycle_bin


def test_move_to_recycle_bin(tmp_path):
    p = tmp_path / "doomed.txt"
    p.write_text("bye", encoding="utf-8")
    where = move_to_recycle_bin(p)
    assert not p.exists()
    assert where  # 回收站 / Trash / 永久删除(回退)


def test_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        move_to_recycle_bin(tmp_path / "nope.txt")

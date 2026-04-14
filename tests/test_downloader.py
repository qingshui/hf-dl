import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from hf_dl.downloader import _build_proxies, _cleanup_failed_file
from hf_dl.config import DownloadConfig


def test_build_proxies_none():
    assert _build_proxies(None) == {}


def test_build_proxies_with_value():
    result = _build_proxies("http://127.0.0.1:7890")
    assert result == {"http": "http://127.0.0.1:7890", "https": "http://127.0.0.1:7890"}


def test_cleanup_failed_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test.bin")
        # 创建一个假文件
        with open(filepath, "w") as f:
            f.write("partial")
        assert os.path.exists(filepath)

        _cleanup_failed_file(filepath)
        assert not os.path.exists(filepath)


def test_cleanup_nonexistent_file():
    # 不存在的文件不应报错
    _cleanup_failed_file("/tmp/nonexistent_hf_dl_test_file.bin")

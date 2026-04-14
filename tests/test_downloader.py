import json
import os
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from hf_dl.downloader import (
    get_file_size,
    split_ranges,
    download_chunk,
    download_file_multithread,
)
from hf_dl.config import DownloadConfig


def test_split_ranges_even():
    ranges = split_ranges(1000, 4)
    assert len(ranges) == 4
    assert ranges[0] == (0, 249)
    assert ranges[3] == (750, 999)
    assert sum(e - s + 1 for s, e in ranges) == 1000


def test_split_ranges_not_divisible():
    ranges = split_ranges(100, 3)
    assert len(ranges) == 3
    assert sum(e - s + 1 for s, e in ranges) == 100


def test_split_ranges_single():
    ranges = split_ranges(100, 1)
    assert ranges == [(0, 99)]


def test_download_chunk_writes_file():
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "test.bin")
        mock_resp = MagicMock()
        mock_resp.iter_content.return_value = [b"hello", b" world"]
        mock_resp.status_code = 200
        mock_resp.headers = {"content-length": "11"}

        with patch("hf_dl.downloader.requests.get", return_value=mock_resp):
            download_chunk(
                url="https://example.com/file",
                filepath=filepath,
                start=0,
                end=10,
                chunk_index=0,
                headers={},
                proxies=None,
            )

        with open(filepath, "rb") as f:
            content = f.read()
        assert content == b"hello world"


def test_get_file_size():
    mock_resp = MagicMock()
    mock_resp.headers = {"content-length": "12345"}
    mock_resp.status_code = 200

    with patch("hf_dl.downloader.requests.head", return_value=mock_resp):
        size = get_file_size("https://example.com/file", {}, None)
    assert size == 12345


def test_get_file_size_no_content_length():
    mock_resp = MagicMock()
    mock_resp.headers = {}
    mock_resp.status_code = 200

    with patch("hf_dl.downloader.requests.head", return_value=mock_resp):
        size = get_file_size("https://example.com/file", {}, None)
    assert size == -1


def test_download_file_multithread_creates_progress():
    with tempfile.TemporaryDirectory() as tmpdir:
        filepath = os.path.join(tmpdir, "bigfile.bin")
        progress_file = os.path.join(tmpdir, ".bigfile.bin.progress")

        mock_resp_head = MagicMock()
        mock_resp_head.headers = {"content-length": "1000"}
        mock_resp_head.status_code = 200

        mock_resp_get = MagicMock()
        mock_resp_get.iter_content.return_value = [b"x" * 100]
        mock_resp_get.status_code = 200
        mock_resp_get.headers = {"content-length": "100"}

        cfg = DownloadConfig(repo_id="test/model", threads=2, chunk_threshold="100")

        with patch("hf_dl.downloader.requests.head", return_value=mock_resp_head), \
             patch("hf_dl.downloader.requests.get", return_value=mock_resp_get):
            download_file_multithread(
                url="https://example.com/bigfile.bin",
                filepath=filepath,
                file_size=1000,
                config=cfg,
            )

        assert not os.path.exists(progress_file)
        assert os.path.exists(filepath)

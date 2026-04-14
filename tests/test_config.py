import os
import pytest
from hf_dl.config import DownloadConfig


def test_default_config():
    cfg = DownloadConfig(repo_id="gpt2")
    assert cfg.repo_id == "gpt2"
    assert cfg.endpoint == "https://huggingface.co"
    assert cfg.use_mirror is False
    assert cfg.proxy is None
    assert cfg.threads == 4
    assert cfg.chunk_threshold == 100 * 1024 * 1024
    assert cfg.resume is True
    assert cfg.local_dir == "gpt2"


def test_mirror_enabled():
    cfg = DownloadConfig(repo_id="gpt2", use_mirror=True)
    assert cfg.endpoint == "https://hf-mirror.com"


def test_mirror_with_custom_url():
    cfg = DownloadConfig(repo_id="gpt2", use_mirror=True, mirror_url="https://my-mirror.com")
    assert cfg.endpoint == "https://my-mirror.com"


def test_no_mirror():
    cfg = DownloadConfig(repo_id="gpt2", use_mirror=False)
    assert cfg.endpoint == "https://huggingface.co"


def test_custom_proxy():
    cfg = DownloadConfig(repo_id="gpt2", proxy="http://127.0.0.1:7890")
    assert cfg.proxy == "http://127.0.0.1:7890"


def test_proxy_from_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://env-proxy:8080")
    cfg = DownloadConfig(repo_id="gpt2")
    assert cfg.proxy == "http://env-proxy:8080"


def test_explicit_proxy_overrides_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://env-proxy:8080")
    cfg = DownloadConfig(repo_id="gpt2", proxy="http://explicit:7890")
    assert cfg.proxy == "http://explicit:7890"


def test_token_from_env(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_test_token")
    cfg = DownloadConfig(repo_id="gpt2")
    assert cfg.token == "hf_test_token"


def test_explicit_token_overrides_env(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "hf_env_token")
    cfg = DownloadConfig(repo_id="gpt2", token="hf_explicit")
    assert cfg.token == "hf_explicit"


def test_custom_local_dir():
    cfg = DownloadConfig(repo_id="gpt2", local_dir="/tmp/models/gpt2")
    assert cfg.local_dir == "/tmp/models/gpt2"


def test_custom_threads_and_threshold():
    cfg = DownloadConfig(repo_id="gpt2", threads=8, chunk_threshold="50M")
    assert cfg.threads == 8
    assert cfg.chunk_threshold == 50 * 1024 * 1024

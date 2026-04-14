import pytest
from hf_dl.utils import parse_size, match_glob_pattern


def test_parse_size_bytes():
    assert parse_size("100") == 100


def test_parse_size_kb():
    assert parse_size("10K") == 10 * 1024
    assert parse_size("10k") == 10 * 1024


def test_parse_size_mb():
    assert parse_size("50M") == 50 * 1024 * 1024
    assert parse_size("100MB") == 100 * 1024 * 1024


def test_parse_size_gb():
    assert parse_size("2G") == 2 * 1024 * 1024 * 1024


def test_parse_size_invalid():
    with pytest.raises(ValueError):
        parse_size("abc")


def test_match_glob_pattern_star():
    assert match_glob_pattern("model.safetensors", "*.safetensors")
    assert not match_glob_pattern("config.json", "*.safetensors")


def test_match_glob_pattern_question():
    assert match_glob_pattern("file1.txt", "file?.txt")
    assert not match_glob_pattern("file10.txt", "file?.txt")


def test_match_glob_pattern_exact():
    assert match_glob_pattern("config.json", "config.json")
    assert not match_glob_pattern("config.json", "tokenizer.json")

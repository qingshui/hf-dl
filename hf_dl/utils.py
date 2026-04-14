"""工具函数"""

import fnmatch
import re


def parse_size(size_str: str) -> int:
    """将人类可读的文件大小字符串解析为字节数。

    支持格式: 100, 10K, 50M, 100MB, 2G, 1GB（不区分大小写）
    """
    match = re.match(r'^(\d+(?:\.\d+)?)\s*([KMG]?)(B?)$', size_str.strip(), re.IGNORECASE)
    if not match:
        raise ValueError(f"无法解析文件大小: {size_str}")

    number = float(match.group(1))
    unit = match.group(2).upper()

    multipliers = {"": 1, "K": 1024, "M": 1024 ** 2, "G": 1024 ** 3}
    return int(number * multipliers[unit])


def match_glob_pattern(filename: str, pattern: str) -> bool:
    """检查文件名是否匹配 glob 模式。"""
    return fnmatch.fnmatch(filename, pattern)

"""镜像源、代理、endpoint 配置管理"""

import os
from dataclasses import dataclass, field
from typing import Optional

from hf_dl.utils import parse_size

MIRROR_ENDPOINT = "https://hf-mirror.com"
OFFICIAL_ENDPOINT = "https://huggingface.co"


@dataclass
class DownloadConfig:
    """下载配置"""

    repo_id: str
    local_dir: Optional[str] = None
    include: Optional[str] = None
    exclude: Optional[str] = None
    use_mirror: bool = True
    proxy: Optional[str] = None
    threads: int = 4
    chunk_threshold: str = "100M"
    resume: bool = True
    token: Optional[str] = None

    # 计算属性，初始化后设置
    endpoint: str = field(init=False, repr=False)
    _chunk_threshold_bytes: int = field(init=False, repr=False)

    def __post_init__(self):
        # endpoint
        self.endpoint = MIRROR_ENDPOINT if self.use_mirror else OFFICIAL_ENDPOINT

        # chunk_threshold 解析
        self._chunk_threshold_bytes = parse_size(self.chunk_threshold)
        self.chunk_threshold = self._chunk_threshold_bytes

        # local_dir 默认值
        if self.local_dir is None:
            self.local_dir = self.repo_id.split("/")[-1]

        # proxy: 显式参数 > 环境变量
        if self.proxy is None:
            self.proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")

        # token: 显式参数 > 环境变量
        if self.token is None:
            self.token = os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")

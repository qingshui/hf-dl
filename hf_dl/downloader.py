"""下载引擎：单文件下载 + 多线程分片下载 + 断点续传"""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import requests
from rich.progress import BarColumn, DownloadColumn, Progress, TimeRemainingColumn, TransferSpeedColumn

from hf_dl.config import DownloadConfig

logger = logging.getLogger(__name__)


def get_file_size(url: str, headers: dict, proxies: Optional[str]) -> int:
    """通过 HEAD 请求获取文件大小，失败返回 -1。"""
    try:
        resp = requests.head(url, headers=headers, proxies=_build_proxies(proxies), timeout=30, allow_redirects=True)
        resp.raise_for_status()
        return int(resp.headers.get("content-length", -1))
    except Exception:
        return -1


def split_ranges(file_size: int, num_chunks: int) -> List[Tuple[int, int]]:
    """将文件大小分割为 num_chunks 个 range 区间。"""
    chunk_size = file_size // num_chunks
    ranges = []
    for i in range(num_chunks):
        start = i * chunk_size
        end = start + chunk_size - 1 if i < num_chunks - 1 else file_size - 1
        ranges.append((start, end))
    return ranges


def _build_proxies(proxy: Optional[str]) -> Optional[dict]:
    """构建 requests 代理字典。"""
    if not proxy:
        return None
    return {"http": proxy, "https": proxy}


def download_chunk(
    url: str,
    filepath: str,
    start: int,
    end: int,
    chunk_index: int,
    headers: dict,
    proxies: Optional[str],
    max_retries: int = 3,
    retry_delay: float = 5.0,
) -> bool:
    """下载单个分片，写入文件的指定偏移位置。返回是否成功。"""
    range_headers = {**headers, "Range": f"bytes={start}-{end}"}
    for attempt in range(max_retries):
        try:
            resp = requests.get(
                url,
                headers=range_headers,
                proxies=_build_proxies(proxies),
                stream=True,
                timeout=300,
            )
            resp.raise_for_status()

            with open(filepath, "r+b" if os.path.exists(filepath) else "wb") as f:
                f.seek(start)
                for data in resp.iter_content(chunk_size=8192):
                    f.write(data)
            return True
        except Exception as e:
            logger.warning(f"分片 {chunk_index} 第 {attempt + 1} 次下载失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay)
    return False


def _load_progress(progress_file: str) -> Dict:
    """加载断点续传进度文件。"""
    if os.path.exists(progress_file):
        with open(progress_file, "r") as f:
            return json.load(f)
    return {}


def _save_progress(progress_file: str, data: Dict):
    """保存断点续传进度文件。"""
    with open(progress_file, "w") as f:
        json.dump(data, f)


def download_file_multithread(
    url: str,
    filepath: str,
    file_size: int,
    config: DownloadConfig,
):
    """多线程分片下载大文件，支持断点续传。"""
    progress_file = filepath + ".progress"
    num_chunks = config.threads
    ranges = split_ranges(file_size, num_chunks)

    # 加载已有进度
    progress_data = _load_progress(progress_file)
    completed_chunks = set(progress_data.get("completed", []))

    # 创建占位文件
    if not os.path.exists(filepath):
        with open(filepath, "wb") as f:
            f.seek(file_size - 1)
            f.write(b"\0")

    headers = {}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"

    with Progress(
        "[progress.description]{task.description}",
        BarColumn(),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
    ) as progress:
        task = progress.add_task(f"[cyan]{os.path.basename(filepath)}", total=file_size)

        with ThreadPoolExecutor(max_workers=num_chunks) as executor:
            futures = {}
            for idx, (start, end) in enumerate(ranges):
                if idx in completed_chunks:
                    progress.update(task, advance=end - start + 1)
                    continue
                future = executor.submit(
                    download_chunk,
                    url=url,
                    filepath=filepath,
                    start=start,
                    end=end,
                    chunk_index=idx,
                    headers=headers,
                    proxies=config.proxy,
                )
                futures[future] = idx

            for future in as_completed(futures):
                idx = futures[future]
                start, end = ranges[idx]
                success = future.result()
                if success:
                    completed_chunks.add(idx)
                    progress.update(task, advance=end - start + 1)
                    _save_progress(progress_file, {"completed": list(completed_chunks)})
                else:
                    raise RuntimeError(f"分片 {idx} 下载失败，已重试多次")

    if os.path.exists(progress_file):
        os.remove(progress_file)


def download_file_single(
    repo_id: str,
    filename: str,
    config: DownloadConfig,
):
    """使用 huggingface_hub 下载单个文件（小文件默认路径）。"""
    from huggingface_hub import hf_hub_download

    hf_hub_download(
        repo_id=repo_id,
        filename=filename,
        local_dir=config.local_dir,
        endpoint=config.endpoint,
        token=config.token,
    )


def download_repo(config: DownloadConfig):
    """下载整个仓库，根据文件大小选择下载方式。"""
    from huggingface_hub import HfApi

    api = HfApi(endpoint=config.endpoint, token=config.token)
    files = api.list_repo_tree(repo_id=config.repo_id)

    from hf_dl.utils import match_glob_pattern

    include_patterns = config.include.split(",") if config.include else None
    exclude_patterns = config.exclude.split(",") if config.exclude else None

    target_files = []
    for f in files:
        # RepoFile has 'size', RepoFolder does not - skip folders
        if not hasattr(f, "size"):
            continue
        fname = f.path
        fsize = f.size

        if include_patterns and not any(match_glob_pattern(fname, p.strip()) for p in include_patterns):
            continue
        if exclude_patterns and any(match_glob_pattern(fname, p.strip()) for p in exclude_patterns):
            continue

        target_files.append((fname, fsize))

    if not target_files:
        print("[yellow]没有匹配的文件[/yellow]")
        return

    print(f"[green]共 {len(target_files)} 个文件需要下载[/green]")

    base_url = f"{config.endpoint}/{config.repo_id}/resolve/main"

    for fname, fsize in target_files:
        local_path = os.path.join(config.local_dir, fname)
        os.makedirs(os.path.dirname(local_path), exist_ok=True)

        if os.path.exists(local_path) and os.path.getsize(local_path) == fsize:
            print(f"[dim]跳过已存在: {fname}[/dim]")
            continue

        if config.threads > 0 and fsize > config.chunk_threshold:
            url = f"{base_url}/{fname}"
            try:
                remote_size = get_file_size(url, {}, config.proxy)
                if remote_size <= 0:
                    remote_size = fsize
                download_file_multithread(
                    url=url,
                    filepath=local_path,
                    file_size=remote_size,
                    config=config,
                )
            except Exception as e:
                logger.error(f"多线程下载 {fname} 失败: {e}, 回退到单文件下载")
                download_file_single(config.repo_id, fname, config)
        else:
            try:
                download_file_single(config.repo_id, fname, config)
            except Exception as e:
                logger.error(f"下载 {fname} 失败: {e}")

"""下载引擎：单文件下载 + 多线程分片下载 + 断点续传"""

import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Tuple

import requests
from rich.progress import (
    BarColumn,
    DownloadColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from hf_dl.config import DownloadConfig

logger = logging.getLogger(__name__)

# 进度条列定义
_FILE_PROGRESS_COLUMNS = (
    SpinnerColumn(),
    TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
    BarColumn(bar_width=40),
    DownloadColumn(),
    TransferSpeedColumn(),
    TimeRemainingColumn(),
)


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


def _build_auth_headers(config: DownloadConfig) -> dict:
    """构建认证请求头。"""
    headers = {}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    return headers


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
    progress: Optional[Progress] = None,
    parent_task_id: Optional[int] = None,
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

    headers = _build_auth_headers(config)
    filename = os.path.basename(filepath)

    own_progress = progress is None
    if own_progress:
        progress = Progress(*_FILE_PROGRESS_COLUMNS)
        progress.start()

    task = progress.add_task(
        "", total=file_size, filename=filename, status="",
    )

    # 如果有父任务，也同步更新
    def _advance(amount):
        progress.update(task, advance=amount)
        if parent_task_id is not None:
            progress.update(parent_task_id, advance=amount)

    try:
        with ThreadPoolExecutor(max_workers=num_chunks) as executor:
            futures = {}
            for idx, (start, end) in enumerate(ranges):
                if idx in completed_chunks:
                    _advance(end - start + 1)
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
                    _advance(end - start + 1)
                    _save_progress(progress_file, {"completed": list(completed_chunks)})
                else:
                    raise RuntimeError(f"分片 {idx} 下载失败，已重试多次")
    finally:
        if own_progress:
            progress.stop()

    if os.path.exists(progress_file):
        os.remove(progress_file)


def download_file_single(
    url: str,
    filepath: str,
    config: DownloadConfig,
    progress: Optional[Progress] = None,
    parent_task_id: Optional[int] = None,
):
    """使用 requests 流式下载单个文件，带进度条显示。"""
    headers = _build_auth_headers(config)
    filename = os.path.basename(filepath)

    # 续传：如果本地文件已存在部分内容
    downloaded = 0
    if os.path.exists(filepath):
        downloaded = os.path.getsize(filepath)
        if downloaded > 0:
            headers["Range"] = f"bytes={downloaded}-"

    resp = requests.get(
        url,
        headers=headers,
        proxies=_build_proxies(config.proxy),
        stream=True,
        timeout=300,
    )
    resp.raise_for_status()

    total_size = int(resp.headers.get("content-length", 0))
    # 如果服务器支持 Range，total_size 是剩余部分
    if downloaded > 0 and resp.status_code == 206:
        total_size += downloaded
    elif total_size == 0:
        total_size = downloaded

    own_progress = progress is None
    if own_progress:
        progress = Progress(*_FILE_PROGRESS_COLUMNS)
        progress.start()

    task = progress.add_task(
        "", total=total_size if total_size > 0 else None,
        filename=filename, status="",
    )

    # 如果有续传偏移，先更新进度条
    if downloaded > 0:
        progress.update(task, advance=downloaded)
        if parent_task_id is not None:
            progress.update(parent_task_id, advance=downloaded)

    try:
        mode = "ab" if downloaded > 0 and resp.status_code == 206 else "wb"
        os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)
        with open(filepath, mode) as f:
            for data in resp.iter_content(chunk_size=8192):
                f.write(data)
                size = len(data)
                progress.update(task, advance=size)
                if parent_task_id is not None:
                    progress.update(parent_task_id, advance=size)
    finally:
        if own_progress:
            progress.stop()


def download_repo(config: DownloadConfig):
    """下载整个仓库，根据文件大小选择下载方式。"""
    from huggingface_hub import HfApi

    from hf_dl.utils import match_glob_pattern

    console = _get_console()
    console.print(f"[bold]正在获取文件列表...[/bold]")

    api = HfApi(endpoint=config.endpoint, token=config.token)
    files = api.list_repo_tree(repo_id=config.repo_id)

    include_patterns = config.include.split(",") if config.include else None
    exclude_patterns = config.exclude.split(",") if config.exclude else None

    target_files = []
    for f in files:
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
        console.print("[yellow]没有匹配的文件[/yellow]")
        return

    total_size = sum(s for _, s in target_files)
    console.print(f"[bold green]共 {len(target_files)} 个文件，总大小 {_format_size(total_size)}[/bold green]")
    console.print()

    base_url = f"{config.endpoint}/{config.repo_id}/resolve/main"

    # 整体进度条：追踪所有文件的下载进度
    with Progress(
        SpinnerColumn(),
        TextColumn("[bold]{task.description}"),
        BarColumn(bar_width=40),
        DownloadColumn(),
        TransferSpeedColumn(),
        TimeRemainingColumn(),
        TextColumn("{task.fields[status]}"),
    ) as progress:
        overall_task = progress.add_task(
            "总体进度", total=total_size,
            status=f"0/{len(target_files)} 文件",
        )

        completed = 0
        for fname, fsize in target_files:
            local_path = os.path.join(config.local_dir, fname)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)

            # 已存在的文件跳过
            if os.path.exists(local_path) and os.path.getsize(local_path) == fsize:
                progress.update(overall_task, advance=fsize)
                completed += 1
                progress.update(overall_task, status=f"{completed}/{len(target_files)} 文件")
                continue

            url = f"{base_url}/{fname}"

            if config.threads > 0 and fsize > config.chunk_threshold:
                # 大文件: 多线程分片下载
                try:
                    remote_size = get_file_size(url, {}, config.proxy)
                    if remote_size <= 0:
                        remote_size = fsize
                    download_file_multithread(
                        url=url,
                        filepath=local_path,
                        file_size=remote_size,
                        config=config,
                        progress=progress,
                        parent_task_id=overall_task,
                    )
                except Exception as e:
                    logger.error(f"多线程下载 {fname} 失败: {e}, 回退到单文件下载")
                    download_file_single(
                        url=url,
                        filepath=local_path,
                        config=config,
                        progress=progress,
                        parent_task_id=overall_task,
                    )
            else:
                # 小文件: 流式下载
                try:
                    download_file_single(
                        url=url,
                        filepath=local_path,
                        config=config,
                        progress=progress,
                        parent_task_id=overall_task,
                    )
                except Exception as e:
                    logger.error(f"下载 {fname} 失败: {e}")

            completed += 1
            progress.update(overall_task, status=f"{completed}/{len(target_files)} 文件")


def _get_console():
    """获取 rich Console 实例。"""
    from rich.console import Console
    return Console()


def _format_size(size: int) -> str:
    """将字节数格式化为人类可读字符串。"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"

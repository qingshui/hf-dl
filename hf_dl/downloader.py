"""下载引擎：并发文件下载 + 断点续传 + 自动回退"""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Optional, Tuple

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

from hf_dl.config import DownloadConfig, OFFICIAL_ENDPOINT

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

# 下载重试次数
_MAX_RETRIES = 5
_RETRY_DELAY = 3.0


def _build_proxies(proxy: str) -> dict:
    """构建 requests 代理字典。"""
    if not proxy:
        return {}
    return {"http": proxy, "https": proxy}


def _build_auth_headers(config: DownloadConfig) -> dict:
    """构建认证请求头。"""
    headers = {}
    if config.token:
        headers["Authorization"] = f"Bearer {config.token}"
    return headers


def download_file(
    url: str,
    filepath: str,
    config: DownloadConfig,
    progress: Progress,
    parent_task_id: int,
):
    """单线程流式下载单个文件，支持断点续传和重试。"""
    filename = os.path.basename(filepath)
    os.makedirs(os.path.dirname(filepath) or ".", exist_ok=True)

    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            _do_download(url, filepath, config, progress, parent_task_id, filename)
            return
        except Exception as e:
            logger.warning(f"下载 {filename} 第 {attempt} 次失败: {e}")
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_DELAY)
            else:
                raise


def _do_download(
    url: str,
    filepath: str,
    config: DownloadConfig,
    progress: Progress,
    parent_task_id: int,
    filename: str,
):
    """执行一次下载尝试，支持断点续传。"""
    headers = _build_auth_headers(config)
    proxies = _build_proxies(config.proxy)

    # 断点续传：检查本地已下载的字节数
    downloaded = 0
    if os.path.exists(filepath):
        downloaded = os.path.getsize(filepath)
        if downloaded > 0:
            headers["Range"] = f"bytes={downloaded}-"

    resp = requests.get(
        url,
        headers=headers,
        proxies=proxies,
        stream=True,
        timeout=300,
    )
    resp.raise_for_status()

    # 计算总大小
    total_size = int(resp.headers.get("content-length", 0))
    if downloaded > 0 and resp.status_code == 206:
        total_size += downloaded
    elif total_size == 0:
        total_size = downloaded

    # 进度条
    task = progress.add_task(
        "", total=total_size if total_size > 0 else None,
        filename=filename, status="",
    )

    if downloaded > 0:
        progress.update(task, advance=downloaded)
        progress.update(parent_task_id, advance=downloaded)

    try:
        mode = "ab" if downloaded > 0 and resp.status_code == 206 else "wb"
        with open(filepath, mode) as f:
            for data in resp.iter_content(chunk_size=8192):
                f.write(data)
                size = len(data)
                progress.update(task, advance=size)
                progress.update(parent_task_id, advance=size)
    except Exception:
        progress.remove_task(task)
        raise

    progress.remove_task(task)


def _download_one_file(
    fname: str,
    fsize: int,
    config: DownloadConfig,
    progress: Progress,
    parent_task_id: int,
    fallback_endpoints: List[str],
) -> bool:
    """下载单个文件，镜像失败自动回退。返回是否成功。"""
    console = _get_console()
    local_path = os.path.join(config.local_dir, fname)

    # 已存在的文件跳过
    if os.path.exists(local_path) and os.path.getsize(local_path) == fsize:
        progress.update(parent_task_id, advance=fsize)
        return True

    # 依次尝试：当前源 -> 备选源
    endpoints_to_try = [config.endpoint] + fallback_endpoints

    for endpoint in endpoints_to_try:
        url = f"{endpoint}/{config.repo_id}/resolve/main/{fname}"
        try:
            download_file(
                url=url,
                filepath=local_path,
                config=config,
                progress=progress,
                parent_task_id=parent_task_id,
            )
            return True
        except Exception as e:
            endpoint_label = "镜像源" if endpoint != OFFICIAL_ENDPOINT else "官方源"
            logger.warning(f"{endpoint_label}下载 {fname} 失败: {e}")
            _cleanup_failed_file(local_path)
            if fallback_endpoints:
                console.print(f"[yellow]{endpoint_label}下载 {fname} 失败，尝试回退官方源...[/yellow]")

    logger.error(f"下载 {fname} 失败: 所有源均不可用")
    console.print(f"[bold red]下载 {fname} 失败: 所有源均不可用[/bold red]")
    return False


def download_repo(config: DownloadConfig):
    """下载整个仓库，多文件并发，镜像失败自动回退官方源。"""
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

    # 构建备选 endpoint 列表（镜像下载失败时回退官方源）
    fallback_endpoints = []
    if config.mirror and config.endpoint != OFFICIAL_ENDPOINT:
        fallback_endpoints = [OFFICIAL_ENDPOINT]

    # 整体进度条
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
        completed_lock = threading.Lock()

        def _on_file_done(future):
            """单个文件下载完成后的回调，更新计数。"""
            nonlocal completed
            with completed_lock:
                completed += 1
                progress.update(overall_task, status=f"{completed}/{len(target_files)} 文件")

        # 并发下载：线程池处理多个文件
        num_workers = min(config.threads, len(target_files))
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {}
            for fname, fsize in target_files:
                future = executor.submit(
                    _download_one_file,
                    fname=fname,
                    fsize=fsize,
                    config=config,
                    progress=progress,
                    parent_task_id=overall_task,
                    fallback_endpoints=fallback_endpoints,
                )
                future.add_done_callback(_on_file_done)
                futures[future] = fname

            # 等待所有任务完成
            for future in as_completed(futures):
                fname = futures[future]
                try:
                    future.result()
                except Exception as e:
                    logger.error(f"下载 {fname} 异常: {e}")


def _get_console():
    """获取 rich Console 实例。"""
    from rich.console import Console
    return Console()


def _cleanup_failed_file(filepath: str):
    """清理下载失败的残留文件。"""
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
        except OSError:
            pass


def _format_size(size: int) -> str:
    """将字节数格式化为人类可读字符串。"""
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} PB"

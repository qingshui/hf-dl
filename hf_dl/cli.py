"""CLI 入口，argparse 参数解析与主流程调度"""

import argparse
import logging
import signal
import sys

from rich.console import Console

from hf_dl import __version__
from hf_dl.config import DownloadConfig
from hf_dl.downloader import download_repo

console = Console()


def parse_args(argv=None):
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        prog="hf-dl",
        description="HuggingFace 模型下载工具 - 支持镜像加速和断点续传",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command", help="可用命令")

    # download 子命令
    dl_parser = subparsers.add_parser("download", help="下载模型/数据集")
    dl_parser.add_argument("repo_id", help="仓库ID，如 gpt2 或 org/model-name")
    dl_parser.add_argument("--local-dir", help="本地保存路径（默认: ./<repo_name>）")
    dl_parser.add_argument("--include", help="仅下载指定文件（逗号分隔，支持 glob）")
    dl_parser.add_argument("--exclude", help="排除指定文件（逗号分隔，支持 glob）")
    dl_parser.add_argument("--mirror", nargs="?", const="https://hf-mirror.com", default=None,
                           help="使用镜像源加速，不加值默认 hf-mirror.com，可指定自定义地址")
    dl_parser.add_argument("--proxy", help="HTTP 代理地址，如 http://127.0.0.1:7890")
    dl_parser.add_argument("--threads", type=int, default=4, help="并发下载文件数（默认4）")
    dl_parser.add_argument("--token", help="HuggingFace token")
    dl_parser.add_argument("--no-resume", dest="resume", action="store_false", help="禁用断点续传")

    return parser.parse_args(argv)


def main(argv=None):
    """主入口。"""
    args = parse_args(argv)

    if args.command is None:
        console.print("[bold red]请指定命令，如: hf-dl download gpt2[/bold red]")
        sys.exit(1)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.command == "download":
        config = DownloadConfig(
            repo_id=args.repo_id,
            local_dir=args.local_dir,
            include=args.include,
            exclude=args.exclude,
            mirror=args.mirror,
            proxy=args.proxy,
            threads=args.threads,
            resume=args.resume,
            token=args.token,
        )

        console.print(f"[bold green]仓库:[/bold green] {config.repo_id}")
        console.print(f"[bold green]下载源:[/bold green] {config.endpoint}")
        if config.proxy:
            console.print(f"[bold green]代理:[/bold green] {config.proxy}")
        console.print(f"[bold green]并发数:[/bold green] {config.threads}")
        console.print(f"[bold green]本地路径:[/bold green] {config.local_dir}")
        console.print()

        def signal_handler(sig, frame):
            console.print("\n[yellow]下载中断，已下载部分已保存。重新运行相同命令可续传。[/yellow]")
            sys.exit(0)

        signal.signal(signal.SIGINT, signal_handler)

        try:
            download_repo(config)
            console.print("[bold green]下载完成！[/bold green]")
        except Exception as e:
            console.print(f"[bold red]下载失败: {e}[/bold red]")
            sys.exit(1)


if __name__ == "__main__":
    main()

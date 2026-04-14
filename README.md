# hf-dl: HuggingFace 国内下载加速器

通过 [hf-mirror.com](https://hf-mirror.com) 国内公益镜像加速 HuggingFace 模型下载，支持 HTTP 代理、多线程分片下载和断点续传。

## 功能特性

- **镜像加速**：默认使用 hf-mirror.com 镜像，国内下载速度显著提升
- **HTTP 代理**：支持 `--proxy` 参数或环境变量设置代理
- **多线程分片**：大文件自动启用多线程分片下载（默认 4 线程）
- **断点续传**：下载中断后重新运行相同命令即可续传
- **文件过滤**：支持 `--include` / `--exclude` 按 glob 模式过滤文件
- **进度显示**：实时显示下载进度条、速度和剩余时间

## 安装

### 前置条件

- Python 3.8+
- pip

### 从源码安装

```bash
git clone <repo-url> hf-dl
cd hf-dl
pip install -e .
```

### 依赖说明

| 依赖 | 最低版本 | 用途 |
|------|---------|------|
| huggingface_hub | >=0.20.0 | HuggingFace API 调用、小文件下载 |
| requests | >=2.28.0 | 多线程分片下载的 HTTP 请求 |
| rich | >=13.0.0 | 终端进度条和彩色输出 |

开发依赖：

| 依赖 | 最低版本 | 用途 |
|------|---------|------|
| pytest | >=7.0.0 | 单元测试框架 |

安装开发依赖：

```bash
pip install -e ".[dev]"
```

## 快速开始

```bash
# 下载整个模型仓库
hf-dl download gpt2

# 下载到指定目录
hf-dl download gpt2 --local-dir /data/models/gpt2

# 仅下载指定文件
hf-dl download gpt2 --include config.json,tokenizer.json

# 排除大文件
hf-dl download gpt2 --exclude "*.safetensors"

# 使用 HTTP 代理
hf-dl download gpt2 --proxy http://127.0.0.1:7890

# 8 线程下载大模型
hf-dl download meta-llama/Llama-2-7b-hf --threads 8

# 切换到官方源（不走镜像）
hf-dl download gpt2 --no-mirror

# 使用认证 token（私有模型）
hf-dl download meta-llama/Llama-2-7b-hf --token hf_xxxxx
```

## 命令参考

```
hf-dl download <repo_id> [选项]

位置参数:
  repo_id               仓库ID，如 gpt2 或 org/model-name

选项:
  --local-dir PATH      本地保存路径（默认: ./<repo_name>）
  --include PATTERNS    仅下载指定文件（逗号分隔，支持 glob 模式）
  --exclude PATTERNS    排除指定文件（逗号分隔，支持 glob 模式）
  --no-mirror           不使用镜像，直连 HuggingFace 官方源
  --proxy URL           HTTP 代理地址，如 http://127.0.0.1:7890
  --threads N           多线程数（默认: 4，设为 0 禁用分片下载）
  --chunk-threshold SIZE 分片下载阈值（默认: 100M，超过此大小启用分片）
  --token TOKEN         HuggingFace 认证 token
  --no-resume           禁用断点续传
  --version             显示版本号
  -h, --help            显示帮助信息
```

### 环境变量

| 变量 | 说明 | 优先级 |
|------|------|--------|
| `HTTPS_PROXY` / `HTTP_PROXY` | HTTP 代理地址 | 低于 `--proxy` 参数 |
| `HF_TOKEN` / `HUGGING_FACE_HUB_TOKEN` | HuggingFace 认证 token | 低于 `--token` 参数 |

## 架构设计

### 模块结构

```
hf_dl/
 ├── __init__.py    # 包初始化，版本号
 ├── cli.py         # CLI 入口，参数解析与主流程调度
 ├── config.py      # 镜像源、代理、endpoint 配置管理
 ├── downloader.py  # 下载引擎（单文件 + 多线程分片 + 断点续传）
 └── utils.py       # 工具函数（文件大小解析、glob 匹配）
```

### 核心流程

```
用户执行 hf-dl download <repo_id>
         │
         ▼
    cli.py: 解析参数 → 构建 DownloadConfig
         │
         ▼
  config.py: 确定镜像源 endpoint、代理、token
         │
         ▼
  downloader.py: download_repo()
         │
         ├─ HfApi.list_repo_tree() 获取文件列表
         ├─ --include/--exclude 过滤
         │
         ▼
    遍历文件列表，按大小分流：
         │
         ├── 文件 ≤ 阈值 ──→ download_file_single()
         │                    └─ huggingface_hub.hf_hub_download()
         │                       (自带断点续传 + endpoint 替换)
         │
         └── 文件 > 阈值 ──→ download_file_multithread()
                              ├─ HEAD 获取文件大小
                              ├─ split_ranges() 分片
                              ├─ ThreadPoolExecutor 并行下载
                              │   └─ download_chunk() × N
                              │       └─ GET Range 请求 + 重试
                              ├─ .progress 文件记录已完成分片
                              └─ 全部完成 → 删除 .progress
```

### 镜像与代理策略

```
                    hf-mirror.com（默认）
    镜像源 ─────────────────────────────────
                    huggingface.co（--no-mirror）

    代理 ──── --proxy 参数 > HTTPS_PROXY > HTTP_PROXY

    组合关系：
    ┌──────────┬──────────┬────────────────────────────┐
    │ 镜像源   │ 代理     │ 效果                        │
    ├──────────┼──────────┼────────────────────────────┤
    │ hf-mirror│ 无       │ 国内直连镜像，无需代理      │
    │ hf-mirror│ HTTP代理 │ 镜像+代理双重加速           │
    │ 官方源   │ HTTP代理 │ 通过代理访问官方源          │
    │ 官方源   │ 无       │ 直连官方源（国内可能较慢）  │
    └──────────┴──────────┴────────────────────────────┘
```

### 断点续传机制

**小文件**（huggingface_hub 内置）：
- 下载中标记 `.incomplete` 文件
- 重试时通过 `Range` 请求头续传

**大文件**（自研分片）：
- 每个 `.progress` 文件记录已完成分片索引列表
- 续传时跳过已完成分片，仅下载 pending 分片
- 全部完成后自动删除 `.progress` 文件
- Ctrl+C 中断后重新运行相同命令即可续传

## 运行测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 运行单个模块测试
python -m pytest tests/test_utils.py -v
python -m pytest tests/test_config.py -v
python -m pytest tests/test_downloader.py -v
```

## 常见问题

### 下载速度慢？

1. 确认使用了镜像源（默认已启用，输出中应显示 `镜像源: https://hf-mirror.com`）
2. 增加线程数：`--threads 8`
3. 降低分片阈值让更多文件走多线程：`--chunk-threshold 50M`
4. 如果镜像源也不快，尝试叠加代理：`--proxy http://127.0.0.1:7890`

### 下载中断了怎么办？

重新运行相同命令即可自动续传。大文件会通过 `.progress` 文件跳过已完成分片，小文件由 `huggingface_hub` 内置续传机制处理。

### 如何下载私有模型？

```bash
hf-dl download org/private-model --token hf_xxxxx
```

或将 token 写入环境变量：

```bash
export HF_TOKEN=hf_xxxxx
hf-dl download org/private-model
```

### 如何不使用镜像？

```bash
hf-dl download gpt2 --no-mirror
```

## 致谢

- [hf-mirror.com](https://hf-mirror.com) - 提供国内公益镜像服务
- [huggingface_hub](https://github.com/huggingface/huggingface_hub) - HuggingFace 官方 Python 库

## 许可证

MIT License

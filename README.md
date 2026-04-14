# hf-dl: HuggingFace 模型下载工具

HuggingFace 模型下载工具，支持国内镜像加速、HTTP 代理、断点续传和自动回退。

## 功能特性

- **国内镜像加速**：`--mirror` 启用 hf-mirror.com 镜像
- **自定义镜像源**：`--mirror https://your-mirror.com` 指定自定义镜像地址
- **自动回退**：镜像下载失败自动尝试官方源
- **HTTP 代理**：支持 `--proxy` 参数或环境变量设置代理
- **断点续传**：下载中断后重新运行相同命令即可续传
- **文件过滤**：支持 `--include` / `--exclude` 按 glob 模式过滤文件
- **进度显示**：实时显示当前下载文件、速度和剩余时间

## 安装

### 前置条件

- Python 3.8+
- pip

### 从源码安装

```bash
git clone https://github.com/qingshui/hf-dl.git
cd hf-dl
pip install -e .
```

### 依赖说明

| 依赖 | 最低版本 | 用途 |
|------|---------|------|
| huggingface_hub | >=0.20.0 | HuggingFace API 调用 |
| requests | >=2.28.0 | HTTP 下载 |
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
# 下载整个模型仓库（默认直连官方源）
hf-dl download gpt2

# 使用国内镜像加速（默认 hf-mirror.com）
hf-dl download gpt2 --mirror

# 使用自定义镜像源
hf-dl download gpt2 --mirror https://my-mirror.com

# 下载到指定目录
hf-dl download gpt2 --local-dir /data/models/gpt2

# 仅下载指定文件
hf-dl download gpt2 --include config.json,tokenizer.json

# 排除大文件
hf-dl download gpt2 --exclude "*.safetensors"

# 使用 HTTP 代理
hf-dl download gpt2 --proxy http://127.0.0.1:7890

# 使用认证 token（私有模型）
hf-dl download meta-llama/Llama-2-7b-hf --token hf_xxxxx

# 镜像 + 代理组合
hf-dl download meta-llama/Llama-2-7b-hf --mirror --proxy http://127.0.0.1:7890
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
  --mirror [URL]        使用镜像源加速，不加值默认 hf-mirror.com，可指定自定义地址
  --proxy URL           HTTP 代理地址，如 http://127.0.0.1:7890
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
 ├── downloader.py  # 下载引擎（流式下载 + 断点续传 + 自动回退）
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
  config.py: 确定 endpoint（官方源/镜像源）、代理、token
         │
         ▼
  downloader.py: download_repo()
         │
         ├─ HfApi.list_repo_tree() 获取文件列表
         ├─ --include/--exclude 过滤
         │
         ▼
    遍历文件列表，逐个下载：
         │
         ├── 已存在且完整 → 跳过
         │
         └── 未下载/不完整 → download_file()
              │
              ├─ 检查本地已下载字节数（断点续传）
              ├─ GET 请求 + Range 头续传
              ├─ 流式写入 + 进度条更新
              ├─ 失败重试（5 次，间隔 3s）
              └─ 镜像失败 → 自动回退官方源
```

### 下载源策略

```
    下载源 ─── huggingface.co（默认）
            ├── hf-mirror.com（--mirror）
            └── 自定义地址（--mirror https://your-mirror.com）

    自动回退：
    ┌────────────────────────┬────────────────────────────┐
    │ 场景                    │ 行为                        │
    ├────────────────────────┼────────────────────────────┤
    │ 官方源下载成功          │ 正常完成                    │
    │ 镜像源下载成功          │ 正常完成                    │
    │ 镜像源失败              │ 自动回退官方源重试          │
    │ 镜像+官方均失败         │ 报错，继续下一个文件        │
    └────────────────────────┴────────────────────────────┘
```

### 断点续传机制

- 每个文件下载时检查本地已有部分的大小
- 通过 `Range: bytes=<已下载大小>-` 请求剩余部分
- 服务器返回 206 (Partial Content) 时追加写入
- 中断后重新运行相同命令即可续传
- 每个文件独立重试 5 次，间隔 3 秒

## 运行测试

```bash
# 运行全部测试
python -m pytest tests/ -v

# 运行单个模块测试
python -m pytest tests/test_config.py -v
python -m pytest tests/test_downloader.py -v
```

## 常见问题

### 下载速度慢？

1. 使用国内镜像加速：`--mirror`
2. 叠加代理：`--proxy http://127.0.0.1:7890`
3. 排除不需要的大文件：`--exclude "*.safetensors"`

### 下载中断了怎么办？

重新运行相同命令即可自动续传。已下载的部分不会重复下载。

### SSL 报错怎么办？

hf-mirror.com 对大文件可能重定向到 CDN，CDN 连接不稳定时会自动重试 5 次。如果仍失败，会自动回退到官方源下载。

### 如何下载私有模型？

```bash
hf-dl download org/private-model --token hf_xxxxx
```

或将 token 写入环境变量：

```bash
export HF_TOKEN=hf_xxxxx
hf-dl download org/private-model
```

## 致谢

- [hf-mirror.com](https://hf-mirror.com) - 提供国内公益镜像服务
- [huggingface_hub](https://github.com/huggingface/huggingface_hub) - HuggingFace 官方 Python 库

## 许可证

MIT License

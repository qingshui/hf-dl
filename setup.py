from setuptools import setup, find_packages

setup(
    name="hf-dl",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "huggingface_hub",
        "requests",
        "rich",
    ],
    extras_require={
        "dev": [
            "pytest",
        ],
    },
    entry_points={
        "console_scripts": [
            "hf-dl=hf_dl.cli:main",
        ],
    },
    python_requires=">=3.8",
    description="HuggingFace 国内下载加速器 - 通过 hf-mirror.com 镜像加速",
)

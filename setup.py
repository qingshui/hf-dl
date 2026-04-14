from setuptools import setup, find_packages

setup(
    name="hf-dl",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "huggingface_hub>=0.20.0",
        "requests>=2.28.0",
        "rich>=13.0.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "hf-dl=hf_dl.cli:main",
        ],
    },
    python_requires=">=3.8",
    description="HuggingFace 国内下载加速器 - 通过 hf-mirror.com 镜像加速",
    long_description=open("README.md", encoding="utf-8").read(),
    long_description_content_type="text/markdown",
    url="https://github.com/humingqing/hf-dl",
    author="humingqing",
    license="MIT",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: Scientific/Engineering :: Artificial Intelligence",
    ],
)

#!/bin/bash
# 这是一个在 Linux 容器内部运行的脚本

echo "--- 开始安装项目环境 ---"

# 1. 升级 pip
pip install --upgrade pip

# 2. 核心逻辑：自动寻找安装入口
if [ -f "setup.py" ]; then
    echo "检测到 setup.py，正在安装..."
    pip install -e .
elif [ -f "requirements.txt" ]; then
    echo "检测到 requirements.txt，正在安装..."
    pip install -r requirements.txt
elif [ -f "pyproject.toml" ]; then
    echo "检测到 pyproject.toml，正在安装..."
    pip install .
else
    echo "警告：未发现标准的安装文件，尝试直接安装当前目录"
    pip install -e .
fi

echo "--- 环境安装完成 ---"
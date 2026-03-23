#!/bin/bash
# 智能环境感知脚本 - 适用于 R2E 自动化构建

echo "--- [R2E] 正在初始化项目环境 ---"

# 1. 动态确定环境名称 (基于当前目录名)
ENV_NAME=$(basename $(pwd))

# 2. 检查是否有 Conda（Base 镜像应预装 Miniconda）
if command -v conda &> /dev/null; then
    echo "检测到 Conda，正在创建隔离环境: $ENV_NAME"
    
    # 尝试从 pyproject.toml 或 setup.py 提取 python 版本要求 (可选增强)
    # 这里我们默认使用 3.9，或者由外部环境变量传入
    PYTHON_VERSION=${PYTHON_VERSION:-"3.9"}
    
    conda create -y -n "$ENV_NAME" python="$PYTHON_VERSION"
    source activate "$ENV_NAME"
else
    echo "未检测到 Conda，使用系统 Pip (不建议在生产环境大规模运行)"
fi

# 3. 升级基础工具
pip install --upgrade pip setuptools wheel

# 4. 智能安装逻辑 (优先级排序)
if [ -f "pyproject.toml" ]; then
    echo "--- 发现 pyproject.toml，优先使用 PEP 517 安装 ---"
    # 如果有 poetry.lock 或 pdm.lock，可以考虑对应的工具
    pip install .
elif [ -f "setup.py" ]; then
    echo "--- 发现 setup.py，执行可编辑安装 ---"
    pip install -e .
elif [ -f "requirements.txt" ]; then
    echo "--- 发现 requirements.txt，执行批量安装 ---"
    pip install -r requirements.txt
fi

# 5. [R2E 关键] 自动安装测试框架
# 如果代码里有大量 pytest 标记，但没装 pytest，Agent 会无法运行测试
if grep -q "pytest" **/*.py 2>/dev/null; then
    echo "检测到 pytest 迹象，确保安装测试运行器..."
    pip install pytest pytest-cov
fi

echo "--- 环境配置完成 ---"
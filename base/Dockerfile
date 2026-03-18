# Dockerfile.template
FROM python:3.9-slim-bookworm

# 1. 安装系统级依赖 (编译 C 扩展、Git、基础工具)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    build-essential \
    libffi-dev \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# 2. 设置工作目录 (SWE-bench 规范通常叫 /testbed)
WORKDIR /testbed

# 3. 预置一个脚本，用来自动化安装项目依赖
COPY setup_env.sh /usr/local/bin/setup_env.sh
RUN chmod +x /usr/local/bin/setup_env.sh

CMD ["/bin/bash"]
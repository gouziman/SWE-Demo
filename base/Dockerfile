# 使用 Debian Bookworm 作为稳定底座
FROM debian:bookworm-slim

# 1. 安装系统级基础依赖 (包含 Git 和编译工具)
RUN apt-get update && apt-get install -y \
    git \
    curl \
    wget \
    build-essential \
    libffi-dev \
    libssl-dev \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# 2. 安装 Miniconda (R2E 灵活切换 Python 版本的核心)
ENV CONDA_DIR /opt/conda
RUN wget --quiet https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh -O ~/miniconda.sh && \
    /bin/bash ~/miniconda.sh -b -p $CONDA_DIR && \
    rm ~/miniconda.sh
ENV PATH=$CONDA_DIR/bin:$PATH

# 3. 设置工作目录
WORKDIR /testbed

# 4. 预置智能安装脚本 (即我们刚才讨论的 smart_setup_env.sh)
COPY setup_env.sh /usr/local/bin/setup_env.sh
RUN chmod +x /usr/local/bin/setup_env.sh

# 5. [关键] 将代码复制进镜像并执行安装
# 注意：在 R2E 自动化流程中，代码会在构建镜像前由 Python 脚本准备好
COPY . /testbed
RUN /bin/bash /usr/local/bin/setup_env.sh

# 确保容器启动时默认进入 bash 并能识别 conda
SHELL ["/bin/bash", "--login", "-c"]
CMD ["/bin/bash"]
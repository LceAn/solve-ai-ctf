# ctfbox-base —— CTF Workbench 沙箱基础镜像
# 改编自 CTF-BTFly images/base/Dockerfile（MIT License, huihuilikaile/CTF-BTFly）
# 差异：不内置 Pi Agent/Node（本平台的求解器为任意命令模板），精简为通用解题底座。
FROM python:3.11-slim

ARG DEBIAN_FRONTEND=noninteractive
ARG APT_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian
ARG APT_SECURITY_MIRROR=https://mirrors.tuna.tsinghua.edu.cn/debian-security
ARG PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple

RUN sed -i \
        -e "s|http://deb.debian.org/debian|${APT_MIRROR}|g" \
        -e "s|http://deb.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
        -e "s|http://security.debian.org/debian-security|${APT_SECURITY_MIRROR}|g" \
        /etc/apt/sources.list.d/debian.sources \
    && apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        bash \
        ca-certificates \
        curl \
        file \
        findutils \
        git \
        jq \
        less \
        netcat-openbsd \
        procps \
        ripgrep \
        tini \
        unzip \
        wget \
        xz-utils \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -i ${PIP_MIRROR} --upgrade pip \
    && groupadd --gid 1000 ctf \
    && useradd --uid 1000 --gid ctf --create-home --shell /bin/bash ctf \
    && mkdir -p /workspace \
    && chown -R ctf:ctf /workspace /home/ctf

# workbench 目录由运行时只读挂载到 /solver（{solver_dir} 占位符在沙箱模式下指向这里）
ENV HOME=/home/ctf \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_INDEX_URL=${PIP_MIRROR}

USER ctf
WORKDIR /workspace
ENTRYPOINT ["/usr/bin/tini", "--"]

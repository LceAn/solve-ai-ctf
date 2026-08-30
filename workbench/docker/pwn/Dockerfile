# ctfbox-pwn —— 二进制利用工具层（包清单沿用 CTF-BTFly images/pwn，MIT）
# 运行时需 SYS_PTRACE（server 对 pwn 类目自动 --cap-add SYS_PTRACE）
FROM ctfbox-base:0.1.0
USER root
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        binutils \
        build-essential \
        checksec \
        gdb \
        gdbserver \
        patchelf \
        qemu-user \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        pwntools==4.14.1 \
        ropper==1.13.13
USER ctf

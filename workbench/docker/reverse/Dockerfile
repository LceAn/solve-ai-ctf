# ctfbox-reverse —— 逆向工具层（包清单沿用 CTF-BTFly images/reverse，MIT）
FROM ctfbox-base:0.1.0
USER root
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        apktool \
        binutils \
        default-jre-headless \
        gdb \
        ltrace \
        strace \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        angr==9.2.170
USER ctf

# ctfbox-misc —— misc/密码/取证通用工具层（薄增量，参考 BTFly 题型分层）
FROM ctfbox-base:0.1.0

USER root
ARG PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        binwalk \
        exiftool \
        p7zip-full \
        xxd \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir -i ${PIP_MIRROR} \
        pycryptodome==3.20.0 \
        gmpy2==2.1.5 \
        sympy==1.13.3 \
        z3-solver==4.13.4.0 \
        requests==2.32.3 \
        beautifulsoup4==4.12.3 \
        pillow==10.4.0 \
        numpy==2.0.2
USER ctf

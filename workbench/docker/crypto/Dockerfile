# ctfbox-crypto —— 密码攻击工具层（包清单沿用 CTF-BTFly images/crypto，MIT）
FROM ctfbox-base:0.1.0
USER root
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        john \
        libgmp-dev \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        gmpy2==2.2.1 \
        pycryptodome==3.23.0 \
        sympy==1.14.0 \
        z3-solver==4.15.1.0
USER ctf

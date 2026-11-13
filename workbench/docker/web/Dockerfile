# ctfbox-web —— Web 环境（SQL注入/目录爆破/反序列化/JWT/本地起服务复现）
FROM ctfbox-base:0.1.0

USER root
RUN apt-get -o Acquire::Retries=5 update     && apt-get -o Acquire::Retries=5 install -y --no-install-recommends         dirb         dnsutils         gobuster         nmap         sqlmap         whatweb         php-cli         php-curl         nginx     && rm -rf /var/lib/apt/lists/*     && pip install --no-cache-dir         beautifulsoup4==4.13.4         httpx==0.28.1         pyjwt==2.10.1         requests==2.32.4         flask         lxml         cryptography         python-arango         requests-toolbelt         websockets

# 本地复现服务：mysql/redis 客户端 + 常用 CMS 工具
RUN apt-get -o Acquire::Retries=5 update     && apt-get -o Acquire::Retries=5 install -y --no-install-recommends         default-mysql-client         redis-tools     && rm -rf /var/lib/apt/lists/*

# --- web 环境欢迎信息 ---
RUN echo 'echo "═══ Web 环境 ═══"' >> /home/ctf/.bashrc &&     echo 'echo "  sqlmap / gobuster / nmap — 注入与枚举"' >> /home/ctf/.bashrc &&     echo 'echo "  flask / httpx — 本地起服务复现"' >> /home/ctf/.bashrc

USER ctf
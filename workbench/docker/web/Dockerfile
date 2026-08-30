# ctfbox-web —— Web 工具层（包清单沿用 CTF-BTFly images/web，MIT）
FROM ctfbox-base:0.1.0
USER root
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        dirb \
        dnsutils \
        gobuster \
        nmap \
        sqlmap \
        whatweb \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        beautifulsoup4==4.13.4 \
        httpx==0.28.1 \
        pyjwt==2.10.1 \
        requests==2.32.4
USER ctf

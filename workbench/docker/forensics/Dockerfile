# ctfbox-forensics —— 取证工具层（包清单沿用 CTF-BTFly images/forensics，MIT）
FROM ctfbox-base:0.1.0
USER root
RUN apt-get -o Acquire::Retries=5 update \
    && apt-get -o Acquire::Retries=5 install -y --no-install-recommends \
        binwalk \
        foremost \
        libimage-exiftool-perl \
        p7zip-full \
        sleuthkit \
        tshark \
        yara \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir \
        oletools==0.60.2 \
        scapy==2.6.1 \
        volatility3==2.26.2
USER ctf

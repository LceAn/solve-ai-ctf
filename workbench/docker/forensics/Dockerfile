# ctfbox-forensics —— 取证环境（内存/磁盘/流量/隐写 全覆盖）
FROM ctfbox-base:0.1.0

USER root
RUN apt-get -o Acquire::Retries=5 update     && apt-get -o Acquire::Retries=5 install -y --no-install-recommends         binwalk         foremost         libimage-exiftool-perl         p7zip-full         sleuthkit         tshark         yara         steghide         outguess         zlib1g-dev     && rm -rf /var/lib/apt/lists/*     && pip install --no-cache-dir         oletools==0.60.2         scapy==2.6.1         volatility3==2.26.2         pillow         numpy

# stegano / zsteg（PNG/LSB 隐写）— zsteg 是 ruby 工具，改用 python 替代
RUN pip install --no-cache-dir stego-lsb 2>/dev/null;     pip install --no-cache-dir stegano

# vol2 内存取证的 python2 依赖跳过（volatility3 覆盖绝大多数场景）
# pdf 取证
RUN pip install --no-cache-dir pikepdf 2>/dev/null;     pip install --no-cache-dir pdfminer.six 2>/dev/null || true

USER ctf
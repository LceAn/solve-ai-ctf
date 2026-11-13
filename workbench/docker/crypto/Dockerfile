# ctfbox-crypto —— 密码学环境（古典→现代→数论全覆盖）
# 工具矩阵：John+hashcat 破解 / RsaCtfTool 自动 RSA / PARI-GP 数论 / factordb 在线查
FROM ctfbox-base:0.1.0

USER root
RUN apt-get -o Acquire::Retries=5 update     && apt-get -o Acquire::Retries=5 install -y --no-install-recommends         john         hashcat         libgmp-dev         libssl-dev         openssl         pari-gp     && rm -rf /var/lib/apt/lists/*     && pip install --no-cache-dir         pycryptodome==3.23.0         gmpy2==2.2.1         sympy==1.14.0         z3-solver==4.15.1.0         libnum         factordb-pycli         pyOpenSSL         tinyec         pyDes

# RsaCtfTool（RSA 自动攻击全家桶：wiener/hastad/coppersmith 常见攻击一键）
RUN git clone --depth 1 https://github.com/RsaCtfTool/RsaCtfTool.git /opt/RsaCtfTool     && pip install --no-cache-dir -r /opt/RsaCtfTool/requirements.txt     && ln -s /opt/RsaCtfTool/RsaCtfTool.py /usr/local/bin/rsactftool

USER ctf
# ctfbox-reverse —— 逆向环境（angr 符号执行 / 反编译 / Java/APK）
FROM ctfbox-base:0.1.0

USER root
RUN apt-get -o Acquire::Retries=5 update     && apt-get -o Acquire::Retries=5 install -y --no-install-recommends         apktool         binutils         default-jre-headless         gdb         ltrace         strace         wget     && rm -rf /var/lib/apt/lists/*     && wget -qO /tmp/r2.deb "https://github.com/radareorg/radare2/releases/download/5.9.4/radare2_5.9.4_amd64.deb"     && apt-get install -y /tmp/r2.deb     && rm -f /tmp/r2.deb     && pip install --no-cache-dir angr==9.2.170     && pip install --no-cache-dir "pycparser==2.21" "cffi==1.16.0"     && pip install --no-cache-dir -i https://pypi.org/simple "bitstring==3.1.9"

USER ctf

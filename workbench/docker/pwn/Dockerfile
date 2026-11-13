# ctfbox-pwn —— 二进制利用环境（pwntools 调试 / glibc 精准 / ROP/堆利用）
FROM ctfbox-base:0.1.0

USER root
RUN apt-get -o Acquire::Retries=5 update     && apt-get -o Acquire::Retries=5 install -y --no-install-recommends         binutils         build-essential         checksec         gdb         gdbserver         patchelf         qemu-user         socat         lib32z1         lib32ncurses6     && rm -rf /var/lib/apt/lists/*     && pip install --no-cache-dir         pwntools==4.14.1         ropper==1.13.13        ROPgadget         libc-database ;     pip install --no-cache-dir         pwntools==4.14.1         ropper

# gdb 工具：pwndbg（堆/ROP 调试必备）
RUN git clone --depth 1 https://github.com/pwndbg/pwndbg.git /opt/pwndbg     && cd /opt/pwndbg && ./setup.sh >/dev/null 2>&1 || true     && echo "source /opt/pwndbg/gdbinit.py" >> /home/ctf/.gdbinit

# OneGadget（glibc one_gadget 搜索，需 ruby）
RUN apt-get -o Acquire::Retries=5 update     && apt-get -o Acquire::Retries=5 install -y --no-install-recommends ruby-full     && gem install one_gadget seccomp-tools 2>/dev/null || true

USER ctf
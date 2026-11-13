# ctfbox-misc —— 杂项/取证通用环境（图片/音频/压缩/编码）
FROM ctfbox-base:0.1.0

USER root
RUN apt-get -o Acquire::Retries=5 update     && apt-get -o Acquire::Retries=5 install -y --no-install-recommends         binwalk         exiftool         p7zip-full         xxd         imagemagick         ffmpeg         sox         libzbar0     && rm -rf /var/lib/apt/lists/*     && pip install --no-cache-dir         pillow         numpy         pyzbar ;     pip install --no-cache-dir         stegano         pytesseract
USER ctf
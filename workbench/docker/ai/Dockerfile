# ctfbox-ai —— LLM/AI 安全题型层（提示注入、agent 攻防、模型输出不可信下的验证）
FROM ctfbox-base:0.1.0
USER root
ARG PIP_MIRROR=https://pypi.tuna.tsinghua.edu.cn/simple
RUN pip install --no-cache-dir -i ${PIP_MIRROR} \
        openai==3.8.0 \
        anthropic==1.4.0 \
        tiktoken==0.14.0 \
        jsonlines==4.0.0
USER ctf

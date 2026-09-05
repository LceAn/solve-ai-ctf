# 比赛环境 Docker 设计：四层镜像矩阵 + 声明式 env spec

> 目标：让**每场比赛、每道题**都能拥有与自己匹配的容器环境——pwn 题锁定精确 glibc，
> web 题一键拉起 LNMP 本地复现，比赛私有工具只建一次全场复用。
>
> 设计蓝本：
> - 安恒内部分享《如何制作一个渗透沙箱》（2026-09，"底座提供能力，规则界定边界"）
> - 本仓库现有沙箱（workbench/docker/，参考 CTF-BTFly 分层模型）

---

## 0. 现状与空缺

| 现有 | 位置 | 结论 |
|---|---|---|
| 7 个静态题型镜像 | workbench/docker/{base,misc,crypto,pwn,web,reverse,forensics}/ | 能力已分层，但**只读不改** |
| 按类别选镜像 | workbench/server.py:1127 `SANDBOX_DEFAULTS.images` | 题目只能"选"，不能"定义" |
| 运行时安全模型 | workbench/server.py:1422-1473（cap-drop ALL / 断网默认 / 三限 / 看门狗） | 保留，是本设计的监管底座 |
| 比赛目录结构 | scripts/competition.py:86 `cmd_init` | 有 `cases/`、`artifacts/`，**没有 env/** |

空缺一句话：**镜像层是"题型粒度"，而比赛需要"题目粒度"。**

---

## 1. 从渗透沙箱 PDF 继承的三条原则

1. **底座提供能力，规则界定边界** —— 镜像只管"能做什么"，红线与监管放在镜像外（宿主侧 server）。
   PDF 的原话是"约束 skill 上下文一长就乱来了"，所以安全边界**永远**在宿主：
   cap-drop、断网默认、看门狗、一次性网关令牌、提交白名单一个都不放松，env 机制只增能力不加豁免。
2. **能力层/约束层分离** —— PDF 用 `Dockerfile + CLAUDE.md + skills/`；本仓库对应
   `docker/* + env/solver/CLAUDE.md + references/playbooks-*.md`（转制成 skill 包）。
3. **供应链自持** —— 锁 digest、国内镜像源走 build-arg（不破缓存）、预置二进制带 sha256 校验
   （PDF 的 `tools/ + 校验文件` 与 `@sha256:` 锁定同款做法）。

PDF 的 skill/MCP 界定四问，映射到本仓库正好是现成的分工：

| 判定 | 落点 |
|---|---|
| 要连外部系统、有副作用、要审计（提交 flag） | server 端 `scripts/submitter.py` 白名单接口（"MCP 类"） |
| 输入输出固定、可复用（分诊/flag 扫描/哈希） | 确定性脚本（已有） |
| 需要模型临场推理（解题方法论、给方向不给细节） | skill 包（playbooks 转制，烤入/挂载进容器） |

---

## 2. 四层镜像矩阵（能力层）

```
L0  ctfbox-base            通用底座（已有）：python-slim + CLI + tini + ctf 用户
                           + 烤入约束层文件（CLAUDE.md / AGENTS.md）
L1  ctfbox-<category>      七题型层（已有）：pwn / web / crypto / reverse / forensics / misc / ai
L2  ctf-<comp>             比赛层（可选）：该比赛统一的东西——语言版本、私有工具、
                           团队脚本、镜像源偏好。建一次，全场题目复用。
L3  ctf-<comp>-<slug>      题目层（按需）：精确 glibc/库版本、题目依赖、
                           预置文件、本地复现服务栈。
```

```
ctfbox-base:0.1.0 ─┬─ ctfbox-pwn:0.1.0 ──── ctf-hkbis-pwn-easyheap:20260905-a1b2
                   ├─ ctfbox-web:0.1.0 ─┬── ctf-hkbis-web-blog:20260905-a1b2
                   │                    └── ctf-hkbis:20260905   (L2 比赛层)
                   └─ ...
```

规则：

- **FROM 只能向"更低的本地层"**：L3 FROM L2（没有 L2 时 FROM L1），L1 FROM L0。禁止题目层直接 FROM 公网镜像做底座（服务容器 `services.image` 除外，见 §4）。
- **tag 规范**：`ctf-<comp>[-<slug>]:<YYYYMMDD>-<spec哈希前8位>`，comp/slug 归一化为 `[a-z0-9-]`。可再打 `latest` 便于本地调试（PDF 第四/五步的同款 tag 策略）。
- **懒构建 + 预热**：开赛时（fetch_challs 抓完题）批量预热 L1；L3 只在"该题确实要本地环境"时构建，派发求解时镜像缺失 → 按优先级回落（§5），UI 提示一键构建。
- **缓存友好**：包清单层在前、`build.pre` 自由脚本层在后；apt/pip/npm 全部走 BuildKit
  `--mount=type=cache`（PDF 同款），镜像源用 build-arg 注入不破缓存。

---

## 3. 声明式 env spec（YAML 是构建期格式，JSON 是运行期格式）

每场比赛一个目录，挂在 `competition.py init` 建的比赛目录下：

```
比赛/xxx/
  competition.json          # 已有，唯一真源
  cases/<slug>/case.json    # 已有
  artifacts/                # 已有，附件原件
  env/                      # ★ 新增
    comp.yaml               # 比赛级：默认 base、镜像源、公共工具、约束层
    challenges/<slug>.yaml  # 题目级：覆盖与新增（按题一文件）
    assets/<slug>/...       # 构建上下文：libc、源码包、预置文件（配 sha256 清单）
    solver/CLAUDE.md        # 比赛级约束层（可选，缺省用 L0 烤入的）
    solver/skills/          # 比赛级 skill 包（可选）
    gen/                    # ★ 构建产物（勿手改，进 .gitignore）
      .built.json           # slug → {image, digest, built_at, base}（server 只读这个 JSON）
      <slug>/Dockerfile     # 由 spec 渲染
      <slug>/compose.yaml   # 由 services 渲染（有服务编排的题才有）
```

**分层读取顺序**：题目 spec 逐字段覆盖比赛 spec，比赛 spec 提供默认值。构建器把
YAML 渲染成 Dockerfile/compose 后构建；**运行时组件（server.py）只读 `gen/.built.json`
（纯 JSON），不碰 YAML**——运行时保持零 pip 依赖，PyYAML 只在构建机上需要。

### spec 字段表

| 字段 | 说明 | 渲染产物 |
|---|---|---|
| `api` | 固定 `ctfbox/v1` | 版本校验 |
| `slug` / `category` | 题目标识与题型（决定默认 base 与 cap 预置） | 镜像 tag |
| `base` | 显式 FROM（L1/L2 tag）；缺省 = L2 → L1 | `FROM` |
| `build.apt` / `build.pip` / `build.npm` | 包清单（可带版本） | RUN 层（cache mount） |
| `build.pre` / `build.post` | 自由 shell（PDF 的 RUN heredoc 同款） | `RUN <<EOF` |
| `assets[]` | 构建上下文文件：`src`（必须在 `env/assets/` 下）+ `sha256` + `dst` | 校验后 `COPY --chmod` |
| `files[]` | 运行时预置：挂载进 `/workspace`（只读），改文件不重建镜像 | `docker run -v` |
| `run.network` | `none`（默认）/ `bridge` / `services` | `--network` |
| `run.caps[]` | 在 cap-drop ALL 之上白名单加回（如 `SYS_PTRACE`） | `--cap-add` |
| `run.resources` | 覆盖 memory/cpus/pids（只能调低不能调高） | 三限参数 |
| `services{}` | 多容器题目编排（web 本地复现等） | `gen/<slug>/compose.yaml` |
| `constraints` | `claudemd` / `skills`：比赛级约束覆盖 | 运行时挂载（免重建） |

### 示例一：pwn 题（锁 glibc 2.35）

见 [envs/challenge.pwn-glibc235.example.yaml](envs/challenge.pwn-glibc235.example.yaml)。
要点：assets 带 sha256；libc 预置到 `/opt/libc/2.35/`（配合 Debian 机上 glibc-aio 的既有习惯）；
`run.caps: [SYS_PTRACE]` 显式声明（server 对 pwn 类目已有的自动加回逻辑保留为缺省）。

### 示例二：web 题（LNMP 本地复现）

见 [envs/challenge.web-lamp.example.yaml](envs/challenge.web-lamp.example.yaml)。
要点：`services` 起 php/apache + mysql；**service 容器里的 FLAG 一律占位值**
（`flag{placeholder-do-not-submit}`）——真 flag 只能来自平台实例，防 fixture flag 污染
provenance（SKILL.md 红线第 7/8 条）；端口只绑 `127.0.0.1`。

---

## 4. 运行编排：单容器走老路，多服务走 compose

- **单容器题**（绝大多数）：现有 `docker run` 路径（server.py:1459）一行不改，只换镜像 tag。
- **多服务题**：builder 渲染 `gen/<slug>/compose.yaml`（默认 `internal: true` 的独立网络），
  runner 用 `docker compose -p ctf-<comp>-<slug>` 拉起；solver 容器以
  `--network <project>_default` 加入；任务结束看门狗（server.py:722）在 `docker stop` 之后追加
  `docker compose down -v`。服务生命周期与求解任务同生共死，不留孤儿容器。

```
┌─ compose project: ctf-hkbis-web-blog ────────────────┐
│  web(php:8.2-apache) ← mysql:8.0   internal network  │
│                        ↑                             │
│  solver(ctf-hkbis-web-blog) ──┘ --network <proj>_def │
│  现有安全参数原样保留：cap-drop ALL/三限/看门狗         │
└──────────────────────────────────────────────────────┘
```

---

## 5. 镜像选择优先级与集成点（落到现有代码）

派发求解时（server.py dispatch，~1422 处的 `image =` 逻辑替换为）：

```
1. case.json env.image        （题目人工指定，最高；缺失 → 硬报错，不静默回落）
2. env/gen/.built.json[slug]  （题目层已构建；缺失 → 硬报错并提示重建）
3. comp.yaml 的 L2 ctf-<comp> （比赛层已构建且题目 spec 无覆盖）
4. SANDBOX_DEFAULTS.images[category]  （现有题型层，现状回落）
5. cfg["image"]               （兜底）
```

集成点清单（✅ = 已落地）：

| # | 位置 | 改动 | 状态 |
|---|---|---|---|
| 1 | scripts/competition.py `cmd_init`（:86） | 创建 `env/` 骨架 + comp.yaml 模板 | ✅ |
| 2 | scripts/competition.py `cmd_add_challenge` | 每题生成 `env/challenges/<slug>.yaml` 骨架（fetch_challs 经 add-challenge 注册时同样生效） | ✅ |
| 3 | workbench/env_builder.py（新增） | `build / status / verify / export / preheat / render` | ✅ |
| 4 | workbench/server.py dispatch | 镜像选择按 §5 优先级，读 `gen/.built.json`；spec 声明的 cap 白名单与资源收紧生效 | ✅ |
| 5 | workbench/server.py 任务生命周期 | 有 compose 的任务在结束/超时/手动停止时 `compose down -v` | ✅ |
| 6 | workbench static 前端 | 「比赛管理 → 🐳 环境」面板：L0/L1/L2 状态、构建/验证按钮、spec 漂移 | ✅ |
| 7 | workbench/test_workbench.py | 双解析器一致性回归 + 渲染/合并/tag/逃逸 + env API（98 项断言） | ✅ |

---

## 6. 约束层：进镜像的全局约束 + 挂载的比赛约束 ✅

- **L0 烤入全局约束**（所有层继承）：`/workspace/CLAUDE.md`（并双写 `AGENTS.md` 兼容 codex
  生态——PDF 里"平台默认 codex 生态"的转换思路）。内容见
  [envs/solver/CLAUDE.md](envs/solver/CLAUDE.md)：工作区约定（attachments 只读区 /
  scratch 工作区 / artifacts·WRITEUP 产出区）、红线（不自动提交 flag——提交只能走 server 的 submitter API；不动平台；工具输出不可信）、
  资源纪律。由 `env_builder.py sync-solver` 同步进 `base/` 构建上下文。
- **skill 包**：`references/playbooks-*.md` 由 `sync-solver` 转制成七个题型 skill 包随 L0 烤入
  （`/workspace/.claude/skills/<category>/SKILL.md`）——遵循 PDF 的
  "skill 给方向和范围规范，不写 xss 怎么发包这类细节"。
- **比赛级约束运行时挂载**（`env/solver/` → ro 挂载），改了不用重建镜像。
- **监管永远在宿主**：env 机制不给任何安全豁免。`run.caps` 是显式白名单且写入任务日志，
  network 默认 none，services 网络默认 internal，提交仍只能走 submitter 白名单接口。
- **flag 卫生强校验**：`services.*.env.FLAG` 只允许 `flag{placeholder-…}` 占位值，
  真值形态直接拒绝构建。

---

## 7. env_builder.py（构建器）子命令设计

纯 Python 标准库 + 可选 PyYAML（仅构建机需要，`pip install pyyaml`；缺它时报清晰错误）。

```
python workbench/env_builder.py build   比赛/xxx [--slug pwn-easyheap] [--all] [--comp-image] [--push REG]
      # 解析 spec（题目覆盖比赛）→ 校验（assets sha256、路径逃逸、字段白名单）
      # → 渲染 Dockerfile/compose → docker build → 登记 gen/.built.json
      # --dry-run 只渲染不构建；无定制内容的骨架 spec 自动跳过（--force 强制）
python workbench/env_builder.py status  比赛/xxx [--json]
      # spec / 镜像 / 漂移（spec 改了镜像没重建）一览表
python workbench/env_builder.py verify  比赛/xxx [--slug ...] [--probe "cmd"]
      # 起容器跑探针矩阵：gdb --version、python -c "import pwn"、锁定的 libc 版本…
      # （PDF 的"第三步：测试运行"固化成命令，实战检验闭环）
python workbench/env_builder.py export  比赛/xxx [--slug ...] --out ENV.tar [--with-spec]
      # docker save 导出比赛环境：归档、复盘、队内分发（赛后重建审计）
python workbench/env_builder.py preheat 比赛/xxx [--categories pwn,web] [--check]
      # 预热 L0/L1（按 env spec 推断题型）
python workbench/env_builder.py render  比赛/xxx --slug ... [--comp]
      # 打印渲染产物（Dockerfile / compose.yaml），调试用
python workbench/env_builder.py sync-solver [--check]
      # 约束层资产同步：CLAUDE.md/AGENTS.md 双写 + playbook → 七类 skill 包，随 L0 烤入
```

docker CLI 发现：PATH 的 `docker`/`docker.exe` 优先；Windows 下回退 `wsl docker`
（文件路径自动翻译为 `/mnt/<盘>/...`）——Docker 只装在 WSL 里的机器全链路可用，
server.py 的沙箱/停容器/compose 全部走同一发现层。

安全规则（builder 自身）：spec **等同代码**——shell 字段就是本机执行的 Dockerfile 内容，
因此 spec 必须进 git 走 diff 审查；`assets[].src` 强制位于 `env/assets/` 内（拒绝 `..` 与
绝对路径）；`docker build` 用 argv 列表拼装不走 shell。

---

## 8. 安全矩阵（全部保留 + 新增风险对策）

| 项 | 策略 | 来源 |
|---|---|---|
| cap-drop ALL + 显式白名单加回 | 保留；`run.caps` 须在 spec 中显式声明并记入任务日志 | 现有 + pwn SYS_PTRACE 惯例 |
| 默认断网 | 保留；`services` 网络默认 internal，solver 仅在 spec 声明时入网 | 现有 |
| 三限 + 超时看门狗 | 保留；`run.resources` 只允许调低 | 现有 |
| 基础镜像锁定 | L0 锁 `@sha256:`（PDF 同款）；L1+ 只 FROM 本地已构建 tag | 新增 |
| 预置文件完整性 | `assets[]` 强制 sha256，不符即拒绝构建 | 新增（PDF tools 校验） |
| flag 卫生 | service 容器占位 flag；真值只来自平台实例，不进任何镜像/spec | SKILL.md 红线 |
| spec 即代码 | spec 进 git 审查；路径逃逸检查；argv 拼装 | 新增 |
| 模型网关 | 一次性令牌机制不变，env 镜像同样拿不到上游 key | 现有 |

---

## 9. 实战检验闭环（PDF 第八节）

1. **verify 探针矩阵**：每层镜像构建后跑 `verify`，工具存在性 + 版本断言 + libc 版本断言。
2. **赛前 checklist**：预热 L1 → 构建计划攻坚题的 L3 → 全量 `verify` → 断网演练一次求解任务。
3. **赛后复盘**：`export` 归档当场比赛镜像；env spec 与 `gen/.built.json` 进复盘记录，
   可复现性纳入 case 关闭条件（对应 SKILL.md 第 6 步"environment/tool versions"）。
4. **迭代**：小范围用 → 实战发现问题 → 修 spec/模板 → 再发布（PDF 的打磨循环）。

---

## 10. 分阶段落地

| 阶段 | 内容 | 产出 | 状态 |
|---|---|---|---|
| P0 | 设计文档 + envs/ 模板与两份示例 spec + solver 约束层 | 本目录 | ✅ |
| P1 | `env_builder.py` 六子命令 + `competition.py` env 骨架 + 渲染纯函数自测 | 命令行构建比赛环境 | ✅ |
| P2 | server.py 镜像选择优先级 + compose 生命周期挂任务 + 前端「环境」面板 | UI 一键构建/派发 | ✅ |
| P3 | L1 预热命令（preheat）+ export 归档 | 全自动开赛流水线 | ✅ |

真实环境验证（2026-09-05，Windows + WSL2 docker）：L0/L1 构建 30s/60s，
题目层（apt+jq、pip+six）增量构建 <10s，verify 探针矩阵全过，
compose 服务（busybox）拉起 → solver 容器按服务名解析 → down 清理，全链路通过。
第二轮优化：约束层（CLAUDE.md/AGENTS.md + 七类 skill 包）烤入 L0 并在容器内实测；
`ctfbox-ai` 题型层补齐七层；镜像集合缓存使 env/status 冷 3s → 热 0.01s（WSL 通道）；
`services.*.env.FLAG` 占位强校验生效。

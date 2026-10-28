# 多 AI 协作体系设计方案（R108 调研 → 待审阅实施）

> 2026-10-29 · 基于 R104-R107 已上线的 Agent 网关（身份/心跳/认领/吊销），
> 补齐「协作」剩下的三块：**调度、互知、交接**。本文是设计文档——你批哪块我做哪块。

---

## 0. 现状与缺口

已上线（可用）：
- **身份层**：`/api/agent-gw/register` 发放独立密钥（哈希存储/可吊销/心跳）
- **认领协议**：`claim/release`（TTL 45min，冲突 409）
- **过程留痕**：case.attempt/hypothesis/findings 全部进审计流
- **人侧看板**：Agent 态势卡 / 泳道时间线 / 无人认领提醒 / 协作快照复制

缺口（AI 侧视角的真实痛点）：
| # | 缺口 | 后果 |
|---|---|---|
| G1 | **无调度协议**：新加入的 AI 问"我现在该干哪道题？"——只能问人或自己翻 /api/competition 拼凑 | 协作门槛高，AI 之间无法自组织 |
| G2 | **认领态不可见**：claim 在网关里，但不在看板泳道/题目卡/无人认领条上反映 | 人与 AI 都可能撞车 |
| G3 | **无交接机制**：AI-A 做到一半弃坑，AI-B 接手只能翻审计日志拼上下文 | 交接成本极高 |
| G4 | **权限无差别**：agent key 等同 session——协作 AI 可以互相删对方的假设/尝试 | 误操作放大 |

---

## 1. 设计方案（四层，按依赖排序）

### L1 调度端点 `GET /api/agent-gw/dispatch?agent=<key>`（G1，R109）

一句话：**AI 问"我该干啥"，服务端按优先级公式 + 认领态 + 全局态势回答，并顺手完成认领。**

返回结构（纯数据，AI 拿到即可行动）：
```json
{
  "assignment": {
    "slug": "web-blog", "name": "Baby Blog", "category": "web", "points": 300,
    "priority": 42.0,                       // competition.py prioritize 同款公式
    "status": "new", "claimed_by_me": true,
    "prompt": "…build_prompt 全文…",         // 免二次请求
    "conflicts": [],                         // 其他 agent 正在跑的同题任务（提醒）
    "unclaimed_count": 3, "agents_active": 2
  },
  "alternatives": [ {"slug": "...", "priority": 38.0} ],   // 备选 3 题
  "situational": { "solved": 2, "total": 12, "running_tasks": 3, "unclaimed": 3 }
}
```
选取逻辑：`competition.py prioritize` 的 `P(成功)×分值×紧迫度÷预期分钟` 排序，
跳过已 solved/认领给别人的题；已被我认领的题优先返回（续做）。
可选参数 `?category=web` 限定方向、`?slug=x` 直接指定。

### L2 认领态全局可见（G2，R110）

- `/api/board` 泳道与题目卡吸收 claims：认领中的题显示 `🔒 agent 名`；
  无人认领条排除"已被认领"的题（它们不是没人管，是有人管）；
- `POST /api/action competition.update` 级联：认领后 case 自动 `in_progress`（可配置）。

### L3 交接简报（G3，R111-R112）

- **弃坑声明**：`POST /api/agent-gw/handoff {slug, summary}`——AI 交还题目时留下
  结构化简报（已试方向/关键发现/建议下一步），写入 case `handoffs[]` 并发事件；
- **接手注入**：`/api/agent-gw/dispatch` 返回的 prompt 自动附加最近一条 handoff 简报
  （新 AI 秒懂上下文，不用翻日志）；
- **看板展示**：题目泳道 tooltip 显示"上次交接：xxx"。

### L4 权限分级（G4，R113，可后置）

- agent 注册时选角色：`solver`（只能动自己认领的 case）/ `observer`（只读）；
- `case.attempt/hypothesis` 等写动作校验"该题是否由本 agent 认领"——
  未认领的题先 claim 再写，防止互删。

---

## 2. AI 侧接入体验（设计目标态）

新 AI 加入全流程（零人工介入）：
```
1. 人：看板点「＋注册 Agent」→ 把密钥+协作提示发给 AI
2. AI：GET /api/agent-gw/dispatch?mine=1        ← "我该继续哪题？"
3. AI：GET /api/prompt?slug=…（或直接用返回的 prompt 字段）
4. AI：POST /api/agent-gw/heartbeat（周期）+ POST /api/agent-gw/claim（动手前）
5. AI：case.hypothesis / case.attempt / case.scan_flags 登记过程
6. AI：出 flag → case.candidate → submit.dryrun（人放行）
7. AI：弃坑或完成 → POST /api/agent-gw/handoff {summary}
```

---

## 3. 实施计划（每轮独立可交付）

| 轮 | 内容 | 工作量 |
|---|---|---|
| R109 | L1 调度端点（含 prompt 注入、冲突提醒）+ 测试 | M |
| R110 | L2 认领态上板（泳道/题目卡/无人认领条） | S |
| R111 | L3 handoff 存储与注入 + 测试 | M |
| R112 | L3 看板交接展示 + L4 权限分级（若你批） | M |
| R113 | CHANGELOG/账本/帮助文档收尾 | S |

---

## 4. 不做的（明确边界）

- **不做 AI 之间直接对话**（消息总线）：协作经 case 审计流 + 看板就够，直接对话不可审计；
- **不做自动任务分配队列**：调度端点是"建议 + 认领"，最终决定权在 AI 自己（避免中心化瓶颈）；
- **不做 agent 间加密通信**：本地/Tailscale 可信网络内，HTTPS 反代是部署层的事。

---

## 5. 审阅结论区（由你填写）

- 批准：L1 / L2 / L3 / L4（圈选）
- 调整：
- 追加：

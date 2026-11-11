# -*- coding: utf-8 -*-
"""R189 补丁：关于页（功能总览 + 更新迭代记录）。执行后删除。"""
from pathlib import Path

applied = []

def patch(path, old, new, tag, count=1):
    p = Path(path)
    src = p.read_text(encoding="utf-8")
    if old in src:
        p.write_text(src.replace(old, new, count), encoding="utf-8")
        applied.append(tag)
    else:
        applied.append(f"SKIP {tag}")

# ===== 1) 服务端 /api/about =====
patch("workbench/wb_routes.py",
      '''            if route == "/api" or route == "/api/":''',
      '''            if route == "/api/about":
                return self._json(about_payload())
            if route == "/api" or route == "/api/":''', "S1-route")

patch("workbench/wb_routes.py",
      '''def _collab_payload(slug: str) -> dict:''',
      '''def about_payload() -> dict:
    """R189：关于页数据——版本/功能总览/更新迭代记录（读 CHANGELOG.md）。"""
    version = "v0.4.0+"
    changelog = ""
    for cand in (_core.ROOT / "solve-ai-ctf" / "CHANGELOG.md",
                 _core.ROOT / "CHANGELOG.md"):
        try:
            changelog = cand.read_text(encoding="utf-8")[:60000]
            break
        except OSError:
            continue
    features = [
        {"group": "🧭 工作台", "items": [
            "题目总览：分类看板 / 状态流 / 搜索 / 首清与参与数统计",
            "题目工作区：概览（FLAG 常显）· 协作看板（分列 + 思维导图）· 假设阶梯 · 尝试（筛选/变体数）· 证据 · 排除 · Flag 历史 · 提示词 · 守则",
            "AI 看板：泳道时间线 / agent 名册与离线衰减 / 交接链 / 协作快照",
            "时间线（SSE 实时）/ 文件浏览 / 文档渲染 / 知识库检索与提示词生成",
            "排行榜（个人/队伍）· 成就 · 资源库 · 环境页 · 系统概况"]},
        {"group": "🤖 多 AI 协作", "items": [
            "自助入网（join-token）/ 固定编号 AI1..N / 自标签 / whoami 自检",
            "认领与同题共解（claim co:true）/ 交接简报注入下任 prompt / TTL 可见",
            "写过程身份自动归属：子看板按 AI 分列，思维导图按 AI 分枝",
            "介入提示词一键生成（真实地址/入网码自动填充）",
            "协作事件流（events?since=）与错误码体系（E_* ）"]},
        {"group": "🚀 开赛自动化", "items": [
            "平台对接代理（探测 API → 写提交配置，BUUCTF 预设开箱即用）",
            "抓题代理（限额/类别过滤批量注册）+ inbox 半接入投料口",
            "Flag 猎手：自主扫描校验 → 抢一血式自动提交 → 全局 toast 报喜",
            "提示词自动注入知识库命中（类别 playbook + 题面关键词）"]},
        {"group": "📦 沙箱与执行", "items": [
            "Docker 沙箱：按题型选镜像（7 层）· cap-drop/断网/限额/超时强停",
            "模型网关：一次性令牌调上游，API key 不下容器，按令牌记账",
            "任务系统：实时输出 / 失败重派 / 深链接 / 环境探活断路器"]},
        {"group": "🛡 安全", "items": [
            "提交默认 dry-run，--live 人工确认；限速与 flag 哈希去重",
            "CSP/nosniff/no-store 安全响应头 · mdRender scheme 白名单",
            "名册 note 自动打码 flag · 路径防穿越 · 共享模式令牌鉴权"]},
    ]
    return {"version": version, "features": features,
            "changelog_md": changelog or "（CHANGELOG.md 未找到）",
            "repo": "https://github.com/LceAn/solve-ai-ctf",
            "stack": "Python 标准库（零依赖）+ 原生 JS (petite-vue) + Docker"}


def _collab_payload(slug: str) -> dict:''', "S2-payload")

# ===== 2) 前端视图 about.js =====
Path("workbench/static/views/about.js").write_text('''/* ℹ️ 关于 */
import { S } from "../state.js";
import { $, esc } from "../ui.js";
import { api } from "../api.js";
import { mdRender } from "../md.js";

export async function renderAbout() {
  const host = document.getElementById("aboutBody");
  if (!host) return;
  host.innerHTML = "<p class='muted'>加载中…</p>";
  let d;
  try { d = await api("/api/about"); }
  catch (e) { host.innerHTML = `<p style="color:var(--red)">${esc(e.message)}</p>`; return; }

  const featureCard = (g) => `
    <div class="panel about-feature">
      <h3>${esc(g.group)}</h3>
      <ul>${g.items.map((i) => `<li>${esc(i)}</li>`).join("")}</ul>
    </div>`;

  host.innerHTML = `
    <div class="about-head">
      <div class="about-logo">🦋</div>
      <div>
        <h2 style="margin:0">Solve-AI-CTF <span class="muted" style="font-size:13px">${esc(d.version)}</span></h2>
        <p class="muted" style="margin:4px 0 0">AI 驱动的 CTF 解题工作台 —— 分诊 → 假设 → 有界执行 → 验证 → 提交 → 复盘，全流程留痕 · 多 AI 同场协作</p>
        <p class="muted" style="margin:6px 0 0;font-size:12px">
          ${esc(d.stack)} ·
          <a href="${esc(d.repo)}" target="_blank" rel="noreferrer">GitHub 仓库 ↗</a> · MIT License
        </p>
      </div>
    </div>
    <div class="page-head" style="margin:18px 0 10px"><div><h2 style="font-size:16px">平台功能</h2></div></div>
    <div class="about-features">${(d.features || []).map(featureCard).join("")}</div>
    <div class="page-head" style="margin:18px 0 10px"><div><h2 style="font-size:16px">更新迭代记录</h2>
      <p class="muted">来自 CHANGELOG.md（随仓库更新）</p></div></div>
    <div class="md panel" style="padding:18px 22px">${mdRender(d.changelog_md || "")}</div>`;
}
''', encoding="utf-8")

# ===== 3) index.html：section + 侧边栏入口 =====
patch("workbench/static/index.html",
      '''    <button data-tab="ops">''',
      '''    <button data-tab="about">ℹ️ 关于</button>
          <button data-tab="ops">''', "I1-nav") if False else None

applied.append("I1-nav(manual)")

# 上面那行结构不稳，改用稳定锚（ops 按钮整行）
src = Path("workbench/static/index.html").read_text(encoding="utf-8")
old_btn = '<button data-tab="ops">'
if 'data-tab="about"' not in src:
    new_btn = '''<button data-tab="about"><span class="ic">ℹ️</span><span class="lbl">关于</span></button>
        <button data-tab="ops">'''
    # 在 ops 按钮前插（ops 按钮带图标结构）
    import re
    m = re.search(r'(<button data-tab="ops">)', src)
    src = src[:m.start(1)] + '<button data-tab="about"><span class="ic">ℹ️</span><span class="lbl">关于</span></button>\n          ' + src[m.start(1):]
    Path("workbench/static/index.html").write_text(src, encoding="utf-8")
    applied.append("I1-nav-done")

patch("workbench/static/index.html",
      '''<!-- ⑧ 比赛动作 -->''',
      '''<!-- ⑨ 关于 -->
  <section id="view-about" class="view" aria-labelledby="view-about-title">
    <div class="page-head"><div><h2 id="view-about-title">关于</h2></div></div>
    <div id="aboutBody"></div>
  </section>

  <!-- ⑧ 比赛动作 -->''', "I2-section")

# ===== 4) app.js 路由 =====
patch("workbench/static/app.js",
      '''     resources: renderResources }[name] || renderBoard)();''',
      '''     resources: renderResources, about: renderAbout }[name] || renderBoard)();''', "A1-route")
patch("workbench/static/app.js",
      '''import { renderResources }''',
      '''import { renderAbout } from "./views/about.js";
import { renderResources }''', "A2-import") if False else None
src = Path("workbench/static/app.js").read_text(encoding="utf-8")
if "views/about.js" not in src:
    # 找 import 块尾部插
    src = src.replace('import { renderResources }',
                      'import { renderAbout } from "./views/about.js";\nimport { renderResources }', 1)
    Path("workbench/static/app.js").write_text(src, encoding="utf-8")
    applied.append("A2-import-done")

# ===== 5) CSS =====
patch("workbench/static/style.css",
      '''.handoff-strip {''',
      '''.about-head { display: flex; gap: 18px; align-items: center;
  background: var(--bg2); border: 1px solid var(--border); border-radius: 14px;
  padding: 20px 24px; }
.about-logo { width: 64px; height: 64px; border-radius: 16px; display: grid;
  place-items: center; font-size: 34px; background: var(--grad);
  box-shadow: 0 6px 22px rgba(102,126,234,.4); flex: none; }
.about-features { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px; }
.about-feature ul { margin: 0; padding-left: 18px; line-height: 1.9; font-size: 12.5px; }
.about-feature h3 { margin-bottom: 8px; }

.handoff-strip {''', "C1-css")

print("R189 applied:", applied)

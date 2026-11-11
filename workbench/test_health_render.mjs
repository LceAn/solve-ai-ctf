/* R203 渲染回归：不依赖浏览器，直接跑 health.js 的 renderHealth()。
 *
 * 目的不是替代视觉检查，而是守住"页面不会白屏 / 字段缺失不炸 / 转义正确"。
 * 跑法：node --test workbench/test_health_render.mjs
 */
import assert from "node:assert";
import { test } from "node:test";

const FIXTURE = {
  server: { ok: true, detail: "workbench" },
  stats: { competitions: 1, configured: 1, challenges: 3, tasks_running: 0, tasks_total: 2 },
  docker: { ok: true, detail: "29.7.2" },
  summary: { online: 12, degraded: 1, off: 2, total: 15, headline: "1 项需要关注", state: "warn" },
  groups: ["核心运行时", "求解环境", "协作接入", "数据与交付"],
  attention: [
    { key: "tasks", name: "任务执行器", state: "degraded", hint: "24h 内 1 个任务失败" },
    { key: "gateway", name: "协作网关", state: "off", hint: "本机模式，其他 AI 无法接入" },
    { key: "model_gw", name: "模型网关", state: "off", hint: "派发沙箱任务后自动生效" },
  ],
  overview: {
    port: 8787, host: "127.0.0.1", exposed: false,
    uptime: "2h", uptime_seconds: 7200, server_time: "2026-11-11T21:30:00",
  },
  modules: [
    { key: "http", name: "HTTP 服务", group: "核心运行时", state: "online",
      detail: "127.0.0.1:8787（仅本机）", probe: "本进程",
      metrics: [{ label: "运行时长", value: "2h" }, { label: "在线设备", value: "3" }] },
    { key: "scripts", name: "脚本层", group: "核心运行时", state: "online",
      detail: "12 个脚本全部可加载", probe: "compile()", metrics: [] },
    { key: "data", name: "比赛数据", group: "核心运行时", state: "online",
      detail: "1 场比赛 · 3 题", probe: "case.json", metrics: [] },
    { key: "tasks", name: "任务执行器", group: "求解环境", state: "degraded",
      detail: "运行中 0 · 累计 2 · 24h 内异常 1",
      hint: "24h 内 1 个任务失败", probe: "tasks.json", metrics: [] },
    { key: "docker", name: "Docker 与沙箱", group: "求解环境", state: "online",
      detail: "引擎 29.7.2 · 沙箱关闭（宿主直跑）", probe: "docker version", metrics: [] },
    { key: "submitter", name: "提交器", group: "求解环境", state: "online",
      detail: "已提交 4 次", probe: "submissions.jsonl", metrics: [] },
    { key: "gateway", name: "协作网关", group: "协作接入", state: "off",
      detail: "本机模式，其他 AI 无法接入", hint: "AI 看板 →「让其他 AI 接入」一键开启局域网共享",
      probe: "RUNTIME.exposed", metrics: [] },
    { key: "netdev", name: "接入设备", group: "协作接入", state: "online",
      detail: "1 台在线", probe: "wb_monitor", metrics: [] },
    { key: "model_gw", name: "模型网关", group: "协作接入", state: "off",
      detail: "无活跃令牌", hint: "派发沙箱任务后自动生效", probe: "tokens", metrics: [] },
    { key: "events", name: "事件流", group: "数据与交付", state: "online",
      detail: "最后事件 1h 前 · 共 71 条", probe: "events.jsonl", metrics: [] },
    { key: "kb", name: "知识库", group: "数据与交付", state: "online",
      detail: "24 篇参考 · 命中率 92%", probe: "kb_queries.jsonl", metrics: [] },
    { key: "docs", name: "文档与题解", group: "数据与交付", state: "online",
      detail: "8 篇文档 · 3 篇题解", probe: "docs/*.md", metrics: [] },
    { key: "export", name: "交付打包", group: "数据与交付", state: "online",
      detail: "最近 11-03 12:16 · 15.4 KB", probe: "交付/*.zip", metrics: [] },
    { key: "board", name: "积分与成就", group: "数据与交付", state: "online",
      detail: "0 支队伍 · 0 个成就解锁", probe: "leaderboard.db", metrics: [] },
    { key: "inbox", name: "半接入 inbox", group: "数据与交付", state: "online",
      detail: "无待导入条目", probe: "inbox/", metrics: [] },
  ],
};

// ---- 极简 DOM stub：health.js 只用 innerHTML / onclick / hidden / textContent
const nodes = new Map();
function node(sel) {
  if (!nodes.has(sel)) {
    const obj = { _sel: sel, innerHTML: "", textContent: "", hidden: false, onclick: null, open: false };
    // 极简 querySelector：innerHTML 里出现过这个 class/id 就当存在
    obj.querySelector = (q) => {
      const key = String(q).replace(/^[.#]/, "");
      return obj.innerHTML.includes(key) ? node(sel + " " + q) : null;
    };
    obj.querySelectorAll = () => [];
    nodes.set(sel, obj);
  }
  return nodes.get(sel);
}

globalThis.window = {};
globalThis.localStorage = {
  _d: { "wb.health.auto": "0" },   // 关掉自动刷新，避免 setInterval 挂住进程
  getItem(k) { return this._d[k] ?? null; },
  setItem(k, v) { this._d[k] = String(v); },
  removeItem(k) { delete this._d[k]; },
};
globalThis.document = {
  // 渲染后页面里的元素都“存在”，每个选择器给一个可写节点即可
  querySelector(sel) { return node(sel); },
  visibilityState: "visible",
};
globalThis.fetch = async () => ({
  ok: true, status: 200, headers: { get: () => null },
  json: async () => FIXTURE,
});

const { renderHealth } = await import("./static/views/health.js");

test("系统概况渲染出在线矩阵", async () => {
  nodes.clear();
  await renderHealth(true);
  const html = node("#healthWrap").innerHTML;

  assert.match(html, /hm-hero/, "缺少顶部总览");
  assert.match(html, /12<\/b><span>\/15/, "分数渲染错误");
  assert.match(html, /功能在线/, "缺少分数标签");
  assert.match(html, /1 项需要关注/, "缺少结论行");
  assert.match(html, /局域网|仅本机/, "缺少共享状态");
  assert.match(html, /检测于 21:30:00/, "缺少检测时刻");
  assert.match(html, /运行 2h/, "缺少运行时长");
});

test("四个分组与全部模块都在页面上", async () => {
  nodes.clear();
  await renderHealth(true);
  const html = node("#healthWrap").innerHTML;
  for (const g of FIXTURE.groups) assert.ok(html.includes(g), `缺分组：${g}`);
  for (const m of FIXTURE.modules) assert.ok(html.includes(m.name), `缺模块：${m.name}`);
  // 每个模块一张卡
  assert.equal((html.match(/class="hm-card /g) || []).length, FIXTURE.modules.length);
});

test("降级项进「需要关注」，未启用项进折叠区", async () => {
  nodes.clear();
  await renderHealth(true);
  const html = node("#healthWrap").innerHTML;
  assert.match(html, /hm-attn-title[\s\S]*?需要关注[\s\S]*?1/, "缺关注区");
  assert.ok(html.includes("24h 内 1 个任务失败"), "缺降级提示");
  assert.match(html, /2 项未启用/, "缺未启用折叠区");
  assert.ok(html.includes("一键开启局域网共享"), "缺未启用的下一步");
});

test("off 卡片灰显但仍有内容（不是空白）", async () => {
  nodes.clear();
  await renderHealth(true);
  const html = node("#healthWrap").innerHTML;
  const offCard = html.slice(html.indexOf("协作网关"));
  assert.ok(offCard.includes("本机模式"), "off 卡片缺说明");
  assert.match(html, /s-off/, "缺 off 状态类");
});

test("字段缺失不炸（降级到占位）", async () => {
  nodes.clear();
  FIXTURE.modules.push({ key: "x", name: "裸模块", group: "协作接入", state: "online" });
  await renderHealth(true);
  const html = node("#healthWrap").innerHTML;
  assert.ok(html.includes("裸模块"), "缺 metrics/probe 的模块应仍可渲染");
  FIXTURE.modules.pop();
});

test("内容做 HTML 转义（防注入）", async () => {
  nodes.clear();
  FIXTURE.modules.push({ key: "evil", name: "<img src=x onerror=alert(1)>",
    group: "协作接入", state: "online", detail: "<script>x</script>", probe: "p",
    metrics: [{ label: "<b>", value: "<i>" }] });
  await renderHealth(true);
  const html = node("#healthWrap").innerHTML;
  assert.ok(!html.includes("<img src=x onerror"), "模块名未转义");
  assert.ok(!html.includes("<script>x</script>"), "说明未转义");
  assert.ok(html.includes("&lt;img"), "转义结果不对");
  FIXTURE.modules.pop();
});

test("矩阵构建失败时给出错误而不是白屏", async () => {
  nodes.clear();
  const real = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true, status: 200, headers: { get: () => null },
    json: async () => ({ server: { ok: true }, stats: {}, matrix_error: "KeyError: x" }),
  });
  await renderHealth(true);
  const html = node("#healthWrap").innerHTML;
  assert.ok(html.includes("功能矩阵构建失败"), "缺错误提示");
  globalThis.fetch = real;
});

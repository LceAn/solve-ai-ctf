/* R204 渲染回归：不起浏览器，直接跑 about.js 的 renderAbout()。
 *
 * 守的是"页面不会白屏 / 结构齐全 / 转义正确"——视觉仍靠人眼。
 * 跑法：node --test workbench/test_about_render.mjs
 */
import assert from "node:assert";
import { test } from "node:test";

const FIXTURE = {
  version: "v0.5.0+3 commits",
  build: { commit: "abc1234", commit_at: "2026-11-11T22:39:57+08:00", tag: "v0.5.0", branch: "main" },
  stats: { online: 12, total: 15, competitions: 5, challenges: 25, agents_online: 2 },
  stack: "Python 标准库（零依赖）+ 原生 JS（vendored petite-vue）+ Docker",
  repo: "https://github.com/LceAn/solve-ai-ctf",
  features: [
    { group: "🧭 工作台", desc: "从总览到单题工作区", items: ["题目总览", "题目工作区"] },
    { group: "🤖 多 AI 协作", desc: "多个 AI 同时打同一场", items: ["自助入网", "认领与同题共解"] },
    { group: "🚀 开赛自动化", desc: "抓题扫 flag", items: ["平台对接代理"] },
    { group: "📦 沙箱与执行", desc: "容器里跑", items: ["Docker 沙箱"] },
    { group: "🛡 安全", desc: "默认 dry-run", items: ["提交默认 dry-run"] },
  ],
  changelog_sections: [
    { title: "[Unreleased]", body: "### 改进（R204）\n- 关于页重做", latest: true, id: "cl-0" },
    { title: "[v0.5.0] — 2026-11-11（多 AI 实战协作大版本）", body: "### 主题\n- 把比赛打完", latest: false, id: "cl-1" },
    { title: "[v0.4.0] — 2026-11-02", body: "- 旧版本", latest: false, id: "cl-2" },
  ],
};

const nodes = new Map();
function node(sel) {
  if (!nodes.has(sel)) {
    const obj = { _sel: sel, innerHTML: "", textContent: "", hidden: false, onclick: null };
    obj.querySelector = () => null;
    obj.querySelectorAll = () => [];
    nodes.set(sel, obj);
  }
  return nodes.get(sel);
}

globalThis.window = {};
globalThis.location = { host: "127.0.0.1:8787", href: "" };
// navigator 在 Node 22 是只读 getter，不覆盖；renderAbout 只在点击复制时才用它
globalThis.localStorage = {
  _d: {}, getItem(k) { return this._d[k] ?? null; },
  setItem(k, v) { this._d[k] = String(v); }, removeItem(k) { delete this._d[k]; },
};
globalThis.document = {
  querySelector(sel) { return node(sel); },
  querySelectorAll() { return []; },
  createElement() { return { value: "", select() {}, remove() {}, style: {} }; },
  body: { appendChild() {} },
};
let PAYLOAD = FIXTURE;
globalThis.fetch = async () => ({
  ok: true, status: 200, headers: { get: () => null }, json: async () => PAYLOAD,
});

const { renderAbout } = await import("./static/views/about.js");

test("Hero：名称、版本、定位、仓库入口", async () => {
  nodes.clear();
  await renderAbout();
  const html = node("#aboutBody").innerHTML;
  assert.match(html, /Solve-AI-CTF/);
  assert.ok(html.includes("v0.5.0+3 commits"), "缺版本号");
  assert.ok(html.includes("AI 驱动的 CTF 解题工作台"), "缺定位语");
  assert.ok(html.includes("github.com/LceAn/solve-ai-ctf"), "缺仓库链接");
  assert.ok(html.includes("abc1234"), "缺 commit");
  assert.ok(html.includes("main"), "缺分支");
  assert.ok(html.includes("2026-11-11 22:39"), "缺构建时间");
});

test("运行链路五段齐全", async () => {
  nodes.clear();
  await renderAbout();
  const html = node("#aboutBody").innerHTML;
  for (const name of ["浏览器", "HTTP 服务", "脚本层", "沙箱 / Agent", "CTF 平台"]) {
    assert.ok(html.includes(name), `链路缺：${name}`);
  }
  assert.equal((html.match(/class="ab-node"/g) || []).length, 5);
});

test("运行现状四个数字", async () => {
  nodes.clear();
  await renderAbout();
  const html = node("#aboutBody").innerHTML;
  assert.match(html, /12<span>\/15<\/span>/, "功能在线分数不对");
  assert.ok(html.includes("<b>5</b><em>场比赛</em>"), "缺比赛数");
  assert.ok(html.includes("<b>25</b><em>题目</em>"), "缺题目数");
  assert.ok(html.includes("<b>2</b><em>AI 在线</em>"), "缺 AI 在线数");
});

test("五张能力卡，标题去掉 emoji，保留要点", async () => {
  nodes.clear();
  await renderAbout();
  const html = node("#aboutBody").innerHTML;
  assert.equal((html.match(/class="ab-fcard"/g) || []).length, 5);
  assert.ok(html.includes(">工作台<"), "能力卡标题应去掉 emoji 前缀");
  assert.ok(html.includes("从总览到单题工作区"), "缺一句话说明");
  assert.ok(html.includes("题目工作区"), "缺要点");
});

test("更新记录：只展开最新一段，其余折叠", async () => {
  nodes.clear();
  await renderAbout();
  const html = node("#aboutBody").innerHTML;
  assert.equal((html.match(/class="ab-cl-item"/g) || []).length, 3);
  assert.equal((html.match(/ab-cl-item" data-idx="\d+" open/g) || []).length, 1, "只该有一段默认展开");
  assert.ok(html.includes("最新"), "缺最新徽章");
  assert.ok(html.includes("v0.5.0"), "缺版本名");
  assert.ok(html.includes("3 个版本段"), "缺段数统计");
});

test("页脚：技术栈 / 快捷键 / 本地优先", async () => {
  nodes.clear();
  await renderAbout();
  const html = node("#aboutBody").innerHTML;
  assert.ok(html.includes("Python 标准库"), "缺技术栈");
  assert.ok(html.includes("<kbd>Alt</kbd>"), "缺快捷键");
  assert.ok(html.includes("本地优先"), "缺数据位置说明");
});

test("转义：能力目录里的标签不被当 HTML 执行", async () => {
  nodes.clear();
  PAYLOAD = {
    ...FIXTURE,
    features: [{ group: "🧪 <b>x</b>", desc: "<script>alert(1)</script>", items: ["<img src=x>"] }],
  };
  await renderAbout();
  const html = node("#aboutBody").innerHTML;
  assert.ok(!html.includes("<script>alert(1)</script>"), "说明未转义");
  assert.ok(!html.includes("<img src=x>"), "要点未转义");
  assert.ok(html.includes("&lt;script&gt;"), "转义结果不对");
  PAYLOAD = FIXTURE;
});

test("后端降级：没有 changelog 也不白屏", async () => {
  nodes.clear();
  PAYLOAD = { ...FIXTURE, changelog_sections: [], build: {}, stats: {} };
  await renderAbout();
  const html = node("#aboutBody").innerHTML;
  assert.ok(html.includes("没有找到 CHANGELOG.md"), "缺空态文案");
  assert.ok(html.includes("Solve-AI-CTF"), "骨架仍应在");
  PAYLOAD = FIXTURE;
});

test("接口失败时给出可读错误而不是空白", async () => {
  nodes.clear();
  const real = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false, status: 500, headers: { get: () => null },
    json: async () => ({ error: "boom" }),
  });
  await renderAbout();
  assert.ok(node("#aboutBody").innerHTML.includes("加载失败"), "缺错误提示");
  globalThis.fetch = real;
});

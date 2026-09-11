/* ---------------- ③ Flag 审核（状态流水线） ---------------- */
import { S } from "../state.js";
import { $, $$, esc, toast, copyText, openModal } from "../ui.js";
import { api, post, authHeaders } from "../api.js";
import { chOf } from "./detail.js";
import { TaskUI } from "./tasks.js";
import { doAction, loadCompetition, setTab } from "../app.js";

let hunterTimer = null;

export function pipeStep(label, n, color) {
  return `<div class="pipe-step" ${color ? `style="--pc:${color}"` : ""}>
    <b style="${color ? `color:${color}` : ""}">${n}</b><span class="lbl">${label}</span></div>`;
}

export function candRow({ ch, x }, actions) {
  return `<tr><td>${esc(ch.name)}</td><td class="wrap">${esc(x.id)}</td>
    <td class="wrap mono">${esc(x.value)}</td>
    <td class="wrap muted">${esc(x.note || "")}</td>
    <td><div class="row" style="margin:0">${actions}</div></td></tr>`;
}

export function renderFlags() {
  const el = $("#flagsWrap");
  if (!S.comp) { el.innerHTML = ""; return; }
  const all = [];
  for (const c of S.comp.challenges)
    for (const x of c.case?.candidates || []) all.push({ ch: c, x });
  const by = (sts) => all.filter((r) => sts.includes(r.x.status));
  const unv = by(["unverified"]), val = by(["validated"]),
        subm = by(["submitted"]), acc = by(["accepted"]), rej = by(["rejected"]);

  el.innerHTML = `
    <div class="panel">
      <h3>Flag 流水线 <span class="muted">每个候选只出现在它所处的状态分区</span></h3>
      <div class="pipe">
        ${pipeStep("扫描发现", all.length, "#8b96a8")}
        <span class="pipe-arrow">→</span>
        ${pipeStep("待校验", unv.length, "#fbbf24")}
        <span class="pipe-arrow">→</span>
        ${pipeStep("可提交", val.length, "#34d399")}
        <span class="pipe-arrow">→</span>
        ${pipeStep("已提交", subm.length, "#a78bfa")}
        <span class="pipe-arrow">→</span>
        ${pipeStep("已接受", acc.length, "#34d399")}
        <span class="pipe-arrow" title="rejected">⌫</span>
        <span class="muted" style="font-size:11px">驳回 ${rej.length}</span>
      </div>
      <div class="row" style="margin:14px 0 0">
        <button id="hunterBtn" class="primary">🚩 启动猎手扫描</button>
        <label class="row" style="margin:0;gap:6px;flex-wrap:nowrap">
          <input type="checkbox" id="autoSub">
          <span class="muted" style="white-space:nowrap">自动提交 · 抢一血（默认开，dry-run 通过即 --live）</span>
        </label>
        <label class="muted" style="white-space:nowrap">每轮上限 <input id="maxLive" type="number" value="3" min="1" max="10" style="width:56px"></label>
        <span class="spacer" style="flex:1"></span>
        <span id="hunterState" class="muted"></span>
      </div>
      <p class="muted" style="margin:6px 0 0">猎手自主扫描全部 case 并校验；「可提交」区逐枚放行，或开启自动提交（受每轮限额 + submitter 限速/去重保护）。</p>
      <details id="hunterDetails" class="hidden" style="margin-top:8px">
        <summary class="sec-sum muted">猎手实时输出</summary>
        <pre class="out" id="hunterOut" style="max-height:180px"></pre>
      </details>
    </div>

    <div class="panel">
      <h3>✅ 可用标志（已验证，可提交）<span class="muted">${val.length} 枚</span></h3>
      ${val.length ? val.map(({ ch, x }) => `
        <div class="ready-row">
          <span class="dot s-solved"></span>
          <div style="flex:1;min-width:0">
            <div class="mono" style="font-size:13.5px;word-break:break-all">${esc(x.value)}</div>
            <div class="muted">${esc(ch.name)} · ${esc(x.id)} · ${esc(x.note || "人工/代理校验")}</div>
          </div>
          <button class="small copy-btn" data-copy="${esc(x.value)}">复制</button>
          <button class="small danger" data-a="submit" data-ch="${esc(ch.slug)}" data-id="${esc(x.id)}">提交…</button>
        </div>`).join("")
        : `<div class="empty"><div class="big">🎯</div>暂无可用标志：启动猎手自主识别，或在下方「待人工校验」区确认。</div>`}
    </div>

    <div class="panel">
      <h3>🔍 待人工校验<span class="muted">${unv.length} 条</span></h3>
      ${unv.length ? `<table><tr><th>题目</th><th>ID</th><th>候选值</th><th>备注</th><th>操作</th></tr>
        ${unv.map((r) => candRow(r, `
          <button class="small primary" data-a="validate" data-ch="${esc(r.ch.slug)}" data-id="${esc(r.x.id)}">✓ 校验通过</button>
          <button class="small" data-a="reject" data-ch="${esc(r.ch.slug)}" data-id="${esc(r.x.id)}">✗ 驳回</button>`)).join("")}
        </table>`
        : `<div class="empty"><div class="big">🔍</div>没有待校验的候选。</div>`}
    </div>

    <details class="panel">
      <summary class="sec-sum">🚀 已提交 / 已接受（${subm.length + acc.length}）</summary>
      <div style="margin-top:10px">
      ${(subm.length + acc.length) ? `<table><tr><th>题目</th><th>ID</th><th>候选值</th><th>状态</th><th>备注</th></tr>
        ${[...subm, ...acc].map((r) => `<tr><td>${esc(r.ch.name)}</td><td class="wrap">${esc(r.x.id)}</td>
          <td class="wrap mono">${esc(r.x.value)}</td>
          <td><span class="badge b-${esc(r.x.status)}">${esc(r.x.status)}</span></td>
          <td class="wrap muted">${esc(r.x.note || "")}</td></tr>`).join("")}</table>`
        : `<p class="muted" style="margin:0">还没有提交记录。</p>`}
      </div>
    </details>

    <details class="panel">
      <summary class="sec-sum">✗ 已驳回（${rej.length}）</summary>
      <div style="margin-top:10px">
      ${rej.length ? `<table><tr><th>题目</th><th>ID</th><th>候选值</th><th>驳回原因</th></tr>
        ${rej.map((r) => `<tr><td>${esc(r.ch.name)}</td><td class="wrap">${esc(r.x.id)}</td>
          <td class="wrap mono">${esc(r.x.value)}</td>
          <td class="wrap muted">${esc(r.x.note || "")}</td></tr>`).join("")}</table>`
        : `<p class="muted" style="margin:0">没有驳回记录。</p>`}
      </div>
    </details>`;

  $$("#flagsWrap button[data-a]").forEach((b) => b.onclick = async () => {
    const a = b.dataset.a;
    if (a === "validate") doAction("case.candidate", { case_dir: chOf(b.dataset.ch).case.case_dir,
      candidate_id: b.dataset.id, candidate_status: "validated" });
    else if (a === "reject") doAction("case.candidate", { case_dir: chOf(b.dataset.ch).case.case_dir,
      candidate_id: b.dataset.id, candidate_status: "rejected", note: "人工驳回" });
    else if (a === "submit") {
      const ch = chOf(b.dataset.ch);
      const cand = ch.case.candidates.find((x) => x.id === b.dataset.id);
      openSubmitModal(ch, cand);
    }
  });

  api(`/api/autosubmit?dir=${encodeURIComponent(S.dir)}`).then((cfg) => {
    $("#autoSub").checked = cfg.enabled;
    $("#maxLive").value = cfg.max_live;
  }).catch(() => {});
  $("#autoSub").onchange = saveAutosubmit;
  $("#maxLive").onchange = saveAutosubmit;
  $("#hunterBtn").onclick = startHunter;
  $$("#flagsWrap [data-copy]").forEach((b) => b.onclick = () => copyText(b.dataset.copy, "flag"));
  if (hunterTimer) { clearTimeout(hunterTimer); hunterTimer = null; }
}

export async function saveAutosubmit() {
  const r = await fetch("/api/autosubmit", { method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ dir: S.dir, enabled: $("#autoSub").checked,
                           max_live: parseInt($("#maxLive").value, 10) || 3 }) })
    .then((x) => x.json()).catch((e) => ({ ok: false, error: String(e) }));
  if (r.ok) toast(`自动提交已${r.enabled ? "开启（上限 " + r.max_live + "/轮）" : "关闭"}`);
  else toast("保存失败：" + (r.error || "?"), true);
}

export async function startHunter() {
  $("#hunterBtn").disabled = true;
  $("#hunterState").textContent = "猎手派发中…";
  const r = await fetch("/api/hunter/start", { method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ dir: S.dir }) }).then((x) => x.json()).catch((e) => ({ ok: false, error: String(e) }));
  $("#hunterBtn").disabled = false;
  if (!r.ok) { $("#hunterState").textContent = ""; return toast(r.error || "派发失败", true); }
  const t = r.task;
  $("#hunterState").innerHTML = `任务 ${esc(t.id)} 运行中（agent: ${esc(t.agent)}）· <a href="#" id="hunterTail">查看实时输出</a>`;
  $("#hunterTail").onclick = (e) => { e.preventDefault(); TaskUI.selected = t.id; setTab("tasks"); };
  toast("Flag 猎手已派发 ✓");
  let ticks = 0;
  const poll = async () => {
    if ((localStorage.getItem("wb.tab") || "") !== "flags") return;
    ticks += 1;
    try {
      const tail = await api(`/api/task/tail?id=${encodeURIComponent(t.id)}`);
      if (tail.output) {
        $("#hunterDetails").classList.remove("hidden");
        $("#hunterDetails").open = true;
        $("#hunterOut").textContent = (tail.output || "").slice(-900);
      }
      if (tail.task.status === "running" && ticks < 40) {
        hunterTimer = setTimeout(poll, 2000);
      } else {
        $("#hunterState").innerHTML = `上次运行 ${esc(t.id)}：${esc(tail.task.status)}`;
        await loadCompetition();
        renderFlags();
        return;
      }
    } catch { /* 静默重试 */ }
    if (ticks < 40) hunterTimer = setTimeout(poll, 2000);
  };
  hunterTimer = setTimeout(poll, 1500);
}

export function openSubmitModal(ch, cand) {
  const chs = S.comp.challenges;
  const archived = S.comp.config?.platform?.migration?.status === "archived" ||
    S.comp.config?.platform?.submission_mode === "browser_ui";
  openModal(`
    <h3>Flag 提交 <span class="muted">submitter.py · 默认 dry-run</span></h3>
    <form id="subForm" class="grid">
      <label class="f">题目<select name="challenge">${chs.map((c) =>
        `<option value="${esc(c.slug)}" ${ch && ch.slug === c.slug ? "selected" : ""}>${esc(c.name)}</option>`).join("")}</select></label>
      <label class="f">flag（完整值）<input name="flag" value="${esc(cand?.value || "")}" required style="font-family:var(--mono)"></label>
      <label class="f">候选 ID<input name="candidate" value="${esc(cand?.id || "")}"></label>
      <label class="f">来源<select name="source"><option>workbench</option><option>manual</option></select></label>
      <label class="f">备注<input name="note"></label>
      <label class="f row"><input type="checkbox" name="allow_unvalidated"> 允许未校验候选（--allow-unvalidated）</label>
      <div class="full row">
        <button type="button" id="dryBtn" class="primary">1 · dry-run 预览</button>
        <button type="button" id="liveBtn" class="danger" disabled>${archived ? "请在迁移平台 UI 提交" : "2 · 确认真实提交 --live"}</button>
        <button type="button" id="cancelBtn">取消</button>
      </div>
      <div class="full"><pre class="out" id="subOut">${archived ? "（旧平台已归档：可查看 dry-run，但真实提交请在迁移平台浏览器 UI 完成）" : "（先执行 dry-run，确认平台响应与去重无误后再真实提交）"}</pre></div>
    </form>`);
  const f = $("#subForm");
  const collect = () => ({
    challenge: f.challenge.value, flag: f.flag.value,
    candidate: f.candidate.value || undefined, source: f.source.value,
    note: f.note.value || undefined, allow_unvalidated: f.allow_unvalidated.checked,
  });
  $("#cancelBtn").onclick = closeModal;
  $("#dryBtn").onclick = async () => {
    $("#subOut").textContent = "执行 dry-run …";
    const r = await post("submit.dryrun", { dir: S.dir, ...collect() });
    $("#subOut").textContent = `exit=${r.exit}\n` + (r.stdout || "") + (r.stderr ? "\n[stderr]\n" + r.stderr : "");
    $("#liveBtn").disabled = archived || r.exit !== 0;
    if (r.exit !== 0) toast("dry-run 未通过，请检查输出", true);
  };
  $("#liveBtn").onclick = async () => {
    if (archived) { toast("旧平台已归档：请在迁移平台浏览器 UI 提交，再用 submitter.py record 记录回执", true); return; }
    if (!confirm("确认真实提交到比赛平台？该操作会真正调用平台接口（受限速与去重保护）。")) return;
    const r = await post("submit.live", { dir: S.dir, ...collect(), confirm: true });
    $("#subOut").textContent = `exit=${r.exit}\n` + (r.stdout || "") + (r.stderr ? "\n[stderr]\n" + r.stderr : "");
    const slug = collect().challenge;
    if (r.exit === 0) { toast(`🎉 ${slug} 提交被接受 ✓`); await loadCompetition(); }
    else toast(`${slug} 提交未通过（outcome 非 accepted），详见输出`, true);
  };
}

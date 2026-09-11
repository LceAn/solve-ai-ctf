/* ---------------- ⑩ 成就 ---------------- */
import { S } from "../state.js";
import { $, esc, toast } from "../ui.js";
import { api } from "../api.js";

let META = null;

async function ensureMeta() {
  if (META) return META;
  try {
    const r = await fetch("/static/achievements.meta.json");
    META = await r.json();
  } catch (e) {
    META = { rules: {}, categories: {} };
  }
  return META;
}

function parseMeta(metaStr) {
  try { return JSON.parse(metaStr || "{}"); } catch (e) { return {}; }
}

export async function renderAchievements() {
  const body = $("#achievementsBody");
  if (!S.comp) { body.innerHTML = "<p class='muted'>没有可用的比赛目录。</p>"; return; }
  body.innerHTML = `
    <div class="ach-grid">
      ${Array.from({ length: 5 }, () => `<div class="skeleton skeleton-card" style="height:140px"></div>`).join("")}
    </div>`;
  await loadAndRender();
}

async function loadAndRender() {
  const body = $("#achievementsBody");
  if (!body || !S.dir) return;
  const meta = await ensureMeta();
  try {
    const r = await api(`/api/achievements?dir=${encodeURIComponent(S.dir)}`);
    const unlocked = (r.achievements || []);
    const rules = meta.rules || {};
    const ruleKeys = Object.keys(rules);
    // 按规则聚合
    const byRule = {};
    for (const a of unlocked) {
      byRule[a.rule] = byRule[a.rule] || [];
      byRule[a.rule].push(a);
    }
    const cards = ruleKeys.map((ruleKey) => {
      const meta_info = rules[ruleKey] || { icon: "🏅", label: ruleKey, desc: "" };
      const items = byRule[ruleKey] || [];
      const isUnlocked = items.length > 0;
      const latest = items[items.length - 1];
      const metaDetail = latest ? parseMeta(latest.meta) : {};
      const detailStr = (() => {
        if (!latest) return "";
        if (ruleKey === "first_blood") return `首次解出 ${metaDetail.challenge_slug || "—"}`;
        if (ruleKey === "full_category_clear") return `${metaDetail.category || ""} 类别（${metaDetail.count || 0} 题）`;
        if (ruleKey === "speedrun") return `${metaDetail.minutes ?? "—"} 分钟`;
        if (ruleKey === "zero_false_positive") return `${metaDetail.validated_count || 0} 个 validated 候选`;
        if (ruleKey === "streak") return `连续通关 ${metaDetail.streak || 0} 题`;
        return "";
      })();
      return `
        <div class="ach-card ${isUnlocked ? "unlocked" : "locked"}" aria-label="${esc(meta_info.label)} ${isUnlocked ? "已解锁" : "未解锁"}">
          <div class="ach-icon" aria-hidden="true">${esc(meta_info.icon)}</div>
          <div class="ach-title">${esc(meta_info.label)}</div>
          <div class="ach-desc">${esc(meta_info.desc)}</div>
          ${isUnlocked ? `
            <div class="ach-meta" title="${esc(latest.unlocked_at || "")}">✓ ${esc(latest.unlocked_at || "")}
              ${detailStr ? ` · ${esc(detailStr)}` : ""}</div>
          ` : `<div class="ach-meta muted">未解锁</div>`}
        </div>`;
    }).join("");
    const total = unlocked.length;
    const totalRules = ruleKeys.length;
    body.innerHTML = `
      <div class="panel" style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
        <div style="font-size:34px;font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums">${total}<small style="font-size:14px;color:var(--muted);font-weight:400">/${totalRules}</small></div>
        <div>
          <div style="font-weight:600">已获得徽章</div>
          <div class="muted">${total === totalRules ? "🎯 全部训练徽章已获得！" : "继续训练获得更多徽章"}</div>
        </div>
        <div style="flex:1;min-width:120px">
          <div class="progress" style="margin:0"><i style="width:${totalRules ? Math.round(total/totalRules*100) : 0}%"></i></div>
        </div>
        <button id="achCheck" class="small" aria-label="重新检查成就">重新检查</button>
      </div>
      <div class="ach-grid">${cards}</div>`;
    const btn = $("#achCheck");
    if (btn) btn.onclick = async () => {
      btn.disabled = true;
      try {
        const { post } = await import("../api.js");
        const r = await post("achievement.check", { dir: S.dir });
        if (r.ok) {
          const newCount = (r.stdout || "").match(/unlocked\s+(\d+)/);
          toast(`成就检查完成${newCount ? ` · 新解锁 ${newCount[1]} 个` : " ✓"}`, "ok");
          await loadAndRender();
        } else {
          toast(`成就检查失败：${r.error || "exit=" + r.exit}`, true);
        }
      } catch (e) { toast("检查失败：" + e.message, true); }
      btn.disabled = false;
    };
  } catch (e) {
    body.innerHTML = `<div class="panel" style="color:var(--red)">加载失败：${esc(e.message)}<br><span class="muted">提示：首次使用需运行 leaderboard.py init（server 会自动初始化）</span></div>`;
  }
}

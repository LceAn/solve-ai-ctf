/* ---------------- ⑨ 训练进度仪表盘（非竞技排行榜） ----------------
 * 平台定位：CTF 解题训练系统。本视图不再展示多队伍排名/首血/动态评分竞争，
 * 而是聚合 operator 的训练进度：六维技能雷达 / 类别覆盖率 / 近 7 天活跃。
 * 数据源：/api/leaderboard 返回的 progress 字段（by_operator / by_category /
 * coverage / recent_activity / skill_axes / operator_skill）。
 */
import { S } from "../state.js";
import { $, $$, esc, toast } from "../ui.js";
import { api } from "../api.js";

const SIX_AXES = ["crypto", "pwn", "web", "reverse", "misc", "forensics"];
const CAT_ICON = {
  crypto: "🔐", pwn: "💥", web: "🌐", reverse: "🔍", misc: "🧩", forensics: "🧬",
};
const CAT_LABEL = {
  crypto: "Crypto", pwn: "Pwn", web: "Web", reverse: "Reverse",
  misc: "Misc", forensics: "Forensics",
};

export async function renderLeaderboard() {
  const body = $("#leaderboardBody");
  if (!S.comp) {
    body.innerHTML = "<p class='muted'>没有可用的训练目录。</p>";
    return;
  }
  // 骨架屏占位
  body.innerHTML = `
    <div class="lb-layout">
      <div class="col-main">
        <div class="skeleton skeleton-card" style="height:160px"></div>
        <div class="skeleton skeleton-line"></div>
        <div class="skeleton skeleton-line mid"></div>
      </div>
      <div class="lb-side col-side">
        <div class="skeleton skeleton-card" style="height:280px"></div>
      </div>
    </div>`;
  await loadProgress();
}

async function loadProgress() {
  const body = $("#leaderboardBody");
  if (!body || !S.dir) return;
  try {
    const r = await api(`/api/leaderboard?dir=${encodeURIComponent(S.dir)}&mode=individual`);
    const progress = r.progress || {};
    S.lbProgress = progress;
    S.lbOperator = S.lbOperator || (progress.by_operator?.[0]?.id || "");
    renderDashboard(body, progress);
  } catch (e) {
    body.innerHTML = `<div class="panel" style="color:var(--red)">加载失败：${esc(e.message)}</div>`;
  }
}

function renderDashboard(body, progress) {
  const byOp = progress.by_operator || [];
  const byCat = progress.by_category || [];
  const coverage = progress.coverage || { solved_challenges: 0, total_challenges: 0, ratio: 0 };
  const recent = progress.recent_activity || [];
  const skill = progress.operator_skill || {};
  const axes = progress.skill_axes?.length ? progress.skill_axes : SIX_AXES;

  if (!byOp.length) {
    body.innerHTML = `
      <div class="empty">
        <div class="big">📈</div>
        <strong>训练进度尚未建立</strong>
        <div class="muted">第一个 live accepted 提交后将在这里生成你的技能雷达与覆盖率统计。</div>
      </div>`;
    return;
  }

  const currentOp = S.lbOperator && byOp.some((o) => o.id === S.lbOperator)
    ? S.lbOperator
    : byOp[0].id;
  S.lbOperator = currentOp;
  const opSkill = skill[currentOp] || {};
  const opInfo = byOp.find((o) => o.id === currentOp) || {};

  body.innerHTML = `
    <div class="panel" style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">
      <div style="font-size:34px;font-weight:700;color:var(--accent);font-variant-numeric:tabular-nums">
        ${coverage.solved_challenges}<small style="font-size:14px;color:var(--muted);font-weight:400">/${coverage.total_challenges}</small>
      </div>
      <div>
        <div style="font-weight:600">训练覆盖率</div>
        <div class="muted">已 accepted 题 / 全部注册题 · ${(coverage.ratio * 100).toFixed(1)}%</div>
      </div>
      <div style="flex:1;min-width:120px">
        <div class="progress" style="margin:0"><i style="width:${(coverage.ratio * 100).toFixed(1)}%"></i></div>
      </div>
      <div style="text-align:right">
        <div style="font-weight:600">${byOp.length} 位活跃</div>
        <div class="muted">operator</div>
      </div>
      <button id="lbRefresh" class="small" aria-label="刷新训练进度">刷新</button>
    </div>

    <div class="lb-layout">
      <div class="col-main">
        <div class="panel">
          <h3>技能雷达 · <span style="color:var(--accent)">${esc(currentOp)}</span></h3>
          <p class="muted" style="margin:0 0 12px">六维技能分布（每维 = 该方向已 accepted 题数）。</p>
          ${renderRadarSvg(axes, opSkill, byCat)}
          <div class="row" style="gap:12px;flex-wrap:wrap;margin-top:12px">
            ${axes.map((ax) => {
              const v = opSkill[ax] || 0;
              const cat = byCat.find((c) => c.category === ax) || {};
              const total = cat.total || 0;
              return `<div class="badge" style="--b-c:var(--muted)">
                <span aria-hidden="true">${CAT_ICON[ax] || "•"}</span>
                ${esc(CAT_LABEL[ax] || ax)}：<b>${v}</b>${total ? ` / ${total}` : ""}
              </div>`;
            }).join("")}
          </div>
        </div>

        <div class="panel">
          <h3>类别覆盖率</h3>
          <table aria-label="类别覆盖率">
            <thead><tr><th>方向</th><th>已解出</th><th>总题数</th><th>覆盖率</th><th>参与者</th></tr></thead>
            <tbody>
              ${byCat.map((c) => {
                const pct = (c.coverage * 100).toFixed(1);
                const weak = c.total > 0 && c.coverage === 0;
                return `<tr ${weak ? 'style="color:var(--yellow)"' : ""}>
                  <td><span class="cat-dot" style="background:var(--accent)"></span>${CAT_ICON[c.category] || "•"} ${esc(CAT_LABEL[c.category] || c.category)}</td>
                  <td class="mono">${c.solved}</td>
                  <td class="mono">${c.total}</td>
                  <td>
                    <div class="progress" style="margin:0;min-width:120px"><i style="width:${pct}%"></i></div>
                    <small class="muted">${pct}%</small>
                  </td>
                  <td>${(c.operators || []).length}</td>
                </tr>`;
              }).join("")}
            </tbody>
          </table>
          <p class="muted" style="margin:8px 0 0">标黄的类别为完全未解出方向——建议作为下一阶段训练重点。</p>
        </div>
      </div>

      <div class="lb-side col-side">
        <div class="panel">
          <h3>operator 训练记录</h3>
          <p class="muted" style="margin:0 0 8px">点击切换雷达图聚焦。</p>
          <div class="lb-op-list" role="list">
            ${byOp.map((o) => {
              const on = o.id === currentOp;
              return `<button class="lb-op-item ${on ? "on" : ""}" data-op="${esc(o.id)}" role="listitem"
                aria-pressed="${on}" aria-label="${esc(o.id)} 训练记录">
                <div class="lb-op-name">${esc(o.id)}</div>
                <div class="lb-op-stats">
                  <span title="解出题数">✓ ${o.solves || 0}</span>
                  <span title="首次突破">🌟 ${o.first_clears || 0}</span>
                  <span title="累计训练分">${(o.points || 0).toFixed(0)}pt</span>
                </div>
              </button>`;
            }).join("")}
          </div>
        </div>

        <div class="panel">
          <h3>近 7 天活跃</h3>
          <div class="lb-heatmap" aria-label="近 7 天训练活跃热力图">
            ${recent.map((d) => {
              const lvl = d.count === 0 ? 0 : d.count < 2 ? 1 : d.count < 4 ? 2 : 3;
              return `<div class="hm-cell hm-l${lvl}" title="${esc(d.day)}：${d.count} 次 accepted">
                <div class="hm-bar" style="height:${10 + lvl * 22}px"></div>
                <span class="hm-label">${esc(d.day.slice(5))}</span>
                <span class="hm-count">${d.count}</span>
              </div>`;
            }).join("")}
          </div>
          <p class="muted" style="margin:8px 0 0">柱高代表当日 accepted 频次，训练连续性比单日峰值更重要。</p>
        </div>
      </div>
    </div>`;

  const refresh = $("#lbRefresh");
  if (refresh && !refresh.dataset.bound) {
    refresh.dataset.bound = "1";
    refresh.onclick = () => loadProgress().then(() => toast("训练进度已刷新", "ok"));
  }
  $$("#leaderboardBody .lb-op-item").forEach((b) => b.onclick = () => {
    S.lbOperator = b.dataset.op;
    const p = S.lbProgress || {};
    renderDashboard(body, p);
  });
}

/**
 * 纯 SVG 雷达图（无第三方依赖）。
 * @param {string[]} axes - 六维轴名
 * @param {Object<string, number>} skill - {axis: count}
 * @param {Object[]} byCat - [{category, total}] 用于归一化
 */
function renderRadarSvg(axes, skill, byCat) {
  const W = 320, H = 280, cx = W / 2, cy = H / 2 + 6;
  const R = 100;
  const rings = 4;
  const angle = (i) => (-90 + i * (360 / axes.length)) * Math.PI / 180;
  const pt = (i, r) => [cx + r * Math.cos(angle(i)), cy + r * Math.sin(angle(i))];
  // 归一化：每维最大值 = 该类别的 total（若有）或所有 operator 中该维最大值
  const maxByAxis = {};
  axes.forEach((ax, i) => {
    const cat = byCat.find((c) => c.category === ax);
    const total = cat?.total || 0;
    const v = skill[ax] || 0;
    // 归一化基准 = max(total, v, 1)，避免 0 除
    maxByAxis[ax] = Math.max(total, v, 1);
  });

  // 同心多边形网格
  let grid = "";
  for (let k = 1; k <= rings; k++) {
    const r = (R * k) / rings;
    const pts = axes.map((_, i) => pt(i, r).join(",")).join(" ");
    grid += `<polygon points="${pts}" fill="none" stroke="var(--border)" stroke-width="1" opacity="${0.3 + k * 0.15}"/>`;
  }
  // 轴线 + 标签
  let axesSvg = "";
  axes.forEach((ax, i) => {
    const [x, y] = pt(i, R + 14);
    const [lx, ly] = pt(i, R);
    axesSvg += `<line x1="${cx}" y1="${cy}" x2="${lx}" y2="${ly}" stroke="var(--border)" stroke-width="1" opacity="0.5"/>`;
    const anchor = Math.abs(x - cx) < 4 ? "middle" : (x > cx ? "start" : "end");
    axesSvg += `<text x="${x}" y="${y}" text-anchor="${anchor}" dominant-baseline="middle"
      font-size="12" fill="var(--text)" opacity="0.85">${CAT_ICON[ax] || ""} ${esc(CAT_LABEL[ax] || ax)}</text>`;
  });
  // 数据多边形
  const dataPts = axes.map((ax, i) => {
    const v = skill[ax] || 0;
    const r = R * (v / maxByAxis[ax]);
    return pt(i, r).join(",");
  }).join(" ");
  // 顶点圆点
  let dots = "";
  axes.forEach((ax, i) => {
    const v = skill[ax] || 0;
    const r = R * (v / maxByAxis[ax]);
    const [x, y] = pt(i, r);
    if (v > 0) dots += `<circle cx="${x}" cy="${y}" r="3" fill="var(--accent)"/>`;
  });

  return `
    <svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(S.lbOperator || "")} 技能雷达图"
      style="width:100%;max-width:${W}px;display:block;margin:0 auto">
      ${grid}
      ${axesSvg}
      <polygon points="${dataPts}" fill="var(--accent)" fill-opacity="0.18"
               stroke="var(--accent)" stroke-width="2" stroke-linejoin="round"/>
      ${dots}
    </svg>`;
}

"use strict";
/* ── 조위 — 해양조사원 조위관측소, 레이어 '조위'(O) ────────────────────────────────
   서버가 받아 둔 것(/api/tide)을 그린다. 해안 표식(실측 · 예측과의 차이), 마우스를 올리면 요약 툴팁, 누르면 그 자리에 팝업(게이지 + 물결).
   단계는 해양조사원 고조정보 4단계(삼천포 · 부산항신항은 기준이 없어 값만). 대조기는 서버가 예측 조위로 계산한 값. */
let TID = null, TID_T = 0, TID_HIT = [], TID_OPEN = null;
const tdColOf = (s, n) => (n == null ? "var(--ink-3)" : RV_C[s.col[n]]);
const tdHigh = () => (TID?.rows || []).filter(s => (s.stage || 0) >= 1);
const tdCol = () => { const h = tdHigh().sort((a, b) => b.col[b.stage] - a.col[a.stage])[0]; return h ? tdColOf(h, h.stage) : ""; };
const tdHm = t => (t ? `${t.slice(8, 10)}:${t.slice(10, 12)}` : "—");
const tdDay = t => `${+t.slice(4, 6)}.${+t.slice(6, 8)}`;
const tdIso = d => `${+d.slice(5, 7)}.${+d.slice(8, 10)}`;
const tdCm = v => `${+v.toFixed(1)} cm`;
function tdSpringChip() {
  const sp = TID?.spring;
  if (!sp) return "";
  return sp.now ? `<span class="tsp" title="예측 조위로 계산한 값 — 공식 날짜와 다를 수 있다">대조기 ~${tdIso(sp.to)}</span>` : "";
}
async function loadTide() {
  clearTimeout(TID_T);
  if (!OV.has("tide") || CASE) { TID = null; tidePop(null); drawTide(); renderTideLegend(); renderLyIcons(); return; }
  try { TID = await getJson("/api/tide"); } catch (e) { TID = { err: e.message }; }
  drawTide(); renderTideLegend(); renderLyIcons();
  TID_T = setTimeout(loadTide, 5 * 60 * 1000);
}
function drawTide() {
  const g = $("tidr");
  if (!g) return;
  TID_HIT = [];
  if (!OV.has("tide") || !V || !V.s || !TID?.rows) { g.innerHTML = ""; return; }
  const fs = Math.max(10.5, Math.min(14, V.u * 2.3));
  g.innerHTML = TID.rows.filter(s => s.x != null).map(s => {
    const x = V.toX(s.x), y = V.toY(s.y), val = `${Math.round(s.v)}${s.diff != null ? ` (${s.diff >= 0 ? "+" : ""}${s.diff.toFixed(1)})` : ""}`;
    const w = Math.max(s.name.length * fs * 1.05, val.length * fs * 0.64) + 10, h = fs * 2.7;
    const bx = x - w / 2, by = y + 5;                       // 관측소 바로 아래(바다 쪽)
    TID_HIT.push({ x0: bx, x1: bx + w, y0: by, y1: by + h, s });
    return `<g class="td"><rect x="${bx.toFixed(1)}" y="${by.toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="5" style="stroke:${tdColOf(s, s.stage)}"/>`
      + `<text class="n" x="${x.toFixed(1)}" y="${(by + h * 0.3).toFixed(1)}" style="font-size:${(fs * 0.92).toFixed(1)}px">${escH(s.name)}</text>`
      + `<text class="v" x="${x.toFixed(1)}" y="${(by + h * 0.72).toFixed(1)}" style="font-size:${fs.toFixed(1)}px">${escH(val)}</text></g>`;
  }).join("");
}
function tideAt(mx, my) {
  if (!OV.has("tide")) return null;
  return TID_HIT.find(h => mx >= h.x0 && mx <= h.x1 && my >= h.y0 && my <= h.y1)?.s || null;
}
const tdDiffText = s => (s.diff == null ? "" : `예측 ${s.pred}보다 ${Math.abs(s.diff)} ${s.diff >= 0 ? "높음" : "낮음"}`);
const tdNext = s => {
  if (s.stage == null) return "";
  return s.stage < s.cuts.length ? `${s.names[s.stage + 1]}까지 ${tdCm(s.cuts[s.stage] - s.v)}` : `${s.names.at(-1)} 넘음`;
};
function tideTip(s) {
  return `<b>${escH(s.name)} ${tdCm(s.v)}</b>${s.stage != null ? ` · ${s.names[s.stage]}` : ""}`
    + `<div class="d">${tdDiffText(s)}${s.stale ? " · ⚠ 오래된 값" : ""}</div>`
    + (s.next ? `<div class="d">다음 만조 ${tdHm(s.next.t)} · ${tdCm(s.next.h)}</div>` : "") + `<div class="d">누르면 자세히</div>`;
}
/* 반원 게이지 — 단계 띠에 단계 이름 · 수치를 적고 바늘이 지금 값을 가리킨다 */
function tdGauge(s) {
  if (!s.cuts.length) return "";
  const top = s.cuts.at(-1), max = Math.max(top * 1.14, s.v * 1.04), cx = 150, cy = 128, R = 92;
  const ang = v => -90 + Math.max(0, Math.min(v, max)) / max * 180;
  const pt = (r, a) => { const t = (a - 90) * Math.PI / 180; return [cx + r * Math.cos(t), cy + r * Math.sin(t)]; };
  const ed = [0, ...s.cuts, max];
  const arcs = ed.slice(0, -1).map((a, i) => {
    const [x0, y0] = pt(R, ang(a)), [x1, y1] = pt(R, ang(ed[i + 1]) - .8);
    return `<path d="M${x0.toFixed(1)} ${y0.toFixed(1)}A${R} ${R} 0 0 1 ${x1.toFixed(1)} ${y1.toFixed(1)}" fill="none" stroke="${RV_C[s.col[i]]}" stroke-width="14"/>`;
  }).join("");
  const labs = s.cuts.map((c, i) => {
    const [x, y] = pt(R + 22 - (s.cuts.length > 2 && i === 0 ? 0 : 0), ang(c));
    const an = x < cx - 10 ? "end" : x > cx + 10 ? "start" : "middle";
    return `<text x="${x.toFixed(1)}" y="${(y - 2).toFixed(1)}" font-size="11" text-anchor="${an}" fill="var(--ink-2)">${s.names[i + 1]} ${c}</text>`;
  }).join("");
  const [nx, ny] = pt(R - 18, ang(s.v));
  return `<svg viewBox="0 0 300 140" role="img" aria-label="조위 게이지">${arcs}${labs}<line x1="${cx}" y1="${cy}" x2="${nx.toFixed(1)}" y2="${ny.toFixed(1)}" stroke="var(--ink)" stroke-width="2.6" stroke-linecap="round"/><circle cx="${cx}" cy="${cy}" r="5" fill="var(--ink)"/></svg>`;
}
/* 물결 — 점선 예측 · 실선 실측, 지금 줄, 다음 만조 점, 가장 낮은 기준선 */
function tdWave(s) {
  const a = s.series || [];
  if (a.length < 3) return "";
  const W = 300, H = 78, top = 8, bot = 66;
  const vals = a.flatMap(x => [x[1], x[2]]).filter(v => v != null), lo0 = Math.min(...vals), hi0 = Math.max(...vals);
  const cut = s.cuts.find(c => c >= hi0 * 0.85 && c <= hi0 * 1.25);
  const lo = lo0, hi = Math.max(hi0, cut ?? hi0), sp = hi - lo || 1;
  const X = i => i / (a.length - 1) * W, Y = v => bot - (v - lo) / sp * (bot - top);
  const line = k => { let d = "", on = false; a.forEach((p, i) => { if (p[k] == null) { on = false; return; } d += `${on ? "L" : "M"}${X(i).toFixed(1)} ${Y(p[k]).toFixed(1)}`; on = true; }); return d; };
  const stamp = tdYmd(new Date()), nowI = a.findLastIndex(p => p[0] <= stamp);
  const ni = s.next ? a.findIndex(p => p[0] >= s.next.t.slice(0, 11) + "0".repeat(1)) : -1;
  const nx = ni >= 0 ? X(ni) : null, ny = s.next ? Y(s.next.h) : 0, ncol = s.next ? tdColOf(s, s.next.stage) : "";
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="조위 물결" style="margin:6px 0 2px">`
    + (cut != null ? `<line x1="0" x2="${W}" y1="${Y(cut).toFixed(1)}" y2="${Y(cut).toFixed(1)}" stroke="${RV_C[s.col[s.cuts.indexOf(cut) + 1]]}" stroke-width=".9" stroke-dasharray="2 3"/><text x="${W - 2}" y="${(Y(cut) + 11).toFixed(1)}" text-anchor="end" font-size="11" fill="var(--ink-3)">${s.names[s.cuts.indexOf(cut) + 1]} ${cut}</text>` : "")
    + `<path d="${line(2)}" fill="none" stroke="var(--ink-3)" stroke-width="1.5" stroke-dasharray="4 3"/><path d="${line(1)}" fill="none" stroke="var(--accent)" stroke-width="2.2"/>`
    + (nowI >= 0 ? `<line x1="${X(nowI).toFixed(1)}" x2="${X(nowI).toFixed(1)}" y1="4" y2="${bot + 2}" stroke="var(--ink-3)" stroke-width=".6"/><text x="${(X(nowI) + 4).toFixed(1)}" y="13" font-size="11" fill="var(--ink-3)">지금</text>` : "")
    + (nx != null ? `<circle cx="${nx.toFixed(1)}" cy="${ny.toFixed(1)}" r="3.5" fill="${ncol}"/><text x="${Math.min(W - 30, Math.max(30, nx)).toFixed(1)}" y="${H - 2}" text-anchor="middle" font-size="11" fill="var(--ink-3)">${tdHm(s.next.t)} 만조</text>` : "")
    + `</svg>`;
}
const tdYmd = d => `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}${String(d.getHours()).padStart(2, "0")}${String(d.getMinutes()).padStart(2, "0")}`;
const tdTag = (s, h) => (h.stage == null ? "" : `<span class="tg" style="background:${tdColOf(s, h.stage)}">${s.names[h.stage]}</span>`);
function tidePopHtml(s) {
  const sp = TID?.spring, low = s.facil?.[0];
  TIPS.set("td-info", `<b>조위</b> 바닷물 높이. 조위관측소가 잰 값이고, 기본수준면(가장 낮은 해수면)이 0 이다.<br>
    <b>실선 · 점선</b> 실선은 실측, 점선은 달과 해의 힘으로 계산한 예측.<br>
    <b>예측보다 13.5 높음</b> 지금 바다가 계산보다 그만큼 높다는 뜻. 저기압이나 바람이 밀어 올렸을 수 있다. 호우 · 태풍 때 커지면 주의.<br>
    <b>만조</b> 하루 두 번쯤 오는 가장 높은 때. 큰비와 겹치면 빗물이 바다로 잘 빠지지 않아 저지대가 잠기기 쉽다.<br>
    <b>대조기</b> 보름 · 그믐 무렵 만조가 유난히 높아지는 며칠. 여기 날짜는 예측 조위로 계산해 공식 발표와 다를 수 있다.<br>
    <b>단계</b> ${s.scale ? "해양조사원 고조정보 — 관심: 감시 필요 · 주의: 침수 가능성 있음 · 경계: 가능성 높음 · 위험: 매우 높음. 폭풍해일 특보와는 다른 체계다."
      : "이 지점은 기준이 없어 값만 보인다."}${s.name === "마산" ? `<br>
    <b>창원(마산 · 진해) 구역</b> 해양조사원이 마산 관측소 하나로 묶은 시설이다. 진해 용원은 그 구역에 들지만 실제로는 부산항신항 관측소가 더 가깝다 — 그쪽 표식도 함께 본다.` : ""}${s.facil?.length ? `<br>
    <b>시설 높이</b> 시설의 가장 낮은 지반고(cm, 조위와 같은 기준). 만조가 이 높이에 닿으면 그 시설부터 잠길 수 있다.` : ""}`);
  return `<div class="h"><b>${escH(s.name)} 조위</b><i class="inf" data-tip="td-info" aria-label="조위 설명">i</i><span>${tdHm(s.t)}${s.sigun.length ? ` · ${s.sigun.join(" · ")}` : ""}${s.stale ? " · ⚠ 오래된 값" : ""}</span><i class="x" data-x title="닫기">✕</i></div>`
    + tdGauge(s)
    + `<div class="tnow"><b>${tdCm(s.v)}</b><div>${[tdDiffText(s), tdNext(s)].filter(Boolean).join(" · ")}</div></div>`
    + tdWave(s)
    + (s.next ? `<div class="tr"><span>다음 만조</span><span><b>${tdHm(s.next.t)} · ${tdCm(s.next.h)}</b>${tdTag(s, s.next)}</span></div>` : "")
    + (s.top ? `<div class="tr"><span>7일 안 최고 만조</span><span><b>${tdDay(s.top.t)} ${tdHm(s.top.t)} · ${tdCm(s.top.h)}</b>${tdTag(s, s.top)}</span></div>` : "")
    + (sp ? `<div class="tr"><span>대조기(계산)</span><b class="s">${sp.now ? `지금 — ${tdIso(sp.to)}까지` : `아님 · 다음 ${tdIso(sp.from)}~${tdIso(sp.to)}`}</b></div>` : "")
    + (low ? `<div class="tr"><span>${s.wet?.length ? "7일 안 만조가 닿는 곳" : "먼저 잠기는 곳"}${s.name === "마산" ? "(마산 · 진해 구역)" : ""}</span><b class="s">${s.wet?.length ? escH(s.wet.join(" · ")) : `${escH(low.name)} ${low.h}`}</b></div>` : "")
    + (s.scale ? `<div class="nt">눈금: 해양조사원 고조정보</div>` : "");
}
function tidePop(s, x, y) {
  let pop = $("td-pop");
  if (!s) { TID_OPEN = null; if (pop) pop.hidden = true; return; }
  if (!pop) {
    pop = document.createElement("div");
    pop.id = "td-pop";
    $("stage").appendChild(pop);
    pop.addEventListener("click", ev => { if (ev.target.closest("[data-x]")) tidePop(null); });
  }
  TID_OPEN = s.code;
  pop.innerHTML = tidePopHtml(s);
  pop.hidden = false;
  const r = $("stage").getBoundingClientRect(), rail = $("rail")?.getBoundingClientRect();
  const right = rail?.width ? rail.left - r.left - 8 : r.width - 8;       // 오른쪽 패널을 덮지 않게
  const w = pop.offsetWidth, h = pop.offsetHeight;
  const left = x + 14 + w <= right ? x + 14 : Math.max(8, x - 14 - w);
  pop.style.left = left + "px";
  pop.style.top = Math.max(8, Math.min(y - h / 2, r.height - h - 8)) + "px";
}
function renderTideLegend() {
  const box = $("ly-tide");
  if (!box) return;
  if (!OV.has("tide")) { box.hidden = true; return; }
  box.hidden = LY_OPEN !== "tide";
  if (box.hidden) return;
  let body;
  if (!TID) body = `<div class="nt">읽는 중…</div>`;
  else if (TID.err && !TID.rows?.length) body = `<div class="nt w">불러오지 못했다 — ${escH(TID.err)}</div>`;
  else if (!TID.on) body = `<div class="nt w">${TID.demo ? "시연 서버는 조위를 받지 않는다." : "키가 없다 — 설정 › 시스템 › API 키 › 공공데이터포털."}</div>`;
  else if (!TID.rows?.length) body = `<div class="nt">첫 수집을 기다린다.</div>`;
  else {
    const sp = TID.spring;
    body = TID.rows.map(s => `<div class="rr" data-c="${s.code}"><b>${escH(s.name)}</b><span>${Math.round(s.v)}${s.diff != null ? ` ${s.diff >= 0 ? "+" : ""}${s.diff.toFixed(1)}` : ""}</span><em>${s.next ? `만조 ${tdHm(s.next.t)} ${Math.round(s.next.h)}cm` : ""}</em></div>`).join("")
      + (sp ? `<div class="nt" style="margin-top:6px">대조기(계산): ${sp.now ? `지금 — ${tdIso(sp.to)}까지` : `다음 ${tdIso(sp.from)}~${tdIso(sp.to)}`}</div>` : "");
  }
  box.innerHTML = `<div class="hd2" title="눌러서 닫기"><b>조위</b><i class="inf" data-tip="ov-tide">i</i><span>${TID?.at ? TID.at.slice(11, 16) : ""}</span></div>${body}`;
  box.querySelector(".hd2").onclick = ev => { if (!ev.target.closest(".inf")) setLyOpen(null); };
  for (const r of box.querySelectorAll("[data-c]")) r.onclick = () => {
    const s = TID.rows.find(x => x.code === r.dataset.c), h = TID_HIT.find(x => x.s.code === s.code);
    if (h) tidePop(s, h.x1 * MT.sc + MT.tx, h.y0 * MT.sc + MT.ty);
  };
}

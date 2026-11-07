"use strict";
/* ── 상황판단 차트 — 지구마다 지금부터 내일 24시까지 '가장 높은 단계 %' 줄(가로 시간 · 세로 %) + 재생 ─────────────
   점 = 재생 위치 시각의 그 지구(배지: 색 = 위험도 · 그림 = 유형, 지도 '우려지역 지구' 레이어와 같다). 100% 선을 넘는 곳 = 도달 시각.
   거르개: 위 '% 이상'(지금 % 또는 앞으로 최고 %) · 유형 · 시군(경남 전체일 때) · 줄 보이기. 재생하면 지도 창 배지 색도 그 시각으로(BroadcastChannel).
   자료: /api/judge?series=1 의 b[기준].series {t: 시각들, v: %들} — 서버 judge.series_of. 앞쪽만(지난 시간은 그리지 않는다). */
const SJP_FAM = ["산사태", "하천", "지하공간"];
const SJP = { t: 0, play: 0, lines: true, by: "max", fam: new Set(SJP_FAM), off: new Set(), mode: "line", stage: "긴급대피", tc: false };
/* 유형이 둘 이상 보일 때는 배지 · 줄 색 = 유형(위험도는 자리 · 오른쪽 위 칸이 말한다). 밝은 색 — 어두운 바탕 */
const SJP_FC = { 산사태: "#FF9F43", 하천: "#2ED6F5", 지하공간: "#C084FC", "침수·해안": "#60A5FA", "야외·기타": "#E5E7EB" };
const sjpMany = rows => new Set(rows.map(x => x.r.fam)).size > 1;
const sjpBadge = (r, p, many) => (many ? dzBadgeUrl(r.fam, 0, SJP_FC[r.fam] || SJP_FC["야외·기타"]) : dzBadgeUrl(r.fam, dzLv(p)));
try { const o = JSON.parse(localStorage.getItem("gn-sj-plot") || "{}"); for (const k of ["by", "lines", "mode", "stage", "tc"]) if (o[k] != null) SJP[k] = o[k]; } catch {}
{ const q = new URLSearchParams(location.search); if (q.get("pm") === "plane" || q.get("pm") === "line") SJP.mode = q.get("pm"); if (SJ_STG.includes(q.get("pg"))) SJP.stage = q.get("pg"); }   // ?pm=plane&pg=통제 — 바로 그 그림으로
const sjpSave = () => { try { localStorage.setItem("gn-sj-plot", JSON.stringify({ by: SJP.by, lines: SJP.lines, mode: SJP.mode, stage: SJP.stage, tc: SJP.tc })); } catch {} };
/* 조건 평면 — 그 시각의 (가로 누적 %, 세로 시간당 %) 과 그 단계 %(둘 중 작은 것 — '그리고') */
const sjpXY = (r, i) => { const a = sjB(r)?.series?.xy?.[SJP.stage]; return a ? a[Math.min(i, a.length - 1)] : null; };
const sjpStageP = xy => (xy ? Math.min(xy[0] ?? 0, xy[1] ?? 0) : null);
const sjpSer = r => { const b = sjB(r); return [b.top, ...(b.series?.v || [])]; };
const sjpT = () => ["지금", ...((SJ.d?.rows || []).map(r => sjB(r)?.series?.t).filter(Boolean).sort((a, b) => b.length - a.length)[0] || [])];
function sjpRows() {
  return (SJ.d?.rows || []).filter(r => r.b[SJ.basis] && SJP.fam.has(r.fam) && !SJP.off.has(r.sigun))
    .map(r => ({ r, v: sjpSer(r) }))
    .filter(x => !SJ.cut.on || (SJP.by === "max" ? Math.max(...x.v) : x.v[0]) >= SJ.cut.pct);
}
function sjpPlane(T, rows) {
  const W = 1000, H = 380, L = 56, R = 160, TP = 14, B = 38, n = T.length, t = Math.min(SJP.t, n - 1);
  const pts = rows.map(x => ({ ...x, xy: sjpXY(x.r, t) })).filter(x => x.xy);
  if (!pts.length) return `<p class="mute">${escH(SJP.stage)} 기준의 조건 값이 있는 지구가 없다</p>`;
  const all = rows.flatMap(x => (sjB(x.r).series?.xy?.[SJP.stage] || []).filter(Boolean).flat()).filter(v => v != null);
  const m = Math.min(300, Math.max(150, Math.ceil(Math.max(...all, 0) / 50) * 50));
  const X = p => L + Math.min(p ?? 0, m) / m * (W - L - R), Y = p => TP + (1 - Math.min(p ?? 0, m) / m) * (H - TP - B);
  let g = `<rect class="q11" x="${X(100)}" y="${TP}" width="${X(m) - X(100)}" height="${Y(100) - TP}"/>`
    + `<rect class="q01" x="${L}" y="${TP}" width="${X(100) - L}" height="${Y(100) - TP}"/><rect class="q01" x="${X(100)}" y="${Y(100)}" width="${X(m) - X(100)}" height="${Y(0) - Y(100)}"/>`
    + `<text class="qt" x="${X(m) - 6}" y="${TP + 16}" text-anchor="end">둘 다 충족 — ${escH(SJP.stage)}</text>`
    + `<text class="qn" x="${L + 6}" y="${TP + 16}">시간당 · 예보만</text><text class="qn" x="${X(m) - 6}" y="${Y(0) - 8}" text-anchor="end">누적만</text>`;
  for (let p = 50; p <= m; p += 50) {
    g += `<line class="${p === 100 ? "g100" : "gl"}" x1="${X(p)}" x2="${X(p)}" y1="${TP}" y2="${Y(0)}"/><text class="ax" x="${X(p)}" y="${Y(0) + 14}" text-anchor="middle">${p}%</text>`
      + `<line class="${p === 100 ? "g100" : "gl"}" x1="${L}" x2="${X(m)}" y1="${Y(p)}" y2="${Y(p)}"/><text class="ax" x="${L - 6}" y="${Y(p) + 4}" text-anchor="end">${p}%</text>`;
  }
  const my = (TP + Y(0)) / 2;
  g += `<text class="at" x="${(L + X(m)) / 2}" y="${H - 4}" text-anchor="middle">쌓이는 비(일 · 누적 · 선행) ÷ 기준</text>`
    + `<text class="at" x="14" y="${my}" text-anchor="middle" transform="rotate(-90 14 ${my})">시간당 · 예보 시우량 · 수위 ÷ 기준</text>`;
  const name = r => `${SJ.sg === "all" ? `${r.sigun} ` : ""}${sjName(r)}`;
  const many = sjpMany(pts);
  // 시간 색 — 자취 전체(지금 → 내일)를 흰 · 빨 · 주 · 노 · 초 · 파 · 남 · 보로. 끄면 재생 위치까지만 점선
  const step = Math.max(1, Math.ceil(pts.length * T.length / 6000));   // 선이 너무 많으면(경남 전체) 몇 시간씩 건너 — 느린 PC
  const trail = SJP.tc ? pts.map(({ r }) => {
    const all = sjB(r).series.xy[SJP.stage] || [], n = all.length;
    let s = "";
    for (let i = step; i < n; i += step) if (all[i - step] && all[i])
      s += `<line class="tc" x1="${X(all[i - step][0]).toFixed(1)}" y1="${Y(all[i - step][1]).toFixed(1)}" x2="${X(all[i][0]).toFixed(1)}" y2="${Y(all[i][1]).toFixed(1)}" stroke="${dzTimeCol(i / (n - 1))}"/>`;
    return s;
  }).join("") : SJP.lines ? pts.map(({ r }) => {
    const a = (sjB(r).series.xy[SJP.stage] || []).slice(0, t + 1).filter(Boolean);
    return a.length > 1 ? `<polyline class="tr" style="stroke:${many ? SJP_FC[r.fam] : dzColVar(dzLv(sjpStageP(a[a.length - 1])))}" points="${a.map(p => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`).join(" ")}"/>` : "";
  }).join("") : "";
  const at = pts.map(x => ({ ...x, p: sjpStageP(x.xy) })).sort((a, b) => a.p - b.p);
  const mk = at.map(({ r, xy, p }) => {
    const ax = sjB(r).series.ax?.[SJP.stage] || ["", ""];
    return `<g class="pm${r.id === SJ.sel ? " on" : ""}" data-r="${escH(r.id)}"><title>${escH(name(r))} · ${escH(r.fam)} — ${escH(ax[0] || "누적")} ${xy[0]}% · ${escH(ax[1] || "시간당")} ${xy[1]}% → ${p}%</title>`
      + `<image href="${sjpBadge(r, p, many)}" x="${(X(xy[0]) - 9).toFixed(1)}" y="${(Y(xy[1]) - 9).toFixed(1)}" width="18" height="18"/></g>`;
  }).join("");
  let ly = -99;
  const lab = at.slice(-12).sort((a, b) => Y(a.xy[1]) - Y(b.xy[1])).map(({ r, xy, p }) => {
    const y = Math.max(Y(xy[1]) + 4, ly + 13);
    ly = y;
    return `<line class="lk" x1="${X(xy[0]) + 10}" y1="${Y(xy[1])}" x2="${W - R + 6}" y2="${y - 4}"/><text class="lb t${sjLv(p)}" x="${W - R + 9}" y="${y}">${escH(name(r))} ${p}%</text>`;
  }).join("");
  return `<svg class="sjp-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="${escH(SJP.stage)} 조건 평면">${g}${trail}${mk}${lab}</svg>`;
}
function sjpSvg(T, rows) {
  const W = 1000, H = 300, L = 44, R = 150, TP = 12, B = 24, n = Math.max(2, T.length), t = Math.min(SJP.t, n - 1);
  const top = Math.max(150, ...rows.flatMap(x => x.v)), ym = Math.min(300, Math.ceil(top / 50) * 50);
  const X = i => L + i * (W - L - R) / (n - 1), Y = p => TP + (1 - Math.min(p ?? 0, ym) / ym) * (H - TP - B);
  let g = "";
  for (let p = 50; p <= ym; p += 50) g += `<line class="${p === 100 ? "g100" : "gl"}" x1="${L}" x2="${W - R}" y1="${Y(p)}" y2="${Y(p)}"/><text class="ax" x="${L - 6}" y="${Y(p) + 4}" text-anchor="end">${p}%</text>`;
  for (let i = 0; i < n; i += 3) g += `<text class="ax" x="${X(i)}" y="${H - 6}" text-anchor="middle">${escH(T[i] || "")}</text>`;
  const many = sjpMany(rows);
  const ln = SJP.lines ? rows.map(x => `<polyline class="pl" style="stroke:${many ? SJP_FC[x.r.fam] : dzColVar(dzLv(Math.max(...x.v)))};stroke-opacity:${rows.length > 120 ? 0.22 : 0.45}" points="${x.v.map((p, i) => `${X(i).toFixed(1)},${Y(p).toFixed(1)}`).join(" ")}"/>`).join("") : "";
  const at = rows.map(x => ({ ...x, p: x.v[Math.min(t, x.v.length - 1)] })).sort((a, b) => a.p - b.p);
  const name = r => `${SJ.sg === "all" ? `${r.sigun} ` : ""}${sjName(r)}`;
  const mk = at.map(({ r, p }) => `<g class="pm${r.id === SJ.sel ? " on" : ""}" data-r="${escH(r.id)}"><title>${escH(name(r))} · ${escH(r.fam)} · ${p}%</title>`
    + `<image href="${sjpBadge(r, p, many)}" x="${(X(t) - 9).toFixed(1)}" y="${(Y(p) - 9).toFixed(1)}" width="18" height="18"/></g>`).join("");
  // 이름은 높은 12곳만 — 오른쪽 여백에 세로로 겹치지 않게 내려 단다
  let ly = -99;
  const lab = at.slice(-12).reverse().map(({ r, p }) => {
    const y = Math.max(Y(p) + 4, ly + 13);
    ly = y;
    return `<line class="lk" x1="${X(t) + 10}" y1="${Y(p)}" x2="${W - R + 6}" y2="${y - 4}"/><text class="lb t${sjLv(p)}" x="${W - R + 9}" y="${y}">${escH(name(r))} ${p}%</text>`;
  }).join("");
  return `<svg class="sjp-svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="지구별 앞으로 % 줄">${g}${ln}
    <line class="cur" x1="${X(t)}" x2="${X(t)}" y1="${TP}" y2="${H - B}"/>${mk}${lab}</svg>`;
}
function sjPlotInner() {
  const T = sjpT(), rows = sjpRows(), all = SJ.sg === "all", n = T.length;
  SJP.t = Math.min(SJP.t, n - 1);
  const sgs = all ? [...new Set((SJ.d?.rows || []).map(r => r.sigun))] : [];
  return `<div class="sjp-bar"><span class="seg md">${[["line", "시간 줄"], ["plane", "조건 평면"]].map(([k, l]) => `<button data-pm="${k}" class="${SJP.mode === k ? "on" : ""}">${l}</button>`).join("")}</span>
      ${SJP.mode === "plane" ? `<span class="seg md">${SJ_STG.map(s => `<button data-pg="${s}" class="${SJP.stage === s ? "on" : ""}">${s}</button>`).join("")}</span>` : ""}
      <button class="pp" data-pp>${SJP.play ? "❚❚" : "▶"}</button>
      <input type="range" id="sjp-t" min="0" max="${n - 1}" value="${SJP.t}" aria-label="재생 위치"><b class="tm">${escH(T[SJP.t] || "지금")}</b>
      <span class="ct" id="sjp-ct">${sjpCt(rows)}</span>
      <label><input type="checkbox" id="sjp-ln"${SJP.lines ? " checked" : ""}>${SJP.mode === "plane" ? "자취" : "줄"}</label>
      ${SJP.mode === "plane" ? `<label title="자취 전체를 시간 색으로 — 흰(지금) → 보라(내일). 끄면 재생으로 본다"><input type="checkbox" id="sjp-tc"${SJP.tc ? " checked" : ""}>시간 색</label>` : ""}
      <select id="sjp-by" aria-label="% 거르는 기준"><option value="max"${SJP.by === "max" ? " selected" : ""}>앞으로 최고 %로 거름</option><option value="now"${SJP.by === "now" ? " selected" : ""}>지금 %로 거름</option></select>
      <span class="chips">${SJP_FAM.map(f => `<button data-pf="${f}" class="${SJP.fam.has(f) ? "on" : ""}"><img src="${dzBadgeUrl(f, 0)}" alt="">${f}</button>`).join("")}</span></div>
    ${all ? `<div class="sjp-sg">${sgs.map(s => `<button data-ps="${escH(s)}" class="${SJP.off.has(s) ? "" : "on"}">${escH(s)}</button>`).join("")}<button data-ps="*" class="g">모두</button></div>` : ""}
    <div id="sjp-g">${sjpGraph(T, rows)}</div>`;
}
const sjpCt = rows => SJP.mode === "plane"
  ? `${rows.length}곳 · 그때 ${escH(SJP.stage)} 충족 <i class="t100">${rows.filter(x => (sjpStageP(sjpXY(x.r, SJP.t)) ?? 0) >= 100).length}</i>`
  : `${rows.length}곳 · 그때 100%↑ <i class="t100">${rows.filter(x => x.v[Math.min(SJP.t, x.v.length - 1)] >= 100).length}</i>`;
/* 그림 밑 한 줄 — 유형 색 · 시간 색이 무엇인지 */
function sjpKey(T, rows) {
  const out = [];
  if (sjpMany(rows)) out.push([...new Set(rows.map(x => x.r.fam))].map(f => `<span><i style="background:${SJP_FC[f]}"></i>${escH(f)}</span>`).join(""));
  if (SJP.mode === "plane" && SJP.tc) out.push(`<span class="tk">지금<b></b>${escH(T[T.length - 1] || "")}</span>`);
  return out.length ? `<div class="sjp-key">${out.join("")}</div>` : "";
}
const sjpGraph = (T, rows) => T.length < 2 ? `<p class="mute">예보가 아직 없어 그리지 못한다</p>` : !rows.length ? `<p class="mute">거른 조건에 맞는 지구가 없다</p>`
  : (SJP.mode === "plane" ? sjpPlane(T, rows) : sjpSvg(T, rows)) + sjpKey(T, rows);
const sjPlotDraw = () => { const el = $("sj-plot"); if (el) el.innerHTML = sjPlotInner(); };
/* 재생 위치만 바뀌었다 — 막대(끄는 중일 수 있다)는 두고 그림 · 수 · 시각만 */
function sjpMove() {
  const T = sjpT(), rows = sjpRows();
  if (!$("sjp-g")) return;
  $("sjp-g").innerHTML = sjpGraph(T, rows);
  $("sjp-ct").innerHTML = sjpCt(rows);
  $("sjp-t").value = SJP.t;
  $("sjp-t").nextElementSibling.textContent = T[SJP.t] || "지금";
  document.querySelector("#sj-plot [data-pp]").textContent = SJP.play ? "❚❚" : "▶";
}
/* 재생 위치를 지도 창에 — 배지 색을 그 시각으로 */
const sjpTell = () => SJ_BC?.postMessage({ dzt: SJP.t, lab: sjpT()[SJP.t], basis: SJ.basis });
function sjpStep() {
  const n = sjpT().length;
  if (SJP.t >= n - 1) { sjpStop(); return; }
  SJP.t++; sjpMove(); sjpTell();
}
function sjpStop() { clearInterval(SJP.play); SJP.play = 0; sjpMove(); }
$("sj").addEventListener("click", ev => {
  const t = ev.target;
  if (t.closest("[data-pp]")) {
    if (SJP.play) return sjpStop();
    if (SJP.t >= sjpT().length - 1) SJP.t = 0;
    SJP.play = setInterval(sjpStep, 700); sjpMove(); sjpTell(); return;
  }
  const pm = t.closest("[data-pm]");
  if (pm) { SJP.mode = pm.dataset.pm; sjpSave(); return sjPlotDraw(); }
  const pg = t.closest("[data-pg]");
  if (pg) { SJP.stage = pg.dataset.pg; sjpSave(); return sjPlotDraw(); }
  const pf = t.closest("[data-pf]");
  if (pf) { SJP.fam.has(pf.dataset.pf) ? SJP.fam.delete(pf.dataset.pf) : SJP.fam.add(pf.dataset.pf); return sjPlotDraw(); }
  const ps = t.closest("[data-ps]");
  if (ps) {
    const s = ps.dataset.ps;
    if (s === "*") SJP.off.clear(); else SJP.off.has(s) ? SJP.off.delete(s) : SJP.off.add(s);
    return sjPlotDraw();
  }
});
$("sj").addEventListener("input", ev => {
  if (ev.target.id !== "sjp-t") return;
  SJP.t = +ev.target.value;
  sjpMove(); sjpTell();
});
$("sj").addEventListener("change", ev => {
  if (ev.target.id === "sjp-ln") { SJP.lines = ev.target.checked; sjpSave(); sjPlotDraw(); }
  if (ev.target.id === "sjp-by") { SJP.by = ev.target.value; sjpSave(); sjPlotDraw(); }
  if (ev.target.id === "sjp-tc") { SJP.tc = ev.target.checked; sjpSave(); sjPlotDraw(); }
});

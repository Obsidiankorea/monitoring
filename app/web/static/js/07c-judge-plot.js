"use strict";
/* ── 상황판단 차트 — 지구마다 지금부터 내일 24시까지 '가장 높은 단계 %' 줄(가로 시간 · 세로 %) + 재생 ─────────────
   점 = 재생 위치 시각의 그 지구(배지: 색 = 위험도 · 그림 = 유형, 지도 '우려지역 지구' 레이어와 같다). 100% 선을 넘는 곳 = 도달 시각.
   거르개: 위 '% 이상'(지금 % 또는 앞으로 최고 %) · 유형 · 시군(경남 전체일 때) · 줄 보이기. 재생하면 지도 창 배지 색도 그 시각으로(BroadcastChannel).
   자료: /api/judge?series=1 의 b[기준].series {t: 시각들, v: %들} — 서버 judge.series_of. 앞쪽만(지난 시간은 그리지 않는다). */
const SJP_FAM = ["산사태", "하천", "지하공간"];
const SJP = { t: 0, play: 0, lines: true, by: "max", fam: new Set(SJP_FAM), off: new Set() };
try { const o = JSON.parse(localStorage.getItem("gn-sj-plot") || "{}"); if (o.by) SJP.by = o.by; if (o.lines != null) SJP.lines = o.lines; } catch {}
const sjpSave = () => { try { localStorage.setItem("gn-sj-plot", JSON.stringify({ by: SJP.by, lines: SJP.lines })); } catch {} };
const sjpSer = r => { const b = sjB(r); return [b.top, ...(b.series?.v || [])]; };
const sjpT = () => ["지금", ...((SJ.d?.rows || []).map(r => sjB(r)?.series?.t).filter(Boolean).sort((a, b) => b.length - a.length)[0] || [])];
function sjpRows() {
  return (SJ.d?.rows || []).filter(r => r.b[SJ.basis] && SJP.fam.has(r.fam) && !SJP.off.has(r.sigun))
    .map(r => ({ r, v: sjpSer(r) }))
    .filter(x => !SJ.cut.on || (SJP.by === "max" ? Math.max(...x.v) : x.v[0]) >= SJ.cut.pct);
}
function sjpSvg(T, rows) {
  const W = 1000, H = 300, L = 44, R = 150, TP = 12, B = 24, n = Math.max(2, T.length), t = Math.min(SJP.t, n - 1);
  const top = Math.max(150, ...rows.flatMap(x => x.v)), ym = Math.min(300, Math.ceil(top / 50) * 50);
  const X = i => L + i * (W - L - R) / (n - 1), Y = p => TP + (1 - Math.min(p ?? 0, ym) / ym) * (H - TP - B);
  let g = "";
  for (let p = 50; p <= ym; p += 50) g += `<line class="${p === 100 ? "g100" : "gl"}" x1="${L}" x2="${W - R}" y1="${Y(p)}" y2="${Y(p)}"/><text class="ax" x="${L - 6}" y="${Y(p) + 4}" text-anchor="end">${p}%</text>`;
  for (let i = 0; i < n; i += 3) g += `<text class="ax" x="${X(i)}" y="${H - 6}" text-anchor="middle">${escH(T[i] || "")}</text>`;
  const ln = SJP.lines ? rows.map(x => `<polyline class="pl" style="stroke:${dzColVar(dzLv(Math.max(...x.v)))};stroke-opacity:${rows.length > 120 ? 0.22 : 0.45}" points="${x.v.map((p, i) => `${X(i).toFixed(1)},${Y(p).toFixed(1)}`).join(" ")}"/>`).join("") : "";
  const at = rows.map(x => ({ ...x, p: x.v[Math.min(t, x.v.length - 1)] })).sort((a, b) => a.p - b.p);
  const name = r => `${SJ.sg === "all" ? `${r.sigun} ` : ""}${sjName(r)}`;
  const mk = at.map(({ r, p }) => `<g class="pm${r.id === SJ.sel ? " on" : ""}" data-r="${escH(r.id)}"><title>${escH(name(r))} · ${escH(r.fam)} · ${p}%</title>`
    + `<image href="${dzBadgeUrl(r.fam, dzLv(p))}" x="${(X(t) - 9).toFixed(1)}" y="${(Y(p) - 9).toFixed(1)}" width="18" height="18"/></g>`).join("");
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
  return `<div class="sjp-bar"><button class="pp" data-pp>${SJP.play ? "❚❚" : "▶"}</button>
      <input type="range" id="sjp-t" min="0" max="${n - 1}" value="${SJP.t}" aria-label="재생 위치"><b class="tm">${escH(T[SJP.t] || "지금")}</b>
      <span class="ct" id="sjp-ct">${sjpCt(rows)}</span>
      <label><input type="checkbox" id="sjp-ln"${SJP.lines ? " checked" : ""}>줄</label>
      <select id="sjp-by" aria-label="% 거르는 기준"><option value="max"${SJP.by === "max" ? " selected" : ""}>앞으로 최고 %로 거름</option><option value="now"${SJP.by === "now" ? " selected" : ""}>지금 %로 거름</option></select>
      <span class="chips">${SJP_FAM.map(f => `<button data-pf="${f}" class="${SJP.fam.has(f) ? "on" : ""}"><img src="${dzBadgeUrl(f, 0)}" alt="">${f}</button>`).join("")}</span></div>
    ${all ? `<div class="sjp-sg">${sgs.map(s => `<button data-ps="${escH(s)}" class="${SJP.off.has(s) ? "" : "on"}">${escH(s)}</button>`).join("")}<button data-ps="*" class="g">모두</button></div>` : ""}
    <div id="sjp-g">${sjpGraph(T, rows)}</div>`;
}
const sjpCt = rows => `${rows.length}곳 · 그때 100%↑ <i class="t100">${rows.filter(x => x.v[Math.min(SJP.t, x.v.length - 1)] >= 100).length}</i>`;
const sjpGraph = (T, rows) => T.length < 2 ? `<p class="mute">예보가 아직 없어 줄을 못 긋는다</p>` : rows.length ? sjpSvg(T, rows) : `<p class="mute">거른 조건에 맞는 지구가 없다</p>`;
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
});

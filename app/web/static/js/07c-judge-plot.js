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
/* 시군 색 — 평면에 여러 시군 지구를 한꺼번에 넣을 때. 밝은 바탕에서 보이고 노랑 · 파랑 · 빨강 영역 색과 떨어진 18색 */
const SG_COL = ["#0F766E", "#7C3AED", "#EA580C", "#15803D", "#BE185D", "#0369A1", "#854D0E", "#4338CA", "#65A30D",
  "#9D174D", "#0E7490", "#C2410C", "#6D28D9", "#047857", "#A16207", "#1E3A8A", "#B91C1C", "#374151"];
const SG_ORD = ["창원시", "진주시", "통영시", "사천시", "김해시", "밀양시", "거제시", "양산시", "의령군", "함안군", "창녕군", "고성군", "남해군", "하동군", "산청군", "함양군", "거창군", "합천군"];
const sgCol = sg => SG_COL[Math.max(0, SG_ORD.findIndex(x => x.startsWith(sg)))];   // 자료는 '창원' · '창원시' 둘 다
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
/* 조건 평면 = 단계 영역 평면(06e ppAreas) — 유형마다 한 판(산사태 · 하천 · 지하공간 나란히). 가로 누적(지하공간 15분) ㎜ · 세로 시우량 ㎜/h.
   고른 단계(통제 · 사전대피 · 긴급대피) 영역을 진하게. 지구는 재생 위치의 점(배지) + 자취(시간 색이면 끝까지 흰 → 보라).
   고른 지구는 늘 시간색 자취와 그 지구 원문 기준(자홍 흐르는 점선) */
function sjpPlane(T, rows) {
  const reg = SJ.d?.regions;
  if (!reg) return `<p class="mute">영역 자료를 받는 중…</p>`;
  const fams = SJP_FAM.filter(f => SJP.fam.has(f) && rows.some(x => x.r.fam === f));
  if (!fams.length) return `<p class="mute">고른 유형에 지구가 없다</p>`;
  const t = Math.min(SJP.t, T.length - 1), name = r => `${SJ.sg === "all" ? `${r.sigun} ` : ""}${sjName(r)}`;
  const sgs = [...new Set(rows.map(x => x.r.sigun))].sort(), multi = sgs.length > 1, col = r => (multi ? sgCol(r.sigun) : "#374151");
  const W = fams.length > 1 ? Math.floor(1000 / fams.length) - 8 : 760, H = 340;
  const panels = fams.map(f => {
    const rg = reg[f], S = ppScale(rg, W, H, 40, 26, 10, 10), rs = rows.filter(x => x.r.fam === f && sjB(x.r)?.series?.pl?.length);
    const sel = rs.find(x => x.r.id === SJ.sel);
    let s = ppAreas(rg, S, { site: sel ? sjB(sel.r).series.site : [], fs: 11 });
    if (SJP.lines) s += rs.filter(x => x !== sel).map(x => ppTrail(rg, S, sjB(x.r).series.pl, t, SJP.tc, SJP.tc ? null : col(x.r))).join("");
    if (sel) s += ppTrail(rg, S, sjB(sel.r).series.pl, t, true);
    const at = rs.map(x => ({ ...x, p: x.v[Math.min(t, x.v.length - 1)], q: ppPt(rg, sjB(x.r).series.pl[Math.min(t, sjB(x.r).series.pl.length - 1)]) }))
      .filter(x => x.q && x.q[0] != null && x.q[1] != null).sort((a, b) => a.p - b.p);
    s += at.map(({ r, p, q }) => `<g class="pm${r.id === SJ.sel ? " on" : ""}" data-r="${escH(r.id)}"><title>${escH(name(r))} — ${rg.x} ${Math.round(q[0])}㎜ · 시우량 ${Math.round(q[1])}㎜/h · ${p}%</title>`
      + `<circle cx="${S.X(q[0]).toFixed(1)}" cy="${S.Y(q[1]).toFixed(1)}" r="${r.id === SJ.sel ? 7 : 5}" fill="${col(r)}" stroke="#fff" stroke-width="1.5"/></g>`).join("");
    const taken = [];                                       // 이름 — 높은 6곳, 앞 이름과 겹치면 건너뛴다
    for (const { r, p, q } of at.slice(-6).reverse()) {
      const x = S.X(q[0]) + 10, y = S.Y(q[1]) + 4, w = name(r).length * 11;
      if (taken.some(b => x < b.x + b.w && x + w > b.x && Math.abs(y - b.y) < 13)) continue;
      taken.push({ x, y, w });
      s += `<text class="lb2" x="${x.toFixed(1)}" y="${y.toFixed(1)}">${escH(name(r))}</text>`;
    }
    // 지도 지구 카드(06e .hud)와 같은 결 — 머리 띠(유형 배지 · 축 · 지구 수) 아래 평면
    return `<div class="ppcard"><div class="pph"><span class="bdg">${escH(f)}</span><small>가로 ${escH(rg.x)} ㎜ · 세로 시우량 ㎜/h</small><em>${rs.length}곳</em></div>`
      + `<svg class="sjp-svg pp" viewBox="0 0 ${W} ${H}" role="img" aria-label="${escH(f)} 단계 영역 평면">${s}</svg></div>`;
  });
  const sel = rows.find(x => x.r.id === SJ.sel), tx = sel ? (reg[sel.r.fam]?.texts || []) : [];
  const st = sel ? siteText(sjB(sel.r).series.site, reg[sel.r.fam]) : "";
  const sk = multi ? `<div class="ppk big sgk">${sgs.map(g => `<span><i style="background:${sgCol(g)}"></i>${escH(g)}</span>`).join("")}</div>` : "";
  return `<div class="ppk big">${ppKey(reg[fams[0]], sel ? sjB(sel.r).series.site : [])}<span class="mute">영역 = 도(행안부) 공통 기준</span>${SJP.tc || sel ? sjpTimeKey(T) : ""}</div>${sk}<div class="ppw" style="grid-template-columns:repeat(${fams.length}, minmax(0, 1fr))">${panels.join("")}</div>`
    + (st ? `<div class="hsite"><span>지구 기준</span><b>${escH(sjName(sel.r))} — ${escH(st.replace("이 지구 자체 기준: ", ""))}</b></div>` : "")
    + (tx.length ? `<div class="hcond"><span>비가 아닌 조건 · ${escH(sjName(sel.r))}</span>${tx.map(x => `<div>· ${escH(x.stage)}: ${escH(x.text)}</div>`).join("")}</div>` : "");
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
      ${SJP.mode === "plane" ? `<span class="ppcs">${ppChips()}</span>` : ""}
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
  ? `${rows.length}곳 · 그때 ${["통제", "사전대피", "긴급대피"].filter(st => PP_SHOW.has(st)).map(st => `${st} <b style="color:${STG_COL[st]}">${rows.filter(x => { const a = sjB(x.r)?.series?.xy?.[st]; return a && (sjpStageP(a[Math.min(SJP.t, a.length - 1)]) ?? 0) >= 100; }).length}</b>`).join(" · ")}`
  : `${rows.length}곳 · 그때 100%↑ <i class="t100">${rows.filter(x => x.v[Math.min(SJP.t, x.v.length - 1)] >= 100).length}</i>`;
/* 시간 색 막대 — 자취와 같은 색(ppTimeCol)을 칸마다, 6시간마다 눈금 + '몇 시간 뒤'. 평면 오른쪽 위 */
function sjpTimeKey(T) {
  const n = T.length;
  if (n < 2) return "";
  const W = 300, L = 4, R = 16, w = (W - L - R) / (n - 1), X = i => L + i * w;
  let s = Array.from({ length: n - 1 }, (_, i) => `<rect x="${X(i).toFixed(1)}" y="4" width="${(w + 0.5).toFixed(1)}" height="8" fill="${ppTimeCol((i + 1) / (n - 1))}"/>`).join("");
  const st = n > 30 ? 6 : 3;
  for (let i = 0; i < n; i += st) {
    s += `<line x1="${X(i).toFixed(1)}" x2="${X(i).toFixed(1)}" y1="2" y2="15" stroke="var(--ink)" stroke-width="1"/>`
      + `<text x="${X(i).toFixed(1)}" y="26" text-anchor="${i ? "middle" : "start"}" font-size="10" fill="var(--ink-2)">${i ? `+${i}h` : "지금"}</text>`;
  }
  return `<span class="tkey" title="자취 색 = 시각 — 진한 회색(지금) → 빨강 → 노랑 → 초록 → 파랑 → 보라(${escH(T[n - 1] || "")})"><svg viewBox="0 0 ${W} 30" width="${W}" height="30" role="img" aria-label="시간 색 눈금">${s}</svg></span>`;
}
/* 그림 밑 한 줄 — 유형 색 · 시간 색이 무엇인지 */
function sjpKey(T, rows) {
  const out = [];
  if (SJP.mode !== "plane" && sjpMany(rows)) out.push([...new Set(rows.map(x => x.r.fam))].map(f => `<span><i style="background:${SJP_FC[f]}"></i>${escH(f)}</span>`).join(""));
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
  sjbTick();
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
  const pps = t.closest("[data-pps]");
  if (pps) { ppToggle(pps.dataset.pps); return sjPlotDraw(); }
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

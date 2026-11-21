"use strict";
/* ── 상황판단 — 단계판(왼쪽 첫 탭) · 단계 시간표(오른쪽, 지구를 안 골랐을 때) · AI 묻기(떠 있는 창) ─────────────
   단계판 = 묶음(시군 · 읍면동 · 유형)이 지금 어느 단계 칸에 있나 — 긴급대피 · 사전대피 · 통제 · 근접(70%↑).
   시간표 = 앞으로 언제 어느 단계에 들어가나 — 줄 하나가 묶음, 띠 색이 단계(평면과 같은 노랑 · 파랑 · 빨강).
   밤(21~06시, 판정의 취약시간)은 옅은 칸, 일몰은 주황 점선. 사전대피가 일몰 뒤에 시작하면 ⚠ — 밤에는 대피가 어렵다.
   자료는 07c 와 같다(sjGroups · series.xy). 재생 위치(SJP.t)는 세로 파란 선. */
const SJB_COL = ["#6B7280", "#C99A00", "#1F63D6", "#D21F1F"];          // 근접 · 통제 · 사전대피 · 긴급대피
const SJB_NM = ["근접", "통제", "사전대피", "긴급대피"];
/* 그 묶음이 i 시각에 넘은 가장 높은 단계(0 = 없음). 0 은 지금 판정, 그 뒤는 시간별 조건 평면 */
function sjbAt(g, i) {
  let lv = 0;
  for (const r of g.rows) {
    const b = sjB(r);
    for (let k = 3; k > lv; k--) {
      const s = SJB_NM[k], a = b.series?.xy?.[s];
      if (i === 0 ? b.st[s]?.met : a && (sjpStageP(a[Math.min(i, a.length - 1)]) ?? 0) >= 100) { lv = k; break; }
    }
  }
  return lv;
}
const sjbNow = g => SJ_STG.reduce((lv, s, k) => (g.st[s]?.met ? k + 1 : lv), 0);
/* 일몰(시, 소수) — 경남 가운데(진주 35.2N 128.1E). 천문 연감 근사식, 몇 분 오차 */
function sjbSunset(y, m, d, lat = 35.2, lon = 128.1) {
  const R = Math.PI / 180, N = Math.round((Date.UTC(y, m - 1, d) - Date.UTC(y, 0, 0)) / 864e5), lh = lon / 15, t = N + (18 - lh) / 24;
  const M = 0.9856 * t - 3.289, L = (M + 1.916 * Math.sin(M * R) + 0.02 * Math.sin(2 * M * R) + 282.634 + 360) % 360;
  let RA = (Math.atan(0.91764 * Math.tan(L * R)) / R + 360) % 360;
  RA = (RA + Math.floor(L / 90) * 90 - Math.floor(RA / 90) * 90) / 15;
  const sd = 0.39782 * Math.sin(L * R), cd = Math.cos(Math.asin(sd));
  const H = Math.acos((Math.cos(90.833 * R) - sd * Math.sin(lat * R)) / (cd * Math.cos(lat * R))) / R / 15;
  return ((H + RA - 0.06571 * t - 6.622 - lh + 9) % 24 + 24) % 24;
}
const sjbHm = h => `${Math.floor(h)}:${String(Math.round((h % 1) * 60)).padStart(2, "0")}`;
/* 시각 줄 → [{h: 시, day: 0 · 1 · 2}] — '지금'은 실황 시각, 뒤는 꼬리 숫자(넘어가면 다음 날) */
function sjbHours(T) {
  const tm = SJ.d?.tm || "";
  let day = 0, prev = +tm.slice(8, 10) || 0;
  return T.map((l, i) => {
    if (i === 0) return { h: prev, day: 0 };
    const h = +((String(l).match(/(\d{1,2})$/) || [])[1] ?? prev + 1) % 24;
    if (h <= prev) day++;
    prev = h;
    return { h, day };
  });
}
/* ── 시간표 — 오른쪽 패널 */
function sjTimeline() {
  const T = sjpT(), n = T.length, hs = sjbHours(T), tm = SJ.d?.tm || "", all = SJ.sg === "all";
  const rows = sjGroups().map(g => {
    const lv = Array.from({ length: n }, (_, i) => sjbAt(g, i)), first = lv.findIndex(v => v > 0);
    return { g, lv, first, top: Math.max(...lv) };
  }).filter(x => x.first >= 0).sort((a, b) => a.first - b.first || b.top - a.top);
  const shown = rows.slice(0, 18), W = 380, LW = 128, RH = 22, TOP = 24, H = TOP + shown.length * RH + 26, w = (W - LW - 6) / n, X = i => LW + i * w;
  const ss = [0, 1, 2].map(k => { const d = new Date(+tm.slice(0, 4), +tm.slice(4, 6) - 1, +tm.slice(6, 8) + k); return sjbSunset(d.getFullYear(), d.getMonth() + 1, d.getDate()); });
  const night = h => h >= 21 || h < 6, late = (i) => night(hs[i].h) || hs[i].h >= ss[hs[i].day];
  let s = hs.map((x, i) => (night(x.h) ? `<rect x="${X(i).toFixed(1)}" y="${TOP - 4}" width="${(w + 0.4).toFixed(1)}" height="${shown.length * RH + 4}" fill="#3B82F6" fill-opacity=".16"/>` : "")).join("");
  // 일몰 — 그 날 그 시 칸 안의 분까지
  hs.forEach((x, i) => {
    const sh = ss[x.day];
    if (x.h === Math.floor(sh) && i < n) {
      const xx = X(i) + (sh % 1) * w;
      s += `<line x1="${xx.toFixed(1)}" x2="${xx.toFixed(1)}" y1="${TOP - 6}" y2="${TOP + shown.length * RH}" stroke="#F59E0B" stroke-dasharray="3 3"/>`
        + `<text x="${xx.toFixed(1)}" y="${TOP - 10}" text-anchor="middle" fill="#F59E0B" font-size="10">일몰 ${sjbHm(sh)}</text>`;
    }
  });
  shown.forEach(({ g, lv }, j) => {
    const y = TOP + j * RH, p2 = lv.findIndex(v => v >= 2), warn = p2 > 0 && late(p2) && !late(0);
    const lab = `${all ? `${g.sigun} ` : ""}${g.emd} ${g.fam}`, on = g.rows.some(r => r.id === SJ.sel);
    s += `<g class="tlr${on ? " on" : ""}" data-r="${escH(g.rows[0].id)}"><title>${escH(lab)}${warn ? " — 사전대피가 일몰 뒤에 시작: 밤 대피는 어렵다, 일몰 전 검토" : ""}</title>`
      + `<rect x="0" y="${y}" width="${W}" height="${RH}" fill="transparent"/>`
      + `<text x="4" y="${y + 15}" font-size="11.5" fill="var(--ink)">${escH(lab.length > 13 ? `${lab.slice(0, 12)}…` : lab)}</text>`
      + (warn ? `<text x="${LW - 6}" y="${y + 15}" text-anchor="end" font-size="11" fill="#F59E0B">⚠</text>` : "");
    // 같은 단계가 이어지는 칸을 한 띠로
    for (let i = 0; i < n;) {
      let k = i;
      while (k + 1 < n && lv[k + 1] === lv[i]) k++;
      if (lv[i]) s += `<rect x="${X(i).toFixed(1)}" y="${y + 5}" width="${(X(k + 1) - X(i)).toFixed(1)}" height="${RH - 10}" rx="2" fill="${SJB_COL[lv[i]]}"/>`;
      i = k + 1;
    }
    if (g.dec.length) s += `<circle cx="${(X(0) + 4).toFixed(1)}" cy="${y + RH / 2}" r="4" fill="var(--panel)" stroke="var(--ink)" stroke-width="1.5"><title>${escH(g.dec[0].act)} ${g.dec[0].at.slice(11, 16)}</title></circle>`;
  });
  const yb = TOP + shown.length * RH;
  s += hs.map((x, i) => (i === 0 || x.h % 6 === 0 ? `<text x="${(X(i) + w / 2).toFixed(1)}" y="${yb + 14}" text-anchor="middle" font-size="10" fill="var(--ink-3)">${i === 0 ? "지금" : x.h === 0 ? `${x.day === 1 ? "내일" : "모레"}` : `${x.h}시`}</text>` : "")).join("")
    + `<line x1="${LW}" x2="${W - 6}" y1="${yb}" y2="${yb}" stroke="var(--line)"/>`
    + `<line class="tlc" x1="${(X(SJP.t) + w / 2).toFixed(1)}" x2="${(X(SJP.t) + w / 2).toFixed(1)}" y1="${TOP - 6}" y2="${yb}" stroke="#60A5FA" stroke-width="1.5"/>`;
  const nw = shown.filter(({ lv }) => { const p = lv.findIndex(v => v >= 2); return p > 0 && late(p) && !late(0); }).length;
  return `<div class="tl"><h4>언제 어느 단계에 들어가나 <span class="mute">앞으로 ${n - 1}시간 · ${SJ_BN[SJ.basis]}</span></h4>
    ${shown.length ? `<svg viewBox="0 0 ${W} ${H}" class="tls" role="img" aria-label="묶음별 단계 시간표">${s}</svg>` : `<p class="mute">앞으로 ${n - 1}시간 안에 통제 이상에 드는 묶음이 없다</p>`}
    ${rows.length > shown.length ? `<p class="mute">먼저 드는 ${shown.length}묶음만 — 나머지 ${rows.length - shown.length}묶음은 가운데 목록</p>` : ""}
    <div class="tlk">${[1, 2, 3].map(k => `<span><i style="background:${SJB_COL[k]}"></i>${SJB_NM[k]}</span>`).join("")}<span><i class="nt"></i>밤 21~06</span><span><i class="ss"></i>일몰</span><span><i class="dc"></i>결정 기록</span></div>
    ${nw ? `<p class="tlw">⚠ ${nw}묶음은 사전대피가 일몰 뒤에 시작한다 — 밤에는 대피가 어려우니 일몰 전 사전대피를 검토</p>` : ""}
    <p class="mute">줄을 누르면 그 지구 상세 · 띠는 시간별 조건 평면으로 본 단계(묶음 안 지구 중 가장 높은 것)</p></div>`;
}
function sjbTick() {
  const c = document.querySelector("#sj .tl .tlc");
  if (!c) return;
  const T = sjpT(), w = (380 - 128 - 6) / T.length, x = (128 + SJP.t * w + w / 2).toFixed(1);
  c.setAttribute("x1", x); c.setAttribute("x2", x);
}
/* ── 단계판 — 왼쪽 첫 탭. 위에 칸별 수, 아래로 칸마다 카드 */
function sjBoard() {
  const gs = sjGroups(), all = SJ.sg === "all", col = [[], [], [], []];
  for (const g of gs) {
    const lv = sjbNow(g);
    if (lv || g.top >= 70) col[lv].push(g);
  }
  const card = (g, lv) => {
    const nx = SJ_STG[lv], c = nx ? g.st[nx] : g.st[SJ_STG[2]];
    const line = nx ? (c ? `${nx}까지 ${c.unk ? "모름" : `${c.pct}%`}${c.eta ? ` · ${c.eta}시` : ""}` : `${nx} 기준 없음`) : `긴급대피 ${c?.pct ?? "—"}%`;
    const soil = g.rows.some(r => r.soil?.st === "check") ? `<em class="sl">토양 확인</em>` : g.rows.some(r => r.soil?.st === "met") ? `<em class="sl ok">토양 충족</em>` : "";
    const dec = g.sec === 0 ? `<em class="dn w">결정 필요 ⚠</em>` : g.dec.length ? `<em class="dn">✔ ${escH(g.dec[0].act)} ${g.dec[0].at.slice(11, 16)}</em>` : "";
    return `<button class="kc${g.sec === 0 ? " need" : ""}${g.rows.some(r => r.id === SJ.sel) ? " on" : ""}" data-r="${escH(g.rows[0].id)}" style="--kc:${SJB_COL[lv]}">
      <b>${all ? `<i>${escH(g.sigun)}</i> ` : ""}${escH(g.emd)} <small>${escH(g.fam)}</small></b><span>${escH(line)}</span>${dec || soil ? `<span>${dec}${soil}</span>` : ""}</button>`;
  };
  const head = [0, 1, 2, 3].map(k => `<div style="--kc:${SJB_COL[k]}"><em>${k ? SJB_NM[k] : "근접 70%↑"}</em><b>${col[k].length}</b></div>`).join("");
  const body = [3, 2, 1, 0].map(k => `<section class="kb" style="--kc:${SJB_COL[k]}"><h5>${k ? SJB_NM[k] : "근접 — 70% 넘었고 아직 통제 전"}<span>${col[k].length}</span></h5>
    ${col[k].slice(0, 12).map(g => card(g, k)).join("") || `<p class="mute">없음</p>`}${col[k].length > 12 ? `<p class="mute">외 ${col[k].length - 12}묶음 — 가운데 목록</p>` : ""}</section>`).join("");
  return `<div class="kbh">${head}</div>${body}<p class="mute">카드 = 묶음(시군 · 읍면동 · 유형) · 점선 테두리 = 넘었는데 결정 기록 없음 · 재생과 상관없이 지금 판정</p>`;
}
/* ── AI 묻기 — 떠 있는 창(전엔 왼쪽 탭) */
function sjAiDraw() {
  let box = $("sj-ai");
  if (!box) { box = document.createElement("div"); box.id = "sj-ai"; box.className = "sj-ai"; box.setAttribute("role", "dialog"); box.setAttribute("aria-label", "AI 묻기"); $("sj").append(box); }
  box.hidden = !SJ.ai;
  if (!SJ.ai) return;
  box.innerHTML = `<header><b>AI 묻기</b><span class="mute">지금 수치 · 위키 · 판단 기록을 보고 답한다</span><button id="sj-aix" aria-label="AI 창 닫기">✕</button></header>
    <div class="chips">${(SJ.q || []).map(q => `<button data-q="${q.id}">${escH(q.label)}</button>`).join("")}</div><div id="sj-msgs">${SJ.msgs.join("")}</div>
    <form id="sj-ask"><input maxlength="300" placeholder="${SJ.llm ? "AI 에게 묻기" : "AI 꺼짐 — 설정 › AI 답변"}"><button>묻기</button></form>
    <p class="mute">단추는 규칙이라 바로 답한다 · 입력 칸은 AI(연락처는 넘기지 않는다)</p>`;
  $("sj-msgs").lastElementChild?.scrollIntoView({ block: "end" });
}
$("sj").addEventListener("click", ev => {
  const t = ev.target;
  if (t.closest("#sj-aib") || t.closest("#sj-aix")) { SJ.ai = !!t.closest("#sj-aib") && !SJ.ai; sjAiDraw(); $("sj-aib")?.classList.toggle("on", SJ.ai); return; }
  if (t.closest("[data-unsel]")) { SJ.sel = null; sjRender(); }
});

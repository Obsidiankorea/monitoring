"use strict";
/* ── 레이어 — 지도 위에 겹칠 것. 왼쪽 위 '레이어'에서 켜고 끈다(서버 설정 overlays) ──
   지금은 기상특보 하나. 차츰 늘린다(시군 위 막대 등) — OVL 에 한 줄 보태면 메뉴에 뜬다. */
const OVL = [
  { id: "alerts", label: "기상특보", short: "특보", key: "A" },
  { id: "stations", label: "관측소", short: "관측소", key: "S" },
  { id: "stnval", label: "지점 강수량 글자", short: "값", key: "V", parent: "stations" },
  { id: "river", label: "하천 · 댐", short: "하천", key: "D" },
  { id: "tide", label: "조위", short: "조위", key: "O" },
];
/* ⓘ 에 올리거나 누르면 뜨는 설명 — 레이어 목록·범례는 짧게 두고 긴 말은 여기에 */
const TIPS = new Map([
  ["ov-alerts", `<b>기상특보</b> — 발효 중 특보를 시군 <b>테두리 선</b>과 이름 밑 <b>딱지</b>로 그린다.
    주의보 점선 · 경보 실선 · 중대경보 겹실선, 선은 시군 안쪽에만. 면은 칠하지 않는다 — 강수 청색 면과 섞이지 않게.
    바다 특보는 바다 위 글로, 예비특보 · 발효 예정은 범례에만(아직 발효 전). 재현 사례에서는 <b>산출</b> 특보.`],
  ["ov-stations", `<b>관측소</b> — 경남 AWS 55곳의 실측을 지금 그린 격자와 <b>같은 시각</b>으로.
    마름모 속은 지도와 같은 색 단계라 둘레와 색이 다르면 격자와 실측이 어긋난 곳이다.
    ◇ 0 · × 기상청 결측 · 점선 = 그 시각 값을 못 받음. 점에 마우스를 올리면 실측 · 그 칸 격자 · 차이.
    예측 층에서는 자리만. 경남 AWS(내부망) 지점은 이 층에 없다 — 시군을 누르면 오른쪽 패널에 목록으로 나온다(막대 파랑 경남 · 청록 기상청).`],
  ["ov-river", `<b>하천 · 댐</b> — 경남 하천 수위 관측소(눈금 막대) · 댐 · 보를 홍수통제소 자료로. 막대 색은 수위 단계, 주의보부터는 번쩍인다.
    낙동강 위쪽(경북 · 대구) 댐 · 보도 함께 — 경남으로 흘러드는 물이라 점선 둘레로. 점에 마우스를 올리면 수위 · 기준 수위 · 1시간 변화 · 방류. 10분마다 갱신.`],
  ["ov-tide", `<b>조위</b> — 경남 해안 조위관측소의 바닷물 높이(해양조사원). 표식의 숫자는 지금 실측, 괄호는 예측과의 차이.
    마우스를 올리면 요약, 누르면 게이지 · 물결 팝업. 대조기 기간에는 아이콘 옆에 표시한다.`],
  ["ov-stnval", `<b>지점 강수량 글자</b> — 관측소 옆에 값을 단다. 센 곳부터 빈자리에만, 상위 셋은 지점 이름도.
    시군을 골랐으면 그 시군 지점만. 켜면 지도가 붐빌 수 있어 기본은 끔 — 점 색만으로도 단계는 읽힌다.`],
]);
let OV = new Set();
/* 켜진 레이어 아이콘 — 누르면 그 범례·설명이 오른쪽으로 펼쳐진다(다시 누르면 닫힌다). 하나씩만 */
const OV_IC = {
  alerts: `<svg viewBox="0 0 24 24"><path d="M7 16.5a4.2 4.2 0 0 1-.5-8.3 5.6 5.6 0 0 1 10.8 1.3A3.5 3.5 0 0 1 17 16.5"/><path d="m12.6 12-2.4 3.6h2.8L11.4 20"/></svg>`,
  stations: `<svg viewBox="0 0 24 24"><path d="M12 4 20 12 12 20 4 12z"/><circle cx="12" cy="12" r="2" fill="currentColor" stroke="none"/></svg>`,
  tide: `<svg viewBox="0 0 24 24"><path d="M3 15c2.2-2 3.8-2 6 0s3.8 2 6 0 3.8-2 6 0"/><path d="M3 20c2.2-2 3.8-2 6 0s3.8 2 6 0 3.8-2 6 0" opacity=".5"/><path d="M12 11V3M8.8 6 12 3l3.2 3"/></svg>`,
  river: `<svg viewBox="0 0 24 24"><path d="M3 8.5c2.2-2 3.8-2 6 0s3.8 2 6 0 3.8-2 6 0"/><path d="M3 13.5c2.2-2 3.8-2 6 0s3.8 2 6 0 3.8-2 6 0"/><path d="M3 18.5c2.2-2 3.8-2 6 0s3.8 2 6 0 3.8-2 6 0" opacity=".5"/></svg>`,
};
let LY_OPEN = null;                     // 펼친 범례(stations) — 창마다 기억
try { LY_OPEN = localStorage.getItem("gn-map-lyopen") || null; } catch {}
if (LY_OPEN === "alerts") LY_OPEN = null;
/* 특보 줄 — 레이어 아이콘 밑에 얇게 세로로(지도 왼쪽 빈자리). 펼쳐 두면 지도가 그 오른쪽으로 비켜 선다(겹치지 않게).
   ⚠️ 예전에는 아이콘 오른쪽으로 340px 상자가 지도 북서쪽(함양 · 거창)을 덮어 평소엔 접어 뒀다(10-24 얇은 줄로).
   창마다 기억(gn-map-alopen) — 처음엔 펼침. 관측소 범례와 따로 논다(둘 다 펼칠 수 있다) */
let AL_OPEN = true, AL_POS = { dx: 0, dy: 0 };
try { const v = localStorage.getItem("gn-map-alopen"); if (v !== null) AL_OPEN = v === "1"; } catch {}
try { const p = JSON.parse(localStorage.getItem("gn-map-alpos") || "null"); if (p && isFinite(p.dx) && isFinite(p.dy)) AL_POS = p; } catch {}
/* 특보 줄 끌어 옮기기 — 머리를 잡고. 위로 올리면 아이콘을 덮는다(줄이 불투명이라 비치지 않는다). 두 번 누르면 제자리 */
{
  const al = $("ly-alerts");
  al.addEventListener("pointerdown", ev => {
    const hd = ev.target.closest("#al-hd");
    if (!hd || ev.button !== 0 || ev.target.closest(".fd, .inf")) return;
    hd.setPointerCapture(ev.pointerId); al.classList.add("drag");
    const k = V?.k || 1, x0 = ev.clientX, y0 = ev.clientY, p0 = { ...AL_POS }, l0 = parseFloat(al.style.left) || 0, t0 = parseFloat(al.style.top) || 0;
    hd.onpointermove = e => { al.style.left = l0 + (e.clientX - x0) / k + "px"; al.style.top = t0 + (e.clientY - y0) / k + "px"; };
    hd.onpointerup = hd.onpointercancel = e => {
      hd.onpointermove = hd.onpointerup = null; al.classList.remove("drag");
      AL_POS = { dx: Math.round(p0.dx + (e.clientX - x0) / k), dy: Math.round(p0.dy + (e.clientY - y0) / k) };
      try { localStorage.setItem("gn-map-alpos", JSON.stringify(AL_POS)); } catch {}
      fitAlCol(); if (V) { camGo(true); placeSw(); }
    };
  });
  al.addEventListener("dblclick", ev => {
    if (!ev.target.closest("#al-hd") || ev.target.closest(".fd, .inf")) return;
    AL_POS = { dx: 0, dy: 0 }; try { localStorage.removeItem("gn-map-alpos"); } catch {}
    fitAlCol(); if (V) { camGo(true); placeSw(); }
  });
}
const alShown = () => AL_OPEN && OV.has("alerts");
function setAlOpen(on) {
  AL_OPEN = on;
  try { localStorage.setItem("gn-map-alopen", on ? "1" : "0"); } catch {}
  renderLayers();
  drawAlerts();                           // 바다 특보 글자 — 줄이 펼쳐져 있으면 줄이 적는다
  if (V) { camGo(true); placeSw(); }      // 지도가 줄 오른쪽으로 비켜 서거나 돌아온다
}
function setLyOpen(id) {
  LY_OPEN = id;
  if (id) { $("ly-menu").hidden = true; $("ly-btn").setAttribute("aria-expanded", "false"); }   // 같은 자리 — 하나만
  try { localStorage.setItem("gn-map-lyopen", id || ""); } catch {}
  renderLayers();
}
function renderLyIcons() {
  const box = $("ly-act");
  const lvTop = () => {                   // 지금 가장 센 특보 — 아이콘 색
    const lv = (ALERTS?.land || []).reduce((a, g) => ((LVRANK[g.lv] || 0) > (LVRANK[a] || 0) ? g.lv : a), null);
    return lv ? `var(--lv-${lv})` : "";
  };
  box.innerHTML = ["alerts", "stations", "river", "tide"].filter(id => OV.has(id)).map(id => {
    const o = OVL.find(x => x.id === id);
    const hiR = RIV?.rows ? RIV.rows.filter(s => s.kind === "wl" && (s.stage ?? -1) >= 1).length : 0;
    const n = id === "alerts" && ALERTS && !ALERTS.err ? ALERTS.land.length + ALERTS.sea.length : id === "river" ? hiR : id === "tide" ? tdHigh().length : 0;
    const col = id === "alerts" ? lvTop() : id === "river" && hiR ? RV_C[rvMax()] : id === "tide" ? tdCol() : "";
    return `<button class="ly-ic sm" data-d="${id}" aria-expanded="${id === "alerts" ? alShown() : LY_OPEN === id}" title="${o.label} — 눌러서 ${id === "alerts" ? "특보 줄 펼치기 · 접기" : "범례·설명"} (${o.key}: 끄기)"
      ${col ? `style="color:${col}"` : ""}>${OV_IC[id]}${n ? `<span class="bd" style="background:${col || "var(--ink-3)"}">${n}</span>` : ""}${id === "tide" ? tdSpringChip() : ""}</button>`;
  }).join("");
  for (const b of box.querySelectorAll("[data-d]")) b.onclick = () => (b.dataset.d === "alerts" ? setAlOpen(!AL_OPEN)
    : setLyOpen(LY_OPEN === b.dataset.d ? null : b.dataset.d));
  // 관측소 범례는 누른 아이콘 오른쪽 그 높이에. 특보 줄은 아이콘들 밑에 — 범례 위까지(넘치면 굴린다)
  const ic = box.querySelector(`[data-d="stations"]`);
  if (ic) $("ly-stn").style.top = ic.offsetTop + "px";
  const ir = box.querySelector(`[data-d="river"]`);
  if (ir) $("ly-river").style.top = ir.offsetTop + "px";
  const it = box.querySelector(`[data-d="tide"]`);
  if (it) { $("ly-tide").style.top = it.offsetTop + "px"; tdFit(); }
  fitAlCol();
}
/* 특보 줄 자리 — 아이콘들 밑에서 범례 위까지(범례가 바뀌면 다시 — 기상청 색 누적은 범례가 길다) */
function fitAlCol() {
  const al = $("ly-alerts"), box = $("ly-act");
  if (al.hidden || al.classList.contains("drag")) return;
  const last = box.offsetHeight ? box : $("ly-btn"), k = V?.k || 1;
  // 기본 자리(아이콘들 밑) + 사람이 옮긴 만큼(AL_POS, 이 화면에 기억). 판 밖으로 나가지 않게
  al.style.left = AL_POS.dx + "px";
  al.style.top = last.offsetTop + last.offsetHeight + 8 + AL_POS.dy + "px";
  const st = $("stage").getBoundingClientRect();
  let r = al.getBoundingClientRect();
  if (r.top < st.top + 6) { al.style.top = parseFloat(al.style.top) + (st.top + 6 - r.top) / k + "px"; r = al.getBoundingClientRect(); }
  if (r.left < st.left + 4) { al.style.left = parseFloat(al.style.left) + (st.left + 4 - r.left) / k + "px"; r = al.getBoundingClientRect(); }
  // 밑 끝 — 범례와 겹치는 세로 줄이면 범례 위까지, 아니면 판 밑까지
  const lg = $("legend").getBoundingClientRect();
  const bottom = r.left < lg.right && r.right > lg.left ? lg.top - 14 : st.bottom - 16;
  al.style.maxHeight = Math.max(140, (bottom - r.top) / k).toFixed(0) + "px";
}
function renderLayers() {
  if (LY_OPEN && !OV.has(LY_OPEN)) LY_OPEN = null;
  // 이름 · 키 · ⓘ 만 — 설명은 ⓘ 에. 딸린 항목(지점 강수량 글자)은 부모(관측소) 밑에 들여 쓰고, 부모가 꺼져 있으면 흐리게
  $("ly-menu").innerHTML = OVL.map(o => `<label class="ly-it${o.parent ? " sub" : ""}${o.parent && !OV.has(o.parent) ? " off" : ""}"><input type="checkbox" data-ov="${o.id}" ${OV.has(o.id) ? "checked" : ""}${o.parent && !OV.has(o.parent) ? " disabled" : ""}>
    <b>${o.label}</b><kbd>${o.key}</kbd><i class="inf" data-tip="ov-${o.id}" aria-label="설명">i</i></label>`).join("");
  for (const c of $("ly-menu").querySelectorAll("input[data-ov]")) c.onchange = () => setOverlay(c.dataset.ov, c.checked);
  renderAlertLegend();
  renderStnLegend();
  renderRiverLegend();
  renderTideLegend();
  renderLyIcons();
}
function setOverlay(id, on) {
  on ? OV.add(id) : OV.delete(id);
  saveSetting({ overlays: [...OV] });
  if (id === "alerts") { if (on) loadAlerts(); else { ALERTS = null; drawAlerts(); draw(); } if (V) { camGo(true); placeSw(); } }
  if (id === "stations") loadStations();
  if (id === "river") { if (on) setLyOpen("river"); loadRiver(); }
  if (id === "tide") { if (on) setLyOpen("tide"); loadTide(); }
  if (id === "stnval") drawStations();
  renderLayers();
}
$("ly-btn").onclick = () => {
  const open = $("ly-menu").hidden;
  $("ly-menu").hidden = !open;
  $("ly-btn").setAttribute("aria-expanded", String(open));
  if (open && LY_OPEN) setLyOpen(null);   // 메뉴와 범례가 같은 자리에 겹치지 않게
};
document.addEventListener("pointerdown", ev => {
  if (!$("ly-menu").hidden && !ev.target.closest?.("#layers")) {
    $("ly-menu").hidden = true; $("ly-btn").setAttribute("aria-expanded", "false");
  }
});

/* ── 기상특보 ─────────────────────────────────────────────────────────
   ⚠️ **면을 칠하지 않는다.** 강수는 청색 면이다 — 특보까지 면이면 두 색이 섞여 둘 다 못 읽는다.
      특보는 예약색(주의보 노랑 · 경보 빨강 · 중대경보 보라)의 **선**과 **글자 딱지**다.
   ⚠️ 색만으로 가르지 않는다: 주의보 점선 · 경보 실선 · 중대경보 겹실선. 흑백·색약에서도 갈린다.
   ⚠️ 선은 시군 **안쪽**에만 긋는다(제 모양으로 잘라 낸다). 이웃 시군의 다른 특보 선과 겹치지 않는다.
   일부 구역만(합천 서북부 등)이면 시군 전체에 긋고 딱지에 '서북'을 적는다 — 특보구역 경계는 아직 없다.
   바다 특보는 바다 위에 글로, 예비특보는 지도에 긋지 않고 레이어 범례에만 적는다(발효 전이다). */
let ALERTS = null, ALERTBOX = [];
const LVRANK = { severe: 3, warn: 2, watch: 1 };
const LVNAME = { severe: "중대경보", warn: "경보", watch: "주의보" };
/* '합천서북부' → ['합천', '서북'], '창원시' → ['창원', ''] — 시군 이름 뒤가 시 · 군 · 방위(…부)일 때만.
   ⚠️ 앞머리만 맞추면 '남해서부서쪽먼바다'(전남 쪽 바다)가 남해군 특보로 그려졌다. 바다 구역은 시군이 아니다 */
function regSig(reg) {
  if (/바다|해상/.test(reg)) return [null, ""];
  for (const s of ORDER_GN()) if (reg.startsWith(s)) {
    // ⚠️ API 가 세부구역을 '하동군북부'처럼 군을 붙여 주기도 한다(10-27) — 못 읽어 지도에 안 그어지고 줄에 날것으로 보였다
    const rest = reg.slice(s.length).replace(/^[시군](?=[동서남북중]{1,2}부$)/, "");
    if (rest === "" || rest === "시" || rest === "군") return [s, ""];
    if (/^[동서남북중]{1,2}부$/.test(rest)) return [s, rest.replace(/부$/, "")];
  }
  return [null, ""];
}
/* 세부구역 — 군마다 나뉜 특보구역(서버 domain/regions.py SUBZONES 와 같다). 다 들면 그 군 전체로 적는다 */
const SUBZ = { 합천: ["서북", "중", "남"], 산청: ["북", "서남", "동남"], 함양: ["중", "서북"], 거창: ["북", "남"], 하동: ["북", "남"] };
/* [[시군, 세부('' = 전체)], …] → '창원 · 진주 · 하동<sup>북부</sup>'. 관제순(창원 · 진주 · 통영 … 합천), 같은 시군은 한 번,
   세부는 윗첨자(둘이면 '북·서남부' — '부'는 끝에 한 번, 그 군의 세부가 다 들면 생략하고 시군만). 경남 열여덟이 다 들면 '경남 전역' */
function regsHtml(items) {
  const by = {};
  for (const [s, sub] of items) if (s) (by[s] ||= new Set()).add(sub || "");
  const all = ORDER_GN(), sigs = all.filter(s => by[s]);
  const whole = s => by[s].has("") || (!!SUBZ[s] && SUBZ[s].every(x => by[s].has(x)));
  if (sigs.length === all.length && sigs.every(whole)) return `<span class="rg">경남 전역</span>`;
  return sigs.map(s => {
    const subs = whole(s) ? [] : [...new Set([...(SUBZ[s] || []), ...by[s]])].filter(x => x && by[s].has(x));
    return `<span class="rg">${s}${subs.length ? `<sup>${subs.join("·")}부</sup>` : ""}</span>`;
  }).join(" · ");
}
/* 특보 한 줄(발효 예정 · 예비)의 자리 — 육상은 [시군, 세부], 바다는 줄인 이름 */
function placeOf(p, acc) {
  const [s, sub] = regSig(p.reg || "");
  if (s || (p.sigun && !p.sea)) acc.land.push([s || p.sigun, s ? sub : ""]);
  else acc.sea.push(seaShort(p.reg || ""));
}
function parseAlerts(j) {
  const data = j?.data || { groups: [], pending: [] };
  const bySig = {}, land = [], sea = [];
  for (const g of data.groups || []) {
    // 바다 — 서버가 경남 바다만 준다. 혹시 육상으로 와도 구역 이름이 바다면 바다로(시군에 긋지 않는다)
    if (g.sea || (g.regions || []).every(r => /바다|해상/.test(r))) { sea.push({ ...g, sea: true }); continue; }
    const where = [], regs = [];
    for (const reg of g.regions || []) {
      const [s, sub] = regSig(reg);
      if (!s) continue;
      (bySig[s] ||= []).push({ name: g.name, lv: g.lv, sub });
      where.push(sub ? `${s}(${sub})` : s);
      regs.push([s, sub]);
    }
    land.push({ ...g, where: [...new Set(where)], regs });
  }
  return { base: j?.base_time, bySig, land, sea, pending: data.pending || [] };
}
function testAlerts() {
  const t = new Date(), hhmm = `${String(t.getHours()).padStart(2, "0")}:00`;
  return { base_time: `${t.toISOString().slice(0, 10)} ${hhmm}`, data: {
    groups: [
      { lv: "severe", name: "폭염중대경보", sea: false, tmfc: hhmm, regions: ["밀양"] },
      { lv: "warn", name: "호우경보", sea: false, tmfc: hhmm, regions: ["창원", "김해"] },
      { lv: "watch", name: "호우주의보", sea: false, tmfc: hhmm, regions: ["진주", "산청서남부", "함안"] },
      { lv: "watch", name: "강풍주의보", sea: false, tmfc: hhmm, regions: ["통영", "거제", "창원"] },
      { lv: "watch", name: "풍랑주의보", sea: true, tmfc: hhmm, regions: ["남해동부동쪽안쪽먼바다", "거제시동부앞바다"] },
    ],
    pending: [{ kind: "pre", name: "호우", reg: "하동", sigun: "하동", when: "25일 새벽(03~06시)" },
              { kind: "pre", name: "호우", reg: "남해", sigun: "남해", when: "25일 새벽(03~06시)" },
              { kind: "pre", name: "태풍", reg: "남해동부바깥먼바다", sigun: null, sea: true, when: "26일 오전(06~12시)" },
              { kind: "pre", name: "태풍", reg: "거제시동부앞바다", sigun: null, sea: true, when: "26일 오전(06~12시)" },
              { kind: "pre", name: "태풍", reg: "거제시", sigun: "거제", when: "26일 오후(12~18시)" },
              { kind: "pre", name: "태풍", reg: "통영시", sigun: "통영", when: "26일 오후(12~18시)" }] } };
}
let ALERT_SEQ = 0;
async function loadAlerts() {
  if (!OV.has("alerts")) return;
  if (CASE) {                             // 사례: 그 시각의 산출 특보
    ALERTS = CASEM ? caseAlerts() : null;
    drawAlerts(); draw(); renderAlertLegend();
    return;
  }
  const my = ++ALERT_SEQ;
  let j;
  try { j = test ? testAlerts() : await getJson("/api/alerts"); }
  catch (e) { j = { err: e.message }; }
  if (my !== ALERT_SEQ) return;
  ALERTS = j.err ? { err: j.err } : parseAlerts(j);
  drawAlerts(); draw(); renderAlertLegend();
}

/* 경위도 → 500m 칸(정방향). 바다 특보 글자 자리를 경위도로 두려고 쓴다 */
const LCCF = (() => {
  const D = Math.PI / 180, a = 6378137, f = 1 / 298.257222101, e = Math.sqrt(f * (2 - f));
  const m = p => Math.cos(p) / Math.sqrt(1 - e * e * Math.sin(p) ** 2);
  const t = p => Math.tan(Math.PI / 4 - p / 2) / ((1 - e * Math.sin(p)) / (1 + e * Math.sin(p))) ** (e / 2);
  const p1 = 30 * D, p2 = 60 * D, p0 = 38 * D;
  const n = (Math.log(m(p1)) - Math.log(m(p2))) / (Math.log(t(p1)) - Math.log(t(p2)));
  const AF = a * m(p1) / (n * t(p1) ** n), rho0 = AF * t(p0) ** n;
  return (lon, lat) => {
    const rho = AF * t(lat * D) ** n, th = n * (lon - 126) * D;
    return [rho * Math.sin(th) / 500 + 880, (rho0 - rho * Math.cos(th)) / 500 + 1540];
  };
})();

function drawAlerts() {
  const gl = $("walerts"), gb = $("wbadge");
  ALERTBOX = [];
  if (!gl || !gb) return;
  if (!OV.has("alerts") || !ALERTS || ALERTS.err || !V || !V.s) { gl.innerHTML = gb.innerHTML = ""; return; }
  const sc = V.u / 3.3, w = Math.max(3.5, 4.6 * sc);      // 보이는 선 굵기(안쪽 절반)
  const defs = [], lines = [], badges = [];
  for (const [sig, list] of Object.entries(ALERTS.bySig)) {
    const ft = FEAT.find(f => f.properties.sigun === sig);
    if (!ft) continue;
    const top = list.reduce((a, b) => (LVRANK[b.lv] > LVRANK[a.lv] ? b : a));
    const id = `wc${ft.properties.id}`, dClip = PATH(ft);
    defs.push(`<clipPath id="${id}"><path d="${dClip}"/></clipPath>`);
    // ⚠️ 작은 섬(4㎢ 미만 = 16칸)까지 두르면 통영·거제 바다가 점선으로 어지럽다 — 선은 큰 땅에만
    const polys = ft.geometry.type === "Polygon" ? [ft.geometry.coordinates] : ft.geometry.coordinates;
    const areaCells = ring => Math.abs(ring.reduce((s, p, i) => {
      const q = ring[(i + 1) % ring.length];
      return s + p[0] * q[1] - q[0] * p[1];
    }, 0)) / 2;
    const big = polys.filter(p => areaCells(p[0]) >= 16);
    const d = PATH({ type: "MultiPolygon", coordinates: big.length ? big : polys });
    const L = (cls, sw, dash = "") => `<path class="wl ${cls}" d="${d}" clip-path="url(#${id})" stroke-width="${(sw * 2).toFixed(1)}"${dash ? ` stroke-dasharray="${dash}"` : ""}/>`;
    if (top.lv === "severe") lines.push(L("severe", w * 1.3), L("gap", w * 0.85), L("severe", w * 0.45));
    else if (top.lv === "warn") lines.push(L("warn", w));
    else lines.push(L("watch", w, `${(10 * sc).toFixed(1)} ${(6 * sc).toFixed(1)}`));
    // 딱지 — 시군명 밑에 쌓는다(센 것부터)
    const fs = FSN * 0.6, bh = fs * 1.5, x = V.toX(ft.properties.lx);
    let y = V.toY(ft.properties.ly) + FSN * 0.62 + 3;
    // 같은 특보는 딱지 하나 — 세부구역을 모아 '· 북·남', 군의 세부가 다 들면 시군 전체(10-27 거창 북부 · 남부가 딱지 둘이었다)
    const items = [];
    for (const it of list.slice().sort((a, b) => LVRANK[b.lv] - LVRANK[a.lv])) {
      let m = items.find(x => x.name === it.name);
      if (!m) items.push(m = { name: it.name, lv: it.lv, subs: new Set() });
      m.subs.add(it.sub || "");
    }
    for (const it of items) {
      const whole = it.subs.has("") || (!!SUBZ[sig] && SUBZ[sig].every(x => it.subs.has(x)));
      const txt = it.name + (whole ? "" : ` · ${[...new Set([...(SUBZ[sig] || []), ...it.subs])].filter(x => x && it.subs.has(x)).join("·")}`);
      const bw = txt.length * fs * 0.95 + fs * 0.9;
      badges.push(`<g class="wb ${it.lv}"><rect x="${(x - bw / 2).toFixed(1)}" y="${y.toFixed(1)}" width="${bw.toFixed(1)}" height="${bh.toFixed(1)}" rx="${(bh / 3).toFixed(1)}"/>
        <text x="${x.toFixed(1)}" y="${(y + bh / 2).toFixed(1)}" text-anchor="middle" style="font-size:${fs.toFixed(1)}px">${txt}</text></g>`);
      ALERTBOX.push({ x0: x - bw / 2, x1: x + bw / 2, y0: y, y1: y + bh });
      y += bh + 3;
    }
  }
  // 바다 특보 — 경남 바다(남해동부 먼바다 · 거제 · 경남 앞바다)만, 땅에 긋지 않고 바다 위(거제 남쪽)에 글로.
  // 둘째 줄에 구역(줄인 이름) — 어느 바다인지. 시군 경계 · 이름과 겹치지 않게 땅에서 떨어진 자리
  // 왼쪽 특보 줄이 펼쳐져 있으면 거기 적는다. 바다 위젯이 켜져 있으면 그 판이 바다 자리를 쓴다 — 둘 다 아니면 바다 위에 글로
  if (ALERTS.sea.length && !alShown() && !swOn()) {
    // ⚠️ 거제 남쪽(34.55°N)은 1920×1080 에서 화면 맨 아래 — 재생 막대와 겹쳤다. 거제 동남쪽 트인 바다(부산 아래)로
    const [cx, cy] = LCCF(128.98, 34.84);
    const fs = FSN * 0.56, fs2 = fs * 0.72, x = V.toX(cx).toFixed(1);
    const short = seaShort;
    let y = V.toY(cy);
    for (const g of ALERTS.sea) {
      const regs = (g.regions || []).map(short);
      badges.push(`<text class="wsea" x="${x}" y="${y.toFixed(1)}" text-anchor="middle"
        style="font-size:${fs.toFixed(1)}px;fill:var(--lv-${g.lv});stroke-width:${(fs * 0.2).toFixed(1)}px">바다 · ${g.name}</text>`);
      y += fs * 1.1;
      if (regs.length) {
        badges.push(`<text class="wsea" x="${x}" y="${y.toFixed(1)}" text-anchor="middle"
          style="font-size:${fs2.toFixed(1)}px;fill:var(--ink-2);stroke-width:${(fs2 * 0.2).toFixed(1)}px">${regs.slice(0, 3).join(" · ")}${regs.length > 3 ? ` 외 ${regs.length - 3}` : ""}</text>`);
        y += fs2 * 1.5;
      }
    }
  }
  gl.innerHTML = `<defs>${defs.join("")}</defs>${lines.join("")}`;
  gb.innerHTML = badges.join("");
}

const seaShort = r => r.replace(/^남해동부/, "").replace(/시동부앞바다$/, "앞바다").replace(/(먼바다|앞바다)$/, " $1").trim();

/* ── 바다 위젯 — 지도 위 반투명 판(W). 예측 상위 · 지금 오는 비 ─────────────
   바다는 지도에서 남는 자리다 — 예전에는 바다 특보 글자만 떠 있었다(10-24). 고른 것은 서버 설정 sea_w(화면 모두 같이),
   자리는 이 브라우저에 기억(gn-map-sw — 화면 크기가 달라서). 위젯이 켜져 있으면 지도 위 바다 특보 글자는 그리지 않는다
   (위젯이 그 바다 자리를 쓴다 — 바다 특보는 왼쪽 특보 줄에). ⚠️ 특보 탭은 판이 너무 커져 뺐다(10-24).
   예측 상위 · 지금 오는 비는 오른쪽 패널 카드와 같은 자료(CARDS)와 같은 그림(renderFc · renderNow)이다 */
const SW_MODES = ["fc", "now", "avg", "off"];   // ⚠️ 특보 탭은 뺐다 — 판이 너무 커졌다. 특보는 왼쪽 특보 줄(얇게)에(10-24)
// 위젯 몸 높이는 줄 수로 정한다 — 예측 상위 · 지금 오는 비 두 탭이 같은 크기(돌려도 판이 들썩이지 않게, 10-24).
// 예측 상위 열 줄이 기본 — 빈자리가 모자라면 8 · 6 · 5 · 4 줄로(swAuto). 지금 오는 비는 그 높이를 장소 칩으로 채운다
const SW_ROWS = 10;
let SW_N = SW_ROWS;
const swBodyH = n => (n * 30 + 24) * (V?.k || 1);
/* 돌리기 — 서버 설정 sea_rot 초마다 예측 상위 → 지금 오는 비 → 시군 평균(화면 재생과 따로). 보이는 탭(SW_ROT.m)은 이 화면에서만 바꾼다 */
const SW_ROT = { m: null, t: null };
const swRotOn = () => swOn() && +SET.sea_rot > 0;
const swView = () => (swRotOn() && SW_ROT.m) || swMode();
function swProg() {                      // 머리 밑 가는 줄 — 다음 탭까지 남은 시간
  const pr = $("sw").querySelector(".sw-prog");
  pr.hidden = !swRotOn();
  if (pr.hidden) return;
  pr.classList.remove("run"); void pr.offsetWidth;    // 처음부터 다시 차게
  pr.style.setProperty("--d", `${SET.sea_rot}s`); pr.classList.add("run");
}
function swRotate(reset) {
  clearInterval(SW_ROT.t); SW_ROT.t = null;
  if (!swRotOn()) { SW_ROT.m = null; swProg(); return; }
  if (reset || !SW_ROT.m) SW_ROT.m = swMode();
  const ms = SW_MODES.filter(m => m !== "off");        // 예측 상위 → 지금 오는 비 → 시군 평균 → …
  SW_ROT.t = setInterval(() => { SW_ROT.m = ms[(ms.indexOf(SW_ROT.m) + 1) % ms.length]; renderSw(); swProg(); }, SET.sea_rot * 1000);
  swProg();
}
function setSwOpt(k, v) {
  SET[k] = v; saveSetting({ [k]: v });
  if (k === "sea_rot") swRotate(true);
  if (k === "sea_per") { CARDS = null; loadCards(); }    // 시군당 2곳은 읍면동 예측을 다 받아야 한다
  renderSw();
}
/* 예측 상위 시군당 2곳 — 읍면동 예측(emd_sigun)에서 시군마다 큰 둘 */
function swFcRows() {
  const F = CARDS.fc;
  if (+SET.sea_per !== 2 || F.det || F.mode === "day" || !F.emdAll) return null;
  const by = {};
  for (const e of F.emdAll) (by[e.sigun] ||= []).push(e);
  return Object.values(by).flatMap(l => l.sort((a, b) => b.sum - a.sum).slice(0, 2))
    .map(e => ({ sig: e.sigun, label: e.emd, tag: e.sigun, d: e.d.slice(0, 6), sum: e.sum }));
}
/* 지금 오는 비 — 위 60분, 아래 15분 ×4(시간당 환산). 순위가 달라 두 묶음으로. 장소 + 값 칩을 한 줄에 2~3개,
   막대 길이 대신 테두리를 시우량 색으로 — 같은 높이에 더 많이 */
function renderNowSw(n) {
  const N = CARDS.now;
  if (N.cols) { renderNow(SW_T, n); return; }          // 사례 — 1시간 · 3시간 두 칸 그대로
  $("sw-bt").textContent = N.tm || "—";
  $("sw-lg").innerHTML = miniLegend(SIU, "시우량", true, "시우량 범주(㎜/h) — 칩 테두리 색. 지도 1시간 · 예측 상위와 같은 자");
  const l60 = (N.r60 || []).filter(x => x.mm > 0), l15 = (N.r15 || []).filter(x => x.mm > 0);
  const cols = $("sw").classList.contains("tall") ? 2 : 3, body = $("sw-b");
  const rows = Math.max(2, Math.floor((n * 30 + 24 - 44) / 27));          // 44 = 묶음 머리 둘
  const sec = (head, list, nr, mul, none) => `<div class="nwh">${head}</div>` + (!list.length ? `<div class="sw-none">${none}</div>`
    : `<div class="nwg nws" style="--cols:${cols}">` + list.slice(0, nr * cols).map(x => {
      const v = x.mm * mul, c = rampColor(v, SIU, true) || "var(--line)", at = x.pos ? ` data-x="${x.pos.x}" data-y="${x.pos.y}"` : "";
      const tip = mul === 1 ? `60분 ${v.toFixed(1)}㎜` : `15분 ${x.mm.toFixed(1)}㎜ × 4 = 시간당 ${v.toFixed(1)}㎜`;
      return `<div class="nw${N.det ? " det" : ""}" data-s="${x.sig}"${at} style="--c:${c}" title="${x.sig} ${x.name} — ${tip}">`
        + `<span class="nm"><small>${N.det ? x.tag || "" : x.sig}</small>${x.name}</span><b>${v.toFixed(v >= 100 ? 0 : 1)}</b></div>`;
    }).join("") + `</div>`);
  body.innerHTML = !l60.length && !l15.length ? `<div class="sw-none">지난 1시간 비 없음</div>`
    : sec(`60분 강수량 · ${N.det ? "읍면동" : "지점"} 많은 순`, l60, Math.ceil(rows / 2), 1, "지난 1시간 비 없음")
      + sec("15분 강수량 ×4 · 시간당 환산", l15, Math.floor(rows / 2), 4, "지난 15분 비 없음");
  rowEvents(body);
}
const swMode = () => (SW_MODES.includes(SET.sea_w) ? SET.sea_w : "fc");   // 예전 값 alert(특보)는 예측 상위로
const swOn = () => swMode() !== "off";
// 사람이 옮긴 자리 { x: 왼쪽/판 너비, t: 위 끝/판 높이 | b: 아래 끝에서/판 높이, tall } — 가까운 끝에 붙인다(줄 수가 바뀌어도 그 끝에 붙어 있게).
// 없으면 스스로 빈자리를 찾는다(swAuto)
let SWPOS = null;
try { const p = JSON.parse(localStorage.getItem("gn-map-sw") || "null"); if (p && isFinite(p.x) && (isFinite(p.t) || isFinite(p.b))) SWPOS = p; } catch {}
function setSw(m) {
  SET.sea_w = m;
  saveSetting({ sea_w: m });
  if (swRotOn()) swRotate(true);                       // 돌리는 중이면 고른 탭부터 다시(탭 · W · 설정 모두)
  drawAlerts(); renderSw();
}
function renderSw() {
  const box = $("sw");
  box.hidden = !swOn() || !V;
  if (swRotOn() !== !!SW_ROT.t) swRotate();
  if (box.hidden) return;
  const m = swView(), n = SWPOS ? SW_ROWS : SW_N;
  for (const b of box.querySelectorAll(".sw-tabs button")) b.classList.toggle("on", b.dataset.m === m);
  box.querySelector(".sw-rot").classList.toggle("on", swRotOn());
  const body = $("sw-b"), bt = $("sw-bt"), tall0 = box.classList.contains("tall");
  body.style.height = swBodyH(n) + "px";                // 두 탭이 같은 크기
  $("sw-lg").innerHTML = "";
  if (m === "avg") renderAvgSw(n);                      // 지도 자료라 오른쪽 패널이 꺼져 있어도 나온다
  else if (!tlOn || SET.panel === "timeline" || !CARDS) {
    bt.textContent = "—";
    body.innerHTML = `<div class="sw-none">${tlOn && SET.panel !== "timeline" ? "읽는 중…" : "오른쪽 패널을 카드로 켜면 나온다(L · 설정 › 오른쪽 패널)"}</div>`;
  } else if (CARDS.err) { bt.textContent = "—"; body.innerHTML = `<div class="sw-none">불러오지 못했다 — ${CARDS.err}</div>`; }
  else if (m === "fc" && CASE) { bt.textContent = "—"; body.innerHTML = `<div class="sw-none">사례에는 초단기 예측이 없다 — 오른쪽 '호우 기준'을 본다</div>`; }
  else if (m === "fc") renderFc(SW_T, n, swFcRows());
  else renderNowSw(n);
  placeSw();
  // 자리를 찾다가 꼴(넓게 ↔ 길쭉하게)이 바뀌었으면 그 꼴로 다시 — 칩 칸 수 · 타일 지도가 꼴을 따른다
  if (box.classList.contains("tall") !== tall0 && !renderSw.again) {
    renderSw.again = true;
    try { renderSw(); } finally { renderSw.again = false; }
  }
}
/* 시군 평균 — 지금 지도 층(그 시각 · 그 구간)의 시군 면 평균(시군 안 격자 칸 평균, 결측 칸 뺌 — 지도 시군 통계 CURSTAT).
   지도를 따른다(누적이면 그 구간, 1시간이면 1시간, 화면 재생이면 그 화면). 색은 지도 범례 그대로.
   넓은 판은 경남 모양 타일 지도(6×4 — 대략 제자리, 오른쪽 아래 바다 자리에 경남 평균), 길쭉한 판은 많은 순 칩 */
const AVG_GEO = { 함양: [0, 0], 거창: [1, 0], 합천: [2, 0], 창녕: [3, 0], 밀양: [4, 0],
  산청: [0, 1], 진주: [1, 1], 의령: [2, 1], 함안: [3, 1], 김해: [4, 1], 양산: [5, 1],
  하동: [0, 2], 사천: [1, 2], 고성: [2, 2], 창원: [3, 2], 남해: [1, 3], 통영: [2, 3], 거제: [3, 3] };
const fmtAvg = v => (v == null ? "—" : v >= 100 ? String(Math.round(v)) : v.toFixed(1));
function renderAvgSw(n) {
  const body = $("sw-b"), k = V?.k || 1, fac = factor();
  const rows = (CURSTAT?.rows || []).filter(r => r.kind === "gn");
  $("sw-bt").textContent = CUR?.tm ? `${CUR.tm.slice(8, 10)}:${CUR.tm.slice(10, 12)}` : "—";
  if (!rows.length) { body.innerHTML = `<div class="sw-none">${CUR ? "이 층은 시군 통계가 없다" : "지도 자료가 없다 — 지도 층을 바꿔 본다"}</div>`; return; }
  const steps = stepsOf(kind), hr = HOURLY.has(kind), v = r => (r.mean == null ? null : r.mean * fac);
  const col = x => (x != null && rampColor(x, steps, hr)) || "var(--line)";
  // 경남 평균 — 시군 평균을 (결측 뺀) 칸 수로 무게 = 경남 땅 칸 전체 평균
  let sum = 0, cnt = 0;
  for (const r of rows) if (r.mean != null) { const c = r.cells - (r.missing || 0); sum += v(r) * c; cnt += c; }
  const gm = cnt ? sum / cnt : null, wet = rows.filter(r => v(r) >= steps[0]).length;
  const top = Math.max(0, ...rows.map(r => v(r) || 0));
  const tip = r => `${r.sigun} 평균 ${fmtAvg(v(r))}㎜ · 최대 ${fmtAvg(r.max == null ? null : r.max * fac)}㎜${r.where?.emd ? ` (${r.where.emd})` : ""}`;
  const cls = r => (v(r) >= steps[0] ? "" : " dry") + (top > 0 && v(r) === top ? " top" : "");
  const tall = $("sw").classList.contains("tall");
  // 설명 줄은 다른 탭의 작은 범례 자리(sw-lg)에 — 세 탭이 같은 크기
  $("sw-lg").innerHTML = `<span class="cap" title="시군 안 격자 칸의 평균(결측 칸 뺌) — 지도와 같은 면 · 같은 색. 경남은 땅 칸 전체 평균">${labelOf(kind)} · 시군 평균</span>`
    + (tall ? `<span class="gm">경남 <b>${fmtAvg(gm)}</b></span>` : "");
  if (tall) {
    const fit = Math.max(1, Math.floor((swBodyH(n) / k + 4) / 27)), cols = Math.min(3, Math.ceil(rows.length / fit));
    const list = rows.slice().sort((a, b) => (v(b) ?? -1) - (v(a) ?? -1)), nr = Math.ceil(list.length / cols);
    const ch = Math.max(20, Math.min(32, (swBodyH(n) / k - (nr - 1) * 4) / nr));   // 칩을 판 높이에 맞춰 키운다(18곳뿐이라)
    body.innerHTML = `<div class="nwg avl" style="--cols:${cols};--nh:${ch.toFixed(1)}px">` + list.map(r =>
        `<div class="nw av-c${cls(r)}" data-s="${r.sigun}" style="--c:${col(v(r))}" title="${tip(r)}"><span class="nm">${r.sigun}</span><b>${fmtAvg(v(r))}</b></div>`).join("") + `</div>`;
  } else {
    const rh = (swBodyH(n) / k - 3 * 5) / 4;               // 타일 한 줄 높이 — 낮으면 이름 · 값을 한 줄로
    body.innerHTML = `<div class="avm${rh < 50 ? " sm" : ""}" style="--rh:${rh.toFixed(1)}px">` + rows.map(r => {
      const [c, w] = AVG_GEO[r.sigun] || [5, 0];
      return `<div class="av${cls(r)}" data-s="${r.sigun}" style="--c:${col(v(r))};grid-column:${c + 1};grid-row:${w + 1}" title="${tip(r)}">`
        + `<span class="nm">${r.sigun}</span><b>${fmtAvg(v(r))}</b><small>최대 ${fmtAvg(r.max == null ? null : r.max * fac)}</small></div>`;
    }).join("") + `<div class="avs" style="--c:${col(gm)}"><span>경남 평균</span><b>${fmtAvg(gm)}<i>㎜</i></b><small>비 온 시군 ${wet}/${rows.length}</small></div></div>`;
  }
  rowEvents(body);
}
/* 빈자리 찾기 — 경남 땅을 가장 적게 덮는 자리. ⚠️ 처음에는 지도 빈자리 오른쪽 아래에 붙였더니 1920×1080 에서 거제를 덮었다(10-24).
   판을 8px 칸으로 나눠 경남 시군(이웃 부산 · 울산 · 바다는 빈자리로 친다)을 칠하고, 범례 · 재생 막대 · 제목 · 도구 · 오른쪽 패널은 못 가는 칸으로.
   넓은 꼴(430)과 세로로 길쭉한 꼴(262) 둘 다 재 보고 땅을 덜 덮는 쪽 — 같으면 지도 위쪽 오른편에 가까운 쪽(위에 빈자리가 있다는 말), 길쭉한 쪽.
   지도 틀 · 패널 · 범례가 그대로면 다시 재지 않는다(몸 높이는 줄 수로 정해져 탭을 넘겨도 같다 — 머리 등으로 높이가 40px 넘게 바뀔 때만) */
let SW_AUTO = null;
function swGrid(C) {
  const nx = Math.ceil(V.W / C), ny = Math.ceil(V.H / C);
  const cv = document.createElement("canvas"); cv.width = nx; cv.height = ny;
  const ctx = cv.getContext("2d");
  const g = { s: V.s, ox: V.ox, oy: V.oy }, m = MT;
  const path = d3.geoPath(d3.geoTransform({ point(x, y) {
    this.stream.point(((g.ox + (x - V.X0) * g.s) * m.sc + m.tx) / C, ((g.oy + (V.Y1 - y) * g.s) * m.sc + m.ty) / C); } }), ctx);
  ctx.beginPath();
  for (const ft of FEAT) if (ft.properties.kind !== "nb") path(ft);
  ctx.fill();
  const px = ctx.getImageData(0, 0, nx, ny).data, cost = new Float64Array(nx * ny);
  for (let i = 0; i < nx * ny; i++) cost[i] = px[i * 4 + 3] > 60 ? 1 : 0;
  const st = $("stage").getBoundingClientRect(), BIG = 1e4;
  const block = (x0, y0, x1, y1) => {
    const i0 = Math.max(0, Math.floor((x0 - 6) / C)), i1 = Math.min(nx, Math.ceil((x1 + 6) / C));
    const j0 = Math.max(0, Math.floor((y0 - 6) / C)), j1 = Math.min(ny, Math.ceil((y1 + 6) / C));
    for (let j = j0; j < j1; j++) for (let i = i0; i < i1; i++) cost[j * nx + i] = BIG;
  };
  for (const id of ["legend", "play", "lefttop", "ly-alerts", "tools", "testrib"]) {
    const el = $(id);
    if (!el || el.hidden || !el.offsetWidth) continue;
    const r = el.getBoundingClientRect();
    block(r.left - st.left, r.top - st.top, r.right - st.left, r.bottom - st.top);
  }
  if (tlOn) block(V.W - tlWidth(), 0, V.W, V.H);          // 오른쪽 패널(카드 · 타임라인)
  const S = new Float64Array((nx + 1) * (ny + 1));          // 누적 합 — 판 크기 창을 미끄러뜨린다
  for (let j = 0; j < ny; j++) for (let i = 0; i < nx; i++)
    S[(j + 1) * (nx + 1) + i + 1] = cost[j * nx + i] + S[j * (nx + 1) + i + 1] + S[(j + 1) * (nx + 1) + i] - S[j * (nx + 1) + i];
  return { nx, ny, C, S };
}
function swFit(G, w, h) {
  const { nx, ny, C, S } = G, cw = Math.ceil(w / C), ch = Math.ceil(h / C), A = mapArea();
  const tx = A.x1, ty = A.y0, D = Math.hypot(V.W, V.H);    // 같으면 지도 위쪽 오른편에 가까운 쪽
  let best = null;
  const lo = Math.ceil(8 / C);
  for (let j = lo; j + ch <= ny - lo; j++) for (let i = lo; i + cw <= nx - lo; i++) {
    const sum = S[(j + ch) * (nx + 1) + i + cw] - S[j * (nx + 1) + i + cw] - S[(j + ch) * (nx + 1) + i] + S[j * (nx + 1) + i];
    const x = i * C, y = j * C, score = sum + Math.hypot(x + w / 2 - tx, y + h / 2 - ty) / D;
    if (!best || score < best.score) best = { x, y, cost: sum, score };
  }
  return best;
}
function placeSw() {
  const box = $("sw");
  if (box.hidden || !V?.W || !V.H || box.classList.contains("drag")) return;   // 판 크기 0(숨은 창으로 열림) — 재면 boot 가 끊긴다. 크기가 잡히면 relayout 이 다시 부른다
  let x, y;
  if (SWPOS) {
    box.classList.toggle("tall", !!SWPOS.tall);
    const h = box.offsetHeight;
    x = SWPOS.x * V.W; y = isFinite(SWPOS.t) ? SWPOS.t * V.H : V.H - SWPOS.b * V.H - h;
  } else {
    if (CAM || ZA || !FEAT) return;                       // 시군 확대 중엔 감춰져 있다 — 경남 전체로 돌아오면 잰다
    const r = el => { const q = el.getBoundingClientRect(); return `${q.left | 0},${q.top | 0},${q.width | 0},${q.height | 0}`; };
    const key = [V.W, V.H, V.s.toFixed(3), V.ox | 0, V.oy | 0, MT.sc.toFixed(3), MT.tx | 0, MT.ty | 0, tlOn, SET.panel,
                 $("play").hidden ? "" : r($("play")), r($("legend"))].join("|");
    // 두 꼴의 크기를 잰다 — 몸 높이가 줄 수로 정해져 있어(두 탭 같은 크기) 10 · 8 · 6 · 5 · 4 줄 높이를 바로 안다
    const shape = tall => {
      box.classList.toggle("tall", tall);
      const w = box.offsetWidth, h = box.offsetHeight;
      return [10, 8, 6, 5, 4].map(n => ({ tall, n, w, h: h + swBodyH(n) - swBodyH(SW_N) }));
    };
    const cands = [...shape(true), ...shape(false)];
    const hNow = cands.find(c => c.tall === !!SW_AUTO?.tall && c.n === SW_N)?.h || 0;
    const A0 = SW_AUTO;
    if (!A0 || A0.key !== key || Math.abs(hNow - A0.h) > 40) {
      const G = swGrid(8);
      // 땅을 덜 덮는 것(작은 섬 몇 칸은 셈하지 않는다) → 줄이 많은 것 → 세로로 길쭉한 것 → 지도 위쪽 오른편에 가까운 것
      let best = null;
      for (const c of cands) {
        const f = swFit(G, c.w, c.h);
        if (!f) continue;
        const r = { ...c, ...f, land: Math.max(0, f.cost - 4) };
        if (!best || r.land < best.land || (r.land === best.land && (r.n > best.n || (r.n === best.n && (r.tall && !best.tall
            || (r.tall === best.tall && r.score < best.score)))))) best = r;
      }
      SW_AUTO = best ? { key, tall: best.tall, n: best.n, x: best.x, y: best.y, h: best.h, cost: best.cost } : null;
    }
    if (!SW_AUTO) return;
    box.classList.toggle("tall", SW_AUTO.tall);
    if (SW_AUTO.n !== SW_N && !placeSw.again) {     // 줄 수를 바꿔 다시 그린다(그 끝에서 한 번만 다시 온다)
      SW_N = SW_AUTO.n; placeSw.again = true;
      try { renderSw(); } finally { placeSw.again = false; }
      return;
    }
    x = SW_AUTO.x; y = SW_AUTO.y;
  }
  box.querySelector(".sw-sh").textContent = box.classList.contains("tall") ? "⇔" : "⇕";
  const w = box.offsetWidth, h = box.offsetHeight, xr = (tlOn ? V.W - tlWidth() : V.W) - 8;   // 오른쪽 패널 밑으로 들어가지 않게
  box.style.left = Math.max(8, Math.min(xr - w, x)).toFixed(0) + "px";
  box.style.top = Math.max(8, Math.min(V.H - h - 8, y)).toFixed(0) + "px";
}
{
  const box = $("sw"), hd = box.querySelector(".sw-h");
  box.querySelector(".sw-tabs").onclick = ev => {
    const b = ev.target.closest("[data-m]");
    if (!b) return;
    if (b.dataset.m !== swMode()) setSw(b.dataset.m);
    else if (swRotOn()) { swRotate(true); renderSw(); }  // 같은 탭이어도 돌리는 중이면 그 탭부터 다시
  };
  box.querySelector(".sw-rot").onclick = () => setSwOpt("sea_rot", swRotOn() ? 0 : 20);
  // 오른쪽 클릭 — 돌리기 간격 · 예측 상위 시군당 곳 수
  box.addEventListener("contextmenu", ev => {
    ev.preventDefault(); ev.stopPropagation();
    const pop = $("sw-ctx"), rot = +SET.sea_rot || 0, per = +SET.sea_per === 2 ? 2 : 1;
    pop.innerHTML = `<div class="g">돌리기 — 예측 상위 → 지금 오는 비 → 시군 평균</div>`
      + [[0, "끔 — 고른 탭 그대로"], [10, "10초"], [15, "15초"], [20, "20초"], [30, "30초"], [60, "1분"]].map(([v, l]) => `<button data-rot="${v}" class="${rot === v ? "on" : ""}">${l}</button>`).join("")
      + `<div class="sep"></div><div class="g">예측 상위</div>`
      + [[1, "시군당 1곳"], [2, "시군당 2곳 — 읍면동 둘"]].map(([v, l]) => `<button data-per="${v}" class="${per === v ? "on" : ""}">${l}</button>`).join("");
    const rc = $("stage").getBoundingClientRect(), k = V?.k || 1;
    pop.hidden = false;
    const pw = pop.offsetWidth * k, ph = pop.offsetHeight * k;
    pop.style.left = Math.max(4, Math.min(ev.clientX - rc.left, rc.width - pw - 8)) / k + "px";
    pop.style.top = Math.max(4, Math.min(ev.clientY - rc.top - ph / 2, rc.height - ph - 8)) / k + "px";
    void pop.offsetWidth; pop.classList.add("open");
    for (const b of pop.querySelectorAll("button")) b.onclick = e => {
      e.stopPropagation(); pop.classList.remove("open"); pop.hidden = true;
      if (b.dataset.rot != null) setSwOpt("sea_rot", +b.dataset.rot); else setSwOpt("sea_per", +b.dataset.per);
    };
  });
  document.addEventListener("pointerdown", ev => { if (!$("sw-ctx").hidden && !ev.target.closest?.("#sw-ctx")) { $("sw-ctx").classList.remove("open"); $("sw-ctx").hidden = true; } });
  box.querySelector(".sw-x").onclick = () => setSw("off");
  // 지금 자리를 기억한다 — 가까운 끝(위 · 아래)에 붙여서. 마지막으로 옮긴 자리가 이 화면의 기본 자리가 된다
  const savePos = (tall, h = box.offsetHeight) => {
    const top = box.offsetTop;
    SWPOS = top + h / 2 < V.H / 2 ? { x: box.offsetLeft / V.W, t: top / V.H, tall } : { x: box.offsetLeft / V.W, b: (V.H - top - h) / V.H, tall };
    try { localStorage.setItem("gn-map-sw", JSON.stringify(SWPOS)); } catch {}
  };
  box.querySelector(".sw-sh").onclick = () => {
    const h0 = box.offsetHeight, tall = !box.classList.contains("tall");
    savePos(tall, h0);
    renderSw();
  };
  hd.addEventListener("pointerdown", ev => {
    if (ev.button !== 0 || ev.target.closest("button")) return;
    hd.setPointerCapture(ev.pointerId); box.classList.add("drag");
    const x0 = ev.clientX, y0 = ev.clientY, l0 = box.offsetLeft, t0 = box.offsetTop;
    hd.onpointermove = e => { box.style.left = l0 + e.clientX - x0 + "px"; box.style.top = t0 + e.clientY - y0 + "px"; };
    hd.onpointerup = hd.onpointercancel = () => {
      hd.onpointermove = hd.onpointerup = null; box.classList.remove("drag");
      savePos(box.classList.contains("tall"));
      renderSw();                         // 줄 수를 다 채워(자동 자리에서 줄였을 수 있다) 이 자리에 다시
    };
  });
  hd.addEventListener("dblclick", ev => {
    if (ev.target.closest("button")) return;
    SWPOS = null; SW_AUTO = null; try { localStorage.removeItem("gn-map-sw"); } catch {}
    placeSw();
  });
}

function renderAlertLegend() {
  const box = $("ly-alerts");
  if (!OV.has("alerts")) { box.hidden = true; return; }
  box.hidden = !alShown();
  if (box.hidden) { renderLyIcons(); return; }
  if (!ALERTS) { box.innerHTML = `<div class="hd2"><b>기상특보</b><span>읽는 중…</span></div>`; return; }
  if (ALERTS.err) { box.innerHTML = `<div class="hd2"><b>기상특보</b></div><div class="al-none">불러오지 못했다 — ${ALERTS.err}</div>`; return; }
  // 얇은 세로 줄 — 한 특보가 두 줄: 이름(색) / 어디(작게). 너무 길면 '외 N'
  const cut = (list, n) => list.slice(0, n).join(" · ") + (list.length > n ? ` 외 ${list.length - n}` : "");
  const row = (tg, lv, name, where, ds = "") => `<div class="al${lv === "pre" ? " pre" : ""}"${ds ? ` data-s="${ds}"` : ""}>`
    + `<b style="color:var(--lv-${lv})">${name}${tg ? `<span class="tg">${tg}</span>` : ""}</b>${where ? `<span class="where">${where}</span>` : ""}</div>`;
  const rows = [];
  // 같은 종류끼리 한 줄 — 어디는 관제순, 세부구역은 윗첨자(하동<sup>북부</sup>)
  const sigsOf = regs => ORDER_GN().filter(s => regs.some(r => r[0] === s)).join(",");
  const placeTxt = a => [regsHtml(a.land), cut([...new Set(a.sea)], 4)].filter(Boolean).join(" · ");
  for (const g of ALERTS.land)
    rows.push(row("", g.lv, g.name, regsHtml(g.regs || []), sigsOf(g.regs || [])));
  for (const g of ALERTS.sea)
    rows.push(row("바다", g.lv, g.name, cut((g.regions || []).map(seaShort), 4)));
  // 예비특보(태풍 · 호우 …) — 이름 · 발효 예상(날짜 · 시간대)이 같은 것끼리. 바다 구역은 줄인 이름
  // 예비특보 — 머리 밑 체크(서버 설정 al_pre, 화면 모두 같이)로 숨길 수 있다. 숨겨도 몇 종인지는 체크 옆에
  const preBy = {}, preOn = SET.al_pre !== false;
  for (const p of ALERTS.pending.filter(x => x.kind === "pre")) placeOf(p, preBy[`${p.name}|${p.when}`] ||= { land: [], sea: [] });
  const nPre = Object.keys(preBy).length;
  for (const [k, a] of preOn ? Object.entries(preBy) : []) {
    const [name, when] = k.split("|");
    rows.push(row("", "pre", `${name} 예비특보`, `<i>${when}</i><br>${placeTxt(a)}`, sigsOf(a.land)));
  }
  // 발효 예정 — 이름 · 발효 시각이 같은 것끼리. ⚠️ 예전에는 구역마다 한 줄이라 한파주의보 예정이 열 줄 넘게 늘어섰다(10-27)
  const laterBy = {};
  for (const p of ALERTS.pending.filter(x => x.kind === "later")) placeOf(p, laterBy[`${p.name}|${p.tmef || ""}`] ||= { land: [], sea: [] });
  const today = String(NOWD().getDate()).padStart(2, "0");
  for (const [k, a] of Object.entries(laterBy)) {
    const [name, ef] = k.split("|"), hm = `${ef.slice(8, 10)}:${ef.slice(10, 12)}`;
    const at = ef.length >= 12 ? (ef.slice(6, 8) === today ? hm : `${+ef.slice(6, 8)}일 ${hm}`) : "";
    rows.push(row("예정", "pre", name, `${at ? `<i>${at} 발효</i><br>` : ""}${placeTxt(a)}`, sigsOf(a.land)));
  }
  const bt = ALERTS.base ? String(ALERTS.base).slice(11, 16) : "—";
  const nKind = ALERTS.land.length + ALERTS.sea.length;
  // 평소엔 아이콘만(지도 북서쪽 함양·거창을 가리지 않게). 아이콘이나 머리를 누르면 닫힌다
  TIPS.set("al-now", (ALERTS.calc
      ? `<b>산출 특보</b> — 실제 발표가 아니다. 격자 3시간 · 12시간 합에 호우 기준(주의보 60 · 110 / 경보 90 · 180㎜)을
         적용해 계산했다. 특보 이력 API 가 이 키로 막혀(403) 그때 발표 내역을 담지 못했다.`
      : `<b>기상특보</b> — 기상청 발효 중 특보(1분마다 다시 읽는다, 조회 ${bt}). 예비특보(태풍 · 호우 …)와 발효 예정은 지도에 긋지 않고
         여기에만 — 발효 예상 날짜 · 시간대와 함께.`)
    + `<br>지도 왼쪽 빈자리에 얇게 세로로 — 펼쳐 두면 지도가 그 오른쪽으로 비켜 선다. 특보 아이콘(또는 이 머리)을 누르면 접힌다.`);
  box.innerHTML = `<div class="hd2" id="al-hd" title="끌어서 옮기기(이 화면에 기억, 두 번 누르면 제자리) · ✕ 접기 — 지도가 다시 넓어진다"><b>기상특보${ALERTS.calc ? " · 산출" : ""}</b><i class="inf" data-tip="al-now">i</i><i class="fd" title="접기">✕</i></div>`
    + `<div class="hd3"><span>${nKind ? `${nKind}종 · ` : ""}${test ? "테스트 · " : ""}${ALERTS.calc ? "" : "조회 "}${bt}</span>`
    + (ALERTS.calc ? "" : `<label class="alp" title="예비특보(태풍 · 호우 …) 보이기 — 끄면 발효 중 · 발효 예정만(화면 모두 같이)"><input type="checkbox" id="al-pre"${preOn ? " checked" : ""}>예비${nPre ? ` ${nPre}` : ""}</label>`) + `</div>`
    + (rows.length ? rows.join("") : `<div class="al-none">${ALERTS.calc ? "호우 기준을 넘은 시군 없음" : "발효 중인 특보 없음"}</div>`);
  $("al-hd").querySelector(".fd").onclick = ev => { ev.stopPropagation(); setAlOpen(false); };
  if ($("al-pre")) $("al-pre").onchange = ev => { SET.al_pre = ev.target.checked; saveSetting({ al_pre: SET.al_pre }); renderAlertLegend(); };
  for (const r of box.querySelectorAll(".al[data-s]")) {
    const first = r.dataset.s.split(",")[0];
    r.onmouseenter = () => highlight(first);
    r.onmouseleave = () => highlight(null);
  }
  renderLyIcons();
}

/* ── 관측소(점) — 격자와 **같은 시각**의 실측. 레이어 '관측소'(S) ─────────────────
   ⚠️ 격자(면)는 관측소 사이를 메운 분석값이라 관측소 자리에서도 값이 다르다(봉우리가 깎인다).
      점의 속을 지도와 같은 색 단계로 칠해 둘레 칸과 견주게 한다. 값 글자는 빈자리에만 단다.
   ⚠️ 값이 없는 것을 셋으로 가른다: 0(속 빈 마름모) · 기상청 결측(×) · 그 시각 값을 못 받음(점선).
   위치는 data/geo/stations.json(tools/build_stations.py) — 화면은 기상청을 부르지 않는다. */
let SITES = null, SITEBY = new Map();
let STN = null, STN_SEQ = 0, STN_R = 6, LABELBOX = [];
// 고른 시군 — 오른쪽 패널이 그 시군 읍면동·지점으로 바뀐다. Ctrl(⌘)+클릭으로 더해 비교한다.
// 예전 3곳까지 — 넷 이상 비교하고 싶다는 말에 경남 전부(18)로 풀었다(10-24). 이름이 길어지면 '함양·거창 외 3'
let SELS = [];
const SEL_MAX = 18;
const selOn = () => SELS.length > 0;
const isSel = s => SELS.includes(s);
const selQ = () => SELS.join(",");                // API 에 넘길 때
const selName = () => SELS.length > 3 ? `${SELS.slice(0, 2).join("·")} 외 ${SELS.length - 2}` : SELS.join("·");   // 화면에 적을 때
const multi = () => SELS.length > 1;
let ACC_BASIS = "aws";                   // 누적 카드 기준: aws(관측소 다우지점) | grid(격자 누적 최대 칸)
const STNC = new Map();
const isFcst = k => k === "vsrt" || k.startsWith("shrt");
async function stnFetch(key, tm) {
  const p = new URLSearchParams({ layer: key });
  if (tm) p.set("tm", tm);
  if (test) p.set("test", "1");
  if (CASE) p.set("case", CASE);
  accParams(p, key);
  const ck = p.toString();
  if (STNC.has(ck)) return STNC.get(ck);
  let j;
  try { j = await getJson(`/api/grid/stations?${p}`); }
  catch (e) { return { err: e.message, layer: key }; }
  // 아직 못 받은 시각(none)은 기억하지 않는다 — 수집기가 곧 채운다
  if (j.status !== "none") {
    if (STNC.size > 400) STNC.delete(STNC.keys().next().value);
    STNC.set(ck, j);
  }
  return j;
}
function loadStations() {
  if (!OV.has("stations")) { STN = null; drawStations(); renderStnLegend(); return; }
  const key = layerKey(), tm = isFcst(kind) ? null : CUR?.tm;
  const my = ++STN_SEQ;
  const done = j => { if (my !== STN_SEQ) return; STN = j; drawStations(); renderStnLegend(); };
  const p = new URLSearchParams({ layer: key });
  if (tm) p.set("tm", tm);
  if (test) p.set("test", "1");
  if (CASE) p.set("case", CASE);
  const hit = STNC.get(p.toString());
  if (hit) done(hit);                    // 기억해 둔 시각은 같은 틱에 — 재생할 때 격자와 함께 넘어간다
  else stnFetch(key, tm).then(done);
}
/* 지금 그리는 격자와 같은 층·시각의 관측소 값인가 — 아니면 그리지 않는다(어긋난 시각을 나란히 두지 않는다) */
function stnFresh() {
  return !!STN && !STN.err && STN.layer === layerKey() && (STN.status === "forecast" || STN.tm === CUR?.tm);
}
function drawStations() {
  drawRiver();                           // 하천 · 댐 · 보도 같은 때에 다시 그린다(크기 · 시군 선택 · 확대가 바뀔 때)
  const g = $("stns");
  if (!g) return;
  if (!OV.has("stations") || !V || !V.s || !stnFresh()) { g.innerHTML = ""; drawEmdNames(LABELBOX); return; }
  const steps = stepsOf(kind), css = colsOf(kind), fac = factor(), fc = STN.status === "forecast";
  const r = STN_R = Math.max(4.5, Math.min(12, V.u * 1.05));
  const fs = Math.max(11, Math.min(26, V.u * 3.1));
  const val = s => s.v * fac;
  const has = s => !fc && (s.q === "ok" || s.q === "part");
  const dia0 = (x, y, rr) => `M${x.toFixed(1)},${(y - rr).toFixed(1)}L${(x + rr).toFixed(1)},${y.toFixed(1)}L${x.toFixed(1)},${(y + rr).toFixed(1)}L${(x - rr).toFixed(1)},${y.toFixed(1)}Z`;
  /* 기상청 AWS ◇ · 경남 AWS ○(조금 작게 — 216곳이라 붐빈다). 색 단계는 같다 */
  const circ = (x, y, rr) => `M${(x - rr).toFixed(1)},${y.toFixed(1)}a${rr.toFixed(1)},${rr.toFixed(1)} 0 1,0 ${(2 * rr).toFixed(1)},0a${rr.toFixed(1)},${rr.toFixed(1)} 0 1,0 ${(-2 * rr).toFixed(1)},0Z`;
  let dia = dia0;
  const marks = [], boxes = [];
  for (const s of STN.rows) {
    if (SET.gn_off && s.org === "gn") continue;            // 경남 AWS(내부망) 끔 — 꺼진 표식(빗금 점)을 216곳 깔지 않는다
    dia = s.org === "gn" ? (x, y, rr) => circ(x, y, rr * 0.72) : dia0;
    const x = V.toX(s.x), y = V.toY(s.y), dim = selOn() && !isSel(s.sigun) ? " dim" : "";
    boxes.push({ x0: x - r, x1: x + r, y0: y - r, y1: y + r });
    if (has(s)) {
      const k = stepIdx(val(s), steps);
      marks.push(k ? `<g class="st${dim}"><path d="${dia(x, y, r)}" style="fill:${css[k - 1]}"/></g>`
                   : `<g class="st z${dim}"><path d="${dia(x, y, r * 0.8)}"/></g>`);
    } else if (!fc && s.q === "off") {                     // 비활성화 — 계산에서 뺐다
      const q = r * 0.55;
      marks.push(`<g class="st off${dim}"><path d="${dia(x, y, r * 0.8)}"/>
        <line x1="${(x - q).toFixed(1)}" y1="${(y + q).toFixed(1)}" x2="${(x + q).toFixed(1)}" y2="${(y - q).toFixed(1)}"/></g>`);
    } else if (!fc && s.q === "missing") {
      const q = r * 0.42;
      marks.push(`<g class="st miss${dim}"><path d="${dia(x, y, r * 0.8)}"/>
        <line x1="${(x - q).toFixed(1)}" y1="${(y - q).toFixed(1)}" x2="${(x + q).toFixed(1)}" y2="${(y + q).toFixed(1)}"/>
        <line x1="${(x - q).toFixed(1)}" y1="${(y + q).toFixed(1)}" x2="${(x + q).toFixed(1)}" y2="${(y - q).toFixed(1)}"/></g>`);
    } else marks.push(`<g class="st none${dim}"><path d="${dia(x, y, r * 0.75)}"/></g>`);
  }
  // 값 글자 — 레이어 '지점 강수량 글자'(V)를 켰을 때만. 점만으로도 색 단계는 읽힌다(붐비지 않게 기본은 끔).
  // 센 곳부터, 시군명·특보 딱지·격자 최대 라벨·다른 점·앞 글자와 겹치지 않는 자리에만.
  // 상위 셋은 지점 이름도 단다. 시군을 골랐으면 그 시군 지점만, 이름까지.
  const wet = !OV.has("stnval") ? [] : STN.rows.filter(s => has(s) && val(s) >= steps[0] && (!selOn() || isSel(s.sigun))).sort((a, b) => b.v - a.v);
  const named = new Set(wet.slice(0, 3).map(s => s.stn));
  const placed = LABELBOX.concat(boxes), out = [];
  const hit = b => placed.some(p => b.x0 < p.x1 && b.x1 > p.x0 && b.y0 < p.y1 && b.y1 > p.y0);
  const inside = b => b.x0 >= 4 && b.y0 >= 4 && b.x1 <= V.W - 4 && b.y1 <= V.H - 4;
  const pill = kmaOn();                  // 기상청 색(알록달록) 면 위에서는 글자에 바탕 상자 — 색 칸과 글자가 섞여 보이지 않게
  for (const s of wet) {
    const t = val(s).toFixed(1);         // 숫자만 — 빠진 시각이 있으면 툴팁에(몇 시간 빠졌나)
    const nm = selOn() || named.has(s.stn) ? s.name : "";
    const w = t.length * fs * 0.6 + (nm ? nm.length * fs * 0.98 + fs * 0.3 : 0) + 4, h = fs * 1.2;
    const ax = V.toX(s.x), ay = V.toY(s.y), gap = r + 3;
    let best = null;
    for (const [dx, dy] of [[gap, -h / 2], [-gap - w, -h / 2], [-w / 2, -gap - h], [-w / 2, gap]]) {
      const b = { x0: ax + dx, y0: ay + dy, x1: ax + dx + w, y1: ay + dy + h };
      if (inside(b) && !hit(b)) { best = b; break; }
    }
    if (!best) continue;                 // 자리가 없으면 글자는 뺀다 — 점(색)은 남는다. 마우스를 올리면 값이 나온다
    placed.push(best);
    if (pill) out.push(`<rect class="pill" x="${(best.x0 - 1).toFixed(1)}" y="${best.y0.toFixed(1)}" width="${(best.x1 - best.x0 + 1).toFixed(1)}"
      height="${h.toFixed(1)}" rx="${(h * 0.25).toFixed(1)}"/>`);
    out.push(`<text x="${(best.x0 + 2).toFixed(1)}" y="${(best.y0 + h / 2).toFixed(1)}"
      style="font-size:${fs.toFixed(1)}px;stroke-width:${(fs * 0.2).toFixed(1)}px">${t}${nm ? `<tspan class="n" dx="${(fs * 0.3).toFixed(1)}">${nm}</tspan>` : ""}</text>`);
  }
  g.innerHTML = marks.join("") + `<g class="st">${out.join("")}</g>`;
  drawEmdNames(placed);
}
function renderStnLegend() {
  const box = $("ly-stn");
  if (!OV.has("stations")) { box.hidden = true; return; }
  box.hidden = LY_OPEN !== "stations";
  if (box.hidden) return;
  const d = (fill, stroke, extra = "", dash = "") =>
    `<svg viewBox="-8 -8 16 16"><path d="M0,-6L6,0L0,6L-6,0Z" style="fill:${fill};stroke:${stroke};stroke-width:1.5"${dash ? ` stroke-dasharray="${dash}"` : ""}/>${extra}</svg>`;
  const x = `<path d="M-2.6,-2.6L2.6,2.6M-2.6,2.6L2.6,-2.6" style="stroke:var(--ink-2);stroke-width:1.6;stroke-linecap:round"/>`;
  const n = STN?.rows?.length || SITES?.stations?.length || 0, ngn = (STN?.rows || []).filter(s => s.org === "gn").length;
  const o = (fill, stroke) => `<svg viewBox="-8 -8 16 16"><circle r="4.6" style="fill:${fill};stroke:${stroke};stroke-width:1.5"/></svg>`;
  const keys = `<div class="keys2"><span>${d("var(--rain-4)", "var(--ink)")}기상청</span>${ngn ? `<span>${o("var(--rain-4)", "var(--ink)")}경남</span>` : ""}
    <span>${d("var(--land)", "var(--ink-2)")}0</span><span>${d("none", "var(--ink-3)", x)}결측</span>
    <span>${d("none", "var(--ink-3)", "", "2 2")}값 없음</span></div>`;
  // 범례에는 견본 한 줄과 '못 받음' 같은 경고만 — 출처 · 설명 · 위치 없는 지점은 ⓘ 에
  let nt = "", src = "";
  if (!STN || (!STN.err && !stnFresh())) nt = `<div class="nt">읽는 중…</div>`;
  else if (STN.err) nt = `<div class="nt w">불러오지 못했다 — ${STN.err}</div>`;
  else if (STN.status === "forecast") nt = `<div class="nt">예측 화면 — 자리만</div>`;
  else if (STN.status === "none") nt = `<div class="nt w">${hm(STN.tm)} 값을 아직 못 받았다</div>`;
  else {
    const ok = STN.rows.filter(s => s.q === "ok" || s.q === "part").length;
    const np = STN.rows.filter(s => s.q === "part").length;
    src = `${STN.src} · ${ok}곳 값 있음${np ? ` · ${np}곳은 일부 시각이 빠진 합(실제는 이보다 클 수 있다 — 점에 올리면 몇 시간)` : ""}.<br>`;
  }
  const un = (STN?.unsited || SITES?.missing || []).map(m => `${m.name}(${m.stn})`).join(" · ");
  TIPS.set("stn-now", src
    + `면(격자)은 관측소 사이를 메운 분석값이라 관측소 자리에서도 다르다 — 점에 마우스를 올리면 실측 · 그 칸 격자 · 차이.
       값이 없을 때: ◇ 0 · × 기상청 결측 · 점선 = 그 시각 값을 못 받음(수집기가 격자와 같은 시각으로 받는다).`
    + (un ? `<br>위치 없음: ${un} — 어느 API 에도 값이 없는 지점.` : "")
    + `<br>◇ 기상청 AWS · ○ 경남 AWS(경남 AWS 목록 위치). 경남 AWS 값은 스방(내부망)에서 오는 시간 강우량이라
       누적 · AWS 누적 층에서만 — 15분 · 60분 · 실황 층에서는 자리만(점선).`);
  box.innerHTML = `<div class="hd2" title="눌러서 닫기"><b>관측소</b><span class="k">AWS ${n}곳${ngn ? ` (경남 ${ngn})` : ""}</span><i class="inf" data-tip="stn-now">i</i>`
    + `<span>${STN && !STN.err && STN.tm && STN.status !== "forecast" ? (CASE ? `${md(STN.tm)} ` : "") + hm(STN.tm) : ""}</span></div>`
    + keys + nt;
  box.querySelector(".hd2").onclick = ev => { if (!ev.target.closest(".inf")) setLyOpen(null); };
}
/* 마우스 아래 관측소(지도 좌표 mx,my 에서 가장 가까운 점, 점 크기의 1.5배 안) */
function stationAt(mx, my) {
  if (!OV.has("stations") || !stnFresh() || !V) return null;
  const lim = Math.max(9, STN_R * 1.5);
  let best = null, bd = lim * lim;
  for (const s of STN.rows) {
    const dx = V.toX(s.x) - mx, dy = V.toY(s.y) - my, dd = dx * dx + dy * dy;
    if (dd < bd) { bd = dd; best = s; }
  }
  return best;
}
function stationTip(s) {
  const fac = factor(), gv = valueAt(s.x, s.y), site = SITEBY.get(s.stn);
  const has = s.q === "ok" || s.q === "part";
  const gap = STN.status !== "forecast" && s.q === "part" ? ` · ${s.miss ? `${s.miss}시간` : "일부 시각"} 빠진 합(실제는 이보다 클 수 있다)` : "";
  const obs = STN.status === "forecast" ? "예측 화면" : has ? `${(s.v * fac).toFixed(1)}㎜`
    : s.q === "off" ? `비활성 — 계산에서 뺐다${s.v != null ? `(값 ${(s.v * fac).toFixed(1)}㎜)` : ""} · 오른쪽 클릭으로 다시 켜기`
    : s.q === "missing" ? "결측" : "값 없음";
  const grid = gv === undefined ? "—" : gv === MISSING ? "결측" : `${(gv / 10 * fac).toFixed(1)}㎜`;
  const diff = has && gv !== undefined && gv !== MISSING ? gv / 10 * fac - s.v * fac : null;
  const who = s.org === "gn" ? `경남 AWS · ${s.sigun}${s.place ? ` · ${s.place}` : ""}` : `기상청 AWS ${s.stn} · ${s.sigun} ${site?.emd || ""}`;
  return `<b>${s.name} ${obs}</b>${gap} · ${who}`
    + `<div class="d">그 칸 ${kind === "aws" || kind === "aws60" ? "AWS 면" : "격자"} ${grid}${diff != null ? ` (면 − 관측 ${diff >= 0 ? "+" : ""}${diff.toFixed(1)})` : ""} · 해발 ${Math.round(s.ht || 0)}m${s.addr ? ` · ${s.addr}` : ""}${STN.src ? ` · ${STN.src}` : ""}</div>`;
}


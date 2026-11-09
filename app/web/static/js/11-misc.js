"use strict";
/* ── AWS 비활성화 — 관측소 점 오른쪽 클릭. 주변과 동떨어진 값(진주 한 곳 1㎜, 둘레 12~14㎜ — 고장 · 막힘)을 계산에서 뺀다 ──
   서버 설정 map.aws_off(벽면 화면 · 종합 화면도 같이) — 면(AWS 누적 · 1시간 IDW) · 강수 누적 카드 · 지금 오는 비에서 빠진다.
   점은 남겨(회색 · 빨간 빗금) 툴팁에 그 값을 적는다. 설정(Ctrl+,) › 관측소 에 목록 · 다시 켜기 */
const offList = () => (Array.isArray(SET.aws_off) ? SET.aws_off : []);
const isOff = key => offList().some(x => x.id === key);
function stnPop(close) {
  if (close === null) { $("stn-pop").classList.remove("open"); $("stn-pop").hidden = true; }
}
/* 오른쪽 클릭 메뉴를 마우스 자리에 — .rng-pop 은 zoom: var(--k) 라 left · top 도 k 배로 밀린다. k 로 나눠야 마우스 밑에 뜬다(lgPop 과 같은 식) */
function popAt(pop, ev, rc) {
  const k = V?.k || 1;
  pop.hidden = false;
  const pw = pop.offsetWidth * k, ph = pop.offsetHeight * k;
  pop.style.left = Math.max(4, Math.min(ev.clientX - rc.left, rc.width - pw - 8)) / k + "px";
  pop.style.top = Math.max(4, Math.min(ev.clientY - rc.top, rc.height - ph - 8)) / k + "px";
}
function stnMenu(ev, st) {
  const pop = $("stn-pop"), off = isOff(st.key), rc = $("stage").getBoundingClientRect();
  const v = st.v != null ? `${(+st.v * factor()).toFixed(1)}㎜` : "값 없음";
  pop.innerHTML = `<div class="g">${st.sigun} · ${st.name}</div>`
    + `<div class="note">${st.org === "gn" ? "경남 AWS" : `기상청 AWS ${st.stn}`} · 지금 이 층 ${v}</div>`
    + `<button data-a="t" class="${off ? "on" : ""}">${off ? "다시 켜기 — 계산에 넣기" : "비활성화 — 계산에서 빼기"}</button>`
    + `<div class="note">${off ? "" : "이 지점 없이 둘레 관측소로 면을 다시 메운다(카드 · 지금 오는 비에서도 뺀다). "}목록은 설정(Ctrl+,) › 관측소</div>`
    + kakaoBtns(`${st.name}(AWS)`, ...LCC(st.x, st.y));
  popAt(pop, ev, rc);
  void pop.offsetWidth; pop.classList.add("open");
  kakaoBind(pop);
  pop.querySelector("button").onclick = e => {
    e.stopPropagation(); stnPop(null);
    putOff(off ? offList().filter(x => x.id !== st.key) : [...offList(), { id: st.key, name: st.name, sigun: st.sigun, org: st.org }]);
  };
}
async function putOff(list) {
  SET.aws_off = list;
  try {
    await fetch("/api/settings/map", { method: "PUT", headers: { "Content-Type": "application/json" },
                                       body: JSON.stringify({ aws_off: list }) });
  } catch {}
  // 기억해 둔 면 · 통계 · 관측소 값을 버리고 새로 — 지도 · 재생 흐름 · 카드가 같이 바뀐다
  GRIDS.clear(); STATS.clear(); STNC.clear(); OFF.clear(); EMDC.clear();
  show(); loadFlow(); CARDS = null; loadCards();
}
$("stage").addEventListener("contextmenu", ev => {
  if (CASE || !V || !GEO || ev.target.closest("#tl, #play, #legend, #layers, #rail, #pop, #stn-pop, #sw, #camgrab, #cambar, #tools, #aiw, #showdots")) return;
  const rc = $("stage").getBoundingClientRect();
  const mx = (ev.clientX - rc.left - MT.tx) / MT.sc, my = (ev.clientY - rc.top - MT.ty) / MT.sc;
  const st = stationAt(mx, my);
  if (st && st.key) { ev.preventDefault(); $("tip").hidden = true; stnMenu(ev, st); return; }
  // 지구 · 시군 위 — 상황판단 창으로(왼쪽 클릭은 시군 · 읍면동 고르기라 여기로 옮겼다)
  const dz = districtAt(mx, my)?.dz, sg = sigunAt(V.fromX(mx), V.fromY(my));
  ev.preventDefault();
  $("tip").hidden = true;
  mapMenu(ev, dz, sg, placeAt(mx, my, dz) || { n: "", ll: LCC(V.fromX(mx), V.fromY(my)) });
});
const dzName = dz => dz.name && !/구$/.test(dz.name) && dz.name !== "–" ? dz.name : [dz.ri, dz.jibun].filter(x => x && x !== "–").join(" ") || dz.emd;
/* 오른쪽 클릭한 표식 — 카카오맵 핀에 그 이름 · 그 표식 자리를 쓴다(마우스 자리는 표식 반지름만큼 어긋난다). 없으면 null */
function placeAt(mx, my, dz) {
  const at = h => LCC(V.fromX(h.x), V.fromY(h.y));
  const td = tideAt(mx, my);
  if (td) return { n: `${td.name}(조위관측소)`, ll: LCC(td.x, td.y) };
  const rv = riverAt(mx, my), h = rv && RIV_HIT.find(x => x.s === rv);
  if (h) { const k = rv.kind === "wl" ? "수위관측소" : rv.kind === "dam" ? "댐" : "보";
           return { n: rv.name.endsWith(k) ? rv.name : `${rv.name}(${k})`, ll: at(h) }; }
  const res = safetyAt(mx, my)?.res;
  if (res) return { n: `${res.name}(위험저수지)`, ll: [res.lon, res.lat] };
  if (dz?.pos) return { n: `${dzName(dz)}(${dz.kind || dz.fam})`, ll: [dz.pos[1], dz.pos[0]], q: dzAddr(dz) };
  return null;
}
/* 지구 지번 주소 — 카카오맵 주소 검색용. 위키 칸이 고르지 않다('–', '1313 - 55', '286-1 286-4', '825 일원', '실리도') — 지번은 첫 번호만, 번호가 없으면 글 그대로 */
function dzAddr(dz) {
  const cl = v => { v = String(v ?? "").replace(/\s*일원$/, "").replace(/\s*-\s*/g, "-").trim(); return /^[-–]*$/.test(v) ? "" : v; };
  const j = cl(dz.jibun), jn = j.match(/산?\d+(-\d+)?/)?.[0];
  return ["경남", SG_ORD.find(x => x.startsWith(dz.sigun)) || dz.sigun, cl(dz.emd), cl(dz.ri), jn || j].filter(Boolean).join(" ");
}
/* 카카오맵 지도 · 로드뷰 단추 — 핀은 이름이 있어야 꽂혀서 이름이 없으면 좌표를 이름으로. 쉼표 · / 는 주소 구분자라 뺀다 */
function kakaoBtns(name, lon, lat, q) {
  const ll = `${lat.toFixed(5)},${lon.toFixed(5)}`, n = (name || ll.replace(",", " ")).replace(/[,/]/g, " ");
  return `<div class="g">카카오맵 · ${escH(name || `${lat.toFixed(4)}°N ${lon.toFixed(4)}°E`)}</div>`
    + `<button data-u="https://map.kakao.com/link/map/${encodeURIComponent(n)},${ll}">이 자리 지도로 보기</button>`
    + `<button data-u="https://map.kakao.com/link/roadview/${ll}">이 자리 거리뷰(로드뷰)</button>`
    + (q ? `<button data-u="https://map.kakao.com/link/search/${encodeURIComponent(q)}">주소로 찾기 <small>${escH(q.replace(/^경남 /, ""))}</small></button>` : "");
}
function kakaoBind(pop) {
  for (const b of pop.querySelectorAll("button[data-u]")) b.onclick = e => { e.stopPropagation(); stnPop(null); window.open(b.dataset.u, "_blank", "noopener"); };
}
function mapMenu(ev, dz, sg, pl) {
  const pop = $("stn-pop"), rc = $("stage").getBoundingClientRect();
  const nm = dz && dzName(dz);
  pop.innerHTML = kakaoBtns(pl.n, ...pl.ll, pl.q)
    + (dz || sg ? `<div class="g">상황판단 모드</div>` : "")
    + (dz ? `<button data-a="dz">이 지구 — ${escH(nm || dz.emd)} <small>${escH(dz.kind || dz.fam)}</small></button>` : "")
    + (sg ? `<button data-a="sg">${escH(sg)} 전체</button>` : "")
    + (dz ? `<div class="g">지구 좌표</div><button data-a="fix">이 지구 좌표 확인 · 고치기</button>` : "")
    + (dz || sg ? `<div class="note">별도 창으로 연다(듀얼 모니터). 창이 열려 있으면 그 창이 바뀐다.</div>` : "");
  popAt(pop, ev, rc);
  void pop.offsetWidth; pop.classList.add("open");
  kakaoBind(pop);
  for (const b of pop.querySelectorAll("button:not([data-u])")) b.onclick = e => {
    e.stopPropagation(); stnPop(null);
    if (b.dataset.a === "fix") return dzDlg(true, dz.id);
    if (b.dataset.a === "dz") districtOpen(dz);
    else if (!window.open(`/map.html?sj=1&sig=${encodeURIComponent(sg)}`, "gn-judge", "popup=1,width=1680,height=1000")) toast("팝업이 막혔다 — 이 사이트의 팝업을 허용한다");
  };
}
document.addEventListener("pointerdown", ev => {
  if (!$("stn-pop").hidden && !ev.target.closest?.("#stn-pop")) stnPop(null);
});
/* 초단기예측 이미지 길이(분) — 수집 설정 qpf.ahead(180 · 240 · 300 · 360). 설정 창을 열 때 읽는다 */
let QCFG_AHEAD = null;
async function loadQcfg() { try { QCFG_AHEAD = (await getJson("/api/settings")).qpf?.ahead ?? null; } catch {} }
/* AWS 실시간 감시 — 끄면 AWS 누적 · 1시간이 정시마다, 켜면 마지막 정시 뒤 매분자료까지 1분마다.
   설정은 서버에 둔다(벽면 화면 · 1분 수집기가 같이 본다). 켜면 매분을 곧바로 한 번 받아 기다리지 않게 한다 */
async function setLive(on) {
  if (CASE || test) return;
  SET.aws_live = !!on;
  try {
    await fetch("/api/settings/map", { method: "PUT", headers: { "Content-Type": "application/json" },
                                       body: JSON.stringify({ aws_live: SET.aws_live }) });
    if (on) await fetch("/api/refresh/minute", { method: "POST" });
  } catch {}
  buildMenu(); paintHead();
  await refreshMeta();
  loadCards();
}
/* 새 자료가 왔나 — 30초마다. AWS 누적 · 1시간은 '지금' 칸이 1분마다(매분자료), 격자 누적은 10분마다 바뀐다.
   바뀐 층만 다시 그린다: 보고 있는 층이 바뀌었으면 그 층(재생 중 · 지난 시각을 보는 중이면 그대로), 재생 흐름의
   실측 층(격자 60분 | AWS 1시간)이나 초단기가 바뀌었으면 흐름. ⚠️ 예전에는 아무 층이나 바뀌면 흐름 · 지도를 다 다시 했다 */
async function refreshMeta() {
  if (CASE) return;                       // 사례는 바뀌지 않는다
  let m;
  try { m = await getJson("/api/grid/meta"); } catch { return; }
  const tms = x => Object.fromEntries((x?.layers || []).map(l => [l.id, l.tm]));
  const was = tms(META), now = tms(m);
  const diff = new Set(Object.keys(now).filter(k => now[k] !== was[k]));
  META = m;
  if (!diff.size || test) { buildMenu(); paintHead(); return; }
  if (diff.has(flowSrc() === "aws" ? "aws60" : "obs60") || diff.has("vsrt")) await loadFlow();
  if (!playing && diff.has(kind)) show();
  else { buildMenu(); paintHead(); }
}

/* ── 마우스 — 그 칸 값, 좌표, 읍면동. 지도가 옮겨졌으면(타임라인) 그만큼 되돌려 잰다 ── */
async function loadEmd() {
  if (MEMD) return;
  MEMD = true;
  const r = await fetch("/api/grid/geo/mask_emd.u16.gz");
  MEMD = new Uint16Array(await r.arrayBuffer());
  EMDN = new Map(GEO.emd.map(e => [e.id, e]));
}
function valueAt(gx, gy) {
  if (!CUR) return undefined;
  const g = META.grids;
  let c, r;
  if (CUR.grid === "hr") { c = Math.round(gx) - g.hr.i0; r = Math.round(gy) - g.hr.j0; }
  else {
    const [A, B, C] = g.dfs_to_hr.col, [Dd, E, F] = g.dfs_to_hr.row, det = A * E - B * Dd;
    const x = gx - C, y = gy - F;
    c = Math.round((E * x - B * y) / det) - g.dfs.i0;
    r = Math.round((A * y - Dd * x) / det) - g.dfs.j0;
  }
  if (c < 0 || r < 0 || c >= CUR.w || r >= CUR.h) return undefined;
  return CUR.u[r * CUR.w + c];
}
$("stage").addEventListener("mousemove", ev => {
  // 오른쪽 클릭 메뉴가 열려 있으면 툴팁을 감춘다 — 메뉴를 덮지 않게
  if (!V || !GEO || !$("stn-pop").hidden || ev.target.closest("#tl, #play, #legend, #layers, #rail, #pop, #sw, #camgrab, #cambar, #tools, #aiw, #showdots, #td-pop, .rng-pop")) { $("tip").hidden = true; $("stage").style.cursor = ""; return; }
  const rc = $("stage").getBoundingClientRect(), x = ev.clientX - rc.left, y = ev.clientY - rc.top;
  const mx = (x - MT.tx) / MT.sc, my = (y - MT.ty) / MT.sc;
  const gx = V.fromX(mx), gy = V.fromY(my), v = valueAt(gx, gy), tip = $("tip");
  const td = tideAt(mx, my), sp = td ? null : stationAt(mx, my), rv = sp || td ? null : riverAt(mx, my);
  const sf = td || sp || rv ? null : safetyAt(mx, my) || districtAt(mx, my);
  $("stage").style.cursor = td || sp || rv || sf?.res || sf?.dz || sigunAt(gx, gy) ? "pointer" : "";
  if (td) {                              // 조위 표식 위 — 짧은 요약만. 누르면 팝업
    tip.innerHTML = tideTip(td);
    tip.hidden = false;
    tip.style.left = Math.min(V.W - tip.offsetWidth - 6, x + 16) + "px";
    tip.style.top = Math.max(6, y - tip.offsetHeight - 12) + "px";
    return;
  }
  if (rv || sf) {                        // 하천 · 댐 · 보 위 — 수위 · 기준 수위 · 1시간 변화 · 방류 / 저수지 계측기 · 침수흔적
    tip.innerHTML = rv ? riverTip(rv) : sf.dz ? districtTip(sf.dz) : safetyTip(sf);
    tip.hidden = false;
    tip.style.left = Math.min(V.W - tip.offsetWidth - 6, x + 16) + "px";
    tip.style.top = Math.max(6, y - tip.offsetHeight - 12) + "px";
    return;
  }
  if (sp) {                              // 관측소 위 — 실측과 그 칸 격자를 나란히
    highlight(sp.sigun);
    tip.innerHTML = stationTip(sp);
    tip.hidden = false;
    tip.style.left = Math.min(V.W - tip.offsetWidth - 6, x + 16) + "px";
    tip.style.top = Math.max(6, y - tip.offsetHeight - 12) + "px";
    return;
  }
  const hb = META.grids.hr, c = Math.round(gx) - hb.i0, r = Math.round(gy) - hb.j0;
  const inHr = c >= 0 && r >= 0 && c < hb.w && r < hb.h;
  const sg = inHr && MSIG ? GEO.sigun.find(s => s.id === MSIG[r * hb.w + c]) : null;
  highlight(sg && sg.kind === "gn" ? sg.name : null);
  if (v === undefined) { tip.hidden = true; return; }
  loadEmd();
  let where = "";
  if (MEMD instanceof Uint16Array && inHr) {
    const e = EMDN.get(MEMD[r * hb.w + c]);
    if (e) where = `${e.sigun} ${e.name}`;
  }
  if (!where && sg) where = sg.name;
  const [lon, lat] = LCC(gx, gy), fac = factor();
  const val = v === MISSING ? "결측"
    : fac > 1 ? `${(v / 10 * fac).toFixed(1)}㎜/h 환산</b> (15분 ${(v / 10).toFixed(1)}㎜)<b>`
    : `${(v / 10).toFixed(1)}㎜`;
  const el = OV.has("relief") || OV.has("low") ? elevAt(gx, gy) : null;
  tip.innerHTML = `<b>${val}</b>${where ? " · " + where : ""}${el != null && el > 0 ? `<div>표고 약 <b>${el}m</b>${el <= 10 ? " · 저지대" : ""}</div>` : ""}<div class="d">${lat.toFixed(4)}°N ${lon.toFixed(4)}°E · 칸 ${Math.round(gx)}, ${Math.round(gy)}</div>`;
  tip.hidden = false;
  const tw = tip.offsetWidth, th = tip.offsetHeight;
  tip.style.left = Math.min(V.W - tw - 6, x + 16) + "px";
  tip.style.top = Math.max(6, y - th - 12) + "px";
});
$("stage").addEventListener("mouseleave", () => { $("tip").hidden = true; highlight(null); });
/* 시군을 누르면 고른다 — 오른쪽 패널이 그 시군 읍면동(격자)·지점(AWS)으로 바뀐다. 다시 누르거나 바다를 누르면 푼다.
   Ctrl(⌘)+클릭은 더하기·빼기 — 여러 시군 읍면동을 한 판에 견준다 */
$("stage").addEventListener("click", ev => {
  // 누른 아이콘이 다시 그려지면 ev.target 은 문서에서 빠져 closest 가 헛돈다 — 누른 때의 경로로 본다
  if (!V || !GEO || ev.composedPath().some(e => e.matches?.("#tl, #play, #legend, #rail, #layers, #hud, #tip, #sw, #camgrab, #cambar, #tools, #aiw, #showdots, #td-pop, .rng-pop"))) return;
  const rc = $("stage").getBoundingClientRect();
  const mx = (ev.clientX - rc.left - MT.tx) / MT.sc, my = (ev.clientY - rc.top - MT.ty) / MT.sc;
  if (DZ_PICK) { dzPicked(V.fromX(mx), V.fromY(my)); return; }      // 좌표 고치기 — 지도에서 찍기
  const td = tideAt(mx, my);
  if (td) { tidePop(td, ev.clientX - rc.left, ev.clientY - rc.top); return; }
  const gx = V.fromX(mx), gy = V.fromY(my), sg = sigunAt(gx, gy), add = ev.ctrlKey || ev.metaKey;
  if (CAM && sg && isSel(sg) && EFEAT) {                 // 확대한 시군 안 — 읍면동 고르기(Esc 로 하나씩 물러난다)
    loadEmd().then(() => { const id = emdIdAt(gx, gy); if (id && EMDN.get(id)?.sigun === sg) pickEmd(id, add); });
    return;
  }
  pickSig(sg, add);
});

$("b-tl").onclick = () => setTL(!tlOn);
$("tl-x").onclick = () => setTL(false);
$("tl-stat").onclick = () => { SET.tl_stat = SET.tl_stat === "mean" ? "max" : "mean"; saveSetting({ tl_stat: SET.tl_stat }); buildTL(); };
$("b-prefs").onclick = openPrefs;
$("b-help").onclick = () => ($("help").hidden ? openHelp() : closeHelp());
$("b-ai").onclick = () => aiToggle();

/* ── 기준 근접 알림(화면) — 위키 기준에 70%↑ 가까워졌거나 닿은 곳. 단계가 다르니 팝업을 둘로 나눈다:
   주민대피(긴급대피 > 사전대피) · 긴급통제(통제). 대피가 더 윗단계다([[통제·대피 기준]] 통제 → 사전대피 → 긴급대피) ──
   지도 시군명: 앞에 표식(⚠ 대피 · 🚧 통제) + 색. 시군에 둘 다 있으면 대피 쪽이 이긴다 */
const WG = {
  e: { name: "주민대피", ic: "⚠", stages: ["긴급대피", "사전대피"], title: "주민대피 기준 근접" },
  c: { name: "긴급통제", ic: "🚧", stages: ["통제"], title: "긴급통제 기준 근접" },
};
const WS = { 긴급대피: 3, 사전대피: 2, 통제: 1 };
let WATCH = null, WATCH_OPEN = null;                       // 열린 팝업 e | c | null
let WATCH_MAP = true;                                      // 지도의 시군명에 표식 · 색을 낼지(팝업의 '지도에 표시') — 이 브라우저에 기억
try { WATCH_MAP = localStorage.getItem("gn-map-watchmap") !== "0"; } catch {}
const WATCH_SEEN = { e: new Set(), c: new Set() }, WATCH_BL = new Map();   // 본 시군 · 깜박임 끝 시각
const wAll = g => (WATCH?.items || []).filter(i => WG[g].stages.includes(i.stage));
const wItems = g => wAll(g).filter(i => selHas(i.sigun));    // 시군을 고르면 그 시군만 — 지도 표식(wSigun)은 그대로
function watchBadges() {
  for (const g of ["e", "c"]) {
    const items = wItems(g), n = new Set(items.map(i => i.sigun)).size;
    $("ly-risk-" + g).hidden = !n;
    $("ly-risk-n-" + g).textContent = n;
    if (g === "e") $("ly-risk-e").classList.toggle("mid", !items.some(i => i.stage === "긴급대피"));   // 긴급대피가 없으면(사전대피만) 한 단계 옅게
  }
}
function wEmdPct() {                                       // "시군|읍면동" → 기준에 가장 가까운 조건의 비율(%) — 읍면동 이름 옆에 붙인다
  const m = new Map();
  for (const i of WATCH?.items || []) {
    if (i.pct == null) continue;
    const k = i.sigun + "|" + i.emd;
    m.set(k, Math.min(999, Math.max(m.get(k) || 0, i.pct)));
  }
  return m;
}
const STG_C = { "상시대비": "c0", "초기대응": "c1", "평시": "c0", "평시 및 초기대응": "c0", "준비(관심)": "c1", "비상 1단계": "c2", "비상 2단계": "c3", "비상 3단계": "c4", "비상 2·3단계": "c34" };
const wStg = n => WATCH?.stages?.[n] || null;               // 시군 비상단계(매뉴얼이 위키에 있는 시군만) {stage, auto, why, set, do, ...}
const stgChip = d => d ? `<span class="stg ${STG_C[d.stage] || "c0"}${d.std ? " std" : ""}" title="${escH((d.set ? `수동 입력 — 특보 기준 ${d.auto}: ${d.why}` : d.why) + (d.std ? " · 거제시 매뉴얼 준용(이 시군 매뉴얼은 위키에 아직 없다)" : ""))}">${escH(d.stage)}${d.set ? " ✎" : ""}</span>` : "";
function wSigun() {                                        // 시군 → { g: 'e'|'c', s: 가장 센 단계(1~3), near: 충족 없이 근접만 }
  const out = {};
  for (const i of WATCH?.items || []) {
    const s = WS[i.stage] || 0, g = s >= 2 ? "e" : "c", d = out[i.sigun];
    if (!d || s > d.s || (s === d.s && i.st === "met")) out[i.sigun] = { g, s, near: i.st !== "met" };
  }
  return out;
}
function paintWatch() {
  const sg = WATCH_MAP ? wSigun() : {};
  for (const t of document.querySelectorAll("#over .nm[data-s]")) {
    const n = t.dataset.s, d = sg[n];
    t.classList.remove("s1", "s2", "s3");
    t.classList.toggle("wa", !!d);
    t.classList.toggle("near", !!d?.near);
    t.classList.toggle("bl", !!d && (WATCH_BL.get(n) || 0) > Date.now());
    if (d) t.classList.add("s" + d.s);
    t.textContent = d ? `${WG[d.g].ic} ${n}` : n;
  }
  try { drawStations(); } catch {}                         // 읍면동 이름 옆 기준 N% 를 새 값으로
}
function watchPaintList(g) {
  const pop = $("ly-risk-pop-" + g), items = wItems(g), by = {};
  for (const i of items) (by[i.sigun] ||= []).push(i);
  const top = n => Math.max(...by[n].map(i => WS[i.stage] * 10 + (i.st === "met" ? 5 : 0)));
  const names = Object.keys(by).sort((a, b) => top(b) - top(a));
  const row = i => `<div class="it"><span class="tg s${WS[i.stage]}${i.st === "met" ? "" : " near"}">${i.stage} ${i.st === "met" ? "충족" : "근접"}</span><b>${escH(i.emd)} — ${escH(i.fam)}</b><em>${escH(i.rule)}</em>${i.gap ? `<span class="gp">${escH(i.gap)}</span>` : ""}</div>`;
  pop.innerHTML = `<div class="rh"><b>${WG[g].ic} ${WG[g].title} ${names.length}개 시군</b><span>${WATCH.at} 기준 · ${items.length}건</span><i data-x title="닫기">✕</i></div>`
    + `<label class="rm"><input type="checkbox" data-map ${WATCH_MAP ? "checked" : ""}> 지도에 표시 <small>시군 이름에 ${WG.e.ic} · ${WG.c.ic} 와 색</small></label>`
    + (WATCH.do ? `<div class="rm rdo">도 ${stgChip(WATCH.do)}</div>` : "")
    + names.map(n => `<div class="rg"><div class="s" data-s="${escH(n)}" title="이 시군을 고른다">${escH(n)}${stgChip(wStg(n))}<small>충족 ${by[n].filter(i => i.st === "met").length} · 근접 ${by[n].filter(i => i.st !== "met").length}</small></div>`
      + (wStg(n)?.do ? `<div class="act">${escH(wStg(n).do)}</div>` : "")
      + by[n].slice(0, 8).map(row).join("")
      + (by[n].length > 8 ? `<div class="it"><span></span><em>… 외 ${by[n].length - 8}건</em></div>` : "") + `</div>`).join("")
    + `<div class="nt">${g === "e" ? "긴급대피 = 실황 기준(실제 내린 비) · 사전대피 = 예보 기준. 대피장소 · 근거는 AI 상황판단(I). " : "통제 = 출입 · 통행 제한 단계(대피보다 아래). "}근접 = 기준 수치의 70% 이상. 시군 이름 옆 비상단계는 그 시 매뉴얼(특보 종류 기준) — 도 단계와 별개다. 도 · 시군 모두 기준에 닿으면 그 단계가 된 것으로 보고, 실제와 다르면 특보 아이콘에서 바꾼다. 남은 ㎜ · 닿는 시각은 가장 먼 조건 기준이며, 시각은 예보 시우량을 지금 누적에 더한 값이라 실제보다 이를 수 있다. 판단 · 명령은 권한자 몫 — 기준과의 대조일 뿐이다.</div>`;
}
function watchOpen(g) {                                     // g: 'e' | 'c' | null(닫기)
  if (g && !wItems(g).length) g = null;
  if (g && $("ly-fc-pop") && !$("ly-fc-pop").hidden) fcOpen(false);
  WATCH_OPEN = g;
  for (const k of ["e", "c"]) {
    const b = $("ly-risk-" + k), pop = $("ly-risk-pop-" + k), on = k === g;
    b.setAttribute("aria-expanded", String(on));
    pop.hidden = !on;
    if (on) { watchPaintList(k); pop.style.top = b.offsetTop + "px"; }
  }
}
/* 특보 · 단기예보 한눈에 — 아이콘 하나. 지금 발효된 기상특보(+예비) · 오늘/내일 단기예보 강수 시군별 상위.
   값은 지도 층(오늘 더 올 비 · 내일 올 비)과 같은 /api/grid/sigun — 5km 격자라 시군 최대는 그 시군을 지나는 칸 가운데 가장 큰 값. */
let FC_SEQ = 0;
const fcHm = t => t && t.length >= 10 ? `${+t.slice(4, 6)}.${+t.slice(6, 8)}. ${t.slice(8, 10)}시 발표` : "";
function fcTop(r, n = 5) {
  const rows = (r.rows || []).filter(x => x.kind === "gn" && x.max != null && x.max >= 0.1 && selHas(x.sigun)).sort((a, b) => b.max - a.max).slice(0, n);
  if (!rows.length) return `<div class="fe">비 예보 거의 없음</div>`;
  return rows.map(x => `<div class="fl"><b>${escH(x.sigun)}</b><span>최대 ${x.max}㎜${x.where?.emd ? ` <em>${escH(x.where.emd)}</em>` : ""} <em>평균 ${x.mean}㎜</em></span></div>`).join("");
}
async function fcLoad() {
  const pop = $("ly-fc-pop"), my = ++FC_SEQ;
  pop.innerHTML = `<div class="rh"><b>⛅ 특보 · 단기예보</b><i data-x title="닫기">✕</i></div><div class="fe">불러오는 중…</div>`;
  if (CASE) { pop.innerHTML = `<div class="rh"><b>⛅ 특보 · 단기예보</b><i data-x title="닫기">✕</i></div><div class="fe">재현 사례를 보는 중에는 지금의 특보 · 예보가 아니다 — 사례를 닫으면 나온다.</div>`; return; }
  const [a, t, m, ss] = await Promise.allSettled([getJson("/api/alerts"), getJson("/api/grid/sigun?layer=shrt_today"), getJson("/api/grid/sigun?layer=shrt_tomorrow"), getJson("/api/ai/sigunstage")]);
  if (my !== FC_SEQ) return;
  let al = `<div class="fe">특보를 못 받았다${a.status === "rejected" ? " — " + escH(a.reason?.message || "") : ""}</div>`;
  if (a.status === "fulfilled") {
    const d = a.value?.data || {}, gs = (d.groups || []).filter(g => !selOn() || (!g.sea && g.siguns?.some(isSel))), pd = (d.pending || []).filter(p => selHas(p.sigun));
    al = gs.length ? gs.map(g => `<div class="fl"><b>${escH(g.name)}</b><span>${escH(((g.sea ? g.regions : g.siguns?.length ? g.siguns : g.regions) || []).join(" · ") || "—")}${g.sea ? " <em>바다</em>" : ""}</span></div>`).join("")
                   : `<div class="fe">발효 중인 특보 없음</div>`;
    if (pd.length) al += `<h6>예비특보</h6>` + pd.slice(0, 8).map(p => `<div class="fl"><b>${escH(p.name)}</b><span>${escH(p.reg || p.sigun || "")} <em>${escH(p.when || "")}</em></span></div>`).join("");
    if (d.computed) al += `<div class="fn">특보는 산출값(가상)이다</div>`;
  }
  let st = "";                                              // 비상단계 — 도(특보 난 시군 수) · 시군 매뉴얼이 위키에 있는 시군(그 시에 발효된 특보 종류)
  if (ss.status === "fulfilled") {
    const dOrd = ss.value.do_order, d = ss.value.do || { stage: dOrd[0], auto: dOrd[0], why: "호우특보 없음", set: false, order: dOrd };
    const own = Object.entries(ss.value.sigun || {}).filter(([n, v]) => v && selHas(n));
    const sel = (n, v) => `<select data-stg="${escH(n)}" aria-label="${escH(n)} 비상단계 바꾸기" title="실제 발령은 상황판단회의가 정한다 — 바꾸면 24시간 뒤 저절로 특보 기준으로 돌아간다"><option value="">특보 기준대로 — ${escH(v.auto)}</option>`
      + v.order.map(o => `<option value="${escH(o)}"${v.set && v.stage === o ? " selected" : ""}>${escH(o)}</option>`).join("") + `</select>`;
    const ord = ORDER_GN(), rank = n => ord.indexOf(n);
    own.sort((a, b) => rank(a[0]) - rank(b[0]));
    const act = own.filter(([, v]) => v.stage !== v.order[0] || v.set);
    st = `<h6>비상단계</h6><div class="sg do"><div class="c stg ${STG_C[d.stage] || "c0"}" title="${escH(d.stage)} — ${escH(d.set ? `수동 입력 · 특보 기준 ${d.auto}: ${d.why}` : d.why)}">도 ${escH(d.stage)}${d.set ? " ✎" : ""}${sel("도", d)}</div></div><div class="fl"><span><em>${escH(d.set ? `수동 입력 · 특보 기준 ${d.auto}` : d.why)}</em></span></div>`
      + `<div class="sgl">${[["c0", "평시"], ["c1", "준비"], ["c2", "비상 1"], ["c3", "비상 2"], ["c4", "비상 3"]].map(([c, l]) => `<span><i class="stg ${c}"></i>${l}</span>`).join("")}</div>`
      + `<div class="sg">` + own.map(([n, v]) => `<div class="c stg ${STG_C[v.stage] || "c0"}${v.std ? " std" : ""}" title="${escH(v.stage)} — ${escH(v.set ? `수동 입력 · 특보 기준 ${v.auto}: ${v.why}` : v.why)}">${escH(n)}${v.set ? " ✎" : ""}${sel(n, v)}</div>`).join("") + `</div>`
      + Object.entries(act.reduce((m, [n, v]) => {                    // 같은 단계 · 같은 까닭은 한 줄로 묶는다
        const t = `${escH(v.stage)}${v.set ? ` · 수동 입력(특보 기준 ${escH(v.auto)})` : ""}: ${escH(v.why)}<br><em>${escH(v.do)}</em>`;
        (m[t] ||= []).push(n);
        return m;
      }, {})).map(([t, ns]) => `<div class="ad"><b>${ns.map(escH).join(" · ")}</b><span>${t}</span></div>`).join("")
      + `<div class="fn" id="stg-msg">칸을 누르면 바꾼다(✎). 도 단계 = 특보가 난 시군 수 · 시군 단계 = 그 시에 발효된 특보 종류. 두 기준은 별개다. 기준에 닿으면 그 단계가 된 것으로 보고, 실제 발령이 다르면 바꾼다 — 24시간 뒤 저절로 돌아온다.
        거제 · 통영은 자기 매뉴얼(2026.10.), 나머지 시군은 거제 기준을 준용(점선 둘레 — 그 시군 매뉴얼이 위키에 들어오면 바꾼다).</div>`;
  }
  const day = (r, lab) => r.status === "fulfilled"
    ? `<h6>${lab} <em>${escH(fcHm(r.value.tmfc))}</em></h6>` + fcTop(r.value) + (r.value.capped > 0 ? `<div class="fn">30㎜ 이상 든 칸 ${r.value.capped} — 합계는 하한</div>` : "")
    : `<h6>${lab}</h6><div class="fe">${escH(r.reason?.message || "단기예보 격자가 아직 없다")}</div>`;
  pop.innerHTML = `<div class="rh"><b>⛅ 특보 · 단기예보</b><span>${escH(a.value?.data?.base_time || a.value?.base_time || "")}</span><i data-x title="닫기">✕</i></div>`
    + `<h6>기상특보</h6>${al}` + st + day(t, "오늘 더 올 비") + day(m, "내일 올 비")
    + `<div class="fn">단기예보는 3시간마다 발표(5km 격자) · 시군 값은 그 시군을 지나는 칸 가운데 최대 · 오늘은 발표 뒤 남은 시간만. 지도에서는 층 메뉴의 단기 예보(오늘 · 내일).</div>`;
}
function fcOpen(on) {
  const b = $("ly-fc"), pop = $("ly-fc-pop");
  b.setAttribute("aria-expanded", String(on));
  pop.hidden = !on;
  if (on) { watchOpen(null); pop.style.top = b.offsetTop + "px"; fcLoad(); }
}
$("ly-fc").onclick = () => fcOpen($("ly-fc-pop").hidden);
$("ly-fc-pop").addEventListener("click", ev => { if (ev.target.closest("[data-x]")) fcOpen(false); });
$("ly-fc-pop").addEventListener("change", async ev => {      // 사람이 시군 비상단계를 바꾼다(빈 값 = 특보 기준대로)
  const sel = ev.target.closest("select[data-stg]");
  if (!sel) return;
  sel.disabled = true;
  try {
    const r = await fetch("/api/ai/sigunstage", { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sigun: sel.dataset.stg, stage: sel.value || null }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
    await loadWatch();                                       // 칩을 새 값으로
    fcLoad();
  } catch (e) {
    sel.disabled = false;
    const m = $("stg-msg");
    if (m) m.textContent = "바꾸지 못했다 — " + e.message;
  }
});
async function loadWatch() {
  try { WATCH = await getJson("/api/ai/watch"); } catch { return; }
  let fresh = null;
  for (const g of ["e", "c"]) {
    const has = new Set(wAll(g).map(i => i.sigun));
    for (const n of has) if (!WATCH_SEEN[g].has(n)) { WATCH_SEEN[g].add(n); WATCH_BL.set(n, Date.now() + 25000); fresh ||= g; }
    for (const n of [...WATCH_SEEN[g]]) if (!has.has(n)) WATCH_SEEN[g].delete(n);       // 사라졌다 다시 생기면 새로
  }
  watchBadges();
  paintWatch();
  if (fresh) { watchOpen(WATCH_OPEN === "e" ? "e" : fresh); setTimeout(paintWatch, 26000); }   // 새로 생겼으면 그 목록을 펼친다
  else if (WATCH_OPEN) watchOpen(wItems(WATCH_OPEN).length ? WATCH_OPEN : null);
}
for (const g of ["e", "c"]) {
  $("ly-risk-" + g).onclick = () => watchOpen(WATCH_OPEN === g ? null : g);
  $("ly-risk-pop-" + g).addEventListener("click", ev => {
    if (ev.target.closest("[data-x]")) return watchOpen(null);
    if (ev.target.matches("[data-map]")) {
      WATCH_MAP = ev.target.checked;
      try { localStorage.setItem("gn-map-watchmap", WATCH_MAP ? "1" : "0"); } catch {}
      return paintWatch();
    }
    const s = ev.target.closest(".s[data-s]");
    if (s) setSel([s.dataset.s]);
  });
}
setTimeout(loadWatch, 2500);
setInterval(loadWatch, 150000);
$("aiw-x").onclick = () => aiToggle(false);
$("aiw-re").onclick = () => aiLoad();
$("aiw-all").onclick = () => selectSig(null);
$("aiw-q").onclick = ev => { const b = ev.target.closest("[data-q]"); if (b) aiAsk({ q: b.dataset.q }, b.textContent); };
$("aiw-md").onclick = ev => {
  const b = ev.target.closest("[data-m]");
  if (!b || b.dataset.m === AIW.mode) return;
  AIW.mode = b.dataset.m;
  try { localStorage.setItem("gn-ai-mode", AIW.mode); } catch {}
  aiLoad();
};
$("aiw-f").onsubmit = ev => {
  ev.preventDefault();
  const t = $("aiw-in").value.trim();
  if (!t) return;
  $("aiw-in").value = "";
  aiAsk({ text: t }, t);
};
$("aiw-in").addEventListener("keydown", ev => { if (ev.key === "Escape") { ev.stopPropagation(); aiToggle(false); } });
$("acc-h").onclick = toggleBasis;
$("acc-fc").onclick = ev => { ev.stopPropagation(); toggleAccFc(); };
$("acc-sub").onclick = ev => { if ($("acc-sub").classList.contains("pick")) { ev.stopPropagation(); rangePop(); } };
document.addEventListener("pointerdown", ev => {
  if (!$("acc-rng").hidden && !ev.target.closest?.("#acc-rng, #acc-sub")) rangePop(false);
});
$("acc-h1").onclick = ev => { ev.stopPropagation(); toggleAccH1(); };
/* 위 카드 패널 가득 — 아래 두 카드를 감춘다(서버 설정 acc_full — 벽면 화면도 같이). 다시 누르면 돌아온다 */
function applyAccFull() {
  const on = !!SET.acc_full, q = qpfOn();
  $("rail").classList.toggle("accfull", on);
  $("acc-full").classList.toggle("on", on); $("acc-full").setAttribute("aria-pressed", on);
  $("rail").classList.toggle("qpf", q);
  $("acc-qpf").hidden = !!CASE;
  $("acc-qpf").classList.toggle("on", q); $("acc-qpf").setAttribute("aria-pressed", q);
  if (q && !on) loadQpf(); else qpfStop(true);
}
function toggleAccFull() {
  SET.acc_full = !SET.acc_full;
  saveSetting({ acc_full: SET.acc_full });
  applyAccFull();
  if (CARDS && !CARDS.err) renderCards();     // 줄 수는 카드 높이로 정한다 — 늘어난 만큼 다시 채운다
}
$("acc-full").onclick = ev => { ev.stopPropagation(); toggleAccFull(); };
/* 강수 누적 머리 고정(서버 설정 acc_hdr_pin — 벽면 화면도 같이). 끄면 평소에는 시군 줄만 */
function applyHdrPin() {
  const pin = SET.acc_hdr_pin !== false;
  $("c-acc").classList.toggle("hdr-auto", !pin);
  $("acc-pin").classList.toggle("on", pin); $("acc-pin").setAttribute("aria-pressed", pin);
}
$("acc-pin").onclick = ev => {
  ev.stopPropagation();
  SET.acc_hdr_pin = SET.acc_hdr_pin === false;
  saveSetting({ acc_hdr_pin: SET.acc_hdr_pin });
  applyHdrPin();
};
/* 지도 출처 줄 — 누르면 접고(작은 '출처 ▸') 다시 누르면 편다 */
{
  let fold = false;
  try { fold = localStorage.getItem("gn-map-lsrc") === "0"; } catch {}
  $("lsrc").classList.toggle("fold", fold);
  $("lsrc").title = "눌러서 출처 줄 접기 · 펴기";
  $("lsrc").onclick = () => {
    fold = !fold;
    $("lsrc").classList.toggle("fold", fold);
    try { localStorage.setItem("gn-map-lsrc", fold ? "0" : "1"); } catch {}
  };
}

/* ── 초단기예측 이미지 재생(Q) — 오른쪽 아래, 지금 오는 비 · 예측 상위 대신. 종합 화면 오른쪽 위 '예측 분포 재생'과 같은 그림
   (기상청 초단기 QPF B 융합, 10분 간격 +10~+360분, 서버가 경남 광역으로 잘라 둔 것 — /api/qpf/<발표>/<ef>.png).
   평소에는 따로 돈다(스스로 재생). **지도를 재생하는 동안만** 지도 프레임과 같은 시각의 그림으로 따라간다 —
   지도가 실측 구간이면 첫 그림에 멈춰 '예측은 HH:MM부터'라 적는다(그림은 예측뿐이다). 재생을 멈추면 다시 따로.
   재현 사례에는 그때 그림이 없어 쓰지 않는다 */
const qpfOn = () => !CASE && !!SET.acc_qpf;
const QPF = { tmfc: null, efs: [], urls: [], idx: 0, timer: null, play: false, lay: 0, sync: false, was: false, cache: [] };
const qpfTime = i => QPF.tmfc ? tOf(QPF.tmfc) + (QPF.efs[i] || 0) * 60e3 : null;
const hmOf = ms => { const d = new Date(ms); return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; };
async function loadQpf() {
  if (!qpfOn()) return;
  let j;
  try { j = await getJson("/api/qpf"); } catch { j = { tmfc: null, frames: [] }; }
  if (j.tmfc !== QPF.tmfc || (j.frames || []).length !== QPF.efs.length) {
    QPF.tmfc = j.tmfc; QPF.efs = j.frames || [];
    QPF.urls = QPF.efs.map(ef => `/api/qpf/${j.tmfc}/${ef}.png`);
    // 미리 받아 풀어 둔다 — 처음 얹는 순간 압축을 푸느라 멈추지 않게(종합 화면과 같다)
    QPF.cache = QPF.urls.map(u => { const im = new Image(); im.src = u; im.decode?.().catch(() => {}); return im; });
    if (QPF.idx >= QPF.efs.length) QPF.idx = 0;
    $("qpf-seek").max = Math.max(0, QPF.efs.length - 1);
  }
  if (!QPF.play && !QPF.sync && !QPF.stopped && QPF.efs.length > 1) qpfStart();   // 벽면 화면 — 켜면 돈다
  if (!QPF.lg) qpfLegend();
  qzApply();
  drawQpf();
}
/* 범례 — 기상청 원본 그림에서 뽑아 둔 색 · 경계(약한 것부터 온다 — 센 것을 위로 뒤집는다). 눈금은 띄엄띄엄.
   한 칸의 아래 경계가 그 값이다(그 값부터 그 색) */
const QPF_TICKS = [0.1, 1, 5, 10, 20, 30, 50, 110];
async function qpfLegend() {
  const el = $("qpf-scale");
  if (!QPF.lg) { try { QPF.lg = await getJson("/api/qpf/legend"); } catch { QPF.lg = null; } }
  if (!QPF.lg) { el.innerHTML = `<div class="none">범례를 아직 못 받았다 — 다음 발표분에 채워진다</div>`; return; }
  const { colors, bounds, unit } = QPF.lg, n = colors.length;
  const top = [...colors].reverse(), lab = [...bounds].reverse();
  el.innerHTML = `<div class="u">${unit || "mm/h"}</div><div class="sc">
    <div class="tk">${lab.map((v, i) => `<span>${QPF_TICKS.includes(+v) && i === lab.lastIndexOf(v) ? `<b>${v}</b>` : ""}</span>`).join("")}</div>
    <div class="bar">${top.map(c => `<i style="background:${c}"></i>`).join("")}</div></div>`;
}
function qpfShow() {
  const lays = $("qpf-box").querySelectorAll(".qpf-lay"), src = QPF.urls[QPF.idx];
  if (!src) { lays.forEach(l => { l.style.backgroundImage = "none"; l.dataset.src = ""; }); return; }
  const cur = lays[QPF.lay];
  if (cur.dataset.src !== src) {
    const nx = lays[QPF.lay ^ 1];
    if (nx.dataset.src !== src) { nx.style.backgroundImage = `url("${src}")`; nx.dataset.src = src; }
    nx.style.opacity = "1"; cur.style.opacity = ".004"; QPF.lay ^= 1;
  }
  const after = QPF.urls[(QPF.idx + 1) % QPF.urls.length], hid = lays[QPF.lay ^ 1];
  if (after && hid.dataset.src !== after) { hid.style.backgroundImage = `url("${after}")`; hid.dataset.src = after; }
}
function drawQpf(note = "") {
  if (!qpfOn()) return;
  const n = QPF.efs.length;
  qpfShow();
  $("qpf-t").textContent = n ? hmOf(qpfTime(QPF.idx)) : "—";
  $("qpf-ef").textContent = n ? `+${QPF.efs[QPF.idx]}분` : "";
  $("qpf-fc").textContent = QPF.tmfc ? `${hm(QPF.tmfc)} 발표` : "";
  $("qpf-bt").textContent = QPF.tmfc ? `${hm(QPF.tmfc)} 발표` : "—";
  $("qpf-seek").value = QPF.idx;
  $("qpf-play").textContent = QPF.play ? "❚❚" : "▶";
  $("qpf-play").disabled = QPF.sync || n < 2;
  $("qpf-seek").disabled = QPF.sync;
  const sy = $("qpf-sync");
  sy.textContent = QPF.sync ? "지도 재생과 같이" : n ? "따로 재생" : "";
  sy.classList.toggle("sync", QPF.sync);
  $("qpf-note").textContent = !n ? "초단기예측 이미지를 아직 받지 못했다 — 수집기가 다음 발표분을 기다리는 중이다" : note;
  $("qpf-box").classList.toggle("dim", !!note);
}
function qpfStart() {
  if (QPF.efs.length < 2) return;
  clearInterval(QPF.timer);
  QPF.play = true; QPF.stopped = false;
  QPF.timer = setInterval(() => { QPF.idx = (QPF.idx + 1) % QPF.efs.length; drawQpf(); }, +SET.qpf_ms || 600);
  drawQpf();
}
function qpfStop(quiet) {
  clearInterval(QPF.timer); QPF.timer = null; QPF.play = false;
  if (!quiet) drawQpf();
}
/* 지도 재생과 같이 — 지도 프레임 시각(ms)에 가장 가까운 그림. 실측 구간이면 첫 그림에 멈춰 적는다 */
function qpfFollow(t) {
  if (!QPF.sync || !QPF.efs.length || t == null) return;
  const ts = QPF.efs.map((_, i) => qpfTime(i));
  let i = 0, bd = Infinity;
  ts.forEach((x, k) => { const d = Math.abs(x - t); if (d < bd) { bd = d; i = k; } });
  QPF.idx = i;
  const early = t < ts[0] - 5 * 60e3, late = t > ts.at(-1) + 5 * 60e3;
  drawQpf(early ? `지도는 실측 ${hmOf(t)} — 초단기예측 이미지는 ${hmOf(ts[0])}부터` : late ? `초단기예측 이미지는 ${hmOf(ts.at(-1))}까지` : "");
}
function qpfSyncOn() {
  if (!qpfOn() || QPF.sync) return;
  QPF.was = QPF.play; qpfStop(true); QPF.sync = true;
}
function qpfSyncOff() {
  if (!QPF.sync) return;
  QPF.sync = false;
  if (QPF.was) qpfStart(); else drawQpf();
}
function toggleQpf() {
  if (CASE) return;
  SET.acc_qpf = !SET.acc_qpf;
  saveSetting({ acc_qpf: SET.acc_qpf });
  if (SET.acc_qpf && SET.acc_full) { SET.acc_full = false; saveSetting({ acc_full: false }); }   // 둘은 함께 쓸 수 없다
  applyAccFull();
  if (SET.acc_qpf && playing) { qpfSyncOn(); qpfFollow(headT()); }
  if (CARDS && !CARDS.err) renderCards();
}
$("acc-qpf").onclick = ev => { ev.stopPropagation(); toggleQpf(); };
/* 확대 · 옮기기 — 휠은 커서 자리를 기준으로 확대 · 축소, 왼쪽 끌기로 옮기고, 두 번 누르면 처음 크기(판을 꽉 채우는 배율 —
   그림 둘레 여백이 빠진다). 배율 · 자리는 판 크기에 대한 비율로 이 화면(브라우저)마다 기억한다 */
const QPF_R = 950 / 800;                                  // 서버가 잘라 둔 그림 비율(경남 광역)
const QZ = { z: null, fx: 0, fy: 0 };
try { Object.assign(QZ, JSON.parse(localStorage.getItem("gn-map-qpfzoom") || "{}")); } catch {}
function qzCover() {                                      // 판을 꽉 채우는 배율(contain 그림을 cover 로)
  const b = $("qpf-box"), W = b.clientWidth || 1, H = b.clientHeight || 1;
  return W / H > QPF_R ? W / (H * QPF_R) : H / (W / QPF_R);
}
function qzApply(save) {
  const b = $("qpf-box"), W = b.clientWidth || 1, H = b.clientHeight || 1;
  if (QZ.z == null) { QZ.z = qzCover(); QZ.fx = (1 - QZ.z) / 2; QZ.fy = (1 - QZ.z) / 2; }
  QZ.z = Math.max(1, Math.min(8, QZ.z));
  QZ.fx = Math.min(0, Math.max(1 - QZ.z, QZ.fx));         // 판 밖으로 끌려 나가지 않게
  QZ.fy = Math.min(0, Math.max(1 - QZ.z, QZ.fy));
  $("qpf-view").style.transform = `translate(${(QZ.fx * W).toFixed(1)}px, ${(QZ.fy * H).toFixed(1)}px) scale(${QZ.z.toFixed(3)})`;
  if (save) try { localStorage.setItem("gn-map-qpfzoom", JSON.stringify(QZ)); } catch {}
}
{
  const view = $("qpf-view"), box = $("qpf-box");
  box.addEventListener("wheel", ev => {
    ev.preventDefault(); ev.stopPropagation();
    if (QZ.z == null) qzApply();
    const r = box.getBoundingClientRect(), cx = (ev.clientX - r.left) / r.width, cy = (ev.clientY - r.top) / r.height;
    const z1 = Math.max(1, Math.min(8, QZ.z * (ev.deltaY < 0 ? 1.15 : 1 / 1.15)));
    QZ.fx = cx - (cx - QZ.fx) * z1 / QZ.z;                // 커서 밑 자리가 그대로 남게
    QZ.fy = cy - (cy - QZ.fy) * z1 / QZ.z;
    QZ.z = z1;
    qzApply(true);
  }, { passive: false });
  let drag = null;
  view.addEventListener("pointerdown", ev => {
    if (ev.button !== 0) return;
    if (QZ.z == null) qzApply();
    drag = { x: ev.clientX, y: ev.clientY, fx: QZ.fx, fy: QZ.fy };
    view.setPointerCapture(ev.pointerId); view.classList.add("drag");
  });
  view.addEventListener("pointermove", ev => {
    if (!drag) return;
    const r = box.getBoundingClientRect();
    QZ.fx = drag.fx + (ev.clientX - drag.x) / r.width;
    QZ.fy = drag.fy + (ev.clientY - drag.y) / r.height;
    qzApply();
  });
  const up = () => { if (!drag) return; drag = null; view.classList.remove("drag"); qzApply(true); };
  view.addEventListener("pointerup", up);
  view.addEventListener("pointercancel", up);
  view.addEventListener("dblclick", () => { QZ.z = null; qzApply(true); });
  new ResizeObserver(() => { if (qpfOn()) qzApply(); }).observe(box);
}
$("qpf-play").onclick = () => { if (QPF.sync) return; if (QPF.play) { qpfStop(); QPF.stopped = true; } else qpfStart(); };
$("qpf-seek").oninput = ev => { if (QPF.sync) return; qpfStop(); QPF.stopped = true; QPF.idx = +ev.target.value; drawQpf(); };
/* 위 카드 우클릭 — 줄 세우기: 시군당 1 · 2 · 3곳 / 시군 무관(전 지점 순위). 종합 화면 강수 타임라인과 같은 말 */
function accCtx(ev) {
  const pop = $("acc-ctx");
  if (!ev) { pop.classList.remove("open"); pop.hidden = true; return; }
  const opts = [[1, "시군당 1곳"], [2, "시군당 2곳"], [3, "시군당 3곳"], [0, "시군 무관 · 전 지점 순위"]];
  pop.innerHTML = `<div class="g">줄 세우기</div>`
    + opts.map(([n, l], i) => `<button data-n="${n}" class="${accPer() === n ? "on" : ""}" style="--i:${i}">${l}</button>`).join("")
    + `<div class="sep"></div><button data-a="full" class="${SET.acc_full ? "on" : ""}">패널 가득 <small>(G)</small></button>`
    + `<button data-a="qpf" class="${SET.acc_qpf ? "on" : ""}">아래에 초단기예측 이미지 재생 <small>(Q)</small></button>`
    + (selOn() ? `<div class="note">시군을 고른 동안은 그 시군 것을 전부 보인다 — 줄 세우기는 경남 전체에서</div>` : "");
  const cb = $("c-acc").getBoundingClientRect(), k = V?.k || 1;
  pop.hidden = false;
  const pw = pop.offsetWidth * k, ph = pop.offsetHeight * k;
  pop.style.left = Math.max(4, Math.min(ev.clientX - cb.left, cb.width - pw - 4)) / k + "px";
  pop.style.top = Math.max(4, Math.min(ev.clientY - cb.top, cb.height - ph - 4)) / k + "px";
  void pop.offsetWidth; pop.classList.add("open");
  for (const b of pop.querySelectorAll("button")) b.onclick = e => {
    e.stopPropagation();
    accCtx(null);
    if (b.dataset.a === "full") { toggleAccFull(); return; }
    if (b.dataset.a === "qpf") { toggleQpf(); return; }
    const n = +b.dataset.n;
    if (n === accPer()) return;
    SET.acc_per = n; saveSetting({ acc_per: n });
    CARDS = null; loadCards();                // 1곳 ↔ 여러 곳은 받는 자료가 다르다(시군 줄 ↔ 지점 · 읍면동 줄)
  };
}
$("c-acc").addEventListener("contextmenu", ev => { if (CASE) return; ev.preventDefault(); rangePop(false); accCtx(ev); });
document.addEventListener("pointerdown", ev => {
  if (!$("acc-ctx").hidden && !ev.target.closest?.("#acc-ctx")) accCtx(null);
});
$("acc-sel").onclick = ev => { ev.stopPropagation(); selectSig(null); };
document.addEventListener("keydown", ev => {
  if (ev.target.closest?.("input, textarea")) return;
  if (lmenuKey(ev)) return;
  if ((ev.ctrlKey || ev.metaKey) && ev.key === ",") { ev.preventDefault(); $("prefs").hidden ? openPrefs() : closePrefs(); return; }
  if (CAM_EDIT && (ev.key === "Escape" || ev.key === "Enter")) { camEdit(false); return; }
  if (CAM_EDIT && ev.key === "0") { camReset(); return; }
  if (ev.key === "Escape") {
    if (DZ_PICK) { const id = DZ_PICK; DZ_PICK = null; dzDlg(true, id); return; }
    if (dzDlgOpen()) { dzDlg(false); return; }
    if (!$("acc-ctx").hidden) { accCtx(null); return; }
    if (!$("lg-pop").hidden) { lgPop(null); return; }
    if (!$("sw-ctx").hidden) { $("sw-ctx").classList.remove("open"); $("sw-ctx").hidden = true; return; }
    if (!$("stn-pop").hidden) { stnPop(null); return; }
    if ($("td-pop") && !$("td-pop").hidden) { tidePop(null); return; }
    if (!$("showdlg").hidden) { closeShowDlg(); return; }
    if (AIW.open) { aiToggle(false); return; }
    if (SJ.open) { sjToggle(false); return; }
    if (!$("prefs").hidden) closePrefs(); else if (!$("help").hidden) closeHelp(); else if (ESEL.length) pickEmd(null); else if (selOn()) selectSig(null); else if (SHOW.on) stopShow();
    return;
  }
  if (ev.key === "?") { $("help").hidden ? openHelp() : closeHelp(); return; }
  if (!$("prefs").hidden || !$("help").hidden || ev.ctrlKey || ev.metaKey || ev.altKey) return;
  const i = (CASE ? "12" : "123456").indexOf(ev.key);
  if (i >= 0) { stopPlay(); if (HEAT) setHeat(false); pickLayer(keyKind(i)); }
  else if ((ev.key === "t" || ev.key === "T") && !CASE) setTest(!test);
  else if ((ev.key === "i" || ev.key === "I") && !CASE) aiToggle();
  else if (ev.key === "l" || ev.key === "L") setTL(!tlOn);
  else if (ev.key === "c" || ev.key === "C") camEdit(!CAM_EDIT);
  else if ((ev.key === "p" || ev.key === "P") && !CASE) (SHOW.on ? stopShow() : showQuick());
  else if (ev.key === "w" || ev.key === "W") setSw(SW_MODES[(SW_MODES.indexOf(swMode()) + 1) % SW_MODES.length]);
  else if (ev.key === "a" || ev.key === "A") setOverlay("alerts", !OV.has("alerts"));
  else if (ev.key === "s" || ev.key === "S") setOverlay("stations", !OV.has("stations"));
  else if ((ev.key === "v" || ev.key === "V") && OV.has("stations")) setOverlay("stnval", !OV.has("stnval"));
  else if (ev.key === "d" || ev.key === "D") setOverlay("river", !OV.has("river"));
  else if (ev.key === "j" || ev.key === "J") setOverlay("slide", !OV.has("slide"));
  else if (ev.key === "x" || ev.key === "X") sjToggle();
  else if (ev.key === "k" || ev.key === "K") setOverlay("reservoir", !OV.has("reservoir"));
  else if (ev.key === "u" || ev.key === "U") setOverlay("district", !OV.has("district"));
  else if (ev.key === "n" || ev.key === "N") setOverlay("flood", !OV.has("flood"));
  else if (ev.key === "o" || ev.key === "O") setOverlay("tide", !OV.has("tide"));
  else if (ev.key === "e" || ev.key === "E") setOverlay("temp", !OV.has("temp"));
  else if (ev.key === "y" || ev.key === "Y") setOverlay("relief", !OV.has("relief"));
  else if (ev.key === "z" || ev.key === "Z") setOverlay("low", !OV.has("low"));
  else if ((ev.key === "m" || ev.key === "M") && !CASE) setHeat(!HEAT);
  else if (ev.key === "b" || ev.key === "B") toggleBasis();
  else if (ev.key === "f" || ev.key === "F") toggleAccFc();
  else if (ev.key === "h" || ev.key === "H") toggleAccH1();
  else if ((ev.key === "g" || ev.key === "G") && tlOn && SET.panel !== "timeline") toggleAccFull();
  else if ((ev.key === "r" || ev.key === "R") && !CASE && !test) setLive(!awsLive());
  else if ((ev.key === "q" || ev.key === "Q") && !CASE && tlOn && SET.panel !== "timeline") toggleQpf();
  else if (ev.key === " " && FLOWK.has(kind)) { ev.preventDefault(); playing ? stopPlay() : startPlay(); }
  else if ((ev.key === "ArrowRight" || ev.key === "ArrowLeft") && FLOW && FLOWK.has(kind)) {
    stopPlay();
    const n = FLOW.frames.length, j = curFrame();
    seek(((j < 0 ? 0 : j) + (ev.key === "ArrowRight" ? 1 : -1) + n) % n);
  }
});

/* 창 크기뿐 아니라 판 크기가 바뀔 때마다(가려졌다 보일 때 포함) 다시 짠다 */
let rsz = null;
const relayout = () => {
  clearTimeout(rsz);
  rsz = setTimeout(() => { if (!GNB) return; layout(); draw(); buildTL(); }, 120);
};
window.addEventListener("resize", relayout);
new ResizeObserver(relayout).observe($("stage"));
// 누적 카드는 남는 높이를 다 쓴다 — 다른 카드가 늦게 자리 잡으면(글꼴이 늦게 오는 등) 줄 수를 다시 센다.
// ⚠️ 이게 없으면 처음 잰 낮은 높이로 굳어 아래가 빈 채 '외 8곳'이 나왔다(헤드리스 실측)
let accH = 0, accRz = null;
new ResizeObserver(() => {
  const h = $("acc-b").clientHeight;
  if (Math.abs(h - accH) < 2) return;
  accH = h;
  clearTimeout(accRz);
  accRz = setTimeout(() => { if (CARDS && !CARDS.err && tlOn && SET.panel !== "timeline") { renderAcc(); drawRanks(); cardsPlayhead(); } }, 80);
}).observe($("acc-b"));

/* 자료를 서버(언레이드)에서 받는 중이면 머리에 표시 — 설정은 종합 화면(Ctrl+,) › 자료 */
async function originBadge() {
  try {
    const o = await getJson("/api/origin");
    if (o.mode === "server") ORIGIN_BADGE = `<span class="badge srv" title="자료를 서버(${o.url})에서 받는 중 — 종합 화면 설정 › 자료">서버</span>`;
  } catch {}
}
let ORIGIN_BADGE = "";
async function boot() {
  applyTheme();
  await originBadge();
  try {
    [META, TOPO, GEO, SITES] = await Promise.all([getJson("/api/grid/meta"),
      getJson("/api/grid/geo/gyeongnam.topo.json"), getJson("/api/grid/geo/grids.json"),
      getJson("/api/grid/geo/stations.json").catch(() => null)]);    // 없어도 지도는 뜬다(관측소 층만 빈다)
    SITEBY = new Map((SITES?.stations || []).map(s => [s.stn, s]));
    MSIG = new Uint8Array(await (await fetch("/api/grid/geo/mask_sigun.u8.gz")).arrayBuffer());
    glInit();                            // 지도(WebGL) — 못 쓰는 PC 면 여기서 까닭을 띄운다
  } catch (e) {
    $("empty").innerHTML = `지도를 띄울 수 없다<small>${e.message}</small>`;
    $("empty").className = "fail"; $("empty").hidden = false;
    return;
  }
  FEAT = topojson.feature(TOPO, TOPO.objects.sigun).features;
  SET = { ...SET_DEFAULT, ...(META.setting || {}) };
  if (CASE) {
    try { await loadCase(); }
    catch (e) {
      $("empty").innerHTML = `사례를 띄울 수 없다<small>${e.message}</small>`;
      $("empty").className = "fail"; $("empty").hidden = false;
      return;
    }
    // 끝(전부 쌓인 모습)에서 연다 — 재생하면 처음부터 쌓여 간다. ?tm= 이면 그 시각(봉우리 등)
    OBS_TM = CASEM.frames.includes(Q.get("tm")) ? Q.get("tm") : CASEM.end;
  }
  // 누적 카드 기준 — 실황은 서버 설정(기본 AWS), 사례는 격자에서 연다. ?basis= 가 먼저
  ACC_BASIS = ["aws", "grid"].includes(Q.get("basis")) ? Q.get("basis") : CASE ? "grid" : (SET.acc_basis || "aws");
  SELS = (Q.get("sig") || "").split(",").filter(x => ORDER_GN().includes(x)).slice(0, SEL_MAX);   // ?sig=함양,거창 — 고른 채로
  OV = new Set(Q.has("ov") ? Q.get("ov").split(",").filter(Boolean)
               : CASE ? ["alerts"] : (SET.overlays || []));
  renderLayers();
  if (OV.has("river")) loadRiver();
  if (SAF_IDS.some(id => OV.has(id))) loadSafety();
  if (OV.has("district")) loadDistrict();
  if (OV.has("tide")) loadTide();
  glTerrain(); glWater();
  vsrtN = +SET.vsrt_n || 1; x4 = !!SET.x4;
  applyAccFull(); applyHdrPin();
  // 색 — ?pal=kma|blue 가 서버 설정보다 먼저(벽면 화면 고정용). 기상청 색은 서버가 뽑아 둔 범례를 받아 와야 쓴다
  PAL = ["kma", "blue", "rich"].includes(Q.get("pal")) ? Q.get("pal") : ["kma", "rich"].includes(SET.pal) ? SET.pal : "blue";
  if (PAL !== "blue") await loadKmaLegend();
  tlOn = Q.has("tl") ? Q.get("tl") === "1" : (CASE || selOn()) ? true : !!SET.tl_on;
  let want = Q.get("layer") || (CASE ? "acc" : SET.layer) || "obs60";   // URL 이 서버 설정보다 먼저다(화면 고정용)
  if (want === "obsday" && !CASE) want = "acc";                          // 예전 '오늘 누적' — 이제 카드 구간을 따르는 누적
  if (want.startsWith("vsrt")) { kind = "vsrt"; const n = +want.replace(/\D/g, ""); if (n >= 1 && n <= 6) vsrtN = n; }
  else kind = KINDS.includes(want) ? want : "obs60";
  if (!CASE) {
    if (Q.get("layer") && !Q.get("basis") && SRC_OF[kind]) ACC_BASIS = SRC_OF[kind];   // ?layer=aws60 → AWS
    else kind = normKind(kind);
  }
  GNB = gnBounds();
  layout();
  await show();
  heatBoot();
  applyTL(false);                       // 범례가 그려진 뒤에 지도 비켜설 자리를 다시 잰다
  await loadFlow();
  setInterval(refreshMeta, 30000);
  // 카드·특보는 종합 화면처럼 1분마다 다시 읽는다(DB 만 읽는다 — 기상청 호출은 늘지 않는다)
  setInterval(() => { if (!test) { loadCards(); loadAlerts(); } if (qpfOn() && !SET.acc_full) loadQpf(); }, 60000);
  loadAlerts();
  if (!CASE) showResume();               // 화면 재생 — 이 브라우저가 돌리던 목록을 이어서
  // 웹 글꼴이 늦게 오면 카드 높이가 바뀐다 — 다 오면 한 번 더 잰다(누적 카드가 아래를 비운 채 굳지 않게)
  document.fonts?.ready?.then(() => { if (CARDS && !CARDS.err && tlOn && SET.panel !== "timeline") renderCards(); });
  if (Q.has("help")) openHelp(["src", "terms", "how"].includes(Q.get("help")) ? Q.get("help") : "src");   // ?help= — 도움말을 연 채로(안내용 링크)
}
boot();

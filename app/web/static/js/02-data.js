"use strict";
/* ── 자료 ─────────────────────────────────────────────────────────── */
/* ?tm=YYYYMMDDHHMI — 실측 층을 그 시각으로 본다(점검용. 남아 있는 사흘 안에서만). */
const PIN_TM = !CASE && /^\d{12}$/.test(Q.get("tm") || "") ? Q.get("tm") : null;
const pinned = key => PIN_TM && !test && ["obs15", "obs60", "obsday", "odam"].includes(key);
function reqTm(key) {
  if (CASE) return OBS_TM || CASEM?.end || null;
  if (OBSK.has(key) && OBS_TM) return OBS_TM;
  return pinned(key) ? PIN_TM : null;
}
/* 누적(acc) 층 요청에 카드의 구간을 싣는다 — 저장한 설정이 서버에 닿기 전에도 같은 구간을 그리게 */
function accParams(p, key) {
  if (!ACCK.has(key) || CASE) return p;
  p.set("hours", String(SET.acc_hours || 12));
  p.set("since", SET.acc_from === "date" ? SET.acc_date : SET.acc_from || "hours");     // 날짜 지정은 'YYYYMMDD'
  return p;
}
const accSig = key => ACCK.has(key) && !CASE ? `|${SET.acc_from || "hours"}:${SET.acc_hours || 12}:${SET.acc_date || ""}` : "";
function qs(key, tm) {
  const p = new URLSearchParams();
  if (tm) p.set("tm", tm);
  if (test) p.set("test", "1");
  if (CASE) p.set("case", CASE);
  accParams(p, key);
  const s = p.toString();
  return s ? "?" + s : "";
}
function wantTm(key) {
  if (CASE) return "case:" + CASE;
  const k = key.startsWith("vsrt") ? "vsrt" : key;
  return metaOf(k).tm || "";
}
/* 시각을 준 프레임(재생 · 지난 시각)은 '최신'이 바뀌어도 그대로다 — 최신만 최신 시각을 키에 넣는다.
   ⚠️ 예전에는 늘 넣어서, AWS '지금' 칸이 1분마다 바뀌자 재생 흐름 정시 장들을 1분마다 다시 받았다.
   AWS 1시간 정시는 늦게 온 지점이 채워질 수 있어 그 정시(시)만 넣는다 */
const ckOf = (key, tm) => key + "|" + (tm || "") + "|"
  + (test ? "test" : !tm ? wantTm(key) : key === "aws60" ? wantTm(key).slice(0, 10) : "") + accSig(key);
async function fetchGrid(key, tm) {
  const ck = ckOf(key, tm);
  if (GRIDS.has(ck)) return GRIDS.get(ck);
  const r = await fetch(`/api/grid/${encodeURIComponent(key)}${qs(key, tm)}`, { cache: "no-cache" });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
  const buf = await r.arrayBuffer();
  const [h, w] = r.headers.get("X-Grid-Shape").split(",").map(Number);
  const hd = n => r.headers.get("X-Grid-" + n);
  const gr = { ck, key, u: new Uint16Array(buf), h, w, grid: r.headers.get("X-Grid"),
               tm: hd("Tm"), tmfc: hd("Tmfc"), capped: hd("Capped"), from: hd("From"),
               hours: hd("Hours") ? hd("Hours").split(",") : null, n: hd("N"), live: hd("Live") };
  if (gr.u.length !== h * w) throw new Error("격자 크기가 맞지 않는다");
  if (GRIDS.size > 200) GRIDS.delete(GRIDS.keys().next().value);
  GRIDS.set(ck, gr);
  return gr;
}
async function fetchStat(key, tm) {
  const ck = ckOf(key, tm);
  if (STATS.has(ck)) return STATS.get(ck);
  const p = new URLSearchParams({ layer: key });
  if (tm) p.set("tm", tm);
  if (test) p.set("test", "1");
  if (CASE) p.set("case", CASE);
  accParams(p, key);
  const j = await getJson(`/api/grid/sigun?${p}`);
  if (STATS.size > 200) STATS.delete(STATS.keys().next().value);
  STATS.set(ck, j);
  return j;
}

let SEQ = 0, SWITCH_MS = 0;
async function show(fade = false) {
  const my = ++SEQ, t0 = performance.now(), key = layerKey(), tm = reqTm(kind);
  buildMenu(); buildLegend();
  try {
    const [gr, st] = await Promise.all([fetchGrid(key, tm), fetchStat(key, tm)]);
    if (my !== SEQ) return;                     // 그새 다른 층을 골랐다
    CUR = gr; CURSTAT = st;
    if (updScale()) {                       // 누적 — 자료 크기에 맞춘 눈금(바뀌면 범례 · 면 · 관측소 점이 같이)
      buildLegend();
      if (SET.acc_tone && CARDS && !CARDS.err) renderCards();   // 색조 막대도 새 자로
    }
    $("empty").hidden = true;
  } catch (e) {
    if (my !== SEQ) return;
    CUR = null; CURSTAT = null;
    const col = META?.collect?.[COLLECT_OF[kind]];
    const fail = col && !col.ok;
    $("empty").className = fail ? "fail" : "";
    $("empty").innerHTML = (fail ? "조회 실패" : "아직 받은 격자가 없다")
      + `<small>${e.message}${col ? ` · 수집 ${col.tried_at ? col.tried_at.slice(11, 16) : "—"} ${col.detail || ""}` : ""}</small>`;
    $("empty").hidden = false;
  }
  if (CASE && CASEM && CUR) {
    // 사례는 시각마다 특보(산출)·카드 내용이 바뀐다 — 프레임과 함께 다시 그린다
    if (OV.has("alerts")) { ALERTS = caseAlerts(); drawAlerts(); renderAlertLegend(); }
  }
  loadStations();                        // 기억해 둔 시각이면 곧바로(같은 틱에) 바뀐다 — 격자와 함께 넘어간다
  draw(fade);
  paintHead();
  if (swOn() && swView() === "avg") renderSw();         // 바다 위젯 시군 평균은 지도 면을 따른다
  buildPlay();
  tlPlayhead();
  if (CASE && CASEM && CUR && tlOn && SET.panel !== "timeline") loadCards();
  refreshMoment();                       // 위 카드가 '그 시각' 값이면 지도와 같은 프레임으로
  cardsPlayhead();
  SWITCH_MS = performance.now() - t0;
  if (Q.get("debug") === "1") {
    $("dbg").hidden = false;
    $("dbg").textContent = `전환 ${SWITCH_MS.toFixed(1)}ms · 그리기 ${RENDER_MS.toFixed(1)}ms · ${V.W}×${V.H} dpr ${V.dpr} · 칸 ${V.s.toFixed(2)}px`;
  }
  window.__mapPerf = { switch: SWITCH_MS, render: RENDER_MS };
}

function choose(k, save) {
  const cardWas = cardKey();
  ACC_HOLD = false;
  kind = k;
  if (!CASE) OBS_TM = null;              // 메뉴로 고르면 늘 '지금'(사례는 보던 시각 그대로)
  if (save) saveSetting(k === "vsrt" ? { layer: "vsrt", vsrt_n: vsrtN } : { layer: k });
  show();
  // 위 카드 · 예측 카드가 바뀐다: 강수 누적 ↔ '그 시각'(15분 · 1시간 · 실황 · 초단기) ↔ 단기 오늘 ↔ 단기 내일
  if (cardKey() !== cardWas) loadCards();
  // 재생 흐름의 실측 자료가 바뀌었다(격자 60분 ↔ AWS 1시간) — 흐름을 그 자료로 다시 받는다
  if (!CASE && FLOW && (FLOW.src || "grid") !== flowSrc()) loadFlow();
}

/* ── 재생 흐름 ────────────────────────────────────────────────────── */
async function loadFlow() {
  const p = new URLSearchParams({ hours: SET.flow_hours, step: SET.flow_step });
  if (!CASE && flowSrc() === "aws") p.set("src", "aws");   // AWS 1시간 — 정시마다(간격 설정은 격자에만)
  if (test) p.set("test", "1");
  if (CASE) p.set("case", CASE);
  try { FLOW = await getJson(`/api/grid/flow?${p}`); }
  catch { FLOW = null; }
  if (FLOW) {
    FLOW.tt = FLOW.frames.map(f => tOf(f.t));
    FLOW.t0 = Math.min(tOf(FLOW.start), ...FLOW.tt);
    FLOW.t1 = Math.max(tOf(FLOW.now), ...FLOW.tt);
    FLOW.tn = tOf(FLOW.now);
  }
  buildPlay(); buildTL(); tlPlayhead();
  if (test) loadCards();                 // 테스트 카드는 합성 흐름에서 뽑는다 — 지도와 같은 값
  preloadFlow();
}
/* 지금 보는 프레임의 시각(ms) — 흐름 밖 층이면 null */
function headT() {
  if (!FLOWK.has(kind) || !CUR || !CUR.tm) return null;
  return tOf(CUR.tm);
}
function nearestFrame(t) {
  if (!FLOW || !FLOW.frames.length) return -1;
  let best = 0, bd = Infinity;
  FLOW.tt.forEach((x, i) => {
    // 같은 거리면 '지금' 앞은 실측, 뒤는 예측을 고른다
    const d = Math.abs(x - t) + (FLOW.frames[i].kind === "fcst" ? (t <= FLOW.tn ? 1 : -1) : 0);
    if (d < bd) { bd = d; best = i; }
  });
  return best;
}
function curFrame() {
  const t = headT();
  if (t == null || !FLOW) return -1;
  // 같은 시각이라도 층이 맞는 프레임을 고른다(사례는 실측뿐이다)
  const i = FLOW.frames.findIndex(f => (CASE || OBSK.has(kind) ? f.kind === "obs" : f.kind === "fcst" && f.n === vsrtN)
    && tOf(f.t) === t);
  return i >= 0 ? i : nearestFrame(t);
}
function seek(i, fade = true) {
  if (!FLOW || i < 0 || i >= FLOW.frames.length) return;
  const f = FLOW.frames[i];
  if (CASE) {
    OBS_TM = f.t;                         // 사례는 고른 층(1시간/누적) 그대로 시각만 옮긴다
  } else if (f.kind === "obs") {
    kind = f.layer;                       // 격자 60분 | AWS 1시간 — 흐름이 고른 자료 그대로
    OBS_TM = f.t === metaOf(kind).tm ? null : f.t;
  } else {
    kind = "vsrt"; vsrtN = f.n; OBS_TM = null;
  }
  if (playing) qpfFollow(tOf(f.t));
  show(fade);
}
function startPlay() {
  if (!FLOW || !FLOW.frames.length) return;
  stopPlay(true);
  qpfSyncOn();                           // 초단기예측 이미지 — 지도 재생 동안은 같은 시각으로 따라간다
  let i = curFrame();
  playing = setInterval(() => {
    i = (i + 1) % FLOW.frames.length;
    seek(i);
  }, SET.play_ms);
  qpfFollow(headT());                    // 누르는 순간부터 같은 시각
  buildPlay();
}
function stopPlay(quiet) {
  if (playing) { clearInterval(playing); playing = null; if (!quiet) buildPlay(); }
  if (!quiet) qpfSyncOff();              // 재생을 멈추면 초단기예측 이미지는 다시 따로
}
async function preloadFlow() {
  if (!FLOW) return;
  for (const f of FLOW.frames) {
    const key = CASE ? kind : f.layer;
    const tm = CASE ? f.t : f.kind === "obs" && f.t !== metaOf(f.layer).tm ? f.t : null;
    try { await Promise.all([fetchGrid(key, tm), fetchStat(key, tm)]); } catch {}
  }
}

/* 재생 막대 — 지난 실측(틱마다 한 장) │지금│ 예측(시간마다 한 장). 끌어서 옮긴다.
   막대는 흐름이 바뀔 때만 새로 그리고, 재생 중에는 손잡이와 글자만 옮긴다(그래야 미끄러진다). */
const fmtH = t => String(new Date(t).getHours()).padStart(2, "0");
const TRK = { Wt: 640, Ht: 46, padX: 10 };
const trkX = t => TRK.padX + (t - FLOW.t0) / Math.max(1, FLOW.t1 - FLOW.t0) * (TRK.Wt - 2 * TRK.padX);
function playHead() {
  const p = $("play");
  if (p.hidden || !FLOW) return;
  const ht = headT(), i = curFrame(), f = i >= 0 ? FLOW.frames[i] : null;
  const x = ht != null ? trkX(ht) : -40;
  for (const el of p.querySelectorAll(".trk-head, .trk-knob")) el.style.transform = `translateX(${x.toFixed(1)}px)`;
  p.querySelector(".lab").innerHTML = !f ? `<b>—</b><small>흐름 밖</small>`
    : CASE ? `<b>${md(f.t)} ${hm(f.t)}</b><small>재현 · ${kind === "acc" ? "처음부터 누적" : "지난 1시간"}</small>`
    : f.kind === "obs" ? `<b>${hm(f.t)}</b><small>실측 · 지난 1시간${f.layer === "aws60" ? f.live ? " · AWS 매분" : " · AWS" : ""}</small>`
    : `<b>+${f.n}h ${fmtH(tOf(f.t))}시</b><small class="fc">예측 · 초단기</small>`;
  $("b-pp").textContent = playing ? "❚❚" : "▶";
}
function buildPlay() {
  const p = $("play");
  if (!FLOWK.has(kind) || !FLOW || !FLOW.frames.length) { p.hidden = true; p.dataset.sig = ""; return; }
  const wasHidden = p.hidden;
  p.hidden = false;
  const sig = `${FLOW.now}|${FLOW.frames.length}|${FLOW.step}|${FLOW.hours}|${FLOW.src || ""}|${document.documentElement.dataset.theme}`;
  if (p.dataset.sig === sig) { playHead(); return; }
  p.dataset.sig = sig;
  const { Wt, Ht } = TRK, x = trkX;
  const xn = x(FLOW.tn);
  const ticks = FLOW.tt.map((t, i) => `<line class="trk-tick" x1="${x(t)}" x2="${x(t)}" y1="${FLOW.frames[i].kind === "obs" ? 14 : 12}" y2="24"/>`).join("");
  let hours = "";
  const h0 = new Date(FLOW.t0); h0.setMinutes(0, 0, 0);
  const span = (FLOW.t1 - FLOW.t0) / 3600e3, every = span > 14 ? 3 : span > 8 ? 2 : 1;
  for (let t = h0.getTime() + 3600e3; t <= FLOW.t1; t += 3600e3)
    if (new Date(t).getHours() % every === 0 && Math.abs(x(t) - xn) > 18)
      hours += `<text class="trk-hour" x="${x(t)}" y="40">${fmtH(t)}</text>`;
  const padX = TRK.padX;
  p.innerHTML = `<button class="pp" id="b-pp" title="재생 (Space)">▶</button>
    <svg id="trk" class="noanim" width="${Wt}" height="${Ht}" viewBox="0 0 ${Wt} ${Ht}">
      <defs><pattern id="fc-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
        <rect width="6" height="6" style="fill:color-mix(in oklab, var(--accent) 10%, transparent)"/>
        <line x1="0" y1="0" x2="0" y2="6" style="stroke:color-mix(in oklab, var(--accent) 40%, transparent)" stroke-width="2"/></pattern></defs>
      <rect class="trk-past" x="${padX}" y="14" width="${Math.max(0, xn - padX)}" height="10" rx="3"/>
      <rect class="trk-fc" x="${xn}" y="14" width="${Math.max(0, Wt - padX - xn)}" height="10" rx="3"/>
      ${ticks}
      <line class="trk-now" x1="${xn}" x2="${xn}" y1="4" y2="30"/>
      <text class="trk-nowl" x="${xn}" y="42">${NOWL}</text>
      ${hours}
      <line class="trk-head" x1="0" x2="0" y1="6" y2="30"/><circle class="trk-knob" cx="0" cy="19" r="7"/>
    </svg>
    <div class="lab"></div>`;
  $("b-pp").onclick = () => playing ? stopPlay() : startPlay();
  playHead();
  if (wasHidden) placePlay();              // 막대가 막 나타났다 — 이제야 폭을 잴 수 있다
  requestAnimationFrame(() => requestAnimationFrame(() => $("trk") && $("trk").classList.remove("noanim")));
  const trk = $("trk");
  const at = ev => {
    const r = trk.getBoundingClientRect();
    const xx = (ev.clientX - r.left) / r.width * Wt;
    return FLOW.t0 + (xx - padX) / (Wt - 2 * padX) * (FLOW.t1 - FLOW.t0);
  };
  let drag = false, last = -1;
  const go = ev => { const i2 = nearestFrame(at(ev)); if (i2 !== last) { last = i2; seek(i2); } };
  trk.onpointerdown = ev => { drag = true; stopPlay(); trk.setPointerCapture(ev.pointerId); last = -1; go(ev); };
  trk.onpointermove = ev => { if (drag) go(ev); };
  trk.onpointerup = () => { drag = false; };
}

/* ── 강수 타임라인(오른쪽 사이드바) ────────────────────────────────────
   시군마다 한 줄: 지난 실측(실선·면) │지금│ 예측(점선) — 지도와 같은 프레임, 같은 값.
   세로선(재생 위치)과 줄마다 점·오른쪽 값이 지도와 함께 움직인다. 점 색은 지도의 색 단계 그대로. */
let TLG = null;                          // 그린 틀(재생 위치만 바꿀 때 쓴다)
function tlWidth() {
  return Math.round(Math.min(Math.max(560 * V.k, V.W * 0.34), V.W * 0.46));
}
function applyTL(animate = true) {
  if (!V) return;
  const w = tlWidth();
  document.documentElement.style.setProperty("--tlw", w + "px");
  document.body.classList.toggle("tl-on", tlOn);
  const cards = SET.panel !== "timeline";
  document.body.classList.toggle("panel-cards", cards);
  document.body.classList.toggle("panel-tl", !cards);
  camGo(animate);
  placePlay();
  if (tlOn && !cards) buildTL();
  if (tlOn && cards) { if (CARDS) renderCards(); else loadCards(); }
  drawRanks();
  renderSw();
  link(null);
}
/* 타임라인이 나오면 지도가 비켜설 틀(경남 전체를 범례 오른쪽 ~ 사이드바 왼쪽에). 모자라면 살짝 줄인다 */
/* 지도 왼쪽 끝 — 범례 오른쪽, 펼친 특보 줄(왼쪽 레이어 밑 얇은 세로 줄) 오른쪽 */
function leftBound() {
  const st = $("stage").getBoundingClientRect(), lg = $("legend").getBoundingClientRect(), al = $("ly-alerts");
  let x = lg.width ? lg.right - st.left + 10 : 16;
  // 서쪽 지점 글자가 줄에 닿지 않게. 줄을 지도 안쪽으로 끌어다 놓았으면(왼쪽 끝에서 떨어지면) 지도를 밀지 않는다
  if (alShown() && !al.hidden && al.offsetWidth) { const r = al.getBoundingClientRect(); if (r.left - st.left < 120) x = Math.max(x, r.right - st.left + 22); }
  return Math.max(16, x);
}
function tlFit() {
  let tx = 0, ty = 0, sc = 1;
  // 패널이 나오거나 특보 줄을 펼치면 지도가 그 사이로 비켜 선다(겹치지 않게)
  if (tlOn || alShown()) {
    const left = leftBound(), right = tlOn ? V.W - tlWidth() - 16 : V.W - 16;
    const mw = (V.X1 - V.X0) * V.b.s, avail = right - left;
    sc = Math.min(1, avail / mw);
    tx = left + (avail - mw * sc) / 2 - sc * V.b.ox;
    ty = (1 - sc) * V.H / 2;
  }
  return { tx, ty, sc };
}

/* ── 시군 확대(설정 '시군 누르면 확대') ───────────────────────────────────
   고른 시군이 지도 빈자리(범례 오른쪽 ~ 패널 왼쪽, 레이어 단추 아래 ~ 재생 막대 위)에 차게 카메라가 날아간다.
   틀은 MT(CSS 이동) 대신 V 자체를 바꾼다 — 격자는 칸 그대로 또렷하고, 선 굵기·글자 크기는 그대로다.
   날아가는 동안 땅 · 경계 · 격자는 GL 이 매 장 그리고(glCam), 위 SVG 는 CSS transform 으로 통째로 옮긴다(camFrame).
   ⚠️ 예전에는 SVG 두 장의 viewBox 를 바꾸고 격자 Canvas 를 매 장 다시 그려 윈도 PC 에서 버벅였다(11-06 GL 로 옮김).
   글자·점은 잠깐 감췄다가 다 온 뒤 새로 그린다. */
const ZMAX = 9;                          // 경남 전체의 몇 배까지(읍면동을 고르면 4배 더 — 필지가 보이게)
/* 고른 읍면동(GEO.emd id) — 시군을 확대한 뒤 그 안 읍면동을 누르면(Ctrl 은 더하기 · 빼기). 비면 시군 확대 */
let ESEL = [];
const zoomOn = () => !!(selOn() && SET.sel_zoom !== false && FEAT && V);
function mapArea() {
  const st = $("stage").getBoundingClientRect(), lg = $("legend").getBoundingClientRect();
  const hb = $("hud").getBoundingClientRect(), pl = $("play");
  const x0 = leftBound();
  const x1 = tlOn ? V.W - tlWidth() - 16 : V.W - 16;
  const y0 = Math.max(16, hb.height ? hb.bottom - st.top + 12 : 16);   // 지도 위 제목 밑부터
  const y1 = !pl.hidden && pl.offsetHeight ? pl.getBoundingClientRect().top - st.top - 10 : V.H - 16;
  return { x0, y0, x1, y1 };
}
function zoomCam(sigs) {
  const emd = ESEL.length && EFEAT ? EFEAT.filter(f => ESEL.includes(f.properties.id)) : [];
  const fts = emd.length ? emd : FEAT.filter(f => sigs.includes(f.properties.sigun));
  if (!fts.length) return null;
  let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
  for (const ft of fts) {
    const polys = ft.geometry.type === "Polygon" ? [ft.geometry.coordinates] : ft.geometry.coordinates;
    for (const poly of polys) for (const [x, y] of poly[0]) {
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
  }
  const A = mapArea(), pad = 24 * V.k;
  const aw = A.x1 - A.x0 - 2 * pad, ah = A.y1 - A.y0 - 2 * pad;
  if (aw < 80 || ah < 80) return null;
  const s = Math.max(V.b.s, Math.min(aw / (x1 - x0), ah / (y1 - y0), V.b.s * ZMAX * (emd.length ? 4 : 1)));
  const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
  return { s, ox: (A.x0 + A.x1) / 2 - (cx - V.X0) * s, oy: (A.y0 + A.y1) / 2 - (V.Y1 - cy) * s };
}
/* 가야 할 틀. cam = 화면에 보일 틀(MT 를 접어 넣은 값), mt = 다 온 뒤 MT, zoom = 시군 확대인가 */
function camTarget() {
  const c = zoomOn() && !CAM_EDIT ? zoomCam(SELS) : null;      // 지도 위치를 고치는 동안은 경남 전체 틀로
  if (c) return { cam: c, mt: { tx: 0, ty: 0, sc: 1 }, zoom: true };
  const m = tlFit();
  const base = { s: m.sc * V.b.s, ox: m.tx + m.sc * V.b.ox, oy: m.ty + m.sc * V.b.oy };
  // 사람이 옮긴 틀 — CSS 확대(MT)가 아니라 V 를 바꿔 그린다(키워도 칸이 또렷하다). 시군 확대와 같은 길
  if (ucOn()) return { cam: ucApply(base), mt: { tx: 0, ty: 0, sc: 1 }, zoom: false, user: true };
  return { cam: base, mt: m, zoom: false };
}
function setWrap(m, animate) {
  const mw = $("mapwrap");
  if (!animate) mw.style.transition = "none";
  mw.style.transform = `translate(${m.tx.toFixed(1)}px, ${m.ty.toFixed(1)}px) scale(${m.sc.toFixed(4)})`;
  if (!animate) { void mw.offsetWidth; mw.style.transition = ""; }
}
function camGo(animate = true) {
  if (!V) return;
  const T = camTarget();
  if (!T.zoom && !T.user && !CAM && !CAMU && !ZA) {   // 경남 전체 ↔ 경남 전체(타임라인 비켜서기) — 예전대로 CSS 로 옮긴다
    MT = T.mt; setWrap(MT, animate);
    return;
  }
  const cur = T.zoom ? CAM : T.user ? CAMU : null;
  const same = !ZA && cur && Math.abs(T.cam.s / cur.s - 1) < 1e-3
    && Math.abs(T.cam.ox - cur.ox) < 0.5 && Math.abs(T.cam.oy - cur.oy) < 0.5;
  if (same) return;
  if (!animate || matchMedia("(prefers-reduced-motion: reduce)").matches) { camSet(T); return; }
  fly(T);
}
/* 다 왔다 — 그 틀로 경계·격자·글자를 새로 그린다 */
function camSet(T) {
  if (ZA) { cancelAnimationFrame(ZA.raf); ZA = null; }
  CAM = T.zoom ? T.cam : null;
  CAMU = T.user ? T.cam : null;
  MT = T.mt;
  Object.assign(V, T.zoom || T.user ? T.cam : V.b);
  setWrap(MT, false);
  $("over").style.transform = "";
  glCam();
  const st = $("stage");
  st.classList.toggle("zoomed", !!CAM);
  if (CAM) ensureEmd();                  // ?sig= 로 연 때처럼 날지 않고 바로 확대한 경우
  buildBase(); draw(); drawRanks(); hot(null);
  if (!CAM) placeSw();                   // 경남 전체로 돌아왔다 — 바다 위젯 자리를 다시(확대 중에 패널 등이 바뀌었을 수 있다)
  // 새로 그린 글자·점은 감춘 채(opacity 0) 생겼다 — 그 값을 한 번 읽어 굳힌 뒤 걷어야 서서히 나온다
  getComputedStyle($("names")).opacity;
  st.classList.remove("zooming");
}
/* ── 지도 위치(카메라) — 오른쪽 위 도구의 십자 단추(C). 경남 전체 틀을 끌어 옮기고 휠로 키운다(10-24) ──
   바다 위젯 · 패널을 두고 지도를 어디에 놓을지 화면마다 다르다 — 이 브라우저에 기억(gn-map-cam, 벽면 화면마다).
   UC = { z: 경남 전체 틀의 배율, dx · dy: 판 너비 · 높이에 대한 몫 }. 타임라인 · 패널이 비켜선 틀 위에 얹는다.
   시군을 골라 확대하면 그 틀이 먼저다(놓으면 이 틀로 돌아온다). 끄는 동안은 경계를 viewBox 로만 옮기고(fly 와 같다)
   격자만 다시 그린다 — 손을 떼면 새로 그린다 */
const UC0 = { z: 1, dx: 0, dy: 0 };
let UC = { ...UC0 }, CAM_EDIT = false, UC_T = null;
try { const u = JSON.parse(localStorage.getItem("gn-map-cam") || "null"); if (u && isFinite(u.z) && isFinite(u.dx) && isFinite(u.dy)) UC = u; } catch {}
const ucOn = () => CAM_EDIT || Math.abs(UC.z - 1) > 1e-3 || Math.abs(UC.dx) > 1e-4 || Math.abs(UC.dy) > 1e-4;
function ucApply(c) {                    // 경남 전체 틀 c → 사람이 옮긴 틀(경남 가운데를 기준으로 키우고, 판 몫만큼 옮긴다)
  const cx = c.ox + (V.X1 - V.X0) * c.s / 2, cy = c.oy + (V.Y1 - V.Y0) * c.s / 2;
  return { s: c.s * UC.z, ox: cx - (cx - c.ox) * UC.z + UC.dx * V.W, oy: cy - (cy - c.oy) * UC.z + UC.dy * V.H };
}
function ucFrom(cam) {                   // 원하는 틀 → UC(휠 — 커서 자리를 붙잡고 키운다)
  const m = tlFit(), c = { s: m.sc * V.b.s, ox: m.tx + m.sc * V.b.ox, oy: m.ty + m.sc * V.b.oy };
  const z = cam.s / c.s, cx = c.ox + (V.X1 - V.X0) * c.s / 2, cy = c.oy + (V.Y1 - V.Y0) * c.s / 2;
  UC = { z, dx: (cam.ox - (cx - (cx - c.ox) * z)) / V.W, dy: (cam.oy - (cy - (cy - c.oy) * z)) / V.H };
}
const ucClamp = () => { UC.z = Math.max(0.6, Math.min(4, UC.z)); UC.dx = Math.max(-0.9, Math.min(0.9, UC.dx)); UC.dy = Math.max(-0.9, Math.min(0.9, UC.dy)); };
function ucSave() { try { ucOn() || CAM_EDIT ? localStorage.setItem("gn-map-cam", JSON.stringify(UC)) : localStorage.removeItem("gn-map-cam"); } catch {} }
/* 날거나 끄는 동안 — 지도(GL)는 V 를 따라가고, 위 SVG 는 마지막으로 그린 틀 GEN 에서 V 로 통째로 옮긴다(GPU 합성, 다시 그리지 않는다) */
function camFrame() {
  glCam();
  const g = GEN, k = V.s / g.s;
  $("over").style.transform = `translate(${(V.ox - g.ox * k).toFixed(2)}px, ${(V.oy - g.oy * k).toFixed(2)}px) scale(${k.toFixed(5)})`;
}
function camLive() {                     // 끄는 동안 — 손을 떼면 camSettle 이 새로 그린다
  if (!V || !GEN) return;
  Object.assign(V, camTarget().cam);
  $("stage").classList.add("panning");
  camFrame();
  clearTimeout(UC_T); UC_T = setTimeout(camSettle, 260);
}
function camSettle() {                   // 손을 뗐다 — 이 틀로 경계 · 글자를 새로
  clearTimeout(UC_T); UC_T = null;
  $("stage").classList.remove("panning");
  if (!V) return;
  camSet(camTarget()); placeSw();
  ucSave();
}
function camEdit(on) {
  if (on === CAM_EDIT || !V) return;
  CAM_EDIT = on;
  document.body.classList.toggle("cam-edit", on);
  $("camgrab").hidden = $("cambar").hidden = !on;
  $("b-cam").classList.toggle("on", on);
  $("tip").hidden = true; highlight(null); link(null);
  if (on) { camSet(camTarget()); return; }          // 시군을 확대해 뒀으면 경남 전체 틀로 나와서 고친다
  ucSave();
  camGo(true);                                      // 끝 — 시군을 골라 뒀으면 다시 그리로
}
function camReset() { UC = { ...UC0 }; if (CAM_EDIT) camSet(camTarget()); else camGo(true); placeSw(); ucSave(); }
{
  const cg = $("camgrab");
  for (const t of ["click", "mousemove", "contextmenu", "dblclick"]) cg.addEventListener(t, ev => { ev.stopPropagation(); if (t === "contextmenu") ev.preventDefault(); });
  cg.addEventListener("pointerdown", ev => {
    if (ev.button !== 0) return;
    cg.setPointerCapture(ev.pointerId); cg.classList.add("drag");
    const x0 = ev.clientX, y0 = ev.clientY, d0 = { ...UC };
    cg.onpointermove = e => { UC.dx = d0.dx + (e.clientX - x0) / V.W; UC.dy = d0.dy + (e.clientY - y0) / V.H; ucClamp(); camLive(); };
    cg.onpointerup = cg.onpointercancel = () => { cg.onpointermove = cg.onpointerup = null; cg.classList.remove("drag"); camSettle(); };
  });
  cg.addEventListener("wheel", ev => {
    ev.preventDefault(); ev.stopPropagation();
    const C = camTarget().cam, rc = $("stage").getBoundingClientRect(), mx = ev.clientX - rc.left, my = ev.clientY - rc.top;
    const z1 = Math.max(0.6, Math.min(4, UC.z * Math.exp(-ev.deltaY * 0.0015))), f = z1 / UC.z;
    if (Math.abs(f - 1) < 1e-4) return;
    ucFrom({ s: C.s * f, ox: mx - (mx - C.ox) * f, oy: my - (my - C.oy) * f }); ucClamp(); camLive();
  }, { passive: false });
  cg.addEventListener("dblclick", () => camReset());
  $("cam-reset").onclick = camReset;
  $("cam-done").onclick = () => camEdit(false);
  $("b-cam").onclick = () => camEdit(!CAM_EDIT);
}

/* 줌 보간(van Wijk & Nuij 2003, d3.interpolateZoom 과 같은 식) — 멀리 옮길 땐 살짝 물러났다 다가간다.
   a, b = [가운데 x, 가운데 y, 보이는 너비](칸) */
function zoomPath(a, b, rho = 1.25) {
  const [ux0, uy0, w0] = a, [ux1, uy1, w1] = b, dx = ux1 - ux0, dy = uy1 - uy0, d2 = dx * dx + dy * dy;
  const r2 = rho * rho;
  if (d2 < 1e-12) {
    const S = Math.log(w1 / w0) / rho;
    const f = t => [ux0 + t * dx, uy0 + t * dy, w0 * Math.exp(rho * t * S)];
    f.S = Math.abs(S);
    return f;
  }
  const d1 = Math.sqrt(d2);
  const b0 = (w1 * w1 - w0 * w0 + r2 * r2 * d2) / (2 * w0 * r2 * d1);
  const b1 = (w1 * w1 - w0 * w0 - r2 * r2 * d2) / (2 * w1 * r2 * d1);
  const q0 = Math.log(Math.sqrt(b0 * b0 + 1) - b0), q1 = Math.log(Math.sqrt(b1 * b1 + 1) - b1);
  const S = (q1 - q0) / rho;
  const f = t => {
    const z = t * S, c0 = Math.cosh(q0);
    const u = w0 / (r2 * d1) * (c0 * Math.tanh(rho * z + q0) - Math.sinh(q0));
    return [ux0 + u * dx, uy0 + u * dy, w0 * c0 / Math.cosh(rho * z + q0)];
  };
  f.S = Math.abs(S);
  return f;
}
function fly(T) {
  const st = $("stage"), mw = $("mapwrap");
  if (ZA) cancelAnimationFrame(ZA.raf);
  else {
    // 지금 보이는 틀 = V 에 지도 덩어리의 CSS 이동을 접은 것(타임라인이 비켜서는 중이면 그 중간값)
    const m = new DOMMatrix(getComputedStyle(mw).transform === "none" ? undefined : getComputedStyle(mw).transform);
    Object.assign(V, { s: V.s * m.a, ox: m.e + m.a * V.ox, oy: m.f + m.a * V.oy });
    MT = { tx: 0, ty: 0, sc: 1 };
    setWrap(MT, false);
  }
  st.classList.add("zooming");
  st.classList.toggle("zoomed", T.zoom);
  link(null);
  if (T.zoom) { drawEmd(); ensureEmd(); }   // 확대해 들어가면 그 시군 읍면동 선을 미리(지금 그린 틀로) 그려 둔다
  const ctr = c => [V.X0 + (V.W / 2 - c.ox) / c.s, V.Y1 - (V.H / 2 - c.oy) / c.s, V.W / c.s];
  const path = zoomPath(ctr(V), ctr(T.cam));
  const dur = Math.min(950, Math.max(450, path.S * 600)), t0 = performance.now();
  const za = ZA = { T, raf: 0 };
  // 창이 가려지면 requestAnimationFrame 이 멈춘다 — 그래도 끝 상태로는 가 있게
  setTimeout(() => { if (ZA === za) camSet(T); }, dur + 400);
  const step = now => {
    const p = Math.min(1, (now - t0) / dur), e = p < .5 ? 4 * p * p * p : 1 - (-2 * p + 2) ** 3 / 2;
    if (p >= 1) { camSet(T); return; }
    const [cx, cy, w] = path(e), s = V.W / w;
    Object.assign(V, { s, ox: V.W / 2 - (cx - V.X0) * s, oy: V.H / 2 - (V.Y1 - cy) * s });
    camFrame();
    ZA.raf = requestAnimationFrame(step);
  };
  ZA.raf = requestAnimationFrame(step);
}

/* 읍면동 경계(data/geo/emd.topo.json, tools/build_geo.py) — 처음 확대할 때 받는다.
   ⚠️ 시군 경계(SGIS 2020)와 원본(행정동 2026.7)이 달라 바깥 둘레가 수십 m 어긋난다 —
      같은 시군 안 읍면동 사이 선만 긋고, 시군 모양으로 잘라 삐져나온 끝을 감춘다. */
let ETOPO = null, EFEAT = null, EMDP = null;
const EMESH = new Map();
function ensureEmd() {
  if (!EMDP) EMDP = getJson("/api/grid/geo/emd.topo.json").then(t => {
    ETOPO = t; EFEAT = topojson.feature(t, t.objects.emd).features;
    if (zoomOn()) { drawEmd(); if (!ZA) drawStations(); }
    const qe = new URLSearchParams(location.search).get("emd");   // ?sig=창원&emd=진동면,진북면 — 그 읍면동으로 바로
    if (qe && !ESEL.length) {
      ESEL = qe.split(",").map(n => GEO.emd.find(e => e.name === n.trim() && isSel(e.sigun))?.id).filter(Boolean);
      if (ESEL.length) { drawSel(); camGo(false); loadEmd().then(selLabel); }
    }
  }).catch(() => { EMDP = null; });
  return EMDP;
}
/* GL 층 'emd'(01b). shortcut: 예전에는 시군 모양으로 잘라(clipPath) 둘레에서 삐져나온 끝(수십 m)을 감췄다 — GL 은 자르지 않는다.
   확대 화면에서 1~2px 이라 그냥 둔다. 눈에 띄면 서버(build_geo.py)에서 시군 모양으로 잘라 둔다 */
function drawEmd() {
  const on = selOn() && !!ETOPO && $("stage").classList.contains("zoomed");
  if (on) for (const sg of SELS) if (!EMESH.has(sg))
    EMESH.set(sg, topojson.mesh(ETOPO, ETOPO.objects.emd,
      (a, b) => a !== b && a.properties.sigun === sg && b.properties.sigun === sg));
  glData("emd", on ? SELS.join() : "", () => on ? SELS.map(sg => glF(EMESH.get(sg))) : []);
}
/* 읍면동 이름 — 큰 곳부터, 시군명·최대 라벨·관측소와 겹치지 않는 자리에만(가장 덜 중요한 글자) */
function drawEmdNames(taken) {
  const g = $("emdn");
  if (!g) return;
  if (!CAM || !selOn() || !EFEAT || !V) { g.innerHTML = ""; return; }
  const cells = new Map((GEO?.emd || []).map(e => [e.id, e.n]));
  const fs = Math.max(12.5, Math.min(22, V.u * 4.6)), h = fs * 1.25;
  const placed = taken.slice(), out = [];
  const hit = b => placed.some(p => b.x0 < p.x1 && b.x1 > p.x0 && b.y0 < p.y1 && b.y1 > p.y0);
  const A = mapArea();
  const pcs = wEmdPct();
  const list = EFEAT.filter(f => isSel(f.properties.sigun))
    .sort((a, b) => (cells.get(b.properties.id) || 0) - (cells.get(a.properties.id) || 0));
  for (const f of list) {
    const p = f.properties, x = V.toX(p.lx), y = V.toY(p.ly), pc = pcs.get(p.sigun + "|" + p.name);
    const w = (p.name.length + (pc == null ? 0 : String(pc).length * 0.6 + 1.6)) * fs + 6;
    const b = { x0: x - w / 2, x1: x + w / 2, y0: y - h / 2, y1: y + h / 2 };
    if (b.x0 < A.x0 - 8 || b.x1 > A.x1 + 8 || b.y0 < 4 || b.y1 > V.H - 4 || hit(b)) continue;
    placed.push(b);
    out.push(`<text class="en" x="${x.toFixed(1)}" y="${y.toFixed(1)}" style="font-size:${fs.toFixed(1)}px;stroke-width:${(fs * 0.2).toFixed(1)}px">${p.name}${pc == null ? "" : ` <tspan class="pc">${pc}%</tspan>`}</text>`);
  }
  g.innerHTML = out.join("");
  drawWaterLabels(placed);
}
/* 강 이름(레이어 옵션 waterlbl) — 시군 확대에서 국가 · 지방하천 이름을 강 줄기를 따라(기울여) 단다. 읍면동 이름 다음 — 남은 빈자리에만.
   한 이름은 화면에서 가장 긴 줄기에, 450px 마다 하나씩. 좌표는 water.json(칸) → V.toX/Y */
function drawWaterLabels(placed) {
  const g = $("wlab");
  if (!g) return;
  if (!OV.has("water") || !OV.has("waterlbl") || !CAM || !selOn() || !Array.isArray(WATER) || !V) { g.innerHTML = ""; return; }
  const A = mapArea(), fs = Math.max(11.5, Math.min(18, V.u * 3.6)), out = [];
  const hit = b => placed.some(p => b.x0 < p.x1 && b.x1 > p.x0 && b.y0 < p.y1 && b.y1 > p.y0);
  const runs = new Map();                                   // 이름 → [화면 점 줄기 …]
  const keep = (n, r) => { if (r.length > 1) (runs.get(n) || runs.set(n, []).get(n)).push(r); };
  for (const f of WATER) {
    const p = f.properties;
    if (p.k !== "river" || !p.n || p.g > 2 || p.o) continue;
    for (const line of f.geometry.coordinates) {
      let cur = [];
      for (const [gx, gy] of line) {
        const x = V.toX(gx), y = V.toY(gy);
        if (x > A.x0 && x < A.x1 && y > A.y0 && y < A.y1) cur.push([x, y]);
        else { keep(p.n, cur); cur = []; }
      }
      keep(p.n, cur);
    }
  }
  const len = r => r.slice(1).reduce((s, q, i) => s + Math.hypot(q[0] - r[i][0], q[1] - r[i][1]), 0);
  const best = [...runs].map(([n, rs]) => { const r = rs.reduce((a, b) => (len(b) > len(a) ? b : a)); return [n, r, len(r)]; }).sort((a, b) => b[2] - a[2]);
  for (const [name, r, L] of best) {
    const w = name.length * fs * 1.02 + 6;
    if (L < w * 1.4) continue;                               // 이름보다 짧은 줄기엔 달지 않는다
    for (let k = 0, n = Math.max(1, Math.floor(L / 450)); k < n; k++) {
      let t = L * (k + 0.5) / n, i = 1;                      // 줄기를 따라 t 지점
      for (; i < r.length - 1; i++) { const s = Math.hypot(r[i][0] - r[i - 1][0], r[i][1] - r[i - 1][1]); if (t <= s) break; t -= s; }
      const a = r[i - 1], b2 = r[i], s = Math.hypot(b2[0] - a[0], b2[1] - a[1]) || 1;
      const x = a[0] + (b2[0] - a[0]) * Math.min(1, t / s), y = a[1] + (b2[1] - a[1]) * Math.min(1, t / s);
      let ang = Math.atan2(b2[1] - a[1], b2[0] - a[0]) * 180 / Math.PI;
      if (ang > 90) ang -= 180; else if (ang < -90) ang += 180;   // 글자가 뒤집히지 않게
      const c = Math.abs(Math.cos(ang * Math.PI / 180)), sn = Math.abs(Math.sin(ang * Math.PI / 180));
      const bx = { x0: x - (c * w + sn * fs) / 2, x1: x + (c * w + sn * fs) / 2, y0: y - (sn * w + c * fs) / 2, y1: y + (sn * w + c * fs) / 2 };
      if (hit(bx)) continue;
      placed.push(bx);
      out.push(`<text class="wl" transform="translate(${x.toFixed(1)},${y.toFixed(1)}) rotate(${ang.toFixed(1)})" style="font-size:${fs.toFixed(1)}px;stroke-width:${(fs * 0.22).toFixed(1)}px">${escH(name)}</text>`);
    }
  }
  g.innerHTML = out.join("");
}

/* 재생 막대 — 범례 오른쪽 ~ 패널 왼쪽 빈자리 가운데. 막대(약 880px)가 그보다 넓으면 눈금 줄(TRK.Wt)을 줄인다.
   ⚠️ FHD 를 125%(1536px)로 띄우고 패널을 열면 지도 칸이 976px — 막대 왼끝이 범례(결측·비 없음) 밑으로 들어갔다.
   ⚠️ 막대에 zoom(--k)이 걸려 있어 left 도 그만큼 곱해진다 — 나눠 둔다 */
function placePlay() {
  if (!V) return;
  const p = $("play"), st = $("stage").getBoundingClientRect(), lg = $("legend").getBoundingClientRect();
  const x0 = (lg.width ? lg.right - st.left : 0) + 14, x1 = (tlOn ? V.W - tlWidth() : V.W) - 16;
  if (!p.hidden && p.offsetWidth) {
    const pw = p.getBoundingClientRect().width;
    const want = Math.round(Math.max(240, Math.min(640, TRK.Wt - (pw - (x1 - x0)) / V.k)));
    if (Math.abs(want - TRK.Wt) > 3) { TRK.Wt = want; p.dataset.sig = ""; buildPlay(); }
  }
  $("stage").style.setProperty("--playx", ((x0 + x1) / 2 / V.k).toFixed(0) + "px");
  placeSw();                               // 재생 막대가 생기거나 옮겼다 — 바다 위젯이 피해 간다
}
function setTL(on, save = true) {
  tlOn = on;
  if (save) saveSetting({ tl_on: on });
  applyTL(true);
  paintHead();
}

function buildTL() {
  const svg = $("tl-svg");
  $("tl-stat").textContent = SET.tl_stat === "mean" ? "평균" : "최대";
  $("tl-sub").textContent = `시군 ${SET.tl_stat === "mean" ? "평균" : "최대"} 1시간 강수량 · 지난 ${SET.flow_hours}시간 → +6시간`;
  if (!tlOn || !V) return;
  const box = svg.getBoundingClientRect();
  const W = box.width, H = box.height;
  if (!W || !H) return;
  const k = V.k;
  if (!FLOW || !FLOW.frames.length) {
    svg.innerHTML = `<text class="tl-empty" x="${W / 2}" y="${H / 2}" style="font-size:${15 * k}px">재생할 자료가 아직 없다 — 수집이 쌓이면 나타난다</text>`;
    TLG = null; return;
  }
  const stat = SET.tl_stat === "mean" ? "mean" : "max";
  const rowsD = [{ name: "경남", tot: true, v: FLOW.total[stat] }]
    .concat(FLOW.series.map(s => ({ name: s.sigun, v: s[stat] })));
  const nameW = 66 * k, valW = 78 * k, axisH = 30 * k, padR = 14 * k;
  const x0 = nameW + 14 * k, x1 = W - valW - padR;
  const rh = (H - axisH - 8 * k) / rowsD.length;
  const xT = t => x0 + (t - FLOW.t0) / Math.max(1, FLOW.t1 - FLOW.t0) * (x1 - x0);
  let vmax = 10;
  for (const r of rowsD) for (const v of r.v) if (v != null && v > vmax) vmax = v;
  const xn = xT(FLOW.tn);
  const out = [];
  // 예측 쪽 바탕, 시각 눈금, '지금'
  out.push(`<rect class="tl-fczone" x="${xn}" y="${axisH - 6 * k}" width="${x1 - xn + padR / 2}" height="${H - axisH}"/>`);
  const h0 = new Date(FLOW.t0); h0.setMinutes(0, 0, 0);
  const span = (FLOW.t1 - FLOW.t0) / 3600e3, every = span > 14 ? 3 : span > 8 ? 2 : 1;
  for (let t = h0.getTime() + 3600e3; t <= FLOW.t1; t += 3600e3) {
    const xx = xT(t);
    // '지금'·'실측'·'예측' 글자와 겹치는 눈금은 뺀다
    if (new Date(t).getHours() % every === 0 && Math.abs(xx - xn) > 22 * k
        && xx - x0 > 34 * k && x1 - xx > 34 * k)
      out.push(`<text class="tl-hour" x="${xx}" y="${axisH - 12 * k}" style="font-size:${12 * k}px">${fmtH(t)}</text>`);
  }
  out.push(`<text class="tl-zl" x="${x0}" y="${axisH - 12 * k}" style="font-size:${11 * k}px" text-anchor="start">실측</text>`);
  out.push(`<text class="tl-zl" x="${x1}" y="${axisH - 12 * k}" style="font-size:${11 * k}px" text-anchor="end">예측</text>`);
  out.push(`<text class="tl-nowl" x="${xn}" y="${axisH - 12 * k}" style="font-size:${12 * k}px">${NOWL}</text>`);
  out.push(`<line class="tl-now" x1="${xn}" x2="${xn}" y1="${axisH - 4 * k}" y2="${H}"/>`);
  // 실측이 앞쪽까지 다 차 있지 않으면(막 수집을 시작했거나 끊겼다) 비어 있는 까닭을 적는다
  const firstObs = FLOW.frames.findIndex(f => f.kind === "obs");
  const gapTo = firstObs >= 0 ? FLOW.tt[firstObs] : FLOW.tn;
  if (gapTo - FLOW.t0 > FLOW.step * 2 * 60e3 && xT(gapTo) - x0 > 120 * k)
    out.push(`<text class="tl-empty" x="${(x0 + xT(gapTo)) / 2}" y="${axisH + 22 * k}" style="font-size:${12 * k}px">`
      + (firstObs >= 0 ? `실측 ${hm(FLOW.frames[firstObs].t)}부터 — 쌓이는 중` : "실측 없음") + `</text>`);

  const fs = Math.min(18 * k, rh * 0.42);
  rowsD.forEach((r, ri) => {
    const top = axisH + ri * rh, base = top + rh - 5 * k, ph = rh - 12 * k;
    const y = v => base - Math.min(v, vmax) / vmax * ph;
    const seg = sel => {
      // 결측(null)은 끊는다 — 0 으로 잇지 않는다
      let d = "", a = "", run = [];
      const flush = () => {
        if (run.length) {
          d += "M" + run.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join("L");
          a += `M${run[0][0].toFixed(1)},${base}L` + run.map(([px, py]) => `${px.toFixed(1)},${py.toFixed(1)}`).join("L")
             + `L${run[run.length - 1][0].toFixed(1)},${base}Z`;
        }
        run = [];
      };
      FLOW.frames.forEach((f, i) => {
        if (!sel(f)) return;
        const v = r.v[i];
        if (v == null) { flush(); return; }
        run.push([xT(FLOW.tt[i]), y(v)]);
      });
      flush();
      return { d, a };
    };
    const po = seg(f => f.kind === "obs"), pf = seg(f => f.kind === "fcst");
    // 기간 최고 — 1㎜ 넘을 때만 숫자를 단다
    let pi = -1, pv = 0;
    r.v.forEach((v, i) => { if (v != null && v > pv) { pv = v; pi = i; } });
    const peak = pi >= 0 && pv >= 1
      ? `<text class="tl-peak" x="${xT(FLOW.tt[pi])}" y="${Math.max(top + fs * 0.9, y(pv) - 4 * k)}" style="font-size:${11.5 * k}px">${pv.toFixed(pv >= 10 ? 0 : 1)}</text>` : "";
    out.push(`<g class="tl-row ${r.tot ? "tot" : ""}" data-s="${r.tot ? "" : r.name}" data-i="${ri}">
      <rect class="tl-bg" x="0" y="${top}" width="${W}" height="${rh}"/>
      <line class="tl-sep" x1="${8 * k}" x2="${W - 8 * k}" y1="${top + rh}" y2="${top + rh}"/>
      <text class="tl-name ${r.tot ? "tot" : ""}" x="${12 * k}" y="${top + rh / 2}" style="font-size:${fs}px">${r.tot ? "경남" : r.name}</text>
      <path class="tl-area" d="${po.a}"/><path class="tl-line" d="${po.d}"/>
      <path class="tl-farea" d="${pf.a}"/><path class="tl-fline" d="${pf.d}"/>
      ${peak}
      <circle class="tl-dot" r="${5 * k}" cx="-99" cy="-99"/>
      <text class="tl-val" x="${W - padR}" y="${top + rh / 2}" style="font-size:${Math.min(20 * k, rh * 0.48)}px"></text>
    </g>`);
  });
  out.push(`<line class="tl-head" id="tl-head" x1="0" x2="0" y1="${axisH - 6 * k}" y2="${H}" style="transform:translateX(-9px)"/>`);
  svg.innerHTML = out.join("");
  TLG = { xT, y0: axisH, rh, vmax, rowsD, k, base: ri => axisH + ri * rh + rh - 5 * k, ph: rh - 12 * k, x0, x1 };
  for (const g of svg.querySelectorAll(".tl-row")) {
    g.onmouseenter = () => highlight(g.dataset.s || null);
    g.onmouseleave = () => highlight(null);
  }
  // 그래프를 누르거나 끌면 그 시각으로 — 지도가 따라온다
  let drag = false, last = -1;
  const go = ev => {
    const r = svg.getBoundingClientRect(), xx = ev.clientX - r.left;
    if (xx < TLG.x0 - 6 || xx > TLG.x1 + 6) return;
    const t = FLOW.t0 + (xx - TLG.x0) / (TLG.x1 - TLG.x0) * (FLOW.t1 - FLOW.t0);
    const i = nearestFrame(t);
    if (i !== last) { last = i; seek(i); }
  };
  svg.onpointerdown = ev => { drag = true; stopPlay(); svg.setPointerCapture(ev.pointerId); last = -1; go(ev); };
  svg.onpointermove = ev => { if (drag) go(ev); };
  svg.onpointerup = () => { drag = false; };
  // 처음 놓을 때는 미끄러지지 않게 — 화면 밖(-99)에서 날아 들어오는 것처럼 보인다
  svg.classList.add("noanim");
  tlPlayhead();
  requestAnimationFrame(() => requestAnimationFrame(() => svg.classList.remove("noanim")));
}

/* 재생 위치만 바꾼다 — 줄을 다시 그리지 않는다(재생 중 매 프레임 부른다) */
function tlPlayhead() {
  if (!TLG || !tlOn || !FLOW) return;
  const stat = SET.tl_stat === "mean" ? "mean" : "max";
  const ht = headT();
  const i = curFrame();
  const head = $("tl-head");
  if (head) head.style.transform = `translateX(${(ht != null ? TLG.xT(ht) : -9).toFixed(1)}px)`;
  // 값은 지도와 **같은 숫자**여야 한다 — 지금 그린 격자의 시군 통계(CURSTAT)를 먼저 쓴다
  const live = FLOWK.has(kind) && CURSTAT ? Object.fromEntries(CURSTAT.rows.map(r => [r.sigun, r[stat]])) : null;
  let topName = null, topV = 0;
  const rows = document.querySelectorAll(".tl-row");
  rows.forEach((g, ri) => {
    const r = TLG.rowsD[ri];
    let v = null;
    if (live && !r.tot) v = live[r.name];
    else if (i >= 0) v = r.v[i];
    else v = r.v[FLOW.frames.findLastIndex ? FLOW.frames.findLastIndex(f => f.kind === "obs") : -1];
    if (live && r.tot) v = i >= 0 ? r.v[i] : null;
    const dot = g.querySelector(".tl-dot"), txt = g.querySelector(".tl-val");
    const k = stepIdx(v, STEPS.m60), kc = rampColor(v, STEPS.m60, true);
    // cx·cy 를 style 로 줘야 CSS 전환이 걸린다(속성으로 바꾸면 순간이동한다)
    if (ht != null && v != null) {
      dot.style.cx = TLG.xT(ht).toFixed(1) + "px";
      dot.style.cy = (TLG.base(ri) - Math.min(v, TLG.vmax) / TLG.vmax * TLG.ph).toFixed(1) + "px";
      // 청색은 옅은 단계가 어두운 바탕에 묻혀 3단계부터 — 기상청 색은 그대로
      // 기상청 색도 1㎜ 아래는 바탕 쪽으로 섞어 둬서(fadeLow) 점이 묻힌다 — 그때는 회색 점
      dot.style.fill = !kc ? "var(--ink-3)" : kmaOn() ? (v >= 1 ? kc : "var(--ink-3)") : `var(--rain-${Math.max(3, k)})`;
      dot.style.opacity = "1";
    } else { dot.style.opacity = "0"; }
    txt.textContent = v == null ? "—" : v.toFixed(1);
    txt.classList.toggle("zero", !v);
    if (!r.tot && v != null && v > topV) { topV = v; topName = r.name; }
  });
  rows.forEach(g => g.classList.toggle("top", !!topName && g.dataset.s === topName && topV >= 0.1));
}


"use strict";
/* ── 시군 고르기 — 지도에서 시군을 누르면 오른쪽 패널이 그 시군으로 ──────────────────
   누적 카드: 격자 기준이면 그 시군 읍면동(읍면동마다 누적 최대 칸), AWS 기준이면 그 시군 지점 전부
   (내부망 스방이면 265곳 가운데 그 시군 것 — 여러 곳이 나온다). 예측 상위는 그 시군 읍면동,
   지금 오는 비는 그 시군 지점. 지도에는 테두리를 두르고 다른 시군 관측소를 흐리게 한다. */
function sigunAt(gx, gy) {
  if (!MSIG || !META || !GEO) return null;
  const hb = META.grids.hr, c = Math.round(gx) - hb.i0, r = Math.round(gy) - hb.j0;
  if (c < 0 || r < 0 || c >= hb.w || r >= hb.h) return null;
  const sg = GEO.sigun.find(s => s.id === MSIG[r * hb.w + c]);
  return sg && sg.kind === "gn" ? sg.name : null;
}
function drawSel() {
  const p = $("sel");
  if (!p || !PATH || !V) return;
  // 읍면동을 골랐으면 그 읍면동 둘레 · 바깥을 어둡게, 아니면 시군
  const selF = () => (ESEL.length && EFEAT ? EFEAT.filter(f => ESEL.includes(f.properties.id)) : FEAT.filter(f => isSel(f.properties.sigun)));
  const d = selF().map(f => PATH(f)).join("");
  p.setAttribute("d", d);
  $("selh").setAttribute("d", d);
  // 고른 시군(읍면동) 밖을 어둡게(GL 층 'selmask') — 아주 큰 네모에 고른 곳 바깥 둘레를 구멍으로
  glData("selmask", SELS.join() + "|" + ESEL.join(), () => {
    const sel = selF(), B = 1e4;
    if (!sel.length) return [];
    const holes = sel.flatMap(f => (f.geometry.type === "Polygon" ? [f.geometry.coordinates] : f.geometry.coordinates).map(p => p[0]));
    return [glF(glPoly([[[GC[0] - B, GC[1] - B], [GC[0] + B, GC[1] - B], [GC[0] + B, GC[1] + B], [GC[0] - B, GC[1] + B], [GC[0] - B, GC[1] - B]], ...holes]))];
  });
}
/* 지도·카드에서 시군을 눌렀다 — 그냥 누르면 그 시군 하나(이미 그것 하나면 풂), Ctrl 이면 더하거나 뺀다 */
function pickSig(sg, add) {
  if (add) {
    if (!sg) return;
    if (isSel(sg)) return setSel(SELS.filter(x => x !== sg));
    if (SELS.length >= SEL_MAX) { toast(`시군은 ${SEL_MAX}곳까지 비교한다 — 하나를 Ctrl+클릭으로 빼고 더하세요`); return; }
    return setSel([...SELS, sg]);
  }
  setSel(sg && !(SELS.length === 1 && SELS[0] === sg) ? [sg] : []);
}
function selectSig(name) { setSel(name ? [name] : []); }
/* 시군을 확대한 채 그 안 읍면동을 눌렀다 — 그냥 누르면 그 읍면동 하나(이미 그것 하나면 시군으로), Ctrl 이면 더하거나 뺀다 */
function pickEmd(id, add) {
  ESEL = id == null ? [] : add ? (ESEL.includes(id) ? ESEL.filter(x => x !== id) : [...ESEL, id])
    : ESEL.length === 1 && ESEL[0] === id ? [] : [id];
  drawSel(); selLabel(); camGo(true);
}
function emdIdAt(gx, gy) {
  if (!(MEMD instanceof Uint16Array)) return null;
  const hb = META.grids.hr, c = Math.round(gx) - hb.i0, r = Math.round(gy) - hb.j0;
  return c < 0 || r < 0 || c >= hb.w || r >= hb.h ? null : MEMD[r * hb.w + c] || null;
}
function selLabel() {
  const en = ESEL.map(id => EMDN?.get(id)?.name).filter(Boolean);
  $("acc-sel").hidden = !selOn();
  $("acc-sel").textContent = selOn() ? `${selName()}${en.length ? ` ${en.length > 2 ? `${en[0]} 외 ${en.length - 1}` : en.join("·")}` : ""} ✕` : "";
  $("acc-sel").title = selOn() ? `${SELS.join("·")}${en.length ? ` ${en.join("·")}` : ""} — 경남 전체로 (Esc)` : "경남 전체로 (Esc)";
}
let TOASTT = null;
function toast(msg) {
  const t = $("toast");
  t.textContent = msg; t.hidden = false;
  requestAnimationFrame(() => t.classList.add("on"));
  clearTimeout(TOASTT);
  TOASTT = setTimeout(() => { t.classList.remove("on"); setTimeout(() => { t.hidden = true; }, 250); }, 2200);
}
/* ── AI 상황판단 팝업(I) — 고른 시군(없으면 경남 전체)의 보고 → 예상 질문(규칙) → 더 묻기(LLM, 서버 GN_AI) ──
   보고와 예상 질문은 서버가 대시보드 수치와 위키 기준으로 만든다(app/aireport.py) — LLM 없이도 된다. */
const AIW = { open: false, seq: 0, scope: null, mode: "all" };
try { AIW.mode = localStorage.getItem("gn-ai-mode") || "all"; } catch {}
const aiEsc = t => String(t ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;");
const aiTxt = t => aiEsc(t).replace(/\[\[([^\]]+)\]\]/g, '<span class="wk">$1</span>');
/* LLM 답의 마크다운 — 소제목 · 굵게 · 목록(들여쓰기)만. 글자는 aiTxt 가 먼저 막으므로 HTML 이 새지 않는다 */
const aiInl = t => aiTxt(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "$1");
const aiMd = t => String(t ?? "").split(/\r?\n/).map(l => {
  const h = /^#{1,6}\s+(.*)$/.exec(l) || /^\*\*([^*]+)\*\*:?\s*$/.exec(l), li = /^(\s*)([-*•]|\d+[.)])\s+(.*)$/.exec(l);
  if (h) return `<h6>${aiInl(h[1])}</h6>`;
  if (li) return `<div class="li${li[1].length ? " sub" : ""}"><i>${/\d/.test(li[2]) ? aiEsc(li[2]) : "·"}</i><span>${aiInl(li[3])}</span></div>`;
  return !l.trim() || /^\s*(-{3,}|\*{3,})\s*$/.test(l) ? "" : `<p>${aiInl(l)}</p>`;
}).join("");
function aiSections(secs) {
  const last = secs.map(x => !!x.texts).lastIndexOf(true);    // 체크 칸들 맨 뒤에 적용 단추
  return secs.map((x, n) => {
    const todo = x.h === "할 일", ref = x.h.startsWith("참고");
    const list = x.items.map((i, k) => (x.texts ? `<li><label><input type="checkbox" data-t="${aiEsc(x.texts[k]).replace(/"/g, "&quot;")}"${x.on ? " checked" : ""}><span>${aiTxt(i)}</span></label></li>` : `<li>${aiTxt(i)}</li>`)).join("");
    return `<div class="sec${todo ? " todo" : ""}${x.texts ? " chk" : ""}${x.on ? " dn" : ""}${ref ? " ref" : ""}"><h5>${aiEsc(x.h)}</h5>${todo ? `<ol>${list}</ol>` : `<ul>${list}</ul>`}</div>`
      + (n === last ? `<div class="apl"><button type="button" id="aiw-apply" disabled>적용 — 체크한 일을 한 것으로 다시 판단</button></div>` : "");
  }).join("");
}
async function aiLoad() {
  if (!AIW.open) return;
  const sg = SELS[0] || null, my = ++AIW.seq;
  AIW.scope = sg;
  $("aiw-sc").textContent = sg || "경남 전체";
  $("aiw-all").hidden = !sg;
  $("aiw-tm").textContent = "";
  $("aiw-bd").innerHTML = `<div class="ld">${sg || "경남 전체"} 보고를 만드는 중… (읍면동 · 우려지역 · 기준 대조)</div>`;
  $("aiw-q").innerHTML = "";
  let r;
  const qs = new URLSearchParams({ mode: AIW.mode });
  if (sg) qs.set("sigun", sg);
  try { r = await getJson(`/api/ai/report?${qs}`); }
  catch (e) { if (my === AIW.seq) $("aiw-bd").innerHTML = `<div class="ld">못 만들었다 — ${aiEsc(e.message)}</div>`; return; }
  if (my !== AIW.seq) return;
  $("aiw-tm").textContent = r.tm ? `${md(r.tm)} ${hm(r.tm)} 실황 기준${window.GN_SNAP?.fake ? " · 가상" : ""}` : "";
  $("aiw-md").innerHTML = (r.modes || []).map(m => `<button type="button" role="tab" data-m="${m.id}" class="${m.id === (r.mode || "all") ? "on" : ""}"
    aria-selected="${m.id === (r.mode || "all")}">${aiEsc(m.label)}</button>`).join("");
  const fl = r.flash ? `<div class="flash t${r.flash.tone}"><b>속보</b>${aiTxt(r.flash.text)}</div><div class="hl">종합 해설</div>` : "";
  $("aiw-bd").innerHTML = fl + (r.title && r.mode && r.mode !== "all" ? `<div class="sec"><h5>${aiEsc(r.title)}</h5></div>` : "") + aiSections(r.sections);
  $("aiw-q").innerHTML = r.questions.map(q => `<button type="button" data-q="${q.id}">${aiEsc(q.label)}</button>`).join("");
  AIW.llm = r.llm;
  $("aiw-in").placeholder = r.llm ? "더 물어보기 — 지금 상황과 위키를 보고 답한다" : "더 물어보기 — (LLM 미연결: 위 질문 단추만 답한다)";
}
async function aiAsk(body, label) {
  const bd = $("aiw-bd"), my = AIW.seq;
  const blk = document.createElement("div");
  blk.innerHTML = `<div class="q">${aiEsc(label)}</div><div class="ans"><div class="ld">답을 찾는 중…</div></div>`;
  bd.appendChild(blk);
  blk.scrollIntoView({ behavior: "smooth", block: "start" });
  let a;
  try {
    const res = await fetch("/api/ai/ask", { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ sigun: AIW.scope, ...body }) });
    a = await res.json();
    if (!res.ok) throw new Error(a.detail || res.status);
  } catch (e) { a = { sections: [{ h: "답", items: ["못 받았다 — " + e.message] }] }; }
  if (my !== AIW.seq) return;
  blk.querySelector(".ans").innerHTML = (a.text ? `<div class="mdt">${aiMd(a.text)}</div>` : aiSections(a.sections || []))
    + `<div class="src">${aiEsc(a.source || "")}</div>`;
}
const aiChanged = () => [...$("aiw-bd").querySelectorAll("input[data-t]")].filter(b => b.checked !== b.defaultChecked);
$("aiw-bd").addEventListener("change", ev => {                // 체크만으로는 남기지 않는다 — 적용 단추로 한꺼번에
  if (!ev.target.closest("input[data-t]")) return;
  const n = aiChanged().length, b = $("aiw-apply");
  b.disabled = !n;
  b.textContent = n ? `적용 ${n}건 — 한 것으로 치고 다시 판단` : "적용 — 체크한 일을 한 것으로 다시 판단";
});
$("aiw-bd").addEventListener("click", async ev => {
  const b = ev.target.closest("#aiw-apply");
  if (!b) return;
  b.disabled = true;
  try {
    const r = await fetch("/api/ai/task", { method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tasks: aiChanged().map(x => ({ text: x.dataset.t, done: x.checked })) }) });
    if (!r.ok) throw new Error(r.status);
  } catch (e) { b.disabled = false; b.textContent = `적용하지 못했다 — ${e.message}`; return; }
  await aiLoad();
  if (AIW.llm) aiAsk({ text: "'조치 완료'에 적힌 일은 이미 했다고 치고 지금 상황을 다시 판단해 줘. ① 남은 위험 ② 지금 먼저 할 일 셋 ③ '별도 확인 필요' 중 먼저 확인할 것. 위키와 수치에 없는 기준은 만들지 말 것." }, "조치 반영 — 다시 판단");
});
function aiToggle(on = !AIW.open) {
  AIW.open = on;
  $("aiw").classList.toggle("open", on);
  $("aiw").setAttribute("aria-hidden", String(!on));
  $("b-ai").classList.toggle("on", on);
  if (on) aiLoad();
}

function setSel(list) {
  if (list.join() !== SELS.join()) ESEL = [];             // 시군이 바뀌면 고른 읍면동은 푼다
  SELS = list.slice(0, SEL_MAX);
  sjSync(SELS);                                           // 상황판단 창(또는 지도 창)도 같은 시군으로
  if (AIW.open && AIW.scope !== (list[0] || null)) setTimeout(aiLoad, 0);   // 시군을 바꾸면 그 시군 보고로
  drawSel(); drawStations(); hot(null); link(null);
  watchBadges(); renderAlertLegend(); renderRiverLegend(); renderTideLegend();   // 왼쪽 아이콘 · 목록도 고른 시군으로
  if (WATCH_OPEN) watchOpen(WATCH_OPEN);
  if (!$("ly-fc-pop").hidden) fcLoad();
  selLabel();
  if (zoomOn()) ensureEmd();
  if (SET.panel === "timeline") { camGo(true); return; }  // 타임라인 패널은 시군 줄이 이미 다 있다 — 테두리(·확대)만
  if (!tlOn) { CARDS = null; if (selOn()) setTL(true, false); else camGo(true); return; }   // 닫혀 있으면 연다(설정에는 안 남긴다)
  camGo(true);
  loadCards();
}
function toggleBasis() {
  ACC_BASIS = ACC_BASIS === "aws" ? "grid" : "aws";
  if (!CASE) { SET.acc_basis = ACC_BASIS; saveSetting({ acc_basis: ACC_BASIS }); }
  for (const b of $("acc-h").querySelectorAll(".bs b")) b.classList.toggle("on", b.dataset.b === ACC_BASIS);
  // 지도도 같은 자료로 — 1시간 · 누적 층이면 짝 층으로(격자 ↔ AWS). 다른 층은 그대로, 재생 흐름만 그 자료로
  if (!CASE) {
    const nk = normKind(kind);
    if (nk !== kind) { stopPlay(); choose(nk, true); }
    else { buildMenu(); if (FLOW && (FLOW.src || "grid") !== flowSrc()) loadFlow(); }
  }
  if (isDay()) return;                    // 단기 오늘·내일 — 위 카드가 그날 예보 합이라 기준이 없다(자료만 바꿔 둔다)
  if (SET.panel === "timeline") return;
  if (!tlOn) { CARDS = null; setTL(true, false); return; }
  loadCards();
}


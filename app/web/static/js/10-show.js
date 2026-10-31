"use strict";
/* ── 화면 재생(P) — 화면보호기처럼 여러 화면을 차례로(10-24) ───────────────────────────
   재생목록 = 화면(층 · 자료 · 누적 구간)과 머무는 초의 차례. 같은 종류도 여럿(AWS 24시간 · AWS 48시간 …).
   목록은 서버 설정 shows([{name, items:[{t, b?, h?, n?, sec}]}]) — 어느 화면에서 만들어도 벽면에서 불러 쓴다.
   ⚠️ 재생 중에는 층 · 누적 구간 · 자료를 **이 화면에서만** 바꾼다(saveSetting 이 막힌다) — 다른 화면 설정을 흔들지 않게.
   끝내면 재생 앞 상태로 돌아간다. 재생하던 목록 이름은 이 브라우저에 기억 — 새로고침해도 이어서(?show=이름 도) */
const SLIDE = {
  acc_h:      { g: "누적", nm: s => `${bn(s)} 지난 ${s.h}시간 누적`, p: ["b", "h"], d: { b: "aws", h: 24 }, tip: "지난 N시간(1시간~7일)" },
  acc_from:   { g: "누적", nm: s => `${bn(s)} ${s.n}시부터 누적`, p: ["b", "n"], d: { b: "aws", n: 9 }, tip: "오늘 N시부터(지났으면 어제 N시부터)" },
  acc_day:    { g: "누적", nm: s => `${bn(s)} ${dayNm(s.d)} ${s.n}시부터 누적`, p: ["b", "d", "n"], d: { b: "aws", d: 1, n: 18 }, tip: "날짜 지정 — 며칠 전 몇 시부터(어제 18시부터 · 3일 전 9시부터 …), 날마다 그날 기준" },
  acc_today:  { g: "누적", nm: s => `${bn(s)} 오늘 0시부터 누적`, p: ["b"], d: { b: "aws" }, tip: "오늘 0시부터 지금까지" },
  acc_yday:   { g: "누적", nm: s => `${bn(s)} 어제 0시부터 누적`, p: ["b"], d: { b: "aws" }, tip: "어제 0시부터 지금까지" },
  h1:         { g: "지금", nm: s => `${bn(s)} 1시간 강수량`, p: ["b"], d: { b: "aws" }, tip: "가장 최근 1시간" },
  m15:        { g: "지금", nm: () => "격자 15분 강수량", p: [], d: {}, tip: "가장 최근 15분(500m 격자)" },
  flow:       { g: "지금", nm: s => `${bn(s)} 흐름 재생`, p: ["b"], d: { b: "grid" }, tip: "지난 시간 → 지금 → 초단기 +6시간을 재생" },
  vsrt:       { g: "예측", nm: s => `초단기 +${s.n}시간`, p: ["v"], d: { n: 1 }, tip: "초단기예보 N시간 뒤(1~6)" },
  shrt_today: { g: "예측", nm: () => "오늘 24시까지 강수량", p: [], d: {}, tip: "단기예보 오늘 하루 합" },
  shrt_tomorrow: { g: "예측", nm: () => "내일 24시까지 강수량", p: [], d: {}, tip: "단기예보 내일 하루 합" },
};
const bn = s => (s.b === "aws" ? "AWS" : "격자");
const dayNm = d => ["오늘", "어제", "그제"][d] || `${d}일 전`;
const SC_OK = t => t.startsWith("acc_") || t.startsWith("shrt");   // 따로 쓰는 범례를 고를 수 있는 화면(누적 · 단기)
const SHOW_SECS = [5, 10, 15, 20, 30, 45, 60, 90, 120, 180, 300, 600];
const fmtSec = n => (n >= 60 ? `${Math.floor(n / 60)}분${n % 60 ? ` ${n % 60}초` : ""}` : `${n}초`);
const slideOf = (t, more = {}) => ({ t, ...SLIDE[t].d, sec: 30, ...more });
const showLists = () => (Array.isArray(SET.shows) ? SET.shows : []);

/* 한 화면 보이기 — 서버에 남기지 않고 이 화면에서만 */
function slideKind(s) {
  const aws = s.b === "aws";
  if (s.t.startsWith("acc_")) return aws ? "aws" : "acc";
  if (s.t === "h1" || s.t === "flow") return aws ? "aws60" : "obs60";
  if (s.t === "m15") return "obs15";
  return s.t;                                           // vsrt · shrt_today · shrt_tomorrow
}
async function applySlide(s) {
  stopPlay(true);
  if (s.b && ACC_BASIS !== s.b) { ACC_BASIS = s.b; SET.acc_basis = s.b; }
  SET._accLabel = "";
  const hr = NOWD().getHours();
  if (s.t === "acc_h") { SET.acc_from = "hours"; SET.acc_hours = s.h; }
  if (s.t === "acc_from") {               // N시부터 — 지난 몇 시간인지로 바꿔 부른다(지났으면 어제 N시부터)
    let H = hr - s.n; const today = H >= 1;
    if (!today) H += 24;
    SET.acc_from = "hours"; SET.acc_hours = Math.max(1, Math.min(48, H)); SET._accLabel = `${today ? "오늘" : "어제"} ${s.n}시부터`;
  }
  if (s.t === "acc_day") {                // 며칠 전 몇 시부터 — 날마다 그날 기준(재생목록이 낡지 않게). 아직 안 온 시각이면 지금 시
    const t = NOWD(), d = new Date(t.getFullYear(), t.getMonth(), t.getDate() - s.d);
    const n = s.d === 0 ? Math.min(s.n, t.getHours()) : s.n;
    SET.acc_from = "date"; SET.acc_date = n ? `${ymd(d)}${String(n).padStart(2, "0")}` : ymd(d);
  }
  if (s.t === "acc_today") SET.acc_from = "today";
  if (s.t === "acc_yday") SET.acc_from = "yesterday";
  if (s.t === "vsrt") vsrtN = s.n;
  SLIDE_SC = SC_OK(s.t) && s.sc ? s.sc : 0;  // 이 화면만 따로 쓰는 범례(72시간 누적 ↔ 내일 24시까지를 같은 자로 견주기)
  CARDS = null;
  choose(slideKind(s), false);
  loadCards();
  if (s.t === "flow") {                    // 흐름 재생 — 처음부터 돌린다
    if (!FLOW || (FLOW.src || "grid") !== flowSrc()) await loadFlow();
    if (SHOW.on && SHOW.items[SHOW.i] === s) { seek(0); startPlay(); }
  }
}
function showGo(i) {
  clearTimeout(SHOW.timer);
  if (!SHOW.on || !SHOW.items.length) return;
  SHOW.i = (i + SHOW.items.length) % SHOW.items.length;
  const s = SHOW.items[SHOW.i];
  applySlide(s);
  renderDots();
  if (!SHOW.paused) SHOW.timer = setTimeout(() => showGo(SHOW.i + 1), s.sec * 1000);
}
function startShow(items, name = "") {
  if (CASE || !items?.length) return;
  try { if (name) localStorage.setItem("gn-map-show-last", name); } catch {}
  if (!SHOW.on) SHOW.prev = { kind, vsrtN, basis: ACC_BASIS, sbasis: SET.acc_basis, from: SET.acc_from, hours: SET.acc_hours, date: SET.acc_date };
  Object.assign(SHOW, { on: true, items: items.map(x => ({ ...x })), name, paused: false });
  try { name ? localStorage.setItem("gn-map-show", name) : localStorage.removeItem("gn-map-show"); } catch {}
  document.body.classList.add("show-on");
  $("showdots").hidden = false;
  $("b-show").classList.add("on");
  showGo(0);
}
function stopShow() {
  if (!SHOW.on) return;
  clearTimeout(SHOW.timer);
  SHOW.on = false;
  try { localStorage.removeItem("gn-map-show"); } catch {}
  document.body.classList.remove("show-on");
  $("showdots").hidden = true;
  $("b-show").classList.remove("on");
  const p = SHOW.prev;                   // 재생 앞으로 — 이 화면에서만 바꿨으니 되돌리기만
  stopPlay();
  SLIDE_SC = 0;
  if (p) {
    ACC_BASIS = p.basis; Object.assign(SET, { acc_basis: p.sbasis, acc_from: p.from, acc_hours: p.hours, acc_date: p.date, _accLabel: "" });
    vsrtN = p.vsrtN; CARDS = null; choose(p.kind, false); loadCards();
  }
}
function showPause(on = !SHOW.paused) {
  SHOW.paused = on;
  clearTimeout(SHOW.timer);
  if (!on) showGo(SHOW.i);                // 다시 — 그 화면을 처음부터
  else renderDots();
}
function renderDots() {
  const box = $("showdots"), s = SHOW.items[SHOW.i];
  box.classList.toggle("paused", SHOW.paused);
  $("sd-name").textContent = SHOW.name || "재생목록";
  $("sd-lab").textContent = s ? `${SHOW.i + 1}/${SHOW.items.length} · ${SLIDE[s.t].nm(s)}` : "";
  box.querySelector('[data-a="pause"]').textContent = SHOW.paused ? "▶" : "❙❙";
  // 새로 그려야 지금 점의 채움이 처음부터 다시 돈다
  box.querySelector(".sd-dots").innerHTML = SHOW.items.map((x, j) =>
    `<i data-j="${j}" class="${j === SHOW.i ? "on" : ""}" style="--dur:${x.sec}s" title="${j + 1}. ${SLIDE[x.t].nm(x)} · ${fmtSec(x.sec)}"></i>`).join("");
}
$("showdots").addEventListener("click", ev => {
  const d = ev.target.closest("[data-j]"), a = ev.target.closest("[data-a]")?.dataset.a;
  if (d) { SHOW.paused = false; showGo(+d.dataset.j); return; }
  if (a === "prev") showGo(SHOW.i - 1);
  else if (a === "next") showGo(SHOW.i + 1);
  else if (a === "pause") showPause();
  else if (a === "stop") stopShow();
  else if (a === "edit") openShowDlg(SHOW.name);
});
/* P — 재생 중이면 끝, 아니면 마지막에 튼 목록(없으면 첫 목록, 그것도 없으면 만들기 창) */
function showQuick() {
  let last = "";
  try { last = localStorage.getItem("gn-map-show-last") || ""; } catch {}
  const L = showLists(), sh = L.find(x => x.name === last) || L[0];
  if (sh) startShow(sh.items, sh.name); else openShowDlg();
}
$("b-show").onclick = () => (SHOW.on ? openShowDlg(SHOW.name) : openShowDlg());

/* ── 재생목록 창 ── */
const SED = { name: "", items: [], from: "", msg: "" };    // 고치는 중인 목록(저장 전)
let SED_DRAG = null;                                       // 끄는 것 — { j } 줄 · { t } 새 화면
function openShowDlg(name) {
  const L = showLists(), sh = L.find(x => x.name === name) || (name === undefined && L[0]) || null;
  Object.assign(SED, sh ? { name: sh.name, items: sh.items.map(x => ({ ...x })), from: sh.name }
                        : { name: "새 재생목록", items: [], from: "" }, { msg: "" });
  if (SHOW.on && !SHOW.paused) showPause(true);           // 고치는 동안은 멈춘다
  renderShowDlg();
  $("showdlg").hidden = false;
}
function closeShowDlg() { $("showdlg").hidden = true; if (SHOW.on && SHOW.paused) showPause(false); }
function sedRow(x, j) {
  const S = SLIDE[x.t], sel = (k, opts, v) => `<select data-k="${k}" data-j="${j}">${opts.map(([a, l]) => `<option value="${a}"${String(a) === String(v) ? " selected" : ""}>${l}</option>`).join("")}</select>`;
  const ps = S.p.map(k => k === "b" ? sel("b", [["aws", "AWS"], ["grid", "격자"]], x.b)
    : k === "h" ? sel("h", [1, 2, 3, 6, 9, 12, 18, 24, 36, 48, 72, 96, 120, 144, 168].map(v => [v, v % 24 || v < 72 ? `${v}시간` : `${v}시간(${v / 24}일)`]), x.h)
    : k === "d" ? sel("d", [...Array(ACC_DATE_DAYS + 1).keys()].map(v => [v, dayNm(v)]), x.d)
    : k === "n" ? sel("n", [...Array(24).keys()].map(v => [v, `${v}시부터`]), x.n)
    : sel("n", [1, 2, 3, 4, 5, 6].map(v => [v, `+${v}시간`]), x.n)).join("")
    // 따로 쓰는 범례 — 체크하면 이 화면만 그 끝 눈금(누적 · 단기). 72시간 누적 ↔ 내일 24시까지를 같은 자로
    + (SC_OK(x.t) ? `<label class="scl" title="이 화면만 따로 범례(끝 눈금) — 끄면 지도 설정을 따른다"><input type="checkbox" data-k="scon" data-j="${j}"${x.sc ? " checked" : ""}>범례</label>`
      + `<select data-k="sc" data-j="${j}"${x.sc ? "" : " disabled"}>${[30, 60, 150, 300, 800].map(v => `<option value="${v}"${(x.sc || 150) === v ? " selected" : ""}>${v}㎜</option>`).join("")}</select>` : "");
  return `<div class="row" draggable="true" data-j="${j}"><span class="h" title="끌어서 차례 바꾸기">⋮⋮</span><span class="no">${j + 1}</span>
    <span class="nm">${SLIDE[x.t].nm(x)}${ps}</span>${sel("sec", SHOW_SECS.map(v => [v, fmtSec(v)]), x.sec)}
    <button class="ib2" data-a="dup" data-j="${j}" title="같은 것 하나 더(값을 바꿔 쓴다 — 예: AWS 24 · 48시간)">⧉</button><button class="ib2" data-a="del" data-j="${j}" title="빼기">✕</button></div>`;
}
function renderShowDlg() {
  const L = showLists(), tot = SED.items.reduce((a, x) => a + x.sec, 0);
  const groups = {};
  for (const [t, S] of Object.entries(SLIDE)) (groups[S.g] ||= []).push(t);
  $("showdlg").innerHTML = `<div class="box" role="dialog" aria-label="화면 재생">
    <div class="top"><b>화면 재생</b><span class="msg">여러 화면을 차례로 — 화면보호기처럼. 왼쪽을 누르거나 오른쪽으로 끌어 넣고, 오른쪽에서 끌어 차례를 바꾼다</span><span class="sp"></span><button class="x" data-a="close" title="닫기 (Esc)">✕</button></div>
    <div class="lists"><label>재생목록</label><select id="sd-pick"><option value="">— 새로 —</option>${L.map(x => `<option${x.name === SED.from ? " selected" : ""}>${esc(x.name)}</option>`).join("")}</select>
      <label>이름</label><input type="text" id="sd-nm" maxlength="30" value="${esc(SED.name)}">
      <button class="btn" data-a="save">저장</button><button class="btn" data-a="new">새로</button><button class="btn" data-a="rm"${SED.from ? "" : " disabled"}>지우기</button>
      <span class="msg" id="sd-msg">${SED.msg}</span></div>
    <div class="cols"><div class="cat">${Object.entries(groups).map(([g, ts]) => `<h5>${g}</h5>` + ts.map(t =>
        `<button draggable="true" data-add="${t}" title="누르면 맨 뒤에 더한다 · 오른쪽으로 끌어 그 자리에">${SLIDE[t].nm(slideOf(t)).replace(/^(AWS|격자) /, "")}<small>${SLIDE[t].tip}</small></button>`).join("")).join("")}</div>
      <div class="seq" id="sd-seq"><div class="hd"><span>재생 차례 ${SED.items.length}화면</span><span>한 바퀴 ${fmtSec(tot)}</span></div>
        <div class="rows">${SED.items.length ? SED.items.map(sedRow).join("") : `<div class="empty">왼쪽에서 화면을 눌러 더하세요 — 같은 종류도 여럿(AWS 24시간 · 48시간 …)</div>`}</div></div></div>
    <div class="foot"><span class="msg">재생 중에는 층 · 구간을 이 화면에서만 바꾼다(다른 화면 설정은 그대로). 끝은 Esc · P · 점 위 ✕</span><span class="sp"></span>
      ${SHOW.on ? `<button class="btn" data-a="stop">재생 끝</button>` : ""}<button class="btn pri" data-a="play"${SED.items.length ? "" : " disabled"}>▶ 재생</button></div></div>`;
}
const esc = t => String(t ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/"/g, "&quot;");
async function putShows(list) {
  const r = await fetch("/api/settings/map", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ shows: list }) });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
  SET.shows = (await r.json()).map.shows;
}
$("showdlg").addEventListener("click", async ev => {
  if (ev.target.id === "showdlg") return closeShowDlg();
  const add = ev.target.closest("[data-add]"), a = ev.target.closest("[data-a]")?.dataset.a;
  SED.name = $("sd-nm")?.value.trim() || SED.name;
  if (add) { SED.items.push(slideOf(add.dataset.add)); SED.msg = ""; renderShowDlg(); $("showdlg").querySelector(".rows").scrollTop = 1e6; return; }
  if (!a) return;
  const j = +ev.target.closest("[data-j]")?.dataset.j;
  if (a === "close") return closeShowDlg();
  if (a === "dup") { SED.items.splice(j + 1, 0, { ...SED.items[j] }); renderShowDlg(); return; }
  if (a === "del") { SED.items.splice(j, 1); renderShowDlg(); return; }
  if (a === "new") { Object.assign(SED, { name: "새 재생목록", items: [], from: "", msg: "" }); renderShowDlg(); return; }
  if (a === "stop") { stopShow(); renderShowDlg(); return; }
  if (a === "save" || a === "rm") {
    const name = SED.name.slice(0, 30);
    if (a === "save" && (!name || !SED.items.length)) { SED.msg = "이름과 화면 하나 이상이 있어야 저장한다"; renderShowDlg(); return; }
    // 저장 — 고치던 목록(이름을 바꿨어도) 그 자리에, 같은 이름이 따로 있으면 그것을 갈음. 지우기 — 고치던 목록을
    let L = showLists().slice();
    const at = L.findIndex(x => x.name === SED.from);
    if (a === "rm") L = L.filter(x => x.name !== SED.from);
    else {
      L = L.filter((x, i) => i === at || x.name !== name);
      const k2 = L.findIndex(x => x.name === SED.from);
      if (k2 >= 0) L[k2] = { name, items: SED.items }; else L.push({ name, items: SED.items });
    }
    try { await putShows(L); SED.msg = a === "save" ? `저장했다 — ${name}` : `지웠다 — ${SED.from}`; SED.from = a === "save" ? name : ""; }
    catch (e) { SED.msg = `못 했다 — ${e.message}`; }
    renderShowDlg(); return;
  }
  if (a === "play") {
    try { if (SED.from) localStorage.setItem("gn-map-show-last", SED.from); } catch {}
    $("showdlg").hidden = true;
    startShow(SED.items, SED.from && showLists().some(x => x.name === SED.from) ? SED.from : "");
  }
});
$("showdlg").addEventListener("change", ev => {
  const t = ev.target;
  if (t.id === "sd-pick") { openShowDlg(t.value || null); return; }   // 빈 값 = 새로
  if (t.id === "sd-nm") { SED.name = t.value.trim(); return; }
  const j = +t.dataset.j, k = t.dataset.k;
  if (!k || !SED.items[j]) return;
  if (k === "scon") { if (t.checked) SED.items[j].sc = 150; else delete SED.items[j].sc; renderShowDlg(); return; }
  SED.items[j][k] = k === "b" ? t.value : +t.value;
  renderShowDlg();
});
// 끌기 — 왼쪽 화면을 오른쪽 차례 자리로, 오른쪽 줄끼리 차례 바꾸기(HTML 끌어 놓기)
$("showdlg").addEventListener("dragstart", ev => {
  const r = ev.target.closest(".row[data-j]"), c = ev.target.closest("[data-add]");
  SED_DRAG = r ? { j: +r.dataset.j } : c ? { t: c.dataset.add } : null;
  if (r) r.classList.add("drag");
  ev.dataTransfer.effectAllowed = "move"; ev.dataTransfer.setData("text/plain", "x");
});
const sedSlot = ev => {                  // 놓을 자리 — 줄 위 반이면 그 앞, 아래 반이면 그 뒤
  const r = ev.target.closest(".row[data-j]");
  if (!r) return SED.items.length;
  const b = r.getBoundingClientRect();
  return +r.dataset.j + (ev.clientY > b.top + b.height / 2 ? 1 : 0);
};
$("showdlg").addEventListener("dragover", ev => {
  if (!SED_DRAG || !ev.target.closest("#sd-seq")) return;
  ev.preventDefault();
  $("sd-seq").classList.add("over");
  const at = sedSlot(ev);
  $("showdlg").querySelectorAll(".row").forEach((r, j) => { r.classList.toggle("ins", j === at); r.classList.toggle("ins-after", at === SED.items.length && j === SED.items.length - 1); });
});
$("showdlg").addEventListener("dragleave", ev => { if (ev.target.id === "sd-seq") $("sd-seq").classList.remove("over"); });
$("showdlg").addEventListener("drop", ev => {
  if (!SED_DRAG || !ev.target.closest("#sd-seq")) return;
  ev.preventDefault();
  let at = sedSlot(ev);
  if (SED_DRAG.t) SED.items.splice(at, 0, slideOf(SED_DRAG.t));
  else { const [x] = SED.items.splice(SED_DRAG.j, 1); if (at > SED_DRAG.j) at--; SED.items.splice(at, 0, x); }
  SED_DRAG = null; renderShowDlg();
});
$("showdlg").addEventListener("dragend", () => { SED_DRAG = null; $("showdlg").querySelectorAll(".row").forEach(r => r.classList.remove("drag", "ins", "ins-after")); $("sd-seq")?.classList.remove("over"); });
/* 새로고침해도 이어서 — 이 브라우저가 재생하던 목록(또는 ?show=이름) */
function showResume() {
  let name = Q.get("show") || "";
  if (!name) { try { name = localStorage.getItem("gn-map-show") || ""; } catch {} }
  const sh = name && showLists().find(x => x.name === name);
  if (sh) startShow(sh.items, sh.name);
}


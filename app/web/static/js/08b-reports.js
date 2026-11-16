"use strict";
/* ── 보고서 창(오른쪽 위 첫 단추) — 언레이드 재난상황보고서 서버(jaenan-weather)가 만드는 한글 보고서 · 그림을 받기 · 텔레그램으로 보내기.
   그림 작업이 여러 장이면 zip 으로 받고, 텔레그램은 장마다. 작성 창이 있는 보고서(compose — 상황판단회의)는 타일을 누르면 작성 창.
   목록 · 옵션 정의는 서버 등록부(app/reports.py REG)를 그대로 그린다 — 보고서가 늘면 거기 한 줄. 썸네일 img/reports/<id>.png, 없으면 문서 모양 자리표시.
   타일 오른쪽 누름(· 메뉴 키 · Shift+F10 · 타일의 ⚙) = 그 보고서 옵션창 — 런처(윈도우 앱) 옵션 가운데 서버에서 되는 것. 이 브라우저에 보고서별로 기억하고,
   보낼 때는 기본값과 다른 것만(안 보낸 것은 서버 설정을 따른다). 머리 ⚙ = 전체 설정(받을 때 텔레그램에도).
   17시 대기(등록부 wait) — 서버가 1분마다 묻고, 이 화면은 상태만 1분마다 가볍게(걸린 것이 있을 때만) 물어 타일 · 도구 줄 단추에 표시 */
const REP = { d: null, g: "전체", busy: null, t0: 0, tick: 0, set: false, back: null, msg: null, w: {}, op: null, opBack: null };
const repPref = () => { try { return JSON.parse(localStorage.getItem("gn-rep") || "{}"); } catch { return {}; } };
function repSave(p) { try { localStorage.setItem("gn-rep", JSON.stringify({ ...repPref(), ...p })); } catch {} }
const repName = cd => { const m = /filename\*=UTF-8''([^;]+)/i.exec(cd || ""); return m ? decodeURIComponent(m[1]) : ""; };
const REP_TG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 4 3 11l6 2.2M21 4l-3.2 15.5L9 13.2M21 4 9 13.2v5.3l3.2-3.2"/></svg>';
const REP_CLK = '<svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="6.2"/><path d="M8 4.6V8l2.4 1.5"/></svg>';
const repById = id => (REP.d?.reports || []).find(r => r.id === id);
const repSame = (a, b) => JSON.stringify(a ?? "") === JSON.stringify(b ?? "");
/* 이 보고서의 저장된 옵션(없으면 기본값) · 서버로 보낼 것(기본값과 다른 것만) · 바뀐 것이 있나 */
const repVals = r => ({ ...Object.fromEntries(r.opts.map(o => [o.key, o.default])), ...(repPref().opts?.[r.id] || {}) });
const repSend = r => { const v = repVals(r); return Object.fromEntries(r.opts.filter(o => !repSame(v[o.key], o.default)).map(o => [o.key, v[o.key]])); };
const repChanged = r => r.opts.some(o => { const s = repPref().opts?.[r.id]; return s && o.key in s && !repSame(s[o.key], o.default); });

async function openRep() {
  REP.back = document.activeElement;
  $("rep").hidden = false;
  repDraw();
  try { REP.d = await getJson("/api/reports"); } catch (e) { REP.d = { err: e.message, reports: [], groups: [] }; }
  if (!$("rep").hidden) repDraw();
  repPoll();
}
function closeRep() {
  $("rep").hidden = true; REP.set = false; REP.op = null;
  if (REP.back?.isConnected) REP.back.focus();
}
/* 왜 못 만드나 — 시연 · 토큰 없음 · 다른 보고서를 만드는 중 */
function repWhy(r) {
  const d = REP.d;
  if (!r.ready) return "준비 중";
  if (d?.demo) return "시연 화면에서는 만들지 않는다";
  if (d && !d.ready) return "재난상황보고서 서버 토큰이 없다";
  if (REP.busy && REP.busy !== r.id) return "다른 보고서를 만드는 중 — 서버는 한 번에 하나, 끝나면 누르세요";
  return "";
}
/* 17시 대기 표시 — 대기 중(시계) · 준비됨(✓, 누르면 저장해 둔 파일) · 그만둠(사유) */
function repWaitBadge(r) {
  const w = REP.w[r.id];
  if (!w) return "";
  const t = w.state === "waiting" ? "17시 대기 중" : w.state === "ready" ? "17시 보고서 준비됨 — 눌러 받기" : "17시 대기 그만둠";
  const tip = w.state === "waiting" ? `${w.until?.slice(11, 16)} 까지 1분마다 확인${w.status ? ` — 지금 ${w.status}` : ""}${w.tg ? " · 나오면 텔레그램으로" : ""}`
    : w.state === "ready" ? `${w.at?.slice(11, 16)} 에 만들었다${w.tg_st === "ok" ? " · 텔레그램으로 보냈다" : w.tg_st ? ` · 텔레그램 실패` : ""}` : w.why || "";
  return `<div class="rt-w ${escH(w.state)}" title="${escH(tip)}">${w.state === "ready" ? "✓" : REP_CLK}<span>${escH(t)}</span>`
    + `<button type="button" data-wx="${escH(r.id)}" aria-label="${escH(`${r.name} 17시 대기 ${w.state === "waiting" ? "취소" : "지우기"}`)}">${w.state === "waiting" ? "취소" : "지우기"}</button></div>`;
}
function repTile(r) {
  const why = repWhy(r), busy = REP.busy === r.id, off = !!why || busy, d = REP.d || {}, w = REP.w[r.id], rd = w?.state === "ready";
  const th = `<span class="th">${r.thumb ? `<img src="img/reports/${escH(r.id)}.png" alt="" loading="lazy">` : ""}`
    + `<i class="ph" aria-hidden="true"><b></b><u></u><u></u><u></u><u></u><u></u></i>`
    + (busy ? `<em class="run" role="status"><i class="ldbar"><i></i></i>만드는 중 · <span class="sec">${Math.round((Date.now() - REP.t0) / 1000)}</span>초</em>` : "")
    + (!r.ready ? `<em class="soon">준비 중</em>` : "") + (r.ready && repChanged(r) ? `<em class="chg" title="기본값과 다른 옵션이 있다">옵션</em>` : "") + `</span>`;
  const lab = rd ? `${r.name} — 17시 보고서 받기` : `${r.name} 받기${why ? ` — ${why}` : ""}`;
  return `<div class="rt${busy ? " busy" : ""}${r.ready ? "" : " off"}${w ? ` w-${escH(w.state)}` : ""}" data-id="${escH(r.id)}">`
    + `<button type="button" class="rt-main" data-get="${escH(r.id)}"${off && !rd && !r.compose ? " disabled" : ""} title="${escH(rd ? "저장해 둔 17시 보고서를 받는다" : r.compose ? `${r.name} 작성 — 문구를 골라 만든다` : why || `${r.name} 받기 · 오른쪽 누름: 옵션`)}" aria-label="${escH(r.compose ? `${r.name} 작성 창 열기` : lab)}">`
    + `${th}<span class="nm"><b>${escH(r.name)}</b><small>${escH(r.desc)}</small></span></button>`
    + (r.ready && !r.compose ? `<button type="button" class="rt-tg" data-tg="${escH(r.id)}"${off || !d.tg ? " disabled" : ""} aria-label="${escH(`${r.name} 텔레그램으로 보내기`)}"`
      + ` title="${escH(why || (d.tg ? "텔레그램으로 보내기만(받지 않음)" : "텔레그램 키가 없다 — 설정 › API 키"))}">${REP_TG}</button>`
      : "") + (r.ready ? `<button type="button" class="rt-op${r.compose ? " cm" : ""}" data-op="${escH(r.id)}" aria-label="${escH(`${r.name} ${r.compose ? "작성 창" : "옵션"}`)}" title="${r.compose ? "작성 창" : "옵션"} — 타일 오른쪽 누름 · Shift+F10 과 같다">⚙</button>` : "")
    + repWaitBadge(r) + `</div>`;
}
function repSettings() {
  const d = REP.d || {}, p = repPref();
  return `<div class="set" id="rep-set"><b>전체 설정</b>`
    + `<label class="ck"><input type="checkbox" id="rep-tg"${p.tg ? " checked" : ""}${d.tg ? "" : " disabled"}> 받을 때 텔레그램에도 보내기${d.tg ? "" : ` <span class="mute">— 텔레그램 키가 없다</span>`}</label>`
    + `<p class="mute">보고서별 옵션은 타일을 오른쪽 눌러(또는 타일의 ⚙) 연다 · 이 브라우저에만 기억한다.</p>` + repLogos() + `</div>`;
}
/* 로고 — 보고서 [로고] 칸 그림(재난상황보고서 서버 /config/logos + 기본). 고르면 서버 전체에 걸린다(이 브라우저만이 아니다) */
function repLogos() {
  const d = REP.d || {}, L = REP.logos;
  const body = d.demo ? `<p class="mute">시연 화면에서는 로고를 보거나 올리지 않는다</p>` : !d.ready ? `<p class="mute">재난상황보고서 서버 토큰이 없어 로고를 못 본다</p>`
    : !L ? `<p class="mute">로고 목록을 받는 중…</p>` : L.err ? `<p class="mute">로고 목록을 받지 못했다 — ${escH(L.err)}</p>`
    : `<div class="lg" role="radiogroup" aria-label="로고 고르기">${L.logos.map(x => `<button type="button" role="radio" aria-checked="${x.name === L.selected}" data-logo="${escH(x.name)}" class="${x.name === L.selected ? "on" : ""}" title="${escH(x.name)}${x.user ? " · 올린 로고" : " · 기본 로고"}">`
      + `<img src="/api/reports/logos/img?name=${encodeURIComponent(x.name)}" alt=""><span>${x.name === L.selected ? "✓ " : ""}${escH(x.name)}</span></button>`).join("")}</div>`
      + `<label class="lgadd"><input type="file" id="rep-logo" accept="image/png,image/jpeg,image/webp"> 로고 추가 <span class="mute">PNG · JPG · WEBP, 2MB 이하 — 서버가 PNG 로 바꿔 둔다</span></label>`;
  return `<b class="lgh">로고 <span class="mute">[로고] 칸이 있는 보고서에 높이 11mm 로 — 서버 설정이라 모두에게 같다</span></b>${body}<p class="msg" id="rep-lm" role="status"></p>`;
}
async function repLogoLoad() {
  if (!REP.d?.ready || REP.d?.demo) return;
  try { REP.logos = await getJson("/api/reports/logos"); } catch (e) { REP.logos = { err: e.message }; }
  if (REP.set && !$("rep").hidden && !REP.op) repDraw();
}
async function repLogoSend(res, ok) {
  const j = await res.json().catch(() => ({}));
  if (!res.ok) { $("rep-lm").textContent = `안 됐다 — ${j.detail || res.status}`; $("rep-lm").className = "msg bad"; return; }
  await repLogoLoad();
  if ($("rep-lm")) $("rep-lm").textContent = ok(j);
}
/* 옵션창 — 등록부 opts 정의대로(묶음 = sec). 일시 · 수 · 고르기 · 여러 개 · 켜고 끄기 · 글 */
const repDt = v => (v && v.length === 12 ? `${v.slice(0, 4)}-${v.slice(4, 6)}-${v.slice(6, 8)}T${v.slice(8, 10)}:${v.slice(10, 12)}` : "");
function repField(o, v) {
  const id = `rep-o-${o.key}`, hint = o.hint ? `<small class="mute">${escH(o.hint)}</small>` : "", k = o.kind;
  if (k === "bool") return `<label class="ck"><input type="checkbox" id="${id}" data-k="${escH(o.key)}"${v ? " checked" : ""}> ${escH(o.label)}</label>${hint}`;
  if (k === "multi") return `<fieldset class="mu"><legend>${escH(o.label)}</legend>${o.values.map(([x, t]) => `<label><input type="checkbox" data-k="${escH(o.key)}" value="${escH(x)}"${(v || []).includes(x) ? " checked" : ""}> ${escH(t)}</label>`).join("")}</fieldset>${hint}`;
  const inp = k === "choice" ? `<select id="${id}" data-k="${escH(o.key)}">${o.values.map(([x, t]) => `<option value="${escH(x)}"${x === v ? " selected" : ""}>${escH(t)}</option>`).join("")}</select>`
    : k === "int" ? `<input id="${id}" data-k="${escH(o.key)}" type="number" inputmode="numeric" min="${o.min}" max="${o.max}" step="1" value="${escH(String(v ?? ""))}">`
    : k === "datetime" ? `<input id="${id}" data-k="${escH(o.key)}" type="datetime-local" value="${escH(repDt(v))}">`
    : `<input id="${id}" data-k="${escH(o.key)}" type="text" maxlength="${o.max || 60}" value="${escH(v ?? "")}">`;
  return `<label class="fl" for="${id}"><span>${escH(o.label)}${k === "int" ? ` <i class="mute">${o.min}~${o.max}</i>` : ""}</span>${inp}</label>${hint}`;
}
function repOpDraw() {
  const r = repById(REP.op), box = $("rep-op");
  if (!r) { box.hidden = true; return; }
  if (r.compose) return repCmDraw(r);
  const v = repVals(r), secs = [...new Set(r.opts.map(o => o.sec || "옵션"))], d = REP.d || {}, w = REP.w[r.id];
  const wait = r.wait ? `<fieldset class="sec wt"><legend>17시 발표 대기</legend>
      <p class="mute">통보문 · 단기예보(육상)가 오늘 17시 발표로 나올 때까지 서버가 1분마다 확인하다가, 나오면 17시 기준으로 만들어 둔다 — 창을 닫아도 된다. 18:30 까지 안 나오면 그만둔다.</p>
      <label class="ck"><input type="checkbox" id="rep-wtg"${w ? (w.tg ? " checked" : "") : (repPref().tg ? " checked" : "")}${d.tg ? "" : " disabled"}> 나오면 텔레그램으로 보내기${d.tg ? "" : ` <span class="mute">— 텔레그램 키가 없다</span>`}</label>
      <div class="row">${w?.state === "waiting" ? `<button type="button" id="rep-wx">17시 대기 취소</button><span class="mute">대기 중 — ${escH(w.until?.slice(11, 16) || "")} 까지${w.status ? ` · 지금 ${escH(w.status)}` : ""}</span>`
        : `<button type="button" id="rep-wgo"${d.demo || !d.ready ? " disabled" : ""}>17시 발표 대기 걸기</button><span class="mute">${d.demo ? "시연 화면에서는 걸지 않는다" : !d.ready ? "서버 토큰이 없다" : w?.state === "ready" ? "준비된 것이 있다 — 다시 걸면 새로 기다린다" : "지금 옵션으로 만든다"}</span>`}</div></fieldset>` : "";
  box.hidden = false;
  box.innerHTML = `<div class="op" role="dialog" aria-modal="true" aria-labelledby="rep-op-t" tabindex="-1">
    <div class="oh">${r.thumb ? `<img src="img/reports/${escH(r.id)}.png" alt="">` : `<i class="ph" aria-hidden="true"></i>`}<div><b id="rep-op-t">${escH(r.name)} 옵션</b><small class="mute">${escH(r.desc)}</small></div>
      <button type="button" id="rep-opx" aria-label="옵션 닫기 (Esc)" title="닫기 (Esc)">✕</button></div>
    <form class="ob" id="rep-of">${secs.map(s => `<fieldset class="sec"><legend>${escH(s)}</legend>${r.opts.filter(o => (o.sec || "옵션") === s).map(o => repField(o, v[o.key])).join("")}</fieldset>`).join("")
      || `<p class="mute">이 보고서는 고칠 옵션이 없다</p>`}${wait}</form>
    <p class="msg" id="rep-om" role="status"></p>
    <div class="of"><button type="button" id="rep-o0">기본값으로</button><span class="sp"></span><button type="button" id="rep-os">저장</button>
      <button type="button" id="rep-og" class="pri"${repWhy(r) ? " disabled" : ""}>저장하고 받기</button></div></div>`;
  box.querySelector(".op").focus();
}
function repOpOpen(id) {
  const r = repById(id);
  if (!r || !r.ready || REP.op === id) return;
  REP.opBack = document.activeElement; REP.op = id;
  repOpDraw();
}
function repOpClose() {
  REP.op = null; $("rep-op").hidden = true;
  if (REP.opBack?.isConnected) REP.opBack.focus();
}
/* 옵션창 글 → 값(정의 꼴대로). 범위 밖이면 무엇이 틀렸는지 */
function repOpRead(r) {
  const f = $("rep-of"), out = {};
  for (const o of r.opts) {
    if (o.kind === "multi") { out[o.key] = [...f.querySelectorAll(`input[data-k="${CSS.escape(o.key)}"]:checked`)].map(x => x.value); continue; }
    const el = f.querySelector(`[data-k="${CSS.escape(o.key)}"]`);
    if (o.kind === "bool") out[o.key] = el.checked;
    else if (o.kind === "int") {
      const n = Number(el.value);
      if (!Number.isInteger(n) || n < o.min || n > o.max) throw new Error(`${o.label}은 ${o.min}~${o.max} 사이로`);
      out[o.key] = n;
    } else if (o.kind === "datetime") out[o.key] = el.value.replace(/\D/g, "").slice(0, 12);
    else out[o.key] = el.value.trim();
  }
  for (const o of r.opts) if (o.kind === "multi" && !out[o.key].length) throw new Error(`${o.label}을 하나 이상 골라 주세요`);
  return out;
}
function repOpSave(r) {
  try {
    const all = { ...(repPref().opts || {}) };
    all[r.id] = repOpRead(r);
    repSave({ opts: all });
    return true;
  } catch (e) { $("rep-om").textContent = `저장하지 못했다 — ${e.message}`; $("rep-om").className = "msg bad"; return false; }
}
/* ── 작성 창(등록부 compose — 상황판단회의): 재난 종류 · 회의 제목 · 기간 + Ⅱ장 두 묶음(중점 유의사항 · 조치계획) 문구 고르기.
   후보는 재난상황보고서 서버의 문구 파일(/api/reports/phrases), 고른 종류로 거른다(안 고르면 전부 · 고른 것은 늘 보인다).
   고른 것은 그 자리에서 고친다(** 는 굵게) · 직접 추가. 보내는 차례는 목록 차례(끌어 옮기기 없음). 고른 것 · 고친 글 · 옵션은 이 브라우저에 기억 */
const REP_CM = [["유의사항", "중점유의사항", "중점 유의사항"], ["조치계획", "조치계획", "조치계획"]];   /* [문구 묶음, 서식 칸, 제목] */
const repBold = t => escH(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
const repCm = () => { const c = repPref().cm || {}; return { auto: c.auto !== false, sel: { 유의사항: [], 조치계획: [], ...(c.sel || {}) } }; };
const repCmSave = c => repSave({ cm: c });
const REP_CMO = new Set();                                       /* 고쳐 쓰기 칸을 펴 둔 줄(묶음|문구 열쇠) — 처음엔 다 접혀 있다 */
/* 계절 · 시기 프리셋 — 재난 종류만 정해 두고, 문구는 문구 파일에서 그 종류에 맞는 것을 종류마다 돌아가며 고른다(유의사항 7 · 조치계획 5) */
const REP_CMP = [["봄 · 강풍 · 호우 (3~5월)", ["호우", "강풍"]], ["장마철 호우 (6~7월)", ["호우"]], ["여름 폭염 (6~9월)", ["폭염"]],
  ["태풍 (7~10월)", ["태풍", "호우", "강풍", "풍랑"]], ["가을 · 호우 · 강풍 · 풍랑 (9~11월)", ["호우", "강풍", "풍랑"]], ["겨울 대설 · 한파 (12~2월)", ["대설", "한파"]]];
const repCmMine = () => { const v = repPref().cmp; return Array.isArray(v) ? v : []; };
function repCmPick(g, kinds, n) {
  const all = REP.ph?.[g] || [], out = [];
  for (let round = 0; out.length < n && round < 20; round++) for (const k of kinds) {
    const p = all.filter(x => (x.kinds || []).includes(k) && !out.includes(x))[0];
    if (p && out.length < n) out.push(p);
  }
  return all.filter(x => out.includes(x)).map(p => ({ k: p.text, text: p.text, subs: [...(p.subs || [])] }));
}
function repCmOpts(r, o) { const all = { ...(repPref().opts || {}) }; all[r.id] = { ...repVals(r), ...o }; repSave({ opts: all }); }
/* 제목 제안 — 「11. 17.~18. 호우·강풍 대비」. 기간을 안 넣었으면 오늘~내일 */
function repCmTitle(v) {
  const dt = s => (s && s.length === 12 ? new Date(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8)) : null);
  const a = dt(v.start) || new Date(), b = dt(v.end) || new Date(a.getTime() + 864e5);
  const span = `${a.getMonth() + 1}. ${a.getDate()}.` + (a.toDateString() === b.toDateString() ? ""
    : a.getMonth() === b.getMonth() ? `~${b.getDate()}.` : `~${b.getMonth() + 1}. ${b.getDate()}.`);
  return `「${span} ${(v.kinds || []).join("·") || "재난"} 대비」`;
}
/* 묶음 하나의 줄들 — 후보(거른 것 + 고른 것) 다음에 직접 추가한 것 */
function repCmRows(g, kinds, c) {
  const all = REP.ph?.[g] || [], sel = c.sel[g];
  const rows = all.map((p, i) => ({ p, i, si: sel.findIndex(x => x.k === p.text) }))
    .filter(x => x.si >= 0 || !kinds.length || (x.p.kinds || []).some(k => kinds.includes(k)));
  return rows.concat(sel.map((s, si) => ({ p: null, si })).filter(x => !all.some(p => p.text === sel[x.si].k)));   /* 직접 추가 · 파일에서 빠진 것 */
}
/* 보낼 것 — 문구 파일 차례대로 고른 것, 그다음 직접 추가한 것 · 파일에서 빠진 것(빈 글은 뺀다) */
function repCmItems() {
  const c = repCm(), out = {};
  for (const [g, field] of REP_CM) {
    const sel = c.sel[g], all = REP.ph?.[g] || [];
    const order = all.map(p => sel.find(x => x.k === p.text)).filter(Boolean).concat(sel.filter(x => !all.some(p => p.text === x.k)));
    out[field] = order.filter(x => x.text.trim()).map(x => ({ text: x.text.trim(), subs: x.subs.filter(y => y.trim()) }));
  }
  return out;
}
function repCmGroup(g, title, kinds, c) {
  const sel = c.sel[g], n = repCmItems()[REP_CM.find(x => x[0] === g)[1]].length;
  const li = ({ p, si }) => {
    const s = si >= 0 ? sel[si] : null, text = s ? s.text : p.text, subs = s ? s.subs : p.subs, key = s ? `${g}|${si}` : "", open = !!s && REP_CMO.has(`${g}|${s.k}`);
    return `<li class="ci${s ? " on" : ""}${open ? " open" : ""}"><label class="ck"><input type="checkbox" ${s ? `data-cx="${escH(key)}" checked` : `data-ca="${escH(g)}|${escH(p.text)}"`}>`
      + `<span class="pv" ${s ? `data-pv="${escH(key)}"` : ""}>${repBold(text) || `<i class="mute">(빈 줄 — 연필을 눌러 쓴다)</i>`}${subs.length ? `<small>${subs.map(repBold).join("<br>")}</small>` : ""}</span></label>`
      + (s ? `<button type="button" class="eb" data-eo="${escH(key)}" aria-expanded="${open}" aria-label="이 문구 고쳐 쓰기 ${open ? "접기" : "펴기"}" title="고쳐 쓰기 — 날짜 · 시군 수 · 세부 줄">${open ? "▴" : "✎"}</button>` : "")
      + (s && open ? `<div class="ed"><textarea rows="2" aria-label="${escH(title)} 글" data-ed="${escH(key)}">${escH(s.text)}</textarea>`
        + `<textarea rows="${Math.max(1, s.subs.length)}" aria-label="${escH(title)} 세부 · 주석" placeholder="세부 · 주석 — 한 줄에 하나(- 세부 · ※ 주석)" data-es="${escH(key)}">${escH(s.subs.join("\n"))}</textarea></div>` : "")
      + `</li>`;
  };
  const rows = repCmRows(g, kinds, c);
  return `<fieldset class="sec cm"><legend>${escH(title)} <i class="cnt${g === "유의사항" && n > 9 ? " warn" : ""}">${n}개 고름</i></legend>`
    + (g === "유의사항" ? `<small class="mute">유의사항은 7개 안팎이 한 쪽 — 넘치면 표어 상자가 다음 쪽으로 밀린다</small>` : "")
    + `<ul>${rows.map(li).join("") || `<li class="mute">${REP.ph?.[g] ? "고른 종류에 맞는 문구가 없다 — 종류를 바꾸거나 직접 추가" : ""}</li>`}</ul>`
    + `<div class="row"><button type="button" data-cadd="${escH(g)}">직접 추가</button></div></fieldset>`;
}
/* 다시 그린 뒤 초점을 돌려줄 곳 — 같은 단추 · 칸(id 나 data-*) */
function repCmFocusSel(el, box) {
  if (!el || !box.contains(el)) return null;
  if (el.id) return `#${CSS.escape(el.id)}`;
  for (const a of ["kind", "cadd", "cx", "ca", "eo", "ed", "es"]) if (el.dataset[a] != null) return `[data-${a}="${CSS.escape(el.dataset[a])}"]`;
  return null;
}
function repCmDraw(r, focus) {
  const box = $("rep-op"), d = REP.d || {}, v = repVals(r), c = repCm(), kinds = v.kinds || [], why = repWhy(r);
  const old = box.querySelector(".ob"), top = old ? old.scrollTop : 0, fk = focus || repCmFocusSel(document.activeElement, box);
  const kOpt = r.opts.find(o => o.key === "kinds"), sug = repCmTitle(v);
  const ph = REP.ph?.err ? `<p class="note">문구 후보를 받지 못했다 — ${escH(REP.ph.err)} · 직접 추가는 된다</p>` : !REP.ph ? `<p class="mute">문구 후보를 받는 중…</p>` : "";
  box.hidden = false;
  box.innerHTML = `<div class="op cmp" role="dialog" aria-modal="true" aria-labelledby="rep-op-t" tabindex="-1">
    <div class="oh">${r.thumb ? `<img src="img/reports/${escH(r.id)}.png" alt="">` : `<i class="ph" aria-hidden="true"></i>`}<div><b id="rep-op-t">${escH(r.name)} 작성</b><small class="mute">${escH(r.desc)}</small></div>
      <button type="button" id="rep-opx" aria-label="작성 창 닫기 (Esc)" title="닫기 (Esc) — 고른 것은 기억한다">✕</button></div>
    <form class="ob" id="rep-of" onsubmit="return false">
      <fieldset class="sec"><legend>회의</legend>
        <div class="ps"><label class="fl" for="rep-cm-ps"><span>프리셋</span><select id="rep-cm-ps"><option value="">불러오기…</option>
          <optgroup label="계절 · 시기">${REP_CMP.map(([n], i) => `<option value="s:${i}"${REP.ph && !REP.ph.err ? "" : " disabled"}>${escH(n)}</option>`).join("")}</optgroup>
          ${repCmMine().length ? `<optgroup label="내 프리셋">${repCmMine().map((x, i) => `<option value="m:${i}">${escH(x.name)}</option>`).join("")}</optgroup>` : ""}</select></label>
          <details class="psm"><summary>지금 고른 것을 프리셋으로</summary>
            <div class="row"><input id="rep-cm-psn" type="text" maxlength="30" placeholder="이름 — 예: 장마 초기대응" aria-label="프리셋 이름"><button type="button" id="rep-cm-pss">저장</button></div>
            ${repCmMine().map(x => `<div class="row pm"><span>${escH(x.name)}</span><button type="button" class="lnk" data-psd="${escH(x.name)}" aria-label="${escH(x.name)} 프리셋 지우기">지우기</button></div>`).join("")}
          </details></div>
        <div class="kc" role="group" aria-label="${escH(kOpt.label)}">${kOpt.values.map(([x]) => `<button type="button" data-kind="${escH(x)}" aria-pressed="${kinds.includes(x)}" class="${kinds.includes(x) ? "on" : ""}">${escH(x)}</button>`).join("")}</div>
        <small class="mute">고른 종류의 문구만 보인다(안 고르면 전부) · 제목 제안 · 서버의 특보 이력에도 쓴다</small>
        <label class="fl" for="rep-cm-title"><span>회의 제목</span><input id="rep-cm-title" type="text" maxlength="60" value="${escH(c.auto ? sug : v.title || sug)}"></label>
        <small class="mute">${c.auto ? "종류 · 기간을 따라 바뀐다 — 고치면 그대로 둔다" : `고친 제목 — <button type="button" class="lnk" id="rep-cm-auto">제안으로 돌리기(${escH(sug)})</button>`}</small>
      </fieldset>
      <fieldset class="sec"><legend>기간</legend>${r.opts.filter(o => o.sec === "기간").map(o => repField(o, v[o.key])).join("")}</fieldset>
      ${ph}${REP_CM.map(([g, , t]) => repCmGroup(g, t, kinds, c)).join("")}
    </form>
    <p class="msg" id="rep-om" role="status">${why ? escH(why) : ""}</p>
    <div class="of"><span class="sp"></span><button type="button" id="rep-ctg"${why || !d.tg ? " disabled" : ""} title="${escH(d.tg ? "텔레그램으로 보내기만" : "텔레그램 키가 없다 — 설정 › API 키")}">텔레그램으로</button>
      <button type="button" id="rep-cgo" class="pri"${why ? " disabled" : ""}>만들어 받기</button></div></div>`;
  const ob = box.querySelector(".ob");
  ob.scrollTop = top;
  ((fk && box.querySelector(fk)) || box.querySelector(".op")).focus();
  if (!REP.ph) repCmLoad();
}
async function repCmLoad() {
  if (REP.phBusy) return;
  REP.phBusy = true;
  if (REP.d?.demo) REP.ph = { err: "시연 화면에서는 불러오지 않는다" };
  else try { REP.ph = await getJson("/api/reports/phrases"); } catch (e) { REP.ph = { err: e.message }; }
  REP.phBusy = false;
  const r = repById(REP.op);
  if (r?.compose) repCmDraw(r);
}
/* 작성 창 안 누름 · 고침 */
function repCmClick(t, r) {
  const kb = t.closest("[data-kind]");
  if (kb) {
    const v = repVals(r), k = kb.dataset.kind, ks = (v.kinds || []).includes(k) ? v.kinds.filter(x => x !== k) : [...(v.kinds || []), k];
    repCmOpts(r, { kinds: r.opts.find(o => o.key === "kinds").values.map(x => x[0]).filter(x => ks.includes(x)) });
    return repCmDraw(r);
  }
  if (t.closest("#rep-cm-auto")) { const c = repCm(); c.auto = true; repCmSave(c); repCmOpts(r, { title: "" }); return repCmDraw(r); }
  const eo = t.closest("[data-eo]");
  if (eo) {
    const [g, si] = eo.dataset.eo.split("|"), x = repCm().sel[g]?.[+si], k = x && `${g}|${x.k}`;
    if (k) REP_CMO.has(k) ? REP_CMO.delete(k) : REP_CMO.add(k);
    repCmDraw(r);
    return (REP_CMO.has(k) ? $("rep-op").querySelector(`[data-ed="${CSS.escape(eo.dataset.eo)}"]`) : null)?.focus();
  }
  if (t.closest("#rep-cm-pss")) {                             /* 지금 고른 것을 내 프리셋으로 — 같은 이름이면 덮어쓴다 */
    const name = $("rep-cm-psn").value.trim(), c = repCm();
    if (!name) { $("rep-om").textContent = "프리셋 이름을 넣어 주세요"; $("rep-om").className = "msg bad"; return $("rep-cm-psn").focus(); }
    repSave({ cmp: [...repCmMine().filter(x => x.name !== name), { name, kinds: repVals(r).kinds || [], sel: c.sel }].slice(-30) });
    repCmDraw(r, "#rep-cm-ps");
    $("rep-om").textContent = `「${name}」 프리셋으로 저장했다`; $("rep-om").className = "msg";
    return;
  }
  const pd = t.closest("[data-psd]");
  if (pd) { repSave({ cmp: repCmMine().filter(x => x.name !== pd.dataset.psd) }); return repCmDraw(r, "#rep-cm-ps"); }
  const add = t.closest("[data-cadd]");
  if (add) {
    const c = repCm(), g = add.dataset.cadd, nk = `+${Date.now()}`;
    REP_CMO.add(`${g}|${nk}`);
    c.sel[g].push({ k: nk, text: "", subs: [] });
    repCmSave(c); repCmDraw(r);
    return $("rep-op").querySelector(`[data-ed="${CSS.escape(`${g}|${c.sel[g].length - 1}`)}"]`)?.focus();
  }
  if (t.closest("#rep-cgo, #rep-ctg")) {
    const mode = t.closest("#rep-cgo") ? "dl" : "tg", c = repCm();
    try {                                                     /* 제목은 보이는 그대로 보낸다(서버 기본 제목은 기간이 다르다) */
      repCmOpts(r, { ...repOpRead({ opts: r.opts.filter(x => x.sec === "기간") }), title: $("rep-cm-title").value.trim() });
    } catch (e) { $("rep-om").textContent = e.message; $("rep-om").className = "msg bad"; return; }
    repOpClose(); repRun(r.id, mode);
  }
}
function repCmInput(t, r) {
  const c = repCm();
  if (t.id === "rep-cm-title") { c.auto = false; repCmSave(c); return repCmOpts(r, { title: t.value.trim() }); }
  const key = t.dataset.ed || t.dataset.es;
  if (!key) return;
  const [g, si] = key.split("|"), s = c.sel[g]?.[+si];
  if (!s) return;
  if (t.dataset.ed) s.text = t.value.replace(/\n+/g, " ");
  else s.subs = t.value.split("\n");
  repCmSave(c);
  const pv = $("rep-op").querySelector(`[data-pv="${CSS.escape(key)}"]`), subs = s.subs.filter(y => y.trim());
  if (pv) pv.innerHTML = (repBold(s.text) || `<i class="mute">(빈 줄 — 연필을 눌러 쓴다)</i>`) + (subs.length ? `<small>${subs.map(repBold).join("<br>")}</small>` : "");
  const n = repCmItems()[REP_CM.find(x => x[0] === g)[1]].length, cnt = t.closest(".cm")?.querySelector(".cnt");
  if (cnt) cnt.textContent = `${n}개 고름`;
}
function repCmChange(t, r) {
  const c = repCm();
  let focus = null;
  if (t.dataset.ca) {                                         /* 후보 고르기 — 문구 그대로 복사해 고칠 수 있게 */
    const [g, ...rest] = t.dataset.ca.split("|"), text = rest.join("|"), p = (REP.ph?.[g] || []).find(x => x.text === text);
    if (!p) return;
    c.sel[g].push({ k: p.text, text: p.text, subs: [...p.subs] });
    focus = `[data-cx="${CSS.escape(`${g}|${c.sel[g].length - 1}`)}"]`;
  } else if (t.dataset.cx) {                                  /* 고른 것 빼기(고친 글도 버린다) */
    const [g, si] = t.dataset.cx.split("|"), [x] = c.sel[g].splice(+si, 1);
    focus = x.k.startsWith("+") ? `[data-cadd="${CSS.escape(g)}"]` : `[data-ca="${CSS.escape(`${g}|${x.k}`)}"]`;
  } else if (t.id === "rep-cm-ps") {                          /* 프리셋 불러오기 — 종류 · 고른 문구를 통째로 바꾼다(제목은 제안으로) */
    const [kind, i] = t.value.split(":"), mine = repCmMine()[+i], std = REP_CMP[+i];
    if (kind === "m" && mine) { c.sel = { 유의사항: [], 조치계획: [], ...JSON.parse(JSON.stringify(mine.sel || {})) }; repCmOpts(r, { kinds: mine.kinds || [], title: "" }); }
    else if (kind === "s" && std && REP.ph && !REP.ph.err) { c.sel = { 유의사항: repCmPick("유의사항", std[1], 7), 조치계획: repCmPick("조치계획", std[1], 5) }; repCmOpts(r, { kinds: std[1], title: "" }); }
    else return;
    c.auto = true; REP_CMO.clear();
    repCmSave(c); repCmDraw(r, "#rep-cm-ps");
    $("rep-om").textContent = `「${kind === "m" ? mine.name : std[0]}」 을 불러왔다 — 문구는 아래에서 더 고르거나 뺀다`; $("rep-om").className = "msg";
    return;
  } else if (t.type === "datetime-local") {
    try { repCmOpts(r, repOpRead({ opts: r.opts.filter(x => x.sec === "기간") })); } catch {}
    return repCmDraw(r);
  } else return;
  repCmSave(c); repCmDraw(r, focus);
}
function repDraw() {
  const d = REP.d, list = d?.reports || [], gs = ["전체", ...(d?.groups || [])];
  const shown = REP.g === "전체" ? list : list.filter(r => r.group === REP.g);
  const note = !d ? "목록을 받는 중…" : d.err ? `목록을 받지 못했다 — ${d.err}` : d.demo ? "시연 화면 — 목록만 보이고 보고서는 만들지 않는다"
    : !d.ready ? `재난상황보고서 서버 토큰(JAENAN_TOKEN)이 없다 — 설정 › API 키에서 넣는다${d.tg ? "" : " · 텔레그램 키도 없다"}`
    : !d.tg ? "텔레그램 키가 없어 받기만 된다" : "";
  $("rep").innerHTML = `<div class="box" role="dialog" aria-modal="true" aria-labelledby="rep-t" tabindex="-1">
    <div class="top"><b id="rep-t">보고서</b><span class="mute">재난상황보고서 서버에서 한글 파일 · 그림으로</span><span class="sp"></span>
      <button type="button" id="rep-cog" class="${REP.set ? "on" : ""}" aria-expanded="${REP.set}" aria-controls="rep-set" aria-label="전체 설정" title="전체 설정 — 받을 때 텔레그램에도">⚙</button>
      <button type="button" id="rep-x" aria-label="닫기 (Esc)" title="닫기 (Esc)">✕</button></div>
    ${note ? `<p class="note">${escH(note)}</p>` : ""}
    ${REP.set ? repSettings() : ""}
    <nav aria-label="묶음">${gs.map(g => { const n = g === "전체" ? list.length : list.filter(r => r.group === g).length;
      return `<button type="button" data-g="${escH(g)}" aria-pressed="${g === REP.g}" class="${g === REP.g ? "on" : ""}">${escH(g)} <i>${n}</i></button>`; }).join("")}</nav>
    <div class="grid">${shown.map(repTile).join("") || `<p class="mute">이 묶음에는 아직 보고서가 없다</p>`}</div>
    <p class="msg${REP.msg && !REP.msg.ok ? " bad" : ""}" role="status">${escH(REP.msg?.text || (REP.busy ? "보고서 서버가 만드는 중 — 풍수해보고는 1분 안팎 걸린다" : "타일을 누르면 받는다 · 오른쪽 누름(⚙)은 옵션 · 구석 단추는 텔레그램으로 보내기만"))}</p></div>
    <div class="opbg" id="rep-op" hidden></div>`;
  if (REP.op) repOpDraw();
  else if (!$("rep").hidden && !$("rep").contains(document.activeElement)) $("rep").querySelector(".box").focus();   /* 다시 그려 초점이 빠졌으면 창 안으로 */
}
async function repSaveFile(res, fallback) {
  const blob = await res.blob(), name = repName(res.headers.get("Content-Disposition")) || fallback, a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  return name;
}
async function repRun(id, mode) {
  const r = repById(id);
  if (!r) return;
  if (mode === "dl" && REP.w[id]?.state === "ready") {         /* 17시 대기로 만들어 둔 것 */
    try {
      const res = await fetch(`/api/reports/wait/file?id=${encodeURIComponent(id)}`);
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `오류 ${res.status}`);
      REP.msg = { ok: true, text: `받았다 — ${await repSaveFile(res, `${id}.hwp`)} (17시 보고서)` };
    } catch (e) { REP.msg = { ok: false, text: `받지 못했다 — ${e.message}` }; }
    return repDraw();
  }
  if (REP.busy) return;
  const p = repPref(), dl = mode === "dl", tg = mode === "tg" || (dl && !!p.tg && !!REP.d?.tg);
  REP.busy = id; REP.t0 = Date.now(); REP.msg = null; repDraw();
  REP.tick = setInterval(() => { const e = $("rep").querySelector(".rt.busy .sec"); if (e) e.textContent = Math.round((Date.now() - REP.t0) / 1000); }, 1000);
  try {
    const res = await fetch("/api/reports/run", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id, opts: repSend(r), items: r.compose ? repCmItems() : undefined, tg, dl }) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `오류 ${res.status}`);
    if (dl) {
      const t = res.headers.get("X-Tg"), name = await repSaveFile(res, `${id}.hwp`);
      REP.msg = { ok: t !== "fail", text: `받았다 — ${name}${t === "ok" ? " · 텔레그램에도 보냈다" : t === "fail" ? " · 텔레그램은 보내지 못했다" : ""}` };
    } else {
      const j = await res.json();
      REP.msg = { ok: true, text: `텔레그램으로 보냈다 — ${j.name}` };
    }
  } catch (e) { REP.msg = { ok: false, text: `만들지 못했다 — ${e.message}` }; }
  clearInterval(REP.tick); REP.busy = null;
  if (!$("rep").hidden) repDraw();
}
/* 17시 대기 걸기 · 취소 — 상태는 서버(STATE)에 남는다 */
async function repWait(id, on) {
  const r = repById(id), m = $("rep-om");
  try {
    const res = on ? await fetch("/api/reports/wait", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id, opts: repSend(r), tg: !!$("rep-wtg")?.checked }) })
      : await fetch(`/api/reports/wait?id=${encodeURIComponent(id)}`, { method: "DELETE" });
    const j = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(j.detail || `오류 ${res.status}`);
    REP.w = j.wait || {};
    REP.msg = { ok: true, text: on ? `${r.name} — 17시 발표 대기를 걸었다(창을 닫아도 서버가 확인한다)` : `${r.name} — 17시 대기를 껐다` };
  } catch (e) {
    if (m) { m.textContent = `${on ? "걸지" : "끄지"} 못했다 — ${e.message}`; m.className = "msg bad"; }
    return;
  }
  repMark();
  if (!$("rep").hidden) repDraw();
}
/* 상태 묻기 — 창을 닫아도 도구 줄 단추에 점(대기 중 시계 · 준비됨 초록). 걸린 것이 없으면 처음 한 번만 */
async function repPoll() {
  try { REP.w = (await getJson("/api/reports/wait")).wait || {}; } catch { return; }
  repMark();
  if (!$("rep").hidden && !REP.busy && !REP.op) repDraw();        /* 옵션창을 고치는 중이면 다시 그리지 않는다 */
}
function repMark() {
  const v = Object.values(REP.w), st = v.some(x => x.state === "ready") ? "ready" : v.some(x => x.state === "waiting") ? "waiting" : "", b = $("b-rep");
  b.classList.toggle("w-ready", st === "ready"); b.classList.toggle("w-waiting", st === "waiting");
  const t = st === "ready" ? " — 17시 보고서 준비됨" : st === "waiting" ? " — 17시 발표 대기 중" : "";
  b.setAttribute("aria-label", `보고서${t}`);
  b.title = `보고서${t || " — 한글 보고서 · 상황판단회의 · 움짤 · 종합 · 특보 · 기온표 받기 · 텔레그램 보내기"}`;
}
setInterval(() => { if (Object.keys(REP.w).length && !document.hidden) repPoll(); }, 60e3);
setTimeout(repPoll, 4000);
$("rep").addEventListener("click", ev => {
  const t = ev.target, r = repById(REP.op);
  if (REP.op) {                                              /* 옵션창 — 바깥(옵션창 뒤판) 누름은 옵션창만 닫는다 */
    if (t.id === "rep-op" || t.closest("#rep-opx")) return repOpClose();
    if (r?.compose) return repCmClick(t, r);
    if (t.closest("#rep-o0")) { const all = { ...(repPref().opts || {}) }; delete all[r.id]; repSave({ opts: all }); repOpDraw(); $("rep-om").textContent = "기본값으로 돌렸다"; return; }
    if (t.closest("#rep-os")) { if (repOpSave(r)) { repDraw(); $("rep-om").textContent = "저장했다"; } return; }
    if (t.closest("#rep-og")) { if (repOpSave(r)) { const id = r.id; repOpClose(); repRun(id, "dl"); } return; }
    if (t.closest("#rep-wgo")) { if (repOpSave(r)) repWait(r.id, true); return; }
    if (t.closest("#rep-wx")) return repWait(r.id, false);
    return;
  }
  if (t.id === "rep") return closeRep();                     /* 바깥(어두운 뒤판) 누름 */
  if (t.closest("#rep-x")) return closeRep();
  if (t.closest("#rep-cog")) { REP.set = !REP.set; repDraw(); if (REP.set && !REP.logos) repLogoLoad(); return $("rep-cog").focus(); }
  const lg = t.closest("[data-logo]");
  if (lg) {
    return fetch("/api/reports/logos/selected", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: lg.dataset.logo }) })
      .then(res => repLogoSend(res, j => `로고를 「${j.selected}」 로 골랐다 — 다음에 만드는 보고서부터`));
  }
  const g = t.closest("[data-g]");
  if (g) { REP.g = g.dataset.g; repDraw(); return $("rep").querySelector(`[data-g="${CSS.escape(REP.g)}"]`)?.focus(); }
  const op = t.closest("[data-op]");
  if (op) return repOpOpen(op.dataset.op);
  const wx = t.closest("[data-wx]");
  if (wx) return repWait(wx.dataset.wx, false);
  const a = t.closest("[data-get], [data-tg]");
  if (a && !a.disabled) {
    const id = a.dataset.get || a.dataset.tg;
    if (repById(id)?.compose && REP.w[id]?.state !== "ready") return repOpOpen(id);   /* 작성 창이 있는 보고서 — 고르고 만든다 */
    repRun(id, a.dataset.get ? "dl" : "tg");
  }
});
$("rep").addEventListener("contextmenu", ev => {
  const tile = ev.target.closest(".rt[data-id]");
  if (!tile || REP.op) return;
  ev.preventDefault();
  repOpOpen(tile.dataset.id);
});
$("rep").addEventListener("input", ev => { const r = repById(REP.op); if (r?.compose) repCmInput(ev.target, r); });
$("rep").addEventListener("change", ev => {
  const r = repById(REP.op);
  if (r?.compose) return repCmChange(ev.target, r);
  if (ev.target.id === "rep-tg") repSave({ tg: ev.target.checked });
  if (ev.target.id === "rep-logo") {                          /* 로고 올리기 — 종류 · 크기는 여기서 먼저(서버도 다시 본다) */
    const f = ev.target.files[0];
    if (!f) return;
    if (!/^image\/(png|jpeg|webp)$/.test(f.type) || f.size > 2 * 1024 * 1024) { $("rep-lm").textContent = "PNG · JPG · WEBP 그림, 2MB 이하만 올릴 수 있다"; $("rep-lm").className = "msg bad"; return; }
    $("rep-lm").textContent = "올리는 중…";
    fetch(`/api/reports/logos?name=${encodeURIComponent(f.name.replace(/\.[^.]+$/, ""))}`, { method: "POST", headers: { "content-type": "application/octet-stream" }, body: f })
      .then(res => repLogoSend(res, j => `「${j.name}」 을 올렸다 — 목록에서 골라 쓴다`));
  }
});
/* Esc — 옵션창부터 닫기 · Tab 가두기(위에 뜬 창 안에서) · 메뉴 키 · Shift+F10 = 옵션. 창이 열려 있으면 지도 단축키로 넘기지 않는다 */
document.addEventListener("keydown", ev => {
  if ($("rep").hidden) return;
  ev.stopPropagation();
  if (ev.key === "Escape") { ev.preventDefault(); return REP.op ? repOpClose() : closeRep(); }
  if (!REP.op && (ev.key === "ContextMenu" || (ev.shiftKey && ev.key === "F10"))) {
    const tile = document.activeElement?.closest?.(".rt[data-id]");
    if (tile) { ev.preventDefault(); return repOpOpen(tile.dataset.id); }
  }
  if (ev.key !== "Tab") return;
  const box = REP.op ? $("rep-op").querySelector(".op") : $("rep").querySelector(".box");
  const fs = [...box.querySelectorAll("button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex='0']")].filter(x => x.offsetParent !== null);
  if (!fs.length) return;
  const i = fs.indexOf(document.activeElement);
  if (i < 0) { ev.preventDefault(); (ev.shiftKey ? fs[fs.length - 1] : fs[0]).focus(); }
  else if (ev.shiftKey && i === 0) { ev.preventDefault(); fs[fs.length - 1].focus(); }
  else if (!ev.shiftKey && i === fs.length - 1) { ev.preventDefault(); fs[0].focus(); }
}, true);
$("b-rep").onclick = () => ($("rep").hidden ? openRep() : closeRep());

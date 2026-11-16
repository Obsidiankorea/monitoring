"use strict";
/* ── 보고서 창(오른쪽 위 첫 단추) — 언레이드 재난상황보고서 서버(jaenan-weather)가 만드는 한글 보고서를 받기 · 텔레그램으로 보내기.
   목록은 서버 등록부(app/reports.py REG)를 그대로 그린다 — 보고서가 늘면 거기 한 줄. 썸네일 img/reports/<id>.png, 없으면 문서 모양 자리표시.
   서버는 한 번에 한 작업이라 만드는 동안 다른 타일은 기다림 안내. 설정(⚙): 받을 때 텔레그램에도 · 보고서별 옵션(등록부 opts) — 이 브라우저에 기억 */
const REP = { d: null, g: "전체", busy: null, t0: 0, tick: 0, set: false, back: null, msg: null };
const repPref = () => { try { return JSON.parse(localStorage.getItem("gn-rep") || "{}"); } catch { return {}; } };
function repSave(p) { try { localStorage.setItem("gn-rep", JSON.stringify({ ...repPref(), ...p })); } catch {} }
const repName = cd => { const m = /filename\*=UTF-8''([^;]+)/i.exec(cd || ""); return m ? decodeURIComponent(m[1]) : ""; };
const REP_TG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21 4 3 11l6 2.2M21 4l-3.2 15.5L9 13.2M21 4 9 13.2v5.3l3.2-3.2"/></svg>';

async function openRep() {
  REP.back = document.activeElement;
  $("rep").hidden = false;
  repDraw();
  try { REP.d = await getJson("/api/reports"); } catch (e) { REP.d = { err: e.message, reports: [], groups: [] }; }
  if (!$("rep").hidden) repDraw();
}
function closeRep() {
  $("rep").hidden = true; REP.set = false;
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
function repTile(r) {
  const why = repWhy(r), busy = REP.busy === r.id, off = !!why || busy, d = REP.d || {};
  const th = `<span class="th">${r.thumb ? `<img src="img/reports/${escH(r.id)}.png" alt="" loading="lazy">` : ""}`
    + `<i class="ph" aria-hidden="true"><b></b><u></u><u></u><u></u><u></u><u></u></i>`
    + (busy ? `<em class="run" role="status"><i class="ldbar"><i></i></i>만드는 중 · <span class="sec">${Math.round((Date.now() - REP.t0) / 1000)}</span>초</em>` : "")
    + (!r.ready ? `<em class="soon">준비 중</em>` : "") + `</span>`;
  return `<div class="rt${busy ? " busy" : ""}${r.ready ? "" : " off"}">`
    + `<button type="button" class="rt-main" data-get="${escH(r.id)}"${off ? " disabled" : ""} title="${escH(why || `${r.name} 받기 — 한글 파일(.hwp)`)}" aria-label="${escH(`${r.name} 받기${why ? ` — ${why}` : ""}`)}">`
    + `${th}<span class="nm"><b>${escH(r.name)}</b><small>${escH(r.desc)}</small></span></button>`
    + (r.ready ? `<button type="button" class="rt-tg" data-tg="${escH(r.id)}"${off || !d.tg ? " disabled" : ""} aria-label="${escH(`${r.name} 텔레그램으로 보내기`)}"`
      + ` title="${escH(why || (d.tg ? "텔레그램으로 보내기만(받지 않음)" : "텔레그램 키가 없다 — 설정 › API 키"))}">${REP_TG}</button>` : "")
    + `</div>`;
}
function repSettings() {
  const d = REP.d || {}, p = repPref(), opts = (d.reports || []).filter(r => r.ready && r.opts?.length);
  return `<div class="set" id="rep-set"><b>설정</b>`
    + `<label class="ck"><input type="checkbox" id="rep-tg"${p.tg ? " checked" : ""}${d.tg ? "" : " disabled"}> 받을 때 텔레그램에도 보내기${d.tg ? "" : ` <span class="mute">— 텔레그램 키가 없다</span>`}</label>`
    + opts.map(r => r.opts.map(o => `<label class="op"><span>${escH(r.name)} · ${escH(o.label)}</span>`
      + `<input type="text" data-opt="${escH(r.id)}|${escH(o.key)}" value="${escH((p.opts?.[r.id] || {})[o.key] || "")}"${o.kind === "datetime" ? ` inputmode="numeric" maxlength="12" placeholder="YYYYMMDDHHMM"` : ""}>`
      + (o.hint ? `<small class="mute">${escH(o.hint)}</small>` : "") + `</label>`).join("")).join("")
    + `<p class="mute">이 브라우저에만 기억한다.</p></div>`;
}
function repDraw() {
  const d = REP.d, list = d?.reports || [], gs = ["전체", ...(d?.groups || [])];
  const shown = REP.g === "전체" ? list : list.filter(r => r.group === REP.g);
  const note = !d ? "목록을 받는 중…" : d.err ? `목록을 받지 못했다 — ${d.err}` : d.demo ? "시연 화면 — 목록만 보이고 보고서는 만들지 않는다"
    : !d.ready ? `재난상황보고서 서버 토큰(JAENAN_TOKEN)이 없다 — 설정 › API 키에서 넣는다${d.tg ? "" : " · 텔레그램 키도 없다"}`
    : !d.tg ? "텔레그램 키가 없어 받기만 된다" : "";
  $("rep").innerHTML = `<div class="box" role="dialog" aria-modal="true" aria-labelledby="rep-t" tabindex="-1">
    <div class="top"><b id="rep-t">보고서</b><span class="mute">재난상황보고서 서버에서 한글 파일로</span><span class="sp"></span>
      <button type="button" id="rep-cog" class="${REP.set ? "on" : ""}" aria-expanded="${REP.set}" aria-controls="rep-set" aria-label="보고서 설정" title="설정 — 텔레그램 · 보고서별 옵션">⚙</button>
      <button type="button" id="rep-x" aria-label="닫기 (Esc)" title="닫기 (Esc)">✕</button></div>
    ${note ? `<p class="note">${escH(note)}</p>` : ""}
    ${REP.set ? repSettings() : ""}
    <nav aria-label="묶음">${gs.map(g => { const n = g === "전체" ? list.length : list.filter(r => r.group === g).length;
      return `<button type="button" data-g="${escH(g)}" aria-pressed="${g === REP.g}" class="${g === REP.g ? "on" : ""}">${escH(g)} <i>${n}</i></button>`; }).join("")}</nav>
    <div class="grid">${shown.map(repTile).join("") || `<p class="mute">이 묶음에는 아직 보고서가 없다</p>`}</div>
    <p class="msg${REP.msg && !REP.msg.ok ? " bad" : ""}" role="status">${escH(REP.msg?.text || (REP.busy ? "보고서 서버가 만드는 중 — 풍수해보고는 1분 안팎 걸린다" : "타일을 누르면 받는다 · 구석 단추는 텔레그램으로 보내기만"))}</p></div>`;
  if (!$("rep").hidden && !$("rep").contains(document.activeElement)) $("rep").querySelector(".box").focus();   /* 다시 그려 초점이 빠졌으면 창 안으로 */
}
async function repRun(id, mode) {
  if (REP.busy) return;
  const p = repPref(), dl = mode === "dl", tg = mode === "tg" || (dl && !!p.tg && !!REP.d?.tg);
  REP.busy = id; REP.t0 = Date.now(); REP.msg = null; repDraw();
  REP.tick = setInterval(() => { const e = $("rep").querySelector(".rt.busy .sec"); if (e) e.textContent = Math.round((Date.now() - REP.t0) / 1000); }, 1000);
  try {
    const res = await fetch("/api/reports/run", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id, opts: p.opts?.[id] || {}, tg, dl }) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `오류 ${res.status}`);
    if (dl) {
      const blob = await res.blob(), name = repName(res.headers.get("Content-Disposition")) || `${id}.hwp`, a = document.createElement("a"), t = res.headers.get("X-Tg");
      a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 5000);
      REP.msg = { ok: t !== "fail", text: `받았다 — ${name}${t === "ok" ? " · 텔레그램에도 보냈다" : t === "fail" ? " · 텔레그램은 보내지 못했다" : ""}` };
    } else {
      const j = await res.json();
      REP.msg = { ok: true, text: `텔레그램으로 보냈다 — ${j.name}` };
    }
  } catch (e) { REP.msg = { ok: false, text: `만들지 못했다 — ${e.message}` }; }
  clearInterval(REP.tick); REP.busy = null;
  if (!$("rep").hidden) repDraw();
}
$("rep").addEventListener("click", ev => {
  const t = ev.target;
  if (t.id === "rep") return closeRep();                     /* 바깥(어두운 뒤판) 누름 */
  if (t.closest("#rep-x")) return closeRep();
  if (t.closest("#rep-cog")) { REP.set = !REP.set; repDraw(); return $("rep-cog").focus(); }
  const g = t.closest("[data-g]");
  if (g) { REP.g = g.dataset.g; repDraw(); return $("rep").querySelector(`[data-g="${CSS.escape(REP.g)}"]`)?.focus(); }
  const a = t.closest("[data-get], [data-tg]");
  if (a && !a.disabled) repRun(a.dataset.get || a.dataset.tg, a.dataset.get ? "dl" : "tg");
});
$("rep").addEventListener("change", ev => {
  const t = ev.target;
  if (t.id === "rep-tg") repSave({ tg: t.checked });
  if (t.dataset.opt) {
    const [id, k] = t.dataset.opt.split("|"), o = { ...(repPref().opts || {}) };
    o[id] = { ...(o[id] || {}), [k]: t.value.trim() };
    repSave({ opts: o });
  }
});
/* Esc 로 닫기 · Tab 가두기 — 창이 열려 있으면 지도 단축키로 넘기지 않는다(문서 단계에서 먼저 받는다) */
document.addEventListener("keydown", ev => {
  if ($("rep").hidden) return;
  ev.stopPropagation();
  if (ev.key === "Escape") { ev.preventDefault(); return closeRep(); }
  if (ev.key !== "Tab") return;
  const box = $("rep").querySelector(".box"), fs = [...box.querySelectorAll("button:not([disabled]), input:not([disabled]), [tabindex='0']")];
  if (!fs.length) return;
  const i = fs.indexOf(document.activeElement);
  if (i < 0) { ev.preventDefault(); (ev.shiftKey ? fs[fs.length - 1] : fs[0]).focus(); }
  else if (ev.shiftKey && i === 0) { ev.preventDefault(); fs[fs.length - 1].focus(); }
  else if (!ev.shiftKey && i === fs.length - 1) { ev.preventDefault(); fs[0].focus(); }
}, true);
$("b-rep").onclick = () => ($("rep").hidden ? openRep() : closeRep());

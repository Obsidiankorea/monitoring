"use strict";
/* ── 보고서 창(오른쪽 위 첫 단추) — 언레이드 재난상황보고서 서버(jaenan-weather)가 만드는 한글 보고서 · 그림을 받기 · 텔레그램으로 보내기.
   그림 작업이 여러 장이면 zip 으로 받고, 텔레그램은 장마다. 작성 창이 있는 보고서(compose — 상황판단회의)는 타일을 누르면 작성 창.
   목록 · 옵션 정의는 서버 등록부(app/reports.py REG)를 그대로 그린다 — 보고서가 늘면 거기 한 줄. 썸네일 img/reports/<id>.png, 없으면 문서 모양 자리표시.
   타일 오른쪽 누름(· 메뉴 키 · Shift+F10 · 타일의 ⚙) = 그 보고서 옵션창 — 런처(윈도우 앱) 옵션 가운데 서버에서 되는 것. 이 브라우저에 보고서별로 기억하고,
   보낼 때는 기본값과 다른 것만(안 보낸 것은 서버 설정을 따른다). 머리 ⚙ = 전체 설정(받을 때 텔레그램에도).
   17시 대기(등록부 wait) — 서버가 1분마다 묻고, 이 화면은 상태만 1분마다 가볍게(걸린 것이 있을 때만) 물어 타일 · 도구 줄 단추에 표시 */
const REP = { d: null, g: "", share: {}, ctx: null, mt: null, swallow: false, busy: null, jobs: {}, tick: 0, set: false, back: null, msg: null, w: {}, op: null, opBack: null,
  sel: null, done: {}, seen: new Set(), wide: false };
/* '자세히' 보기 — 보고서마다 끌어오는 자료(이름, 어디서). 만드는 동안은 보고서 서버가 보낸 기준 시각 · 기상청 호출로 바뀐다 */
const REP_SRC = {
  weather: [["단기예보", "기상청"], ["중기예보", "기상청"], ["기온(관측)", "기상청 AWS"], ["동네예보 통보문", "기상청"], ["특보 현황", "지도 서버"], ["파고", "기상청"]],
  daily: [["기온(관측)", "기상청 AWS"], ["강수량 · 다우지점", "기상청 AWS"], ["단기 · 중기예보", "기상청"], ["특보 현황", "지도 서버"]],
  nature: [["특보 이력", "기상청 특보자료"], ["기상전망(통보문)", "기상청"], ["3시간 예상강우 그림", "기상청 단기예보"], ["시군 강우", "기상청 AWS"],
    ["강수 표 · 다우지점", "지도 서버(매분 관측)"], ["순간최대풍속", "지도 서버"]],
  meeting: [["기상전망(통보문)", "기상청"], ["3시간 예상강우 그림", "기상청 단기예보"], ["특보 이력", "기상청 특보자료"], ["시군 강우", "기상청 AWS"],
    ["순간최대풍속", "지도 서버"], ["하천 수위", "홍수통제소"], ["조위", "국립해양조사원"], ["특보지역 우려지구", "위키 · 지도 서버"]],
  report: [["강수량 · 다우지점", "기상청 AWS"], ["초단기 강수 예측", "기상청"], ["특보 현황", "지도 서버"]],
  temp: [["기온(관측) 3일", "기상청 AWS"], ["내일 예상기온", "기상청 단기예보"]],
  outlook: [["기상전망(통보문)", "기상청"], ["3시간 강수량 분포도", "기상청 단기예보"]],
  winter: [["통보문 종합", "기상청"], ["특보 현황", "기상청"], ["현재기온", "기상청 AWS"], ["예보 최저 · 최고", "기상청 단기예보"], ["특보 · 기온 분포 · 레이더 그림", "기상청"]],
  winter5: [["통보문 종합", "기상청"], ["특보 현황", "기상청"], ["기온 분포도", "기상청 AWS 객관분석"], ["닷새 최저 · 최고", "기상청 단기 · 중기예보"]],
  cold: [["한파특보", "기상청"], ["현재기온", "기상청 AWS"], ["예보 최저 · 최고", "기상청 단기예보"], ["특보 · 기온 분포 · 레이더 그림", "기상청"]],
  snow: [["특보 현황", "기상청"], ["현재기온", "기상청 AWS"], ["24시간 신적설", "기상청 적설 관측"], ["특보 · 신적설 분포 · 레이더 그림", "기상청"], ["강수형태 분포도", "기상청 단기예보"]],
  typhoon: [["태풍 정보 · 예측", "기상청 태풍"], ["태풍 이름 · 뜻", "기상청 태풍 목록"], ["진로도 바탕", "기상청 태풍 지도 서버"]],
  typhoon_meeting: [["기상전망(통보문)", "기상청"], ["태풍 정보 · 예측", "기상청 태풍"], ["구역 진입 시각", "예측 진로로 계산"], ["진로도 바탕", "기상청 태풍 지도 서버"]],
  gif: [["초단기 강수 예측 격자", "지도 서버"]], combo: [["강수 현황 · 예측", "지도 서버"]], alert: [["특보 현황 · 지도", "지도 서버"]],
};
const repView = () => repPref().view === "det" ? "det" : "grid";
/* 여러 보고서를 한꺼번에 걸 수 있다 — 보고서 서버는 받은 차례대로 하나씩 만든다(작업끼리 자료 · 기록이 섞이지 않게).
   REP.jobs = {보고서 id: {name, job, t0(건 때), run(서버가 만들기 시작한 때 | null), exp(예상 초)}} · REP.busy = 하나라도 있나 */
const repBusy = () => Object.keys(REP.jobs).length;
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
  $("rep").hidden = true; REP.set = false; REP.op = null; REP.sp = null;
  if (REP.back?.isConnected) REP.back.focus();
}
/* 왜 못 만드나 — 시연 · 토큰 없음 · 다른 보고서를 만드는 중 */
function repWhy(r) {
  const d = REP.d;
  if (!r.ready) return r.broken || "준비 중";
  if (d?.demo) return r.live || r.sample ? "" : "시연 샘플이 없다";   // 시연 — 기상상황보고는 지금 시각으로, 나머지는 샘플
  if (d && !d.ready && !d.demo) return "재난상황보고서 서버 토큰이 없다";
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
  const J = REP.jobs[r.id], why = repWhy(r), busy = !!J, off = !!why || busy, d = REP.d || {}, w = REP.w[r.id], rd = w?.state === "ready";
  const th = `<span class="th">${r.thumb ? `<img src="img/reports/${escH(r.id)}.png" alt="" loading="lazy">` : ""}`
    + `<i class="ph" aria-hidden="true"><b></b><u></u><u></u><u></u><u></u><u></u></i>`
    + (busy ? `<em class="run" role="status"><i class="ldbar"><i></i></i>${J.run ? `만드는 중 · <span class="sec" data-sec="${escH(r.id)}">${Math.round((Date.now() - J.run) / 1000)}</span>초` : "차례 기다림"}</em>` : "")
    + (!r.ready ? `<em class="soon${r.broken ? " bad" : ""}">${r.broken ? "안 됨" : "준비 중"}</em>` : "") + (r.ready && repChanged(r) ? `<em class="chg" title="기본값과 다른 옵션이 있다">옵션</em>` : "") + `</span>`;
  const lab = rd ? `${r.name} — 17시 보고서 받기` : `${r.name} 받기${why ? ` — ${why}` : ""}`;
  return `<div class="rt${busy ? " busy" : ""}${r.ready ? "" : " off"}${w ? ` w-${escH(w.state)}` : ""}" data-id="${escH(r.id)}" draggable="true">`
    + `<button type="button" class="rt-main" data-get="${escH(r.id)}"${off && !rd && !r.compose ? " disabled" : ""} title="${escH(rd ? "저장해 둔 17시 보고서를 받는다" : r.compose ? `${r.name} 작성 — 문구를 골라 만든다` : why || `${r.name} 받기 · 오른쪽 누름: 옵션`)}" aria-label="${escH(r.compose ? `${r.name} 작성 창 열기` : lab)}">`
    + `${th}<span class="nm"><b>${escH(r.name)}${r.meta?.memo ? ` <i class="mm" title="${escH(r.meta.memo)}">메모</i>` : ""}</b><small>${escH(r.desc)}</small></span></button>`
    + (r.ready && !r.compose ? `<button type="button" class="rt-tg" data-tg="${escH(r.id)}"${off || !d.tg ? " disabled" : ""} aria-label="${escH(`${r.name} 텔레그램으로 보내기`)}"`
      + ` title="${escH(why || (d.tg ? "텔레그램으로 보내기만(받지 않음)" : "텔레그램 키가 없다 — 설정 › API 키"))}">${REP_TG}</button>`
      : "") + (r.ready ? `<button type="button" class="rt-op${r.compose ? " cm" : ""}" data-op="${escH(r.id)}" aria-label="${escH(`${r.name} ${r.compose ? "작성 창" : "옵션"}`)}" title="${r.compose ? "작성 창" : "옵션"} — 타일 오른쪽 누름 · Shift+F10 과 같다">⚙</button>` : "")
    + (!r.brief ? `<button type="button" class="rt-sp" data-sp="${escH(r.id)}" aria-label="${escH(`${r.name} 샘플 — 기간 정해 만들기 · 지난 호우 때 보고서`)}" title="샘플 — 기간을 정해 만들기 · 지난 호우 때 만든 보고서 보기">샘플</button>` : "")
    + repWaitBadge(r) + `</div>`;
}
/* 자세히 — 왼쪽 목록 한 줄(고르기만, 받기는 오른쪽 창에서) */
function repDli(r) {
  const J = REP.jobs[r.id], D = REP.done[r.id];
  const st = J ? (J.run ? `만드는 중 · ${repPct(J)}%` : "차례 기다림") : D ? (D.ok ? "다 됐다" : "만들지 못했다") : r.brief ? "샘플받기" : r.ready ? r.group : r.broken ? "안 됨" : "준비 중";
  return `<button type="button" class="dli${r.id === REP.sel ? " on" : ""}${r.ready ? "" : " off"}" role="option" aria-selected="${r.id === REP.sel}" data-sel="${escH(r.id)}" data-id="${escH(r.id)}" draggable="true">`
    + `<span class="mi">${r.thumb ? `<img src="img/reports/${escH(r.id)}.png" alt="" loading="lazy">` : ""}</span>`
    + `<span class="dn"><b>${escH(r.name)}</b><small>${escH(st)}</small></span>${J ? `<i class="spin" aria-hidden="true"></i>` : D && !D.ok ? `<i class="x" aria-hidden="true">!</i>` : ""}</button>`;
}
/* 자세히 — 오른쪽 창: 개요 · 받기 단추 · 끌어오는 자료. 만드는 동안은 받은 자료의 기준 시각이 한 줄씩 들어온다 */
function repDet(r) {
  if (!r) return `<p class="mute">왼쪽에서 보고서를 고른다</p>`;
  const J = REP.jobs[r.id], D = REP.done[r.id], P = J?.prog, why = repWhy(r), w = REP.w[r.id];
  const row = (key, cls, name, src, at) => `<li class="${cls}${REP.seen.has(key) ? "" : " nw"}" data-nw="${escH(key)}"><i class="dot" aria-hidden="true"></i>`
    + `<span>${escH(name)}${src ? `<em class="src">${escH(src)}</em>` : ""}</span><span class="at">${escH(at || "")}</span></li>`;
  const plain = (cls, at) => (REP_SRC[r.id] || []).map(([n, s]) => `<li class="${cls}"><i class="dot" aria-hidden="true"></i><span>${escH(n)}<em class="src">${escH(s)}</em></span><span class="at">${at}</span></li>`).join("");
  let rows, head;
  if (J) {
    head = "받는 자료 · 기준 시각";
    const bs = (P?.basis || []).map((b, i) => row(`${r.id}|${J.t0}|b${i}`, b.warn ? "bad" : "ok", b.name, "", b.at));
    const cs = (P?.calls || []).map(c => row(`${r.id}|${J.t0}|c${c.label}`, P.last?.label === c.label && P.last.ago <= 5 ? "run" : c.fail ? "bad" : "ok",
      c.label, "기상청", `${c.ok}건${c.fail ? ` · 실패 ${c.fail}` : ""}`));
    rows = bs.concat(cs).join("") || plain("run", J.run ? "받는 중" : "기다림");
  } else if (D) {
    head = D.ok ? "이번에 쓴 자료 · 기준 시각" : "만들지 못했다";
    rows = (D.basis || []).map((b, i) => row(`${r.id}|d${D.t}|${i}`, b.warn ? "bad" : "ok", b.name, "", b.at)).join("");
  } else {
    head = "끌어오는 자료";
    rows = plain("", "");
  }
  const st = J ? (J.run ? `만드는 중 · ${Math.round((Date.now() - J.run) / 1000)}초 · ${P?.last && P.last.ago <= 5 ? `'${P.last.label}' 받는 중` : (P?.calls || []).length ? "받은 자료로 파일을 만드는 중" : "준비 중"}` : "차례 기다림 — 앞 보고서가 끝나면 시작한다")
    : D ? D.text : why || (w?.state === "ready" ? "17시 보고서가 준비돼 있다" : "");
  const rd = w?.state === "ready", off = !!why && !rd && !r.compose;
  return `<div class="dh">${r.thumb ? `<img src="img/reports/${escH(r.id)}.png" alt="">` : `<span class="th"><i class="ph" aria-hidden="true"><b></b><u></u><u></u><u></u></i></span>`}
      <div><small class="mute">${escH(r.group)}</small><h3>${escH(r.name)}</h3><p>${escH(r.desc)}</p></div></div>
    <div class="da"><button type="button" class="pri" data-get="${escH(r.id)}"${off || J ? " disabled" : ""}>${J ? "만드는 중…" : rd ? "17시 보고서 받기" : r.compose ? "작성하고 만들기" : D ? "다시 만들기" : "만들어 받기"}</button>`
    + (r.ready && !r.compose ? `<button type="button" data-tg="${escH(r.id)}"${off || J || !REP.d?.tg ? " disabled" : ""}>텔레그램으로</button>` : "")
    + (r.ready ? `<button type="button" data-op="${escH(r.id)}">${r.compose ? "작성 창" : "옵션"}</button>` : "")
    + (!r.brief ? `<button type="button" data-sp="${escH(r.id)}">샘플</button>` : "") + `</div>
    ${J ? `<div class="dpb" style="--p:${repPct(J)}%"><i></i></div>` : ""}<p class="dst${D && !D.ok ? " bad" : ""}" role="status">${escH(st)}</p>
    ${REP.share[r.id] ? `<div class="shr"><b>📱 휴대폰 브리핑</b><a href="${escH(REP.share[r.id])}" target="_blank" rel="noopener">${escH(REP.share[r.id])}</a>
      <button type="button" data-shr="copy" data-rid="${escH(r.id)}">링크 복사</button><button type="button" data-shr="send" data-rid="${escH(r.id)}">카톡 등으로 보내기</button>
      <span class="mute">로그인 없이 열린다</span></div>` : ""}
    ${rows ? `<h4>${head}</h4><ul class="dsrc">${rows}</ul>` : ""}
    ${repMetaView(r)}`;
}
/* 사용자가 적은 참고자료 · 메모(서버 전체에 하나) — 자세히 창 아래 */
function repMetaView(r) {
  const m = r.meta || {}, refs = m.refs || [];
  return `<h4>참고자료 · 메모 <button type="button" class="mtb" data-mt="${escH(r.id)}">${refs.length || m.memo ? "고치기" : "적기"}</button></h4>`
    + (refs.length ? `<ul class="dsrc">${refs.map(x => `<li><i class="dot" aria-hidden="true"></i><span>${escH(x.name)}${x.where ? `<em class="src">${escH(x.where)}</em>` : ""}</span><span class="at"></span></li>`).join("")}</ul>` : "")
    + (m.memo ? `<p class="memo">${escH(m.memo).replace(/\n/g, "<br>")}</p>` : "")
    + (m.at ? `<p class="mute mtat">${escH(m.by ? `${m.by} · ` : "")}${escH(m.at)}</p>` : refs.length || m.memo ? "" : `<p class="mute">이 보고서에 대한 참고자료(어디서 무엇을 가져오는지) · 메모를 적어 둘 수 있다</p>`);
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
/* ── 샘플 창 — 바로 만들지 않고 기간부터(기본 어제 00시 ~ 지금, 기간이 없는 보고서는 기준 일시 = 지금) + 지난 호우 때 미리 만들어 둔 보고서(쪽 그림 · 파일).
   샘플 파일은 서버 state/snaps/_reports(시연과 같은 것) — 등록부 listing 의 spl {ext, pages, case} */
const repYmd = d => `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}`;
function repSpKeys(r) {
  const k = new Set(r.opts.map(o => o.key));
  return k.has("start") && k.has("end") ? ["start", "end"] : k.has("tm") ? ["tm"] : [];
}
function repSpDraw() {
  const r = repById(REP.sp), box = $("rep-sp");
  if (!r) { box.hidden = true; return; }
  const now = new Date(), y = new Date(now - 864e5), hm = `${String(now.getHours()).padStart(2, "0")}${String(now.getMinutes()).padStart(2, "0")}`;
  const def = { start: `${repYmd(y)}0000`, end: `${repYmd(now)}${hm}`, tm: `${repYmd(now)}${hm}` };
  const keys = repSpKeys(r), why = repWhy(r), sp = r.spl;
  const fields = keys.map(k => { const o = r.opts.find(x => x.key === k); return repField({ ...o, hint: "" }, def[k]); }).join("")
    || `<p class="mute">이 보고서는 기간을 고르지 않는다 — 지금 자료로 만든다</p>`;
  const view = sp ? (sp.pages ? `<div class="spv">${Array.from({ length: sp.pages }, (_, i) => `<a href="/api/reports/sample/${escH(r.id)}/${i + 1}.png" target="_blank" rel="noopener" title="${i + 1}쪽 크게 보기"><img src="/api/reports/sample/${escH(r.id)}/${i + 1}.png" alt="${escH(`${r.name} 샘플 ${i + 1}쪽`)}" loading="lazy"></a>`).join("")}</div>`
      : /^(png|gif|jpg)$/.test(sp.ext) ? `<div class="spv one"><img src="/api/reports/sample/${escH(r.id)}" alt="${escH(`${r.name} 샘플`)}"></div>` : "")
      + `<div class="row"><a class="btn" href="/api/reports/sample/${escH(r.id)}" download>파일 받기 (.${escH(sp.ext)})</a><span class="mute">${escH(sp.case || "")}</span></div>`
    : `<p class="mute">지난 호우 때 만든 샘플이 아직 없다${keys.length ? "" : " — 지금 자료로만 만드는 보고서"}</p>`;
  box.hidden = false;
  box.innerHTML = `<div class="op spd" role="dialog" aria-modal="true" aria-labelledby="rep-sp-t" tabindex="-1">
    <div class="oh">${r.thumb ? `<img src="img/reports/${escH(r.id)}.png" alt="">` : `<i class="ph" aria-hidden="true"></i>`}<div><b id="rep-sp-t">${escH(r.name)} 샘플</b><small class="mute">기간을 정해 만들거나 · 지난 호우 때 만든 보고서를 본다</small></div>
      <button type="button" id="rep-spx" aria-label="샘플 닫기 (Esc)" title="닫기 (Esc)">✕</button></div>
    <div class="ob"><form class="sec" id="rep-spf" onsubmit="return false"><b class="lg">기간 정해 만들기</b>${fields}</form>
      <section class="sec"><b class="lg">지난 호우 때 보고서</b>${view}</section></div>
    <p class="msg" id="rep-spm" role="status">${why ? escH(why) : ""}</p>
    <div class="of"><span class="sp"></span><button type="button" id="rep-spgo" class="pri"${why ? " disabled" : ""}>${r.compose ? "이 기간으로 작성 창 열기" : keys.length ? "이 기간으로 만들기" : "지금 자료로 만들기"}</button></div></div>`;
  box.querySelector(".op").focus();
}
function repSpOpen(id) { if (!repById(id)) return; REP.spBack = document.activeElement; REP.sp = id; repSpDraw(); }
function repSpClose() { REP.sp = null; $("rep-sp").hidden = true; if (REP.spBack?.isConnected) REP.spBack.focus(); }
function repSpGo() {
  const r = repById(REP.sp), over = {};
  for (const k of repSpKeys(r)) {
    const v = ($("rep-spf").querySelector(`[data-k="${k}"]`)?.value || "").replace(/\D/g, "").slice(0, 12);
    if (v.length !== 12) { $("rep-spm").textContent = "날짜 · 시각을 모두 넣어 주세요"; $("rep-spm").className = "msg bad"; return; }
    over[k] = v;
  }
  if (over.start && over.start >= over.end) { $("rep-spm").textContent = "기간 끝이 시작보다 뒤여야 한다"; $("rep-spm").className = "msg bad"; return; }
  const id = r.id;
  repSpClose();
  if (r.compose) { repCmOpts(r, over); return repOpOpen(id, true); }   /* 상황판단회의 — 기간을 넣고 작성 창으로(넣은 기간은 둔다) */
  repRun(id, "dl", over);
}
function repOpOpen(id, keep) {
  const r = repById(id);
  if (!r || !r.ready || REP.op === id) return;
  REP.opBack = document.activeElement; REP.op = id;
  if (r.compose && !keep) {                                    /* 작성 창은 열 때마다 지금 기준 — 지난번 기간 · 고친 제목은 버린다(재난 종류 · 고른 문구는 둔다) */
    repCmOpts(r, { start: "", end: "", title: "" });
    const c = repCm(); c.auto = true; repCmSave(c);
  }
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
/* 특보 시군 자료 셋 — 내용은 지도 서버가 자동으로(편집 없음), 여기서는 켜고 끄기만 */
const REP_EX = [["특보지역현황", "특보지역 현황", "특보 시군의 인명피해 우려지구 · 둘레 건물 · 지금 판정"], ["과거사례", "과거 유사 사건", "특보 시군의 피해 큰 사건(위키 이력)"],
  ["조위현황", "조위 현황", "태풍 · 풍랑 · 호우이거나 해안 시군일 때만 — 아니면 빠진다"]];
const REP_EX0 = Object.fromEntries(REP_EX.map(([k]) => [k, true]));
const REP_CM = [["유의사항", "중점유의사항", "중점 유의사항"], ["조치계획", "조치계획", "조치계획"]];   /* [문구 묶음, 서식 칸, 제목] */
const repBold = t => escH(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
const repCm = () => { const c = repPref().cm || {}; return { auto: c.auto !== false, sel: { 유의사항: [], 조치계획: [], ...(c.sel || {}) }, ex: { ...REP_EX0, ...(c.ex || {}) } }; };
const repCmSave = c => repSave({ cm: c });
const REP_CMO = new Set();                                       /* 고쳐 쓰기 칸을 펴 둔 줄(묶음|문구 열쇠) — 처음엔 다 접혀 있다 */
/* 계절 · 시기 프리셋 — 재난 종류만 정해 두고, 문구는 문구 파일에서 그 종류에 맞는 것을 종류마다 돌아가며 고른다(유의사항 7 · 조치계획 5) */
const REP_CMP = [["봄 · 강풍 · 호우 (3~5월)", ["호우", "강풍"]], ["장마철 호우 (6~7월)", ["호우"]], ["여름 폭염 (6~9월)", ["폭염"]],
  ["태풍 (7~10월)", ["태풍", "호우", "강풍", "풍랑"]], ["가을 · 호우 · 강풍 · 풍랑 (9~11월)", ["호우", "강풍", "풍랑"]], ["겨울 대설 · 한파 (12~2월)", ["대설", "한파"]]];
const repCmMine = () => { const v = repPref().cmp; return Array.isArray(v) ? v : []; };
function repCmPick(g, kinds, n) {
  const all = REP.ph?.[g] || [], out = [];
  for (let round = 0; out.length < n && round < 20; round++) for (const k of kinds) {
    const p = all.filter(x => (x.kinds || []).includes(k) && !out.includes(x) && !/○/.test(x.text))[0];   // ○(채울 자리)가 있는 문구는 손으로 고를 때만
    if (p && out.length < n) out.push(p);
  }
  return all.filter(x => out.includes(x)).map(p => ({ k: p.text, text: p.text, subs: [...(p.subs || [])] }));
}
function repCmOpts(r, o) { const all = { ...(repPref().opts || {}) }; all[r.id] = { ...repVals(r), ...o }; repSave({ opts: all }); }
/* 제목 제안 — 「11. 17.~18. 호우·강풍 대비」. 기간 칸 날짜(비우면 전일~오늘) */
function repCmTitle(v) {
  const dt = s => (s && s.length === 12 ? new Date(+s.slice(0, 4), +s.slice(4, 6) - 1, +s.slice(6, 8)) : null);
  const p = repCmPeriod(v), a = dt(p.start), b = dt(p.end);   // 기간 칸(비우면 전일 00시 ~ 지금)과 같은 날짜
  const span = `${a.getMonth() + 1}. ${a.getDate()}.` + (a.toDateString() === b.toDateString() ? ""
    : a.getMonth() === b.getMonth() ? `~${b.getDate()}.` : `~${b.getMonth() + 1}. ${b.getDate()}.`);
  return `「${span} ${(v.kinds || []).join("·") || "재난"} 대비」`;
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
/* 작성 창 화면 상태 — 탭(묶음) · 후보 검색 · 설정 펴기 · 후보 패널(오른쪽에서 덮어 나온다, 처음엔 닫힘) */
const REP_CMV = { tab: "유의사항", q: "", set: false, pn: false, anim: false };
const repCmPn = () => REP_CMV.pn;
/* 기간 칸 미리 채우기 — 비운 칸은 서버 기본과 같게(시작 = 전일 00시, 끝 = 지금) 12자리로 */
function repCmPeriod(v) {
  const n = new Date(), y = new Date(n.getFullYear(), n.getMonth(), n.getDate() - 1), f = d => [d.getFullYear(), d.getMonth() + 1, d.getDate(), d.getHours(), d.getMinutes()].map((x, i) => String(x).padStart(i ? 2 : 4, "0")).join("");
  return { start: v.start || f(y), end: v.end || f(n) };
}
const repPlain = t => String(t || "").replace(/\*\*/g, "");
const repCmPv = s => { const subs = s.subs.filter(y => y.trim()); return (repBold(s.text) || `<i class="mute">(빈 줄 — 연필을 눌러 쓴다)</i>`) + (subs.length ? `<small>${subs.map(repBold).join(" · ")}</small>` : ""); };
/* 왼쪽 — 고른 것만, 보내는 차례(문구 파일 차례 → 직접 쓴 것)로 번호. ✎ 고쳐 쓰기 · ✕ 빼기 */
function repCmSel(g, c) {
  const sel = c.sel[g], all = REP.ph?.[g] || [];
  const ord = all.map(p => sel.findIndex(x => x.k === p.text)).filter(i => i >= 0).concat(sel.map((x, i) => i).filter(i => !all.some(p => p.text === sel[i].k)));
  return ord.map((si, n) => {
    const s = sel[si], key = `${g}|${si}`, open = REP_CMO.has(`${g}|${s.k}`), nm = repPlain(s.text).slice(0, 24) || "빈 줄";
    return `<li class="ci${open ? " open" : ""}"><span class="no">${n + 1}</span><span class="pv" data-pv="${escH(key)}">${repCmPv(s)}</span>`
      + `<button type="button" class="eb" data-eo="${escH(key)}" aria-expanded="${open}" aria-label="「${escH(nm)}」 고쳐 쓰기 ${open ? "접기" : "펴기"}" title="고쳐 쓰기 — 날짜 · 시군 수 · 세부 줄">${open ? "▴" : "✎"}</button>`
      + `<button type="button" class="eb" data-cx="${escH(key)}" aria-label="「${escH(nm)}」 빼기" title="빼기 — 후보로 돌아간다">✕</button>`
      + (open ? `<div class="ed"><textarea rows="2" aria-label="문구 글" data-ed="${escH(key)}">${escH(s.text)}</textarea>`
        + `<textarea rows="${Math.max(1, s.subs.length)}" aria-label="세부 · 주석" placeholder="세부 · 주석 — 한 줄에 하나(- 세부 · ※ 주석)" data-es="${escH(key)}">${escH(s.subs.join("\n"))}</textarea></div>` : "")
      + `</li>`;
  }).join("");
}
/* 오른쪽 — 아직 안 고른 후보. 회의 종류로 거르고(안 고르면 전부) 검색어로 한 번 더, 종류별로 묶는다. 누르면 바로 왼쪽으로 */
function repCmCand(g, kinds) {
  const sel = repCm().sel[g], q = REP_CMV.q.trim();
  const list = (REP.ph?.[g] || []).filter(p => !sel.some(x => x.k === p.text) && (!kinds.length || (p.kinds || []).some(k => kinds.includes(k)))
    && (!q || repPlain(`${p.text} ${(p.subs || []).join(" ")}`).includes(q)));
  const grp = new Map();
  for (const p of list) { const k = (p.kinds || []).find(x => kinds.includes(x)) || (p.kinds || [])[0] || "공통"; grp.set(k, [...(grp.get(k) || []), p]); }
  const rank = k => (kinds.indexOf(k) + 1) || 99;
  const html = [...grp.keys()].sort((a, b) => rank(a) - rank(b)).map(k => `<li class="gh">${escH(k)} <i>${grp.get(k).length}</i></li>`
    + grp.get(k).map(p => `<li><button type="button" class="cd" data-ca="${escH(g)}|${escH(p.text)}" title="${escH(repPlain(p.text))}"><span aria-hidden="true">+</span><span class="t">${escH(repPlain(p.text))}</span></button></li>`).join("")).join("")
    || `<li class="mute em">${!REP.ph ? "문구 후보를 받는 중…" : REP.ph.err ? `후보를 받지 못했다 — ${escH(REP.ph.err)}` : q ? "찾는 말이 든 후보가 없다" : "남은 후보가 없다 — 종류를 바꾸거나 직접 쓰기"}</li>`;
  return { html, n: list.length };
}
const repCmN = g => repCmItems()[REP_CM.find(x => x[0] === g)[1]].length;
const repCmMeter = n => `<div class="mw"><div class="mt${n > 7 ? " over" : ""}"><i style="width:${Math.min(100, n / 7 * 100)}%"></i></div><small class="mute">${n} / 7 — ${n > 7 ? "한 쪽을 넘쳐 표어 상자가 다음 쪽으로 밀린다" : "한 쪽에 들어간다"}</small></div>`;
/* 다시 그린 뒤 초점을 돌려줄 곳 — 같은 단추 · 칸(id 나 data-*) */
function repCmFocusSel(el, box) {
  if (!el || !box.contains(el)) return null;
  if (el.id) return `#${CSS.escape(el.id)}`;
  for (const a of ["kind", "cadd", "cx", "ca", "eo", "ed", "es", "tab", "pn"]) if (el.dataset[a] != null) return `[data-${a}="${CSS.escape(el.dataset[a])}"]`;
  return null;
}
function repCmDraw(r, focus) {
  const box = $("rep-op"), d = REP.d || {}, v = repVals(r), c = repCm(), kinds = v.kinds || [], why = repWhy(r);
  const sc = Object.fromEntries([".cml", ".cdl", ".cmx"].map(k => [k, box.querySelector(k)?.scrollTop || 0]));
  const fk = focus || repCmFocusSel(document.activeElement, box);
  const kOpt = r.opts.find(o => o.key === "kinds"), sug = repCmTitle(v), g = REP_CMV.tab, pn = repCmPn(), cand = repCmCand(g, kinds);
  const dt = s => (s && s.length === 12 ? `${+s.slice(4, 6)}.${+s.slice(6, 8)} ${s.slice(8, 10)}:${s.slice(10, 12)}` : "");
  const pv = REP_CMV.def = repCmPeriod(v);
  const title = c.auto ? sug : v.title || sug, nex = REP_EX.filter(([k]) => c.ex[k]).length, nSel = repCmN(g);
  const chips = cls => `<div class="kc${cls}" role="group" aria-label="${escH(kOpt.label)}">${kOpt.values.map(([x]) => `<button type="button" data-kind="${escH(x)}" aria-pressed="${kinds.includes(x)}" class="${kinds.includes(x) ? "on" : ""}">${escH(x)}</button>`).join("")}</div>`;
  box.hidden = false;
  box.innerHTML = `<div class="op cmp" role="dialog" aria-modal="true" aria-labelledby="rep-op-t" tabindex="-1">
    <div class="oh">${r.thumb ? `<img src="img/reports/${escH(r.id)}.png" alt="">` : `<i class="ph" aria-hidden="true"></i>`}<div><b id="rep-op-t">${escH(r.name)} 작성</b><small class="mute">${escH(r.desc)}</small></div>
      <button type="button" id="rep-opx" aria-label="작성 창 닫기 (Esc)" title="닫기 (Esc) — 고른 것은 기억한다">✕</button></div>
    <div class="cmh"><select id="rep-cm-ps" aria-label="프리셋 불러오기"><option value="">프리셋 불러오기…</option>
        <optgroup label="계절 · 시기">${REP_CMP.map(([n], i) => `<option value="s:${i}"${REP.ph && !REP.ph.err ? "" : " disabled"}>${escH(n)}</option>`).join("")}</optgroup>
        ${repCmMine().length ? `<optgroup label="내 프리셋">${repCmMine().map((x, i) => `<option value="m:${i}">${escH(x.name)}</option>`).join("")}</optgroup>` : ""}</select>
      <span class="sum" title="${escH(`${title} · ${kinds.join("·") || "종류 전체"}`)}"><b>${escH(title)}</b> · ${escH(kinds.join("·") || "종류 전체")} · ${escH(`${dt(pv.start)} ~ ${v.end ? dt(v.end) : "지금"}`)} · 자료 ${nex}/${REP_EX.length}</span>
</div>
    <div class="cmx" id="rep-cm-x"><form class="ob" id="rep-of" onsubmit="return false">
      <fieldset class="sec"><legend>회의</legend>
        ${chips("")}
        <label class="fl" for="rep-cm-title"><span>회의 제목</span><input id="rep-cm-title" type="text" maxlength="60" value="${escH(title)}"></label>
        ${c.auto ? "" : `<small class="mute">고친 제목 — <button type="button" class="lnk" id="rep-cm-auto">제안으로 돌리기(${escH(sug)})</button></small>`}
        <details class="psm"><summary>지금 고른 것을 프리셋으로</summary>
          <div class="row"><input id="rep-cm-psn" type="text" maxlength="30" placeholder="장마 초기대응" aria-label="프리셋 이름"><button type="button" id="rep-cm-pss">저장</button></div>
          ${repCmMine().map(x => `<div class="row pm"><span>${escH(x.name)}</span><button type="button" class="lnk" data-psd="${escH(x.name)}" aria-label="${escH(x.name)} 프리셋 지우기">지우기</button></div>`).join("")}
        </details></fieldset>
      <fieldset class="sec"><legend>기간</legend>${r.opts.filter(o => o.sec === "기간").map(o => repField({ ...o, hint: o.key === "end" ? "비우면 지금" : "" }, pv[o.key])).join("")}
        <div class="row dys" role="group" aria-label="기간 프리셋 — 오늘까지 며칠">${[2, 3].map(n => `<button type="button" data-days="${n}">${n}일</button>`).join("")}
          <input id="rep-cm-nd" type="number" inputmode="numeric" min="1" max="31" value="5" aria-label="며칠(직접)"><button type="button" data-days="n">일</button>
          <small class="mute">오늘 포함 — 2일이면 어제 00시 ~ 지금</small></div></fieldset>
      <fieldset class="sec"><legend>특보 시군 자료(자동)</legend>${REP_EX.map(([k, t, h]) => `<label class="ck" title="${escH(h)}"><input type="checkbox" data-cex="${escH(k)}"${c.ex[k] ? " checked" : ""}> ${escH(t)}</label>`).join("")}</fieldset>
    </form></div>
    <div class="cmt" role="tablist" aria-label="Ⅱ장 묶음">${REP_CM.map(([k, , t]) => `<button type="button" role="tab" data-tab="${escH(k)}" aria-selected="${k === g}">${escH(t)}<i>${repCmN(k)}</i></button>`).join("")}</div>
    <div class="cmb${pn ? " pn" : ""}">
      <section class="cml" aria-label="고른 ${escH(g)} — 보고서에 이 차례로 들어간다">
        ${nSel || c.sel[g].length ? `<ol class="sl">${repCmSel(g, c)}</ol>` : `<p class="em mute">아직 고른 문구가 없다 — ${pn ? "오른쪽 후보를 눌러 넣는다" : "‘문구 고르기’로 후보를 연다"}</p>`}
        ${g === "유의사항" ? repCmMeter(nSel) : ""}
        <div class="row">${pn ? "" : `<button type="button" data-pn="1" aria-expanded="false" aria-controls="rep-cm-r">+ 문구 고르기</button>`}<button type="button" data-cadd="${escH(g)}">직접 쓰기</button></div>
      </section>
      ${pn ? `<aside class="cmr${REP_CMV.anim ? " in" : ""}" id="rep-cm-r" aria-label="후보 문구">
        <div class="rh"><b>후보 <i>${cand.n}</i></b><button type="button" class="eb" data-pn="0" aria-expanded="true" aria-label="후보 접기" title="후보 접기">»</button></div>
        <input id="rep-cm-q" type="search" placeholder="후보에서 찾기" aria-label="후보 문구 찾기" value="${escH(REP_CMV.q)}">
        ${chips(" sm")}
        <ul class="cdl">${cand.html}</ul></aside>` : ""}
    </div>
    <p class="msg" id="rep-om" role="status">${why ? escH(why) : ""}</p>
    <div class="of"><span class="sp"></span><button type="button" id="rep-ctg"${why || !d.tg ? " disabled" : ""} title="${escH(d.tg ? "텔레그램으로 보내기만" : "텔레그램 키가 없다 — 설정 › API 키")}">텔레그램으로</button>
      <button type="button" id="rep-cgo" class="pri"${why ? " disabled" : ""}>만들어 받기</button></div></div>`;
  REP_CMV.anim = false;
  for (const [k, t] of Object.entries(sc)) { const el = box.querySelector(k); if (el) el.scrollTop = t; }
  ((fk && [...box.querySelectorAll(fk)].find(x => x.offsetParent)) || box.querySelector(".op")).focus();
  if (!REP.ph) repCmLoad();
}
async function repCmLoad() {
  if (REP.phBusy) return;
  REP.phBusy = true;
  try { REP.ph = await getJson("/api/reports/phrases"); } catch (e) { REP.ph = { err: e.message }; }
  REP.phBusy = false;
  const r = repById(REP.op);
  if (r?.compose) repCmDraw(r);
}
/* 후보 패널 열기 · 닫기 */
function repCmPanel(r, open) {
  REP_CMV.pn = open; REP_CMV.anim = open;
  repCmDraw(r, open ? "#rep-cm-q" : '[data-pn="1"]');
}
/* 작성 창 안 누름 · 고침 */
function repCmClick(t, r) {
  const kb = t.closest("[data-kind]");
  if (kb) {
    const v = repVals(r), k = kb.dataset.kind, ks = (v.kinds || []).includes(k) ? v.kinds.filter(x => x !== k) : [...(v.kinds || []), k];
    repCmOpts(r, { kinds: r.opts.find(o => o.key === "kinds").values.map(x => x[0]).filter(x => ks.includes(x)) });
    return repCmDraw(r);
  }
  const tb = t.closest("[data-tab]");
  if (tb) { REP_CMV.tab = tb.dataset.tab; return repCmDraw(r, `[data-tab="${CSS.escape(tb.dataset.tab)}"]`); }
  const dy = t.closest("[data-days]");
  if (dy) {                                                   /* 기간 프리셋 — 오늘 포함 n일(시작 = n−1일 전 00시, 끝 = 지금) */
    const n = dy.dataset.days === "n" ? Number($("rep-cm-nd").value) : Number(dy.dataset.days);
    if (!Number.isInteger(n) || n < 1 || n > 31) { $("rep-om").textContent = "며칠은 1~31 로 넣어 주세요"; $("rep-om").className = "msg bad"; return; }
    const d = new Date(); d.setDate(d.getDate() - (n - 1));
    repCmOpts(r, { start: `${d.getFullYear()}${String(d.getMonth() + 1).padStart(2, "0")}${String(d.getDate()).padStart(2, "0")}0000`, end: "" });
    return repCmDraw(r, `[data-days="${dy.dataset.days}"]`);
  }
  const pnb = t.closest("[data-pn]");
  if (pnb) return repCmPanel(r, pnb.dataset.pn === "1");
  if (repCmPn() && t.closest(".cml")) return repCmPanel(r, false);   /* 덮은 후보 밖을 누르면 닫는다 */
  const ca = t.closest("[data-ca]");
  if (ca) {                                                   /* 후보 넣기 — 문구 그대로 복사해 고칠 수 있게. 초점은 다음 후보로(이어서 고르게) */
    const c = repCm(), [g, ...rest] = ca.dataset.ca.split("|"), text = rest.join("|"), p = (REP.ph?.[g] || []).find(x => x.text === text);
    if (!p) return;
    const bs = [...$("rep-op").querySelectorAll("[data-ca]")], i = bs.indexOf(ca), nx = bs[i + 1] || bs[i - 1];
    c.sel[g].push({ k: p.text, text: p.text, subs: [...(p.subs || [])] });
    repCmSave(c);
    return repCmDraw(r, nx ? `[data-ca="${CSS.escape(nx.dataset.ca)}"]` : "#rep-cm-q");
  }
  const cx = t.closest("[data-cx]");
  if (cx) {                                                   /* 빼기(고친 글도 버린다) — 초점은 같은 자리의 다음 ✕ */
    const c = repCm(), [g, si] = cx.dataset.cx.split("|"), n = [...$("rep-op").querySelectorAll("[data-cx]")].indexOf(cx), [x] = c.sel[g].splice(+si, 1);
    REP_CMO.delete(`${g}|${x.k}`);
    repCmSave(c); repCmDraw(r);
    const xs = $("rep-op").querySelectorAll("[data-cx]");
    return (xs[n] || xs[n - 1] || $("rep-op").querySelector("[data-cadd]")).focus();
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
  if (t.id === "rep-cm-q") {
    REP_CMV.q = t.value;
    const cand = repCmCand(REP_CMV.tab, repVals(r).kinds || []), box = $("rep-op");
    box.querySelector(".cdl").innerHTML = cand.html; box.querySelector(".cmr .rh i").textContent = cand.n;
    return;
  }
  const key = t.dataset.ed || t.dataset.es;
  if (!key) return;
  const [g, si] = key.split("|"), s = c.sel[g]?.[+si];
  if (!s) return;
  if (t.dataset.ed) s.text = t.value.replace(/\n+/g, " ");
  else s.subs = t.value.split("\n");
  repCmSave(c);
  const box = $("rep-op"), pv = box.querySelector(`[data-pv="${CSS.escape(key)}"]`), n = repCmN(g);
  if (pv) pv.innerHTML = repCmPv(s);
  const cnt = box.querySelector(`[data-tab="${CSS.escape(g)}"] i`), mw = box.querySelector(".cml .mw");
  if (cnt) cnt.textContent = n;
  if (mw && g === "유의사항") mw.outerHTML = repCmMeter(n);
}
function repCmChange(t, r) {
  const c = repCm();
  if (t.dataset.cex) { c.ex[t.dataset.cex] = t.checked; return repCmSave(c); }
  if (t.id === "rep-cm-ps") {                          /* 프리셋 불러오기 — 종류 · 고른 문구를 통째로 바꾼다(제목은 제안으로) */
    const [kind, i] = t.value.split(":"), mine = repCmMine()[+i], std = REP_CMP[+i];
    if (kind === "m" && mine) { c.sel = { 유의사항: [], 조치계획: [], ...JSON.parse(JSON.stringify(mine.sel || {})) }; repCmOpts(r, { kinds: mine.kinds || [], title: "" }); }
    else if (kind === "s" && std && REP.ph && !REP.ph.err) { c.sel = { 유의사항: repCmPick("유의사항", std[1], 7), 조치계획: repCmPick("조치계획", std[1], 5) }; repCmOpts(r, { kinds: std[1], title: "" }); }
    else return;
    c.auto = true; REP_CMO.clear();
    repCmSave(c); repCmDraw(r, "#rep-cm-ps");
    $("rep-om").textContent = `「${kind === "m" ? mine.name : std[0]}」 을 불러왔다 — 후보에서 더 넣거나 ✕ 로 뺀다`; $("rep-om").className = "msg";
    return;
  } else if (t.type === "datetime-local") {
    try {                                                     /* 미리 채운 값 그대로면 비워 둔다 — 다음에 열 때 그때 기준으로 다시 채운다 */
      const o = repOpRead({ opts: r.opts.filter(x => x.sec === "기간") });
      for (const k of ["start", "end"]) if (o[k] === REP_CMV.def?.[k]) o[k] = "";
      repCmOpts(r, o);
    } catch {}
    return repCmDraw(r);
  }
}
function repDraw() {
  const d = REP.d, list = d?.reports || [], gs = d?.groups || [];
  if (gs.length && REP.g !== "*" && !gs.includes(REP.g)) REP.g = gs[0];
  const shown = REP.g === "*" ? list : list.filter(r => r.group === REP.g);      /* '*' = 전체(폴더 아님 — 끌어 놓기 · 메뉴 없음) */
  const empty = !d ? "목록을 받는 중…" : d.err ? `목록을 받지 못했다 — ${d.err}` : "이 폴더에는 아직 보고서가 없다";   /* 위 안내 줄은 뺐다(사용자 요청) — 키가 없으면 받을 때 오류로 알린다 */
  const det = repView() === "det";
  if (det && !shown.some(r => r.id === REP.sel)) REP.sel = (shown.find(r => r.ready) || shown[0] || list[0])?.id || null;
  const wide = det && !!(REP.jobs[REP.sel] || REP.done[REP.sel]);
  $("rep").innerHTML = `<div class="box${det ? " det" : ""}${det && REP.wide ? " wide" : ""}" role="dialog" aria-modal="true" aria-labelledby="rep-t" tabindex="-1">
    <div class="top"><b id="rep-t">보고서</b><nav aria-label="묶음"><button type="button" data-gall="1" aria-pressed="${REP.g === "*"}" class="${REP.g === "*" ? "on" : ""}">전체 <i>${list.length}</i></button>${gs.map(g => { const n = list.filter(r => r.group === g).length;
      return `<button type="button" data-g="${escH(g)}" aria-pressed="${g === REP.g}" class="${g === REP.g ? "on" : ""}" title="오른쪽 누름(길게 누름): 이름 · 차례 · 지우기 · 보고서를 끌어 놓으면 이 폴더로">${escH(g)} <i>${n}</i></button>`; }).join("")}<button type="button" class="gadd" data-gadd="1" aria-label="새 폴더" title="새 폴더">＋</button></nav><span class="sp"></span>
      <div class="vw" role="group" aria-label="보기">${[["grid", "목록"], ["det", "자세히"]].map(([k, t]) => `<button type="button" data-vw="${k}" aria-pressed="${repView() === k}" class="${repView() === k ? "on" : ""}">${t}</button>`).join("")}</div>
      <button type="button" id="rep-cog" class="${REP.set ? "on" : ""}" aria-expanded="${REP.set}" aria-controls="rep-set" aria-label="전체 설정" title="전체 설정 — 받을 때 텔레그램에도">⚙</button>
      <button type="button" id="rep-x" aria-label="닫기 (Esc)" title="닫기 (Esc)">✕</button></div>
    ${REP.set ? repSettings() : ""}
    ${det ? `<div class="dv"><div class="dl" role="listbox" aria-label="보고서">${shown.map(repDli).join("") || `<p class="mute">${escH(empty)}</p>`}</div>
      <section class="dp${REP.sel !== REP.drawn ? " in" : ""}" aria-live="polite">${repDet(repById(REP.sel))}</section></div>`
      : `<div class="grid">${shown.map(repTile).join("") || `<p class="mute">${escH(empty)}</p>`}</div>`}
    <p class="msg${REP.msg && !REP.msg.ok ? " bad" : ""}" role="status">${escH(REP.msg?.text || (repBusy() ? "보고서 서버가 만드는 중 — 여러 개를 걸어 두면 차례대로 만든다. 창을 닫아도(✕) 계속, 오른쪽 위에 진행이 보이고 끝나면 저절로 받는다" : "타일을 누르면 받는다 · 오른쪽 누름(길게 누름)은 메뉴 — 옵션 · 폴더 옮기기 · 참고자료와 메모 · 끌어서 폴더 탭에 놓아도 옮겨진다"))}</p></div>
    <div class="opbg" id="rep-op" hidden></div><div class="opbg" id="rep-sp" hidden></div><div class="opbg" id="rep-mt" hidden></div><div class="rctx" id="rep-ctx" hidden></div>${repBsHtml()}`;
  if (REP.mt) repMtDraw();
  $("rep").querySelectorAll("[data-nw]").forEach(e => REP.seen.add(e.dataset.nw));
  REP.drawn = det ? REP.sel : null;                          /* 오른쪽 창은 고른 보고서가 바뀔 때만 떠오른다(2초마다 다시 그려도 깜빡이지 않게) */
  if (wide !== REP.wide) { const b = $("rep").querySelector(".box"); requestAnimationFrame(() => b.classList.toggle("wide", wide)); REP.wide = wide; }
  if (REP.bs) $("rep-bs").querySelector(".op").focus();
  else if (REP.op) repOpDraw();
  else if (REP.sp) repSpDraw();
  else if (!$("rep").hidden && !$("rep").contains(document.activeElement)) $("rep").querySelector(".box").focus();   /* 다시 그려 초점이 빠졌으면 창 안으로 */
}
async function repSaveFile(res, fallback) {
  const blob = await res.blob(), name = repName(res.headers.get("Content-Disposition")) || fallback, a = document.createElement("a");
  a.href = URL.createObjectURL(blob); a.download = name; document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 5000);
  return name;
}
/* 오른쪽 위 진행 띠 — 보고서 창을 닫아도(✕ · Esc) 만들기는 계속된다. 누르면 창(끝났으면 결과 · 자료 기준)을 다시 연다 */
/* 만드는 동안: 띠가 예상 시간만큼 차오르고(지난번 걸린 시간 — 처음은 60초, 95% 에서 멈춘다) · 누르면 아래로 펼쳐 무엇을 받는 중인지
   (보고서 서버 /api/progress — 기상청 자료마다 받은 수 · 실패 수 · 마지막으로 부른 자료). 끝나면 누르면 보고서 창 */
function repJob(st, text, pct) {
  let el = $("rep-job");
  if (!el) {
    el = document.createElement("button");
    el.type = "button"; el.id = "rep-job"; el.setAttribute("aria-live", "polite"); el.setAttribute("aria-controls", "rep-jobd");
    el.addEventListener("click", () => {
      if (repBusy()) return repJobOpen($("rep-jobd").hidden);
      clearTimeout(REP.jobT); el.hidden = true; repJobOpen(false); openRep();
    });
    const d = document.createElement("div");
    d.id = "rep-jobd"; d.hidden = true; d.setAttribute("role", "region"); d.setAttribute("aria-label", "보고서 만드는 과정");
    document.body.append(el, d);
  }
  clearTimeout(REP.jobT);
  el.className = st; el.hidden = !st;
  el.style.setProperty("--p", `${pct ?? 0}%`);
  el.innerHTML = st === "busy" ? `<i class="spin" aria-hidden="true"></i><span>${escH(text)}</span><i class="car" aria-hidden="true">${$("rep-jobd").hidden ? "▾" : "▴"}</i>` : escH(text);
  el.setAttribute("aria-expanded", String(st === "busy" && !$("rep-jobd").hidden));
  el.title = st === "busy" ? "보고서 서버가 만드는 중 — 창을 닫아도 계속, 끝나면 저절로 받는다. 누르면 무엇을 하는 중인지 펼친다" : "누르면 보고서 창(결과 · 자료 기준 시각)";
  if (st !== "busy") repJobOpen(false);
  if (st === "ok") REP.jobT = setTimeout(() => { el.hidden = true; }, 12000);   // 실패 · 경고는 누를 때까지 둔다
}
function repJobOpen(on) {
  const d = $("rep-jobd");
  if (!d) return;
  d.hidden = !on;
  if (on) repJobDraw();
  const el = $("rep-job"), c = el?.querySelector(".car");
  if (c) c.textContent = on ? "▴" : "▾";
  el?.setAttribute("aria-expanded", String(!!on));
}
function repJobDraw() {
  const d = $("rep-jobd");
  if (!d || d.hidden) return;
  const p = REP.prog || {}, calls = p.calls || [];
  const now = !p.running ? "보고서 서버에 묻는 중…" : p.last && p.last.ago <= 5 ? `기상청 '${p.last.label}' 받는 중` : calls.length ? "받은 자료로 그림 · 한글 파일을 만드는 중" : "준비 중";
  d.innerHTML = Object.values(REP.jobs).map(J => `<div class="jd-h"><b>${escH(J.name)}</b><span>${J.run
      ? `${repPct(J)}% · ${Math.round((Date.now() - J.run) / 1000)}초 · 예상 약 ${J.exp}초` : "차례 기다림"}</span></div>`).join("")
    + `<div class="jd-now"><i class="spin" aria-hidden="true"></i>${escH(now)}</div>
    ${calls.length ? `<ul>${calls.map(c => `<li class="${c.fail ? "f" : ""}"><span>${escH(c.label)}</span><b>${c.ok}건</b>${c.fail ? `<em>실패 ${c.fail}</em>` : ""}</li>`).join("")}</ul>` : ""}
    <div class="jd-ft"><button type="button" data-jd="open">보고서 창 열기</button></div>`;
  d.querySelector('[data-jd="open"]').onclick = () => openRep();
}
async function repRun(id, mode, over) {
  const r = repById(id);
  if (!r) return;
  if (r.brief) {                                                  /* 태풍 4기관 브리핑 — 지금은 샘플받기만(가상 자료 공개 링크) */
    try {
      const res = await fetch("/api/reports/brief-sample", { method: "POST" });
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `오류 ${res.status}`);
      const j = await res.json();
      REP.share[id] = j.share;
      REP.msg = { ok: true, text: `${r.name} — 샘플 링크를 만들었다(오른쪽 창)` };
    } catch (e) { REP.msg = { ok: false, text: `샘플을 받지 못했다 — ${e.message}` }; }
    REP.sel = id;                                                 /* 링크는 그 보고서를 고른 자세히 창에만 */
    if (repView() !== "det") repSave({ view: "det" });
    return repDraw();
  }
  if (mode === "dl" && REP.w[id]?.state === "ready") {         /* 17시 대기로 만들어 둔 것 */
    try {
      const res = await fetch(`/api/reports/wait/file?id=${encodeURIComponent(id)}`);
      if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `오류 ${res.status}`);
      REP.msg = { ok: true, text: `받았다 — ${await repSaveFile(res, `${id}.hwp`)} (17시 보고서)` };
    } catch (e) { REP.msg = { ok: false, text: `받지 못했다 — ${e.message}` }; }
    return repDraw();
  }
  if (REP.jobs[id]) return;                                    // 같은 보고서를 두 번은 걸지 않는다
  delete REP.done[id]; REP.sel = id;
  const p = repPref(), dl = mode === "dl", tg = mode === "tg" || (dl && !!p.tg && !!REP.d?.tg);
  let took = {};
  try { took = JSON.parse(localStorage.getItem("gn-rep-took") || "{}"); } catch {}
  // 예상 — 지난번 걸린 시간(처음은 60초). 차례를 기다리는 동안은 세지 않고, 서버가 그 작업을 시작하면(run) 잰다
  REP.jobs[id] = { name: r.name, job: r.job || id, t0: Date.now(), run: repBusy() ? null : Date.now(), exp: Math.max(15, Math.round(took[id] || 60)) };
  REP.busy = id; REP.msg = null; repDraw(); repTick();
  try {
    const res = await fetch("/api/reports/run", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ id, opts: { ...repSend(r), ...(over || {}) }, items: r.compose ? repCmItems() : undefined, extra: r.compose ? repCm().ex : undefined, tg, dl }) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `오류 ${res.status}`);
    if (dl) {
      const t = res.headers.get("X-Tg"), name = await repSaveFile(res, `${id}.hwp`);
      REP.msg = { ok: t !== "fail", text: `받았다 — ${name}${t === "ok" ? " · 텔레그램에도 보냈다" : t === "fail" ? " · 텔레그램은 보내지 못했다" : ""}`, share: res.headers.get("X-Share") || "" };
      if (REP.msg.share) REP.share[id] = REP.msg.share;
      let b = [];
      try { b = JSON.parse(decodeURIComponent(res.headers.get("X-Basis") || "[]")); } catch {}
      repBasis(r.name, name, b);
    } else {
      const j = await res.json();
      REP.msg = { ok: true, text: `텔레그램으로 보냈다 — ${j.name}`, share: j.share || "" };
      if (j.share) REP.share[id] = j.share;
      repBasis(r.name, j.name, j.basis);
    }
  } catch (e) { REP.msg = { ok: false, text: `만들지 못했다 — ${e.message}` }; }
  REP.done[id] = { ok: !!REP.msg?.ok, text: REP.msg?.text || "", basis: REP.bs?.list || [], t: Date.now() };
  if (repView() === "det") REP.bs = null;
  const J = REP.jobs[id];
  delete REP.jobs[id];
  if (REP.msg?.ok && J.run) { took[id] = (Date.now() - J.run) / 1000; try { localStorage.setItem("gn-rep-took", JSON.stringify(took)); } catch {} }
  const warn = REP.done[id].basis.some(x => x.warn);
  const done = !REP.msg?.ok ? `✕ ${r.name} — 만들지 못했다(눌러서 보기)` : `✓ ${r.name} 받았다${warn ? " · ⚠ 기상청 조회 실패 — 눌러서 확인" : ""}`;
  if (repBusy()) { toast(done); repTick(); }                   // 아직 남은 작업이 있으면 알림만 — 띠는 남은 것을 계속 보인다
  else { REP.busy = null; clearInterval(REP.tick); clearInterval(REP.ptick); REP.tick = REP.ptick = 0; repJob(!REP.msg?.ok ? "bad" : warn ? "warn" : "ok", done); }
  if (!$("rep").hidden) repDraw();
}
/* 진행 % — 서버가 그 작업을 시작한 뒤 지난 시간 ÷ 예상(95% 에서 멈춘다). 차례를 기다리는 동안은 0 */
const repPct = J => J.run ? Math.min(95, Math.round((Date.now() - J.run) / 10 / J.exp)) : 0;
/* 띠 · 타일 초 · 펼친 목록을 1초마다, 서버 진행을 2초마다 — 서버가 지금 만드는 작업(job)이 시작한 때를 run 으로 잡는다 */
function repTick() {
  const draw = () => {
    const L = Object.entries(REP.jobs);
    if (!L.length) return;
    for (const [rid, J] of L) { const e = $("rep").querySelector(`[data-sec="${CSS.escape(rid)}"]`); if (e && J.run) e.textContent = Math.round((Date.now() - J.run) / 1000); }
    const cur = L.find(([, J]) => J.run) || L[0], wait = L.filter(([, J]) => !J.run).length;
    const pct = Math.round(L.reduce((a, [, J]) => a + repPct(J), 0) / L.length);
    repJob("busy", L.length === 1 ? `${cur[1].name} ${cur[1].run ? `만드는 중 · ${pct}%` : "차례 기다림"}`
      : `보고서 ${L.length}개 — ${cur[1].name} 만드는 중${wait ? ` · ${wait}개 차례 기다림` : ""} · ${pct}%`, pct);
    repJobDraw();
  };
  draw();
  if (!REP.tick) REP.tick = setInterval(draw, 1000);
  if (!REP.ptick) REP.ptick = setInterval(async () => {
    try { REP.prog = await getJson("/api/reports/progress"); } catch { return; }
    const P = REP.prog;
    if (!P.running) return;
    const list = P.jobs?.length ? P.jobs : [P];                // 보고서 서버가 동시에 만드는 것마다
    for (const J of Object.values(REP.jobs)) {                  // 서버가 이 작업을 만들기 시작했다 — 그때부터 잰다
      const p = list.find(x => x.job === J.job);
      if (!p) continue;
      J.prog = p;
      if (!J.run) J.run = Date.now() - (p.elapsed || 0) * 1000;
    }
    if (!$("rep").hidden && !REP.op) repDraw();
  }, 2000);
}
/* 자료 기준 시각 팝업 — 만들기가 끝나면 이번 파일에 쓴 기상청 자료의 발표 · 기준 시각(문서에는 안 넣는다) + 우리 자료 시각.
   서버가 보낸 것만(없으면 안 띄운다). 닫기 · Esc · 바깥 누름 */
function repBasis(title, file, list) {
  REP.bs = Array.isArray(list) && list.length ? { title, file, list } : null;
}
function repBsHtml() {
  const b = REP.bs;
  if (!b) return "";
  return `<div class="opbg" id="rep-bs"><div class="op bs" role="dialog" aria-modal="true" aria-labelledby="rep-bs-t" tabindex="-1">
    <div class="oh"><div><b id="rep-bs-t">자료 기준 시각</b><small class="mute">${escH(b.title)} — ${escH(b.file || "")}</small></div>
      <button type="button" id="rep-bsx" aria-label="닫기 (Esc)" title="닫기 (Esc)">✕</button></div>
    <dl class="ob">${b.list.map(x => `<dt${x.warn ? ' class="warn"' : ""}>${escH(x.name)}</dt><dd${x.warn ? ' class="warn"' : ""}>${escH(x.at)}</dd>`).join("")}</dl>
    <p class="mute bsn">기상청 자료 시각은 문서에 넣지 않았다 — 이 창으로만 알린다. 수위 · 우려지역 · 조위는 문서 각주에도 있다.</p>
    <div class="of"><span class="sp"></span><button type="button" id="rep-bsok" class="pri">확인</button></div></div></div>`;
}
function repBsClose() { REP.bs = null; $("rep-bs")?.remove(); $("rep").querySelector(".box")?.focus(); }
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
  if (!$("rep").hidden && !repBusy() && !REP.op) repDraw();        /* 옵션창을 고치는 중이면 다시 그리지 않는다 */
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
  if (REP.bs) { if (t.id === "rep-bs" || t.closest("#rep-bsx, #rep-bsok")) repBsClose(); return; }
  if (REP.sp) {                                              /* 샘플 창 — 바깥 누름은 샘플 창만 닫는다 */
    if (t.id === "rep-sp" || t.closest("#rep-spx")) return repSpClose();
    if (t.closest("#rep-spgo")) return repSpGo();
    return;
  }
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
  const vw = t.closest("[data-vw]");
  if (vw) { repSave({ view: vw.dataset.vw }); repDraw(); return $("rep").querySelector(`[data-vw="${vw.dataset.vw}"]`)?.focus(); }
  const sel = t.closest("[data-sel]");
  if (sel) { REP.sel = sel.dataset.sel; repDraw(); return $("rep").querySelector(`[data-sel="${CSS.escape(REP.sel)}"]`)?.focus(); }
  const g = t.closest("[data-g]");
  const shr = ev.target.closest("[data-shr]");
  if (shr && REP.share[shr.dataset.rid]) {                     // 태풍 브리핑 공개 링크 — 복사 · 휴대폰 공유 창(카톡)
    const u = REP.share[shr.dataset.rid];
    if (shr.dataset.shr === "send" && navigator.share) { navigator.share({ title: "태풍 진로 브리핑", url: u }).catch(() => {}); return; }
    navigator.clipboard?.writeText(u).then(() => toast("링크를 복사했다 — 카톡에 붙여 넣으면 된다"), () => toast(u));
    return;
  }
  if (t.closest("[data-gall]")) { REP.g = "*"; repDraw(); return $("rep").querySelector("[data-gall]")?.focus(); }
  if (g) { REP.g = g.dataset.g; repDraw(); return $("rep").querySelector(`[data-g="${CSS.escape(REP.g)}"]`)?.focus(); }
  const op = t.closest("[data-op]");
  if (op) return repOpOpen(op.dataset.op);
  const spb = t.closest("[data-sp]");
  if (spb) return repSpOpen(spb.dataset.sp);
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
  if (!tile || REP.op || REP.sp) return;
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
  if (ev.key === "Escape") {
    ev.preventDefault();
    const r = repById(REP.op);
    if (!REP.bs && r?.compose && repCmPn()) return repCmPanel(r, false);
    return REP.bs ? repBsClose() : REP.sp ? repSpClose() : REP.op ? repOpClose() : closeRep();
  }
  if (!REP.op && !REP.sp && (ev.key === "ContextMenu" || (ev.shiftKey && ev.key === "F10"))) {
    const tile = document.activeElement?.closest?.(".rt[data-id]");
    if (tile) { ev.preventDefault(); return repOpOpen(tile.dataset.id); }
  }
  if (ev.key !== "Tab") return;
  const box = REP.bs ? $("rep-bs").querySelector(".op") : REP.sp ? $("rep-sp").querySelector(".op") : REP.op ? $("rep-op").querySelector(".op") : $("rep").querySelector(".box");
  const fs = [...box.querySelectorAll("a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex='0']")].filter(x => x.offsetParent !== null);
  if (!fs.length) return;
  const i = fs.indexOf(document.activeElement);
  if (i < 0) { ev.preventDefault(); (ev.shiftKey ? fs[fs.length - 1] : fs[0]).focus(); }
  else if (ev.shiftKey && i === 0) { ev.preventDefault(); fs[fs.length - 1].focus(); }
  else if (!ev.shiftKey && i === fs.length - 1) { ev.preventDefault(); fs[0].focus(); }
}, true);
$("b-rep").onclick = () => ($("rep").hidden ? openRep() : closeRep());

/* ── 사용자가 꾸미는 보고서 창: 폴더(탭) · 자리 · 차례 · 참고자료 · 메모 — 서버 전체에 하나(PUT /api/reports/layout · meta) ──
   오른쪽 누름(휴대폰 길게 누름) 메뉴 · 타일을 폴더 탭에 끌어 놓기(그 폴더로) · 다른 타일 위에 놓기(그 앞으로) */
const repLay = () => { const d = REP.d || {}; return { groups: [...(d.groups || [])], place: Object.fromEntries((d.reports || []).map(r => [r.id, r.group])), order: (d.reports || []).map(r => r.id) }; };
async function repLaySave(lay, msg) {
  try {
    const res = await fetch("/api/reports/layout", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(lay) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `오류 ${res.status}`);
    REP.d = await getJson("/api/reports");
    if (msg) toast(msg);
  } catch (e) { toast(`바꾸지 못했다 — ${e.message}`); }
  repDraw();
}
function repMove(id, g, before) {
  const lay = repLay();
  if (g) lay.place[id] = g;
  if (before && before !== id) { lay.order = lay.order.filter(x => x !== id); lay.order.splice(lay.order.indexOf(before), 0, id); }
  return repLaySave(lay, g && !before ? `「${repById(id)?.name}」 → ${g}` : "");
}
function repStep(id, k) {                                        /* 보이는 폴더 안에서 앞 · 뒤로 한 칸 */
  const lay = repLay(), same = lay.order.filter(x => lay.place[x] === lay.place[id]), i = same.indexOf(id), j = i + k;
  if (j < 0 || j >= same.length) return;
  const a = lay.order.indexOf(id), b = lay.order.indexOf(same[j]);
  [lay.order[a], lay.order[b]] = [lay.order[b], lay.order[a]];
  repLaySave(lay);
}
/* 메뉴 — items: [{t, fn, off} | {h} | {input, ph, ok, value, fn}] · 누른 자리 옆에 뜬다 */
function repCtx(x, y, items) {
  const m = $("rep-ctx"); if (!m) return;
  REP.ctx = items;
  m.innerHTML = `<div role="menu">${items.map((it, i) => it.h ? `<b class="mh">${escH(it.h)}</b>`
    : it.input ? `<form class="mi" data-ci="${i}"><input id="rep-ctx-in" maxlength="20" value="${escH(it.value || "")}" placeholder="${escH(it.ph || "")}" aria-label="${escH(it.ph || "이름")}"><button type="submit">${escH(it.ok || "확인")}</button></form>`
    : `<button type="button" role="menuitem" data-ci="${i}"${it.off ? " disabled" : ""}>${escH(it.t)}</button>`).join("")}</div>`;
  m.hidden = false;
  const box = $("rep").getBoundingClientRect(), w = m.offsetWidth, h = m.offsetHeight;
  m.style.left = `${Math.max(8, Math.min(x - box.left, box.width - w - 8))}px`;
  m.style.top = `${Math.max(8, Math.min(y - box.top, box.height - h - 8))}px`;
  m.querySelector("input, button:not([disabled])")?.focus();
}
const repCtxClose = () => { const m = $("rep-ctx"); if (m) m.hidden = true; REP.ctx = null; };
function repCtxReport(id, x, y) {
  const r = repById(id); if (!r) return;
  const gs = repLay().groups.filter(g => g !== r.group);
  repCtx(x, y, [{ h: r.name },
    ...(r.ready && !r.brief ? [{ t: r.compose ? "작성 창" : "옵션", fn: () => repOpOpen(id) }] : []),
    { t: "참고자료 · 메모 적기", fn: () => repMtOpen(id) },
    { t: "앞으로", fn: () => repStep(id, -1) }, { t: "뒤로", fn: () => repStep(id, 1) },
    { h: "폴더로 옮기기" }, ...gs.map(g => ({ t: `→ ${g}`, fn: () => repMove(id, g) })),
    { input: true, ph: "새 폴더 이름", ok: "만들어 옮기기", fn: v => { const l = repLay(); if (!l.groups.includes(v)) l.groups.push(v); l.place[id] = v; REP.g = v; repLaySave(l, `「${r.name}」 → 새 폴더 ${v}`); } }]);
}
function repCtxGroup(g, x, y) {
  const lay = repLay(), i = lay.groups.indexOf(g), n = (REP.d?.reports || []).filter(r => r.group === g).length, to = lay.groups[i ? 0 : 1] || "";
  repCtx(x, y, [{ h: `폴더 ${g}` },
    { input: true, value: g, ph: "폴더 이름", ok: "이름 바꾸기", fn: v => {
      if (v === g) return;
      if (lay.groups.includes(v)) return toast("같은 이름 폴더가 있다");
      lay.groups[i] = v; for (const k in lay.place) if (lay.place[k] === g) lay.place[k] = v;
      if (REP.g === g) REP.g = v;
      repLaySave(lay); } },
    { t: "왼쪽으로", off: i === 0, fn: () => { [lay.groups[i - 1], lay.groups[i]] = [lay.groups[i], lay.groups[i - 1]]; repLaySave(lay); } },
    { t: "오른쪽으로", off: i === lay.groups.length - 1, fn: () => { [lay.groups[i + 1], lay.groups[i]] = [lay.groups[i], lay.groups[i + 1]]; repLaySave(lay); } },
    { t: n ? `폴더 지우기 — 보고서 ${n}개는 「${to}」 로` : "폴더 지우기", off: lay.groups.length < 2, fn: () => {
      lay.groups.splice(i, 1); for (const k in lay.place) if (lay.place[k] === g) lay.place[k] = to;
      REP.g = to; repLaySave(lay, `폴더 ${g} 를 지웠다`); } },
    { h: "모두" },
    { t: "처음 모양으로(기본 폴더 · 차례)", fn: async () => { await fetch("/api/reports/layout", { method: "DELETE" }); REP.d = await getJson("/api/reports"); repDraw(); toast("처음 모양으로 돌렸다"); } }]);
}
function repCtxAdd(x, y) {
  repCtx(x, y, [{ h: "새 폴더" }, { input: true, ph: "폴더 이름(20자까지)", ok: "만들기", fn: v => {
    const l = repLay(); if (l.groups.includes(v)) return toast("같은 이름 폴더가 있다");
    l.groups.push(v); REP.g = v; repLaySave(l, `폴더 ${v} 를 만들었다 — 보고서를 끌어 놓거나 오른쪽 누름으로 옮긴다`); } }]);
}

/* 참고자료 · 메모 편집 창 */
function repMtOpen(id) { const m = repById(id)?.meta || {}; REP.mt = { id, refs: (m.refs || []).map(x => ({ ...x })), memo: m.memo || "" }; repMtDraw(); }
function repMtDraw() {
  const box = $("rep-mt"), M = REP.mt, r = M && repById(M.id);
  if (!box) return;
  if (!r) { box.hidden = true; return; }
  if (!M.refs.length) M.refs.push({ name: "", where: "" });
  box.hidden = false;
  box.innerHTML = `<div class="op mte" role="dialog" aria-modal="true" aria-labelledby="rep-mt-t" tabindex="-1">
    <div class="oh"><div><b id="rep-mt-t">${escH(r.name)} — 참고자료 · 메모</b><small class="mute">모두에게 같이 보인다 · 자세히 창 아래에 나온다</small></div>
      <button type="button" id="rep-mtx" aria-label="닫기 (Esc)" title="닫기 (Esc)">✕</button></div>
    <div class="ob"><fieldset class="sec"><legend>참고자료 — 무엇을 · 어디서</legend>
      ${M.refs.map((x, i) => `<div class="mtr"><input id="rep-mtn${i}" maxlength="80" value="${escH(x.name)}" placeholder="자료 이름 — 예) 산사태 위험도" aria-label="자료 이름 ${i + 1}">
        <input id="rep-mtw${i}" data-mtw="${i}" maxlength="120" value="${escH(x.where)}" placeholder="어디서 — 예) 산림청 산사태정보시스템" aria-label="어디서 ${i + 1}">
        <button type="button" data-mtdel="${i}" aria-label="${i + 1}번 줄 지우기" title="이 줄 지우기">✕</button></div>`).join("")}
      <button type="button" id="rep-mtadd">＋ 줄 더하기</button></fieldset>
      <fieldset class="sec"><legend>메모</legend><textarea id="rep-mtm" maxlength="2000" rows="6" placeholder="작성 요령 · 확인할 곳 · 주의할 점 — 예) 도로통제 숫자는 도로과 보고서와 맞춘다">${escH(M.memo)}</textarea></fieldset></div>
    <p class="msg" id="rep-mtmsg" role="status"></p>
    <div class="of"><span class="sp"></span><button type="button" id="rep-mtc">닫기</button><button type="button" id="rep-mts" class="pri">저장</button></div></div>`;
  box.querySelector(".op").focus();
}
function repMtRead() {
  const M = REP.mt;
  M.refs = M.refs.map((x, i) => ({ name: $(`rep-mtn${i}`)?.value ?? x.name, where: $(`rep-mtw${i}`)?.value ?? x.where }));
  M.memo = $("rep-mtm")?.value ?? M.memo;
}
async function repMtSave() {
  repMtRead();
  const M = REP.mt, body = { refs: M.refs.filter(x => x.name.trim()), memo: M.memo };
  try {
    const res = await fetch(`/api/reports/meta/${encodeURIComponent(M.id)}`, { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || `오류 ${res.status}`);
    REP.d = await getJson("/api/reports");
    REP.mt = null; REP.sel = M.id; toast("참고자료 · 메모를 저장했다"); repDraw();
  } catch (e) { $("rep-mtmsg").textContent = `저장하지 못했다 — ${e.message}`; $("rep-mtmsg").className = "msg bad"; }
}

/* 사건 — 메뉴 · 메모 창은 다른 처리보다 먼저(capture) */
$("rep").addEventListener("click", ev => {
  const t = ev.target;
  if (REP.swallow) { REP.swallow = false; ev.stopImmediatePropagation(); ev.preventDefault(); return; }   /* 길게 누른 뒤 손을 뗀 누름 */
  if (REP.ctx) {
    const b = t.closest("#rep-ctx button[data-ci]");
    if (b) { const it = REP.ctx[+b.dataset.ci]; repCtxClose(); it?.fn?.(); }
    else if (!t.closest("#rep-ctx")) repCtxClose();
    ev.stopImmediatePropagation(); return;
  }
  if (REP.mt) {
    if (t.id === "rep-mt" || t.closest("#rep-mtx, #rep-mtc")) { REP.mt = null; repMtDraw(); }
    else if (t.closest("#rep-mtadd")) { repMtRead(); REP.mt.refs.push({ name: "", where: "" }); repMtDraw(); $(`rep-mtn${REP.mt.refs.length - 1}`)?.focus(); }
    else if (t.closest("[data-mtdel]")) { repMtRead(); REP.mt.refs.splice(+t.closest("[data-mtdel]").dataset.mtdel, 1); repMtDraw(); }
    else if (t.closest("#rep-mts")) repMtSave();
    ev.stopImmediatePropagation(); return;
  }
  const mt = t.closest("[data-mt]");
  if (mt) { ev.stopImmediatePropagation(); return repMtOpen(mt.dataset.mt); }
  const add = t.closest("[data-gadd]");
  if (add) { ev.stopImmediatePropagation(); const b = add.getBoundingClientRect(); return repCtxAdd(b.left, b.bottom + 4); }
}, true);
$("rep").addEventListener("submit", ev => {
  const f = ev.target.closest("#rep-ctx form[data-ci]"); if (!f) return;
  ev.preventDefault();
  const it = REP.ctx?.[+f.dataset.ci], v = $("rep-ctx-in")?.value.trim();
  if (!v) return;
  repCtxClose(); it?.fn?.(v);
});
$("rep").addEventListener("contextmenu", ev => {
  if (REP.op || REP.mt) return;
  const tile = ev.target.closest("[data-id]"), g = ev.target.closest("[data-g]");
  if (!tile && !g) return;
  ev.preventDefault(); ev.stopImmediatePropagation();
  if (tile) repCtxReport(tile.dataset.id, ev.clientX, ev.clientY); else repCtxGroup(g.dataset.g, ev.clientX, ev.clientY);
}, true);
/* 휴대폰 — 길게 누르면 같은 메뉴(손가락을 떼는 누름은 삼킨다) */
let repLong = null;
$("rep").addEventListener("pointerdown", ev => {
  if (ev.pointerType === "mouse" || REP.op || REP.mt) return;
  const tile = ev.target.closest("[data-id]"), g = ev.target.closest("[data-g]");
  if (!tile && !g) return;
  const x = ev.clientX, y = ev.clientY;
  repLong = { x, y, t: setTimeout(() => { REP.swallow = true; if (tile) repCtxReport(tile.dataset.id, x, y); else repCtxGroup(g.dataset.g, x, y); }, 550) };
});
const repLongX = ev => { if (repLong && (ev.type !== "pointermove" || Math.hypot(ev.clientX - repLong.x, ev.clientY - repLong.y) > 10)) { clearTimeout(repLong.t); repLong = null; } };
["pointerup", "pointercancel", "pointermove"].forEach(k => $("rep").addEventListener(k, repLongX));
/* 끌어 놓기 — 폴더 탭 위: 그 폴더로 · 다른 보고서 위: 그 앞으로(폴더도 그 보고서 폴더로) */
$("rep").addEventListener("dragstart", ev => {
  const tile = ev.target.closest?.("[data-id]"); if (!tile) return;
  ev.dataTransfer.setData("text/x-rep", tile.dataset.id); ev.dataTransfer.effectAllowed = "move"; tile.classList.add("drag");
});
$("rep").addEventListener("dragend", ev => ev.target.closest?.("[data-id]")?.classList.remove("drag"));
$("rep").addEventListener("dragover", ev => {
  const to = ev.target.closest("[data-g], [data-id]"); if (!to || !ev.dataTransfer.types.includes("text/x-rep")) return;
  ev.preventDefault(); ev.dataTransfer.dropEffect = "move";
  $("rep").querySelectorAll(".dropto").forEach(e => e !== to && e.classList.remove("dropto")); to.classList.add("dropto");
});
$("rep").addEventListener("dragleave", ev => ev.target.closest?.(".dropto")?.classList.remove("dropto"));
$("rep").addEventListener("drop", ev => {
  const id = ev.dataTransfer.getData("text/x-rep"), g = ev.target.closest("[data-g]"), tile = ev.target.closest("[data-id]");
  $("rep").querySelectorAll(".dropto").forEach(e => e.classList.remove("dropto"));
  if (!id) return;
  ev.preventDefault();
  if (g) { if (g.dataset.g !== repById(id)?.group) repMove(id, g.dataset.g); return; }
  if (tile && tile.dataset.id !== id) repMove(id, repById(tile.dataset.id)?.group, tile.dataset.id);
});
document.addEventListener("keydown", ev => {
  if ($("rep").hidden || ev.key !== "Escape") return;
  if (REP.ctx) { ev.stopImmediatePropagation(); repCtxClose(); }
  else if (REP.mt) { ev.stopImmediatePropagation(); REP.mt = null; repMtDraw(); }
}, true);

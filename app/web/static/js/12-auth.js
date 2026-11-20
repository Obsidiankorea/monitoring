"use strict";
/* 로그인한 사람 — 계정 조작(로그아웃 · 계정 관리 · 시군 화면 · 화면 저장 · 파견 현황)은 설정(Ctrl+,) › 계정 탭.
   아래 왼쪽 띠는 시군 화면으로 보는 중 · 시연 · 계정 없는 서버의 '처음 설정' 안내만. 이 컴퓨터에서 켠 화면(로컬)은 띄우지 않는다 */
(async () => {
  let me;
  try { me = await getJson("/api/auth/me"); } catch { return; }
  const u = me?.user;
  if (u?.local) return;
  if (u?.demo) {                                         // 시연(8001) — 로그인 없이 도 사용자로. 로그아웃 · 파견 현황 없음
    const d = document.createElement("div");
    d.id = "who";
    d.innerHTML = "<span>시연 · 도 사용자</span>";
    document.body.appendChild(d);
    return;
  }
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const el = document.createElement("div");
  el.id = "who";
  if (me.open || !u) {                                     // 계정이 아직 없다 — 첫 관리자를 만들라는 안내(누르면 로그인 화면의 처음 설정)
    if (!me.open) return;
    el.innerHTML = `<span>로그인 없이 쓰는 중</span><a href="/login.html">처음 설정 — 관리자 만들기</a>`
      + `<a href="${SNAP_URL("/map.html")}">시연 화면</a>`;
    document.body.appendChild(el);
    return;
  }
  ACCT = { me, u, pend: 0, seen: 0 };
  // 계정 조작은 설정(Ctrl+,) › 계정 탭에 — 아래 띠는 '시군 화면으로 보는 중'일 때만(어느 화면인지 늘 보이게)
  if (AS_SIGUN) {
    el.innerHTML = `<b>${esc(AS_SIGUN)} 화면으로 보는 중</b><button type="button" id="who-back">도 화면으로</button>`;
    document.body.appendChild(el);
    $("who-back").addEventListener("click", () => acctAs(""));
  }
  viewAuto();
  if (u.role === "sigun" && u.sigun) lockSigun(u.sigun);
  if (u.role !== "sigun" && AS_SIGUN && (me.siguns || []).includes(AS_SIGUN)) lockSigun(AS_SIGUN);
  if (u.role === "admin") { acctPend(); setInterval(acctPend, 60e3); }
  tourAuto();                                             // 처음 들어온 계정이면 안내(13-tour.js)
})();

/* 설정 › 계정 탭 — 로그인한 사람 · 로그아웃 · 계정 관리(가입 신청 대기 빨간 표시) · 시군 화면으로 보기 · 내 화면 저장 · 바로 가기 */
let ACCT = null;
function acctPrefsHtml() {
  if (!ACCT) return "";
  const { me, u } = ACCT, V = window.GN_VIEW || {}, adm = u.role === "admin";
  return `<h4>계정</h4>
    <div class="row"><span class="k">로그인</span><span class="acct-me">${escH(u.name || u.login)} · ${escH(me.roles[u.role] || u.role)}${u.sigun ? ` · ${escH(u.sigun)}` : ""}</span>
      <span class="seg"><button type="button" data-acct="out">로그아웃</button></span></div>
    ${adm ? `<div class="row"><span class="k">계정 관리</span><span class="seg"><button type="button" data-acct="go" data-href="/admin.html">계정 관리 열기</button></span>
      ${ACCT.pend ? `<em class="acct-pend" role="status">● 가입 신청 ${ACCT.pend}건 — 승인 대기</em>` : `<span class="note">대기 중인 가입 신청 없음</span>`}</div>` : ""}
    ${u.role !== "sigun" ? `<div class="row"><span class="k">시군 화면</span><select id="acct-as" aria-label="시군 화면으로 보기">
        <option value="">${AS_SIGUN ? "도 화면으로" : "도 화면(지금)"}</option>${(me.siguns || []).map(x => `<option${x === AS_SIGUN ? " selected" : ""}>${escH(x)}</option>`).join("")}</select>
      <span class="note">그 시군 담당자가 보는 화면으로 — 자료 범위(연락처 등)는 내 계정 그대로</span></div>` : ""}
    <div class="row"><span class="k">내 화면</span><span class="seg"><button type="button" data-acct="save">지금 화면 저장</button>
      <button type="button" data-acct="load"${V.mine || V.def ? "" : " disabled"}>${V.mine ? "저장한 화면으로 되돌리기" : "처음 화면으로 되돌리기"}</button>
      ${adm ? `<button type="button" data-acct="def">모든 계정의 처음 화면으로</button>` : ""}</span></div>
    <div class="row"><span class="k"></span><span class="note">지도 · 층 · 창 위치 같은 화면은 계정마다 저절로 저장된다(2분마다 · 창을 닫거나 로그아웃할 때) — 어느 PC에서든 마지막 화면으로 시작. 연락처 잠금 번호는 저장하지 않는다.</span></div>
    <div class="row"><span class="k">처음 안내</span><span class="seg"><button type="button" data-acct="tour">처음 안내 다시 보기</button></span><span class="note">주요 기능을 한 단계씩 짚는 안내 — Esc 로 건너뛴다</span></div>
    <div class="row"><span class="k">바로 가기</span><span class="seg"><button type="button" data-acct="go" data-href="/posts.html">공지 · 요청</button><button type="button" data-acct="go" data-href="/board.html">파견 현황</button>
      <button type="button" data-acct="go" data-href="${escH(SNAP_URL("/map.html"))}">시연 화면</button></span></div>`;
}
function acctPrefsBind() {
  const box = $("prefs");
  if (!ACCT || !box.querySelector("[data-acct]")) return;
  [...box.querySelectorAll(".tabs button")].find(b => b.textContent === "계정")?.classList.toggle("alert", ACCT.pend > 0);
  box.querySelector("#acct-as")?.addEventListener("change", e => acctAs(e.target.value));
  box.querySelectorAll("[data-acct]").forEach(b => b.addEventListener("click", async () => {
    const v = b.dataset.acct;
    if (v === "go") return void (location.href = b.dataset.href);
    if (v === "out") {
      await viewSave(false);                              // 이 계정의 마지막 화면을 남기고 나간다
      try { await fetch("/api/auth/logout", { method: "POST" }); } catch {}
      return location.replace("/login.html");
    }
    if (v === "tour") { closePrefs(); return tourStart(); }
    viewAct(v);
  }));
}
/* 관리자 · 도 사용자 — 그 시군 담당자가 보는 화면으로(주소 ?as=창원). 빈 값이면 도 화면 */
function acctAs(sg) {
  const q = new URLSearchParams(location.search);
  sg ? q.set("as", sg) : q.delete("as");
  location.search = q.toString();
}
/* 관리자 — 가입 신청 대기를 1분마다 본다. 있으면 제목 옆 빨간 동그라미(도구를 숨겨도 보인다, 누르면 설정 › 계정) · 설정 단추에 빨간 점 ·
   설정 › 계정 탭에 빨간 글, 늘면 알림 */
async function acctPend() {
  let n;
  try { n = (await getJson("/api/auth/users")).users.filter(x => x.pending).length; } catch { return; }
  ACCT.pend = n;
  const b = $("b-prefs");
  b?.classList.toggle("alert", n > 0);
  b?.setAttribute("aria-label", n ? `설정 — 가입 신청 ${n}건 승인 대기` : "설정");
  if (b) b.title = n ? `설정 (Ctrl+,) — 가입 신청 ${n}건 승인 대기: 설정 › 계정` : "설정 (Ctrl+,)";
  const dot = $("acct-dot");
  if (dot) {
    dot.hidden = !n; dot.textContent = `● 가입 신청 ${n}`;
    dot.title = dot.ariaLabel = `가입 신청 ${n}건 승인 대기 — 눌러서 설정 › 계정`;
    dot.onclick = () => { PF_TAB = 0; openPrefs(); };   // 계정 탭이 맨 앞
  }
  if (n > ACCT.seen) toast(`가입 신청 ${n}건이 승인을 기다립니다 — 설정 › 계정 › 계정 관리`);
  ACCT.seen = n;
}

/* 관리자 · 도 사용자의 '시군 화면으로 보기' — 화면(고정 · 시군 밖 감추기)만 시군처럼. 자료 범위(연락처 등)는 관리자 그대로 */
const AS_SIGUN = new URLSearchParams(location.search).get("as");

/* 계정마다 마지막 화면 — 바꾼 것이 있으면 2분마다 · 창을 숨기거나 닫을 때 · 로그아웃할 때 계정에 저장(PUT /api/prefs).
   다음에 그 계정으로 들어오면 /api/prefs.js 가 그 화면으로 연다(다른 계정이 쓰던 브라우저여도). 연락처 잠금 번호는 빼고 */
const viewData = () => { const d = {}; try { for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k.startsWith("gn-") && k !== "gn-ct-pin") d[k] = localStorage.getItem(k); } } catch {} return d; };
let VIEW_SENT = null;
async function viewSave(leaving) {
  const data = viewData(), s = JSON.stringify(data);
  if (s === VIEW_SENT) return;
  const at = new Date().toISOString(), body = JSON.stringify({ data, at });
  if (leaving && body.length > 60000) return;            // 닫히는 중에는 64KB 까지만 보낼 수 있다(다음 2분 저장에 맡긴다)
  try {
    const r = await fetch("/api/prefs", { method: "PUT", headers: { "content-type": "application/json" }, body, keepalive: !!leaving });
    if (r.ok) { VIEW_SENT = s; try { localStorage.setItem("gnv-at", at); } catch {} }
  } catch {}
}
function viewAuto() {
  if (!window.GN_VIEW?.me) return;
  VIEW_SENT = JSON.stringify(viewData());                 // 연 그대로는 다시 보내지 않는다
  setInterval(() => viewSave(false), 120000);
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "hidden") viewSave(true); });
  addEventListener("pagehide", () => viewSave(true));
}

/* 화면 저장 · 되돌리기 — 설정 › 계정 › 내 화면. save 내 화면 · def 모든 계정의 처음 화면(관리자) · load 저장한 것으로 다시 열기 */
async function viewAct(v) {
  if (v === "load") {
    if (!confirm("이 브라우저의 화면 기억을 지우고 저장한 화면으로 다시 엽니다. 저장하지 않은 지금 화면은 사라집니다.")) return;
    try { for (const k of Object.keys(viewData())) localStorage.removeItem(k); } catch {}
    return location.reload();
  }
  if (v === "def" && !confirm("지금 화면을 모든 계정의 처음 화면으로 저장할까요? 화면을 따로 저장하지 않은 사람이 새 브라우저에서 열 때 이 화면으로 시작합니다.")) return;
  try {
    const at = new Date().toISOString(), data = viewData();
    const r = await fetch(v === "def" ? "/api/prefs/default" : "/api/prefs", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ data, at }) });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
    if (v !== "def") { VIEW_SENT = JSON.stringify(data); try { localStorage.setItem("gnv-at", at); } catch {} }
    toast(v === "def" ? "모든 계정의 처음 화면으로 저장했습니다" : "내 화면으로 저장했습니다 — 다른 PC에서도 이 화면으로 시작합니다");
  } catch (e) { toast(`저장하지 못했습니다 — ${e.message}`); }
}

/* 시군 사용자 — 그 시군에 고정(다른 시군은 어둡게 덮인 채 보기만). 고르기를 바꾸는 길(setSel)을 막아 어디서 불러도 그 시군으로 */
function lockSigun(sg) {
  SIGUN_LOCK = sg;
  const keep = setSel, pick = pickSig;
  setSel = () => keep([sg]);
  pickSig = (s, add) => {
    if (s && s !== sg) return toast(`${sg} 화면입니다 — 다른 시군은 흐리게 보기만 합니다`);
    return pick(s, add);
  };
  SET.sel_zoom = true;                                    // 시군 화면은 늘 확대(설정에는 남기지 않는다)
  const go = () => (FEAT && V ? keep([sg]) : setTimeout(go, 300));   // 지도 자료가 다 오면
  go();
}

"use strict";
/* 로그인한 사람 — 화면 아래 왼쪽 작은 띠(이름 · 역할 · 파견 현황 · 계정 관리 · 로그아웃).
   계정이 없는 서버면 '처음 설정' 안내만. 이 컴퓨터에서 켠 화면(로컬)은 띄우지 않는다 */
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
      + `<a href="${location.protocol}//${location.hostname}:8001/map.html">시연 화면</a>`;
    document.body.appendChild(el);
    return;
  }
  el.innerHTML = `<span>${esc(u.name || u.login)} · ${esc(me.roles[u.role] || u.role)}${u.sigun ? ` · ${esc(u.sigun)}` : ""}</span>`
    + `<a href="/board.html">파견 현황</a>`
    + `<a href="${location.protocol}//${location.hostname}:8001/map.html">시연 화면</a>`
    + (u.role === "admin" ? `<a href="/admin.html">계정 관리</a>` : "")
    + `<button type="button" id="who-out">로그아웃</button>`;
  document.body.appendChild(el);
  $("who-out").addEventListener("click", async () => {
    try { await fetch("/api/auth/logout", { method: "POST" }); } catch {}
    location.replace("/login.html");
  });
  if (u.role === "sigun" && u.sigun) lockSigun(u.sigun);
})();

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

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
      + `<a href="${SNAP_URL("/map.html")}">시연 화면</a>`;
    document.body.appendChild(el);
    return;
  }
  el.innerHTML = `<span>${esc(u.name || u.login)} · ${esc(me.roles[u.role] || u.role)}${u.sigun ? ` · ${esc(u.sigun)}` : ""}</span>`
    + `<a href="/board.html">파견 현황</a>`
    + `<a href="${SNAP_URL("/map.html")}">시연 화면</a>`
    + `<button type="button" id="who-view" aria-expanded="false" aria-controls="vw-pop">화면 저장</button>`
    + (u.role === "admin" ? `<a href="/admin.html">계정 관리</a>` : "")
    + `<button type="button" id="who-out">로그아웃</button>`;
  document.body.appendChild(el);
  viewMenu(u);
  $("who-out").addEventListener("click", async () => {
    try { await fetch("/api/auth/logout", { method: "POST" }); } catch {}
    location.replace("/login.html");
  });
  if (u.role === "sigun" && u.sigun) lockSigun(u.sigun);
})();

/* 화면 저장 — 이 브라우저의 화면 기억(gn-*)을 계정에. 새 PC · 새 주소에서는 저장한 것으로 시작(/api/prefs.js) */
function viewMenu(u) {
  const V = window.GN_VIEW || {}, b = $("who-view");
  const pop = document.createElement("div");
  pop.id = "vw-pop"; pop.hidden = true; pop.setAttribute("role", "dialog"); pop.setAttribute("aria-label", "화면 저장");
  pop.innerHTML = `<p>지도 · 층 · 창 위치 같은 지금 화면을 계정에 저장합니다. 다른 PC나 새 주소에서 로그인하면 이 화면으로 시작합니다.</p>
    <button type="button" data-v="save" class="pri">지금 화면을 내 화면으로 저장</button>
    <button type="button" data-v="load"${V.mine || V.def ? "" : " disabled"}>${V.mine ? "저장한 내 화면으로 되돌리기" : "처음 화면으로 되돌리기"}</button>
    ${u.role === "admin" ? `<button type="button" data-v="def">지금 화면을 모든 계정의 처음 화면으로</button>` : ""}
    <small>연락처 잠금 번호는 저장하지 않습니다.</small>`;
  document.body.appendChild(pop);
  const show = on => { pop.hidden = !on; b.setAttribute("aria-expanded", String(on)); if (on) pop.querySelector("button:not([disabled])").focus(); else b.focus(); };
  const mine = () => { const d = {}; try { for (let i = 0; i < localStorage.length; i++) { const k = localStorage.key(i); if (k.startsWith("gn-") && k !== "gn-ct-pin") d[k] = localStorage.getItem(k); } } catch {} return d; };
  b.addEventListener("click", () => show(pop.hidden));
  pop.addEventListener("keydown", ev => { if (ev.key === "Escape") show(false); });
  document.addEventListener("pointerdown", ev => { if (!pop.hidden && !ev.target.closest("#vw-pop, #who-view")) { pop.hidden = true; b.setAttribute("aria-expanded", "false"); } });
  pop.addEventListener("click", async ev => {
    const v = ev.target.closest("[data-v]")?.dataset.v; if (!v) return;
    if (v === "load") {
      if (!confirm("이 브라우저의 화면 기억을 지우고 저장한 화면으로 다시 엽니다. 저장하지 않은 지금 화면은 사라집니다.")) return;
      try { for (const k of Object.keys(mine())) localStorage.removeItem(k); } catch {}
      return location.reload();
    }
    if (v === "def" && !confirm("지금 화면을 모든 계정의 처음 화면으로 저장할까요? 화면을 따로 저장하지 않은 사람이 새 브라우저에서 열 때 이 화면으로 시작합니다.")) return;
    try {
      const r = await fetch(v === "def" ? "/api/prefs/default" : "/api/prefs", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ data: mine() }) });
      if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
      toast(v === "def" ? "모든 계정의 처음 화면으로 저장했습니다" : "내 화면으로 저장했습니다 — 다른 PC에서도 이 화면으로 시작합니다");
      show(false);
    } catch (e) { toast(`저장하지 못했습니다 — ${e.message}`); }
  });
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

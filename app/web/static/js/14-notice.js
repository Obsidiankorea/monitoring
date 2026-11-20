"use strict";
/* 공지 팝업 — 관리자가 '팝업'으로 올린 공지(posts.html)를 지도를 열 때 한 번. '확인'하면 그 공지는 다시 뜨지 않는다
   (gn-notice-seen — gn-* 라 계정 화면 저장에 따라가 다른 PC 에서도). 처음 안내(13-tour)가 떠 있으면 끝난 뒤에 */
async function noticePop() {
  if (window.GN_SNAP || CASE) return;
  let rows;
  try { rows = (await getJson("/api/posts/popup")).rows || []; } catch { return; }
  let seen = [];
  try { seen = JSON.parse(localStorage.getItem("gn-notice-seen") || "[]"); } catch {}
  const fresh = rows.filter(r => !seen.includes(r.id));
  if (!fresh.length) return;
  if ($("tour")) return void setTimeout(noticePop, 3000);
  const back = document.activeElement, box = document.createElement("div");
  box.id = "notice";
  box.innerHTML = `<div class="nt-card" role="dialog" aria-modal="true" aria-labelledby="nt-h">
      <div class="nt-top"><b id="nt-h">공지${fresh.length > 1 ? ` ${fresh.length}건` : ""}</b><span class="sp"></span><button type="button" data-n="x" aria-label="닫기">✕</button></div>
      ${fresh.map(r => `<section><h3>${escH(r.title)}</h3><div class="nt-meta">${escH(r.created)}</div>${r.body ? `<p>${escH(r.body)}</p>` : ""}</section>`).join("")}
      <div class="nt-bt"><a href="/posts.html">공지 · 요청 게시판</a><span class="sp"></span><button type="button" class="pri" data-n="ok">확인 — 다시 보지 않기</button></div></div>`;
  document.body.appendChild(box);
  const close = keep => {
    if (!keep) { try { localStorage.setItem("gn-notice-seen", JSON.stringify([...seen, ...fresh.map(r => r.id)].slice(-50))); } catch {} }
    box.remove(); back?.focus?.();
  };
  box.addEventListener("click", e => { const a = e.target.closest("[data-n]")?.dataset.n; if (a) close(a === "x"); });
  box.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation(); close(true); } });
  box.querySelector('[data-n="ok"]').focus();
}
setTimeout(noticePop, 1500);

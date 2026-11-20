"use strict";
/* 처음 안내(튜토리얼) — 계정으로 처음 들어오면 한 번. 단계마다 그 단추 · 칸을 밝히고 짧게 설명한다.
   건너뛰기(Esc) · 이전(←) · 다음(→ · Enter). 끝내거나 건너뛰면 gn-tour=done — gn-* 이라 계정 화면 저장에 따라가 다른 PC 에서도 다시 안 뜬다.
   다시 보기: 설정 › 계정 › 처음 안내. 대상이 화면에 없으면(패널을 끈 경우 등) 그 단계는 건너뛴다 */
const TOUR = [
  { t: "경남 강수 지도에 오신 것을 환영합니다", d: "자주 쓰는 기능을 1분 안에 짚어 드립니다. 언제든 <b>건너뛰기</b>(Esc)로 닫을 수 있고, 설정 › 계정 › <b>처음 안내 다시 보기</b>로 다시 볼 수 있습니다." },
  { el: "#ttl", t: "지도 층 고르기", d: "제목을 누르면 지도에 그릴 자료를 고릅니다 — 실측(누적 · 1시간) · 예측(초단기 · 단기). 숫자 키 <kbd>1</kbd>~<kbd>6</kbd>, 자료 기준(AWS ↔ 격자)은 <kbd>B</kbd>." },
  { el: "#ly-btn", t: "레이어 — 지도 위에 겹치기", d: "기상특보 윤곽 · 관측소 · 인명피해 우려지역 지구 · 하천 · 산사태취약지역 같은 것을 켜고 끕니다. 특보 <kbd>A</kbd>, 관측소 <kbd>S</kbd>." },
  { el: "#legend", t: "지도 색 · 눈금", d: "범례 색 띠를 <b>누르면</b> 색 묶음이 바뀝니다(파랑 · 기상청 · 다양한 색조). <b>오른쪽 클릭</b>하면 누적 눈금을 고정해 시각끼리 같은 자로 견줄 수 있습니다." },
  { t: "어둡게 · 밝게", d: "화면 밝기를 바로 바꿔 보세요. 나중에는 설정(<kbd>Ctrl</kbd>+<kbd>,</kbd>) › 화면 › 테마에서 바꿉니다.", theme: true },
  { el: "#c-acc", t: "오른쪽 위 — 강수 누적", d: "시군별 누적 강수 순위입니다. 제목을 누르면 기준이 <b>AWS 관측소 ↔ 격자(500m)</b>로 바뀌고, 구간(지난 몇 시간 · 날짜부터)은 설정 › 오른쪽 패널에서. 줄을 누르면 그 시군을 지도에서 고릅니다." },
  { el: "#c-now", t: "지금 오는 비 · 예측 상위", d: "<b>지금 오는 비</b>는 기상청 매분자료로 막 내리는 곳, <b>예측 상위</b>는 초단기예보 앞으로 6시간 많이 올 곳입니다. 패널 전체는 <kbd>L</kbd>로 켜고 끕니다." },
  { el: "#stage", t: "지도 누르기", d: "<b>시군</b>을 누르면 고르고 확대해 읍면동까지 봅니다(Ctrl+클릭은 여러 시군). 우려지역 <b>지구 동그라미</b>를 누르면 지구 카드 — 단계 그래프 · 담당 · <b>✉ 문자 내역</b>. 지구를 오른쪽 클릭하면 상황판단 모드." },
  { el: "#mode", t: "강수 ↔ 폭염", d: "이 단추로 폭염 화면(시군 기온 · 체감 · 폭염특보)과 강수 화면을 오갑니다." },
  { el: "#b-rep", t: "보고서", d: "기상 · 일일 · 풍수해 · 긴급상황보고 한글 파일을 받습니다. 창을 닫아도 계속 만들고, 오른쪽 위 띠에 진행이 보입니다. 기상청이 느린 자료는 빼고 만들고 무엇이 빠졌는지 알려 줍니다." },
  { el: "#b-sj", t: "상황판단 모드", d: "고른 시군의 대피 기준 도달 % · 도달 예상 시각 · 결정 기록 · 현장 회신을 한 화면에 모읍니다(<kbd>X</kbd>)." },
  { el: "#b-ai", t: "AI 상황판단", d: "특보 · 비 · 기준 · 현장 조치를 묶어 할 일과 살펴볼 곳을 정리하고, 질문에도 답합니다(<kbd>I</kbd>). 결정은 늘 권한자 몫입니다." },
  { el: "#b-help", t: "도움말", d: "용어 · 자료 출처 · 단축키를 봅니다(<kbd>?</kbd>). 이름 옆 ⓘ 에 마우스를 올려도 설명이 나옵니다." },
  { el: "#b-prefs", t: "설정 · 계정", d: "재생 · 패널 · 테마 같은 설정과 <b>계정</b>(로그아웃 · 내 화면 저장 · 시군 화면으로 보기 · 처음 안내 다시 보기)이 여기 있습니다. 화면은 계정마다 저절로 저장됩니다." },
];
let TOUR_I = -1, TOUR_BACK = null;
function tourAuto() {
  if (window.GN_SNAP || CASE) return;
  try { if (localStorage.getItem("gn-tour") === "done") return; } catch { return; }
  const go = (n = 0) => (FEAT && V) || n > 20 ? tourStart() : setTimeout(() => go(n + 1), 500);   // 지도가 그려진 뒤
  go();
}
const tourEl = s => { const e = s && document.querySelector(s); if (!e) return null; const r = e.getBoundingClientRect(); return r.width && r.height ? e : null; };
function tourStart() {
  if ($("tour")) return;
  if (!$("prefs").hidden) closePrefs();
  TOUR_BACK = document.activeElement;
  const box = document.createElement("div");
  box.id = "tour";
  box.innerHTML = `<div class="tr-ring" aria-hidden="true"></div>
    <div class="tr-card" role="dialog" aria-modal="false" aria-labelledby="tr-t" aria-describedby="tr-d">
      <div class="tr-n"></div><h3 id="tr-t"></h3><p id="tr-d"></p><div class="tr-th" hidden></div>
      <div class="tr-bt"><button type="button" data-tr="skip">건너뛰기</button><span class="sp"></span>
        <button type="button" data-tr="prev">이전</button><button type="button" data-tr="next" class="pri">다음</button></div></div>`;
  document.body.appendChild(box);
  document.body.classList.add("tour-on");                // 오른쪽 위 도구가 숨김 · 자동이어도 안내하는 동안은 보이게
  box.addEventListener("click", ev => {
    const a = ev.target.closest("[data-tr]")?.dataset.tr, th = ev.target.closest("[data-th]")?.dataset.th;
    if (th) { setTheme(th); return tourShow(TOUR_I); }
    if (a === "skip") tourEnd();
    else if (a === "prev") tourShow(TOUR_I - 1, -1);
    else if (a === "next") TOUR_I >= TOUR.length - 1 ? tourEnd() : tourShow(TOUR_I + 1);
  });
  document.addEventListener("keydown", tourKey, true);
  addEventListener("resize", tourPlace);
  tourShow(0);
}
function tourKey(ev) {
  if (!$("tour")) return;
  const k = { Escape: "skip", ArrowLeft: "prev", ArrowRight: "next" }[ev.key] || (ev.key === "Enter" && !ev.target.closest?.("#tour button") ? "next" : null);
  if (!k) return;
  ev.preventDefault(); ev.stopPropagation();             // 지도 단축키(← → 한 장씩 등)로 새지 않게
  $("tour").querySelector(`[data-tr="${k}"]`).click();
}
function tourShow(i, dir = 1) {
  while (i >= 0 && i < TOUR.length && TOUR[i].el && !tourEl(TOUR[i].el)) i += dir;   // 화면에 없는 대상은 건너뛴다
  if (i < 0) i = 0;
  if (i >= TOUR.length) return tourEnd();
  TOUR_I = i;
  const s = TOUR[i], box = $("tour"), th = document.documentElement.dataset.theme;
  box.querySelector(".tr-n").textContent = `${i + 1} / ${TOUR.length}`;
  box.querySelector("#tr-t").textContent = s.t;
  box.querySelector("#tr-d").innerHTML = s.d;
  const tb = box.querySelector(".tr-th");
  tb.hidden = !s.theme;
  tb.innerHTML = s.theme ? [["dark", "어둡게"], ["gray", "회색"], ["light", "밝게"]].map(([v, l]) => `<button type="button" data-th="${v}" aria-pressed="${th === v}">${l}</button>`).join("") : "";
  box.querySelector('[data-tr="prev"]').disabled = i === 0;
  box.querySelector('[data-tr="next"]').textContent = i === TOUR.length - 1 ? "끝" : "다음";
  tourPlace();
  box.querySelector('[data-tr="next"]').focus();
}
/* 밝히는 고리는 대상 둘레, 설명 카드는 대상 아래(모자라면 위 · 옆) — 화면 밖으로 나가지 않게 */
function tourPlace() {
  const box = $("tour"); if (!box) return;
  const ring = box.querySelector(".tr-ring"), card = box.querySelector(".tr-card"), e = tourEl(TOUR[TOUR_I]?.el);
  const W = innerWidth, H = innerHeight, cw = card.offsetWidth, ch = card.offsetHeight, g = 12;
  if (!e) { ring.hidden = true; card.style.left = `${(W - cw) / 2}px`; card.style.top = `${Math.max(16, (H - ch) / 2)}px`; return; }
  const r = e.getBoundingClientRect(), p = 6;
  ring.hidden = false;
  Object.assign(ring.style, { left: `${r.left - p}px`, top: `${r.top - p}px`, width: `${r.width + 2 * p}px`, height: `${r.height + 2 * p}px` });
  let top = r.bottom + p + g, left = r.left + r.width / 2 - cw / 2;
  if (top + ch > H - 8) top = r.top - p - g - ch;                          // 아래가 모자라면 위
  if (top < 8) { top = Math.min(H - ch - 8, Math.max(8, r.top)); left = r.right + p + g + cw < W ? r.right + p + g : r.left - p - g - cw; }   // 위도 모자라면 옆
  card.style.left = `${Math.max(8, Math.min(W - cw - 8, left))}px`;
  card.style.top = `${Math.max(8, Math.min(H - ch - 8, top))}px`;
}
function tourEnd() {
  $("tour")?.remove();
  document.body.classList.remove("tour-on");
  document.removeEventListener("keydown", tourKey, true);
  removeEventListener("resize", tourPlace);
  TOUR_I = -1;
  try { localStorage.setItem("gn-tour", "done"); } catch {}
  if (typeof viewSave === "function" && window.GN_VIEW?.me) viewSave(false);   // 계정에 바로 — 다른 PC 에서도 다시 안 뜨게
  TOUR_BACK?.focus?.();
}

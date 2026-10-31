"use strict";
/* ── 설정(Ctrl+,) — 서버에 둔다(어느 PC 에서 열어도 같게) ─────────────────── */
/* 설정을 탭으로 — 머리글(h4)마다 한 탭. 길어서 화면 밖으로 잘리던 것을 나눈다. 고른 탭은 기억한다 */
let PF_TAB = 0;
function prefTabs() {
  const box = $("prefs").querySelector(".box"), top = box.querySelector(".top");
  const panes = [];
  let cur = null;
  // 머리글 아홉 개를 네 탭으로 — 탭이 많아 글자가 꺾이던 것을 묶는다(머리글은 탭 안의 소제목으로 남는다)
  const GROUP = { "재생": "화면", "오른쪽 패널": "화면", "화면": "화면", "관측소": "자료", "API 절약": "자료",
                  "AI 알림": "AI", "AI 위키": "AI", "API 키": "시스템", "업데이트": "시스템", "데모": "시스템" };
  for (const el of [...box.children]) {
    if (el === top) continue;
    if (el.tagName === "H4") {
      const g = GROUP[el.textContent] || el.textContent;
      cur = panes.find(x => x[0] === g)?.[1];
      if (!cur) { cur = document.createElement("div"); cur.className = "pane"; panes.push([g, cur]); }
      cur.appendChild(el);
      continue;
    }
    if (cur) cur.appendChild(el);
  }
  if (PF_TAB >= panes.length) PF_TAB = 0;
  const bar = document.createElement("div");
  bar.className = "tabs";
  bar.innerHTML = panes.map(([t], i) => `<button data-tab="${i}" class="${i === PF_TAB ? "on" : ""}">${t}</button>`).join("");
  const body = document.createElement("div");
  body.className = "panes";
  panes.forEach(([, el], i) => { el.hidden = i !== PF_TAB; body.appendChild(el); });
  top.after(bar, body);
  bar.onclick = ev => {
    const b = ev.target.closest("[data-tab]");
    if (!b) return;
    PF_TAB = +b.dataset.tab;
    bar.querySelectorAll("button").forEach((x, i) => x.classList.toggle("on", i === PF_TAB));
    panes.forEach(([, el], i) => { el.hidden = i !== PF_TAB; });
    if (panes[PF_TAB][1].querySelector("#pf-upd")) loadUpd(true);   // 탭을 열 때마다 GitHub 를 다시 본다(종합 화면과 같다)
  };
  // 업데이트 탭에서 다시 열면 — 처음이면 확인, 아니면 기억해 둔 것을 그대로(설정을 바꿀 때마다 GitHub 를 부르지 않게)
  if (panes[PF_TAB]?.[1].querySelector("#pf-upd") && !UPD.pc && !UPD.loading) loadUpd(true);
}
function openPrefs() {
  if (QCFG_AHEAD === null && !openPrefs.busy) {          // 이미지 길이는 수집 설정 — 처음 열 때 읽어 다시 그린다
    openPrefs.busy = true;
    loadQcfg().then(() => { openPrefs.busy = false; if (QCFG_AHEAD !== null && !$("prefs").hidden) openPrefs(); });
  }
  stopPlay();
  // 고를 것이 4개 이상이면 한 칸짜리 드롭다운 — 가로 칸을 덜 차지한다
  const seg = (key, opts) => opts.length >= 4
    ? `<select class="seg-sel" data-k="${key}">${opts.map(([v, l]) =>
      `<option value="${v}"${String(SET[key]) === String(v) ? " selected" : ""}>${l}</option>`).join("")}</select>`
    : `<span class="seg">${opts.map(([v, l]) =>
      `<button data-k="${key}" data-v="${v}" class="${String(SET[key]) === String(v) ? "on" : ""}">${l}</button>`).join("")}</span>`;
  const th = document.documentElement.dataset.theme;
  $("prefs").innerHTML = `<div class="box" role="dialog" aria-label="설정">
    <div class="top"><b>설정 — 경남 지도</b><span class="sp"></span><button id="pf-x" title="닫기 (Esc)">✕</button></div>
    <h4>재생</h4>
    <div class="grid2">
    <div class="row"><span class="k">실측 간격</span>${seg("flow_step", [[10, "10분"], [20, "20분"], [30, "30분"], [60, "1시간"]])}</div>
    <div class="row wide"><span class="k"></span><span class="note">예측(초단기)은 1시간 간격뿐이다 — 10분 대상시각을 주면 가까운 정시 격자가 온다.
      자료가 AWS 면 실측도 정시마다(경남 AWS 가 정시 자료다) — 이 간격은 격자에만 걸린다.</span></div>
    <div class="row"><span class="k">지난 시간</span>${seg("flow_hours", [[1, "1시간"], [3, "3시간"], [6, "6시간"], [12, "12시간"]])}</div>
    <div class="row"><span class="k">AWS 실시간</span>${seg("aws_live", [[false, "끔 — 정시마다"], [true, "감시 — 1분마다"]])}</div>
    <div class="row wide"><span class="k"></span><span class="note">감시를 켜면 AWS 누적 · 1시간이 마지막 정시 뒤 매분자료까지 1분마다 따라간다(1시간은
      그 분의 직전 60분, 기상청 AWS). 켠 동안만 매분자료를 1분마다 받는다. 층 메뉴 실측 머리의 '실시간' · R 키와 같다.</span></div>
    <div class="row"><span class="k">지도 빠르기</span>${seg("play_ms", [[3000, "아주 느리게"], [2000, "느리게"], [1200, "보통"], [600, "빠르게"], [400, "아주 빠르게"]])}</div>
    <div class="row"><span class="k">초단기예측 이미지</span>${seg("qpf_ms", [[1500, "아주 느리게"], [1000, "느리게"], [600, "보통"], [400, "빠르게"], [250, "아주 빠르게"]])}</div>
    <div class="row"><span class="k">이미지 길이</span><select class="seg-sel" id="pf-ahead">${[180, 240, 300, 360].map(v =>
      `<option value="${v}"${QCFG_AHEAD === v ? " selected" : ""}>${v / 60}시간</option>`).join("")}</select></div>
    <div class="row wide"><span class="k"></span><span class="note">한 장 머무는 시간 — 지도 3 · 2 · 1.2 · 0.6 · 0.4초, 초단기예측 이미지(오른쪽 아래, Q) 1.5 · 1 · 0.6 · 0.4 · 0.25초.
      지도를 재생하는 동안은 이미지가 지도와 같은 시각으로 가므로 지도 빠르기를 따른다.
      이미지 길이는 수집 설정(종합 화면 '최대 선행시간'과 같다) — 다음 발표분부터 그만큼 받는다(6시간이면 3시간의 두 배를 부른다).</span></div>
    </div>
    <h4>오른쪽 패널</h4>
    <div class="grid2">
    <div class="row"><span class="k">표시</span>${seg("tl_on", [[true, "켬"], [false, "끔"]])}</div>
    <div class="row"><span class="k">방식</span>${seg("panel", [["cards", "카드 — 종합 화면 판"], ["timeline", "타임라인 — 시군 선"]])}</div>
    <div class="row"><span class="k">누적 구간</span><select class="seg-sel" id="pf-rng">${RNG_OPTS.map((o, i) =>
      `<option value="${i}"${rngOn(o) ? " selected" : ""}>${o[2].replace("지난 ", "")}</option>`).join("")}</select></div>
    <div class="row wide"><span class="k">날짜 지정</span><span class="dp">${datePick("pf-date")}<button type="button" data-a="date">부터</button></span>
      ${SET.acc_from === "date" ? `<span class="note">지금 ${accSpan().label}</span>` : ""}</div>
    <div class="row wide"><span class="k"></span><span class="note">AWS · 격자 누적을 그날 그 시각부터 — 오늘부터 ${ACC_DATE_DAYS}일 앞까지(예: 어제 18시부터 지금까지).
      지도 누적 층 · 강수 누적 카드가 같이 바뀐다. 격자는 빠진 정각을 10분마다 4장씩 메운다(그동안 합은 하한).</span></div>
    <div class="row"><span class="k">타임라인 값</span>${seg("tl_stat", [["max", "시군 최대"], ["mean", "시군 평균"]])}</div>
    </div>
    <h4>화면</h4>
    <div class="row"><span class="k">테마</span><span class="seg">
      <button data-th="dark" class="${th === "dark" ? "on" : ""}">어둡게</button>
      <button data-th="gray" class="${th === "gray" ? "on" : ""}">회색</button>
      <button data-th="light" class="${th === "light" ? "on" : ""}">밝게</button></span></div>
    <div class="row"><span class="k">예비특보</span>${seg("al_pre", [[true, "보이기"], [false, "숨기기"]])}<span class="note">왼쪽 특보 줄 — 머리 밑 '예비' 체크와 같다</span></div>
    <div class="row"><span class="k">바다 격자</span>${seg("sea_grid", [["full", "그대로"], ["dim", "흐리게"], ["off", "끔"]])}</div>
    <div class="row"><span class="k"></span><span class="note">경남 · 부산 · 울산 땅 밖(바다 · 그 너머) 칸을 옅게 — 땅 · 바다가 갈리게. 흐리게는 다가오는 비 띠가 보일 만큼(35%).</span></div>
    <div class="grid2">
    <div class="row"><span class="k">바다 위젯</span>${seg("sea_w", [["off", "끔"], ["fc", "예측 상위"], ["now", "지금 오는 비"], ["avg", "시군 평균"]])}</div>
    <div class="row"><span class="k">위젯 돌리기</span>${seg("sea_rot", [[0, "끔"], [10, "10초"], [15, "15초"], [20, "20초"], [30, "30초"], [60, "1분"]])}</div>
    <div class="row"><span class="k">위젯 예측</span>${seg("sea_per", [[1, "시군당 1곳"], [2, "시군당 2곳"]])}</div>
    </div>
    <div class="row"><span class="k"></span><span class="note">지도 위 반투명 판(W) — 경남 땅을 가장 적게 덮는 빈자리를 스스로 찾는다(좁고 길면 세로로 길쭉하게).
      머리를 끌어 옮기면 마지막으로 놓은 자리가 이 화면의 기본 자리(두 번 누르면 다시 자동), ⇔ · ⇕ 로 꼴을 바꾼다.
      예측 상위 · 지금 오는 비는 오른쪽 패널(카드)과 같은 자료. 특보는 왼쪽 특보 줄에.
      시군 평균은 지금 지도 층의 시군 면 평균(지도를 따른다). 돌리기는 세 탭을 그 간격으로 차례로(화면 재생과 따로) · 시군당 2곳은 한 시군의 비 많은 읍면동 둘(위젯 위 오른쪽 클릭으로도).</span></div>
    <div class="row"><span class="k">지도 위치</span><span class="seg"><button data-cam="edit">고치기 (C)</button><button data-cam="reset"${ucOn() ? "" : " disabled"}>처음대로</button></span>
      <span class="note">${ucOn() ? `${Math.round(UC.z * 100)}% · 옮김` : "경남 전체가 꼭 차게(기본)"}</span></div>
    <div class="row"><span class="k">화면 재생</span><span class="seg"><button data-show="open">재생목록…</button><button data-show="play">${SHOW.on ? "끝" : "재생 ▶"}</button></span>
      <span class="note">여러 화면을 차례로(화면보호기처럼) — P · 오른쪽 위 화면 단추. 목록 ${showLists().length}개</span></div>
    <div class="row"><span class="k">지도 색</span><span class="seg">${["blue", "kma", "rich"].map(p => `<button data-pal="${p}" class="${PAL === p ? "on" : ""}">${PAL_NAME[p]}</button>`).join("")}</span></div>
    <div class="row"><span class="k"></span><span class="note">범례 색 띠를 눌러도 차례로 바뀐다. 다양한 색조 — 기상청 QPF 범례 색을 다 써 한 색에 서너 색조, 누적은 스무 칸 남짓 · 끝 눈금이 자료를 바짝 따른다.</span></div>
    <div class="row"><span class="k">누적 눈금</span>${seg("acc_scale", [[0, "자동"], ...Object.keys(ACC_FIXED).map(v => [v, v + "㎜"])])}</div>
    <div class="row"><span class="k"></span><span class="note">AWS · 격자 누적 범례 — 자동은 자료 크기에 맞춰 자를 바꾼다. 고정하면 시각끼리 · 화면끼리 같은 자로 견준다. 범례를 오른쪽 클릭해도 고른다.</span></div>
    <div class="row"><span class="k">시군 누르면</span>${seg("sel_zoom", [[true, "확대 — 읍면동 경계·이름"], [false, "테두리만"]])}</div>
    <div class="row"><span class="k">오른쪽 위 도구</span><span class="seg">${[["show", "항상"], ["auto", "마우스를 움직이면"], ["hide", "숨김"]]
      .map(([v, l]) => `<button data-tools="${v}" class="${TOOLS === v ? "on" : ""}">${l}</button>`).join("")}</span></div>
    <div class="row"><span class="k"></span><span class="note">패널 · 도움말 · 설정 — 숨겨도 제목 메뉴 아래와 단축키(L · ? · Ctrl+,)로 연다.</span></div>
    <h4>관측소</h4>
    <div class="row"><span class="k">경남 AWS(내부망)</span>${seg("gn_off", [[false, "쓴다"], [true, "끈다"]])}</div>
    <div class="row"><span class="k"></span><span class="note">끄면 스방 수집을 멈추고, 면(AWS 누적 · 1시간) · 강수 누적 카드 · 지금 오는 비에서 경남 AWS 를 모두 뺀다 — 기상청 AWS 만 쓴다.
      내부망 밖(집 · 서버)에서 스방에 닿지 않을 때, 또는 내부망에서도 경남 AWS 값을 빼고 보고 싶을 때. 한 곳씩 빼는 것은 아래 비활성 AWS.</span></div>
    <div class="row"><span class="k">비활성 AWS</span><span class="note">${offList().length ? `${offList().length}곳 — 면(AWS 누적 · 1시간) · 강수 누적 카드 · 지금 오는 비(종합 화면도)에서 뺐다.` : "없음."}
      지도에서 관측소(S)를 켜고 점을 오른쪽 클릭 → 비활성화. 주변과 동떨어진 값(고장 · 막힘)을 빼고 둘레 관측소로 면을 다시 메운다.</span></div>
    ${offList().map(x => `<div class="row"><span class="k">${x.sigun}</span><span class="offnm">${x.name}<small>${x.org === "gn" ? "경남 AWS" : `기상청 ${x.id}`}</small></span>
      <button class="pf-on" data-id="${x.id}">다시 켜기</button></div>`).join("")}
    ${offList().length > 1 ? `<div class="row"><span class="k"></span><button class="pf-on" data-id="*">모두 다시 켜기</button></div>` : ""}
    <h4>API 절약</h4>
    <div class="row"><span class="note">기상청을 부르는 간격을 늘려 호출량을 줄인다. 켜면 <b>수집 주기가 n분보다 짧은 자료</b>(특보 · 매분자료 · 초단기예측 이미지 등 1분짜리)를 n분마다로 늦추고,
      이미 n분보다 긴 자료(10분짜리 등)는 그대로 둔다. 화면 갱신 주기와는 다르다 — 이건 실제로 부르는 횟수다. 이 서버에만 적용(서버와 PC 가 따로 부른다).</span></div>
    <div class="row"><span class="k">절약 모드</span><span class="seg"><button id="pf-sv-off" type="button">끔</button><button id="pf-sv-on" type="button">켬</button></span></div>
    <div class="row"><span class="k">조회 간격</span><span class="seg" id="pf-sv-min">${[1, 3, 5, 10, 15, 30].map(m => `<button type="button" data-m="${m}">${m}분</button>`).join("")}</span>
      <input id="pf-sv-n" type="number" min="1" max="60" style="width:64px;font:inherit" title="직접 입력(1~60분)"><span class="note">분</span><button id="pf-sv-go" type="button">적용</button></div>
    <div class="row"><span class="k">특보도</span><span class="seg"><button id="pf-sv-al0" type="button">그대로 1분</button><button id="pf-sv-al1" type="button">같이 늦춤</button></span></div>
    <div class="row"><span class="k"></span><span class="note">특보는 발표 리듬이 없고 늦으면 안 되므로 기본은 늦추지 않는다.</span></div>
    <div class="row"><span class="note" id="pf-sv-st">읽는 중…</span></div>
    <h4>API 키</h4>
    <div class="row"><span class="note">서버의 <code>config/api_keys.txt</code> 에 쓰고 바로 쓴다(재시작 불필요) — 저장소(git)에는 올라가지 않는다. 값은 다시 보여 주지 않고 끝 네 글자만 보인다.
      비우고 저장하면 그 키를 지운다. 시연 서버에서는 바꾸지 못한다.</span></div>
    <div id="pf-keys"><div class="row"><span class="note">읽는 중…</span></div></div>
    <h4>업데이트</h4>
    <div class="row"><span class="note">종합 화면 설정 › 업데이트와 같다 — 지도 창만 띄워 둔 화면에서도 여기서 받는다. 배포처는 GitHub 하나.
      이 PC 는 <b>지금 받기</b>(git pull — 이 PC 에서 손댄 파일이 있으면 받지 않는다), 서버(언레이드)는 <b>서버 갱신</b>(1분 안에 서버가 다시 빌드해 띄운다).
      자동으로 받지 않는다 — 누를 때만.</span></div>
    <div class="upd" id="pf-upd">${updHtml()}</div>
    <h4>AI 알림</h4>
    <div class="row"><span class="note">AI 팝업을 열지 않아도, 위키 기준(통제 · 사전대피 · 긴급대피)에 <b>가까워지거나(70%↑) 닿으면</b> 텔레그램으로 알린다 — 새로 생기거나 한 단계 오른 것만, 5분마다 본다.
      <b>켜는 서버는 한 곳만</b>(PC 와 서버를 둘 다 켜면 같은 알림이 두 번 간다). 기본은 끔.</span></div>
    <div class="row"><span class="k">알림</span><span class="seg"><button id="pf-al-off" type="button">끔</button><button id="pf-al-on" type="button">켬</button></span><button id="pf-al-test" type="button">시험 발송</button></div>
    <div class="row"><span class="note" id="pf-al-st">읽는 중…</span></div>
    <h4>AI 위키</h4>
    <div class="row"><span class="note">AI 상황판단(I)이 기준 · 우려지역 · 책자 쪽수를 읽는 재난업무 LLM 위키(옵시디언) 폴더. <b>이 서버(PC)</b> 안의 경로다 —
      폴더에 <code>tools/lookup.py</code> 와 문서(.md)가 있어야 한다. 비우고 저장하면 환경변수(GN_WIKI) · 기본으로 돌아간다.</span></div>
    <div class="row"><input id="pf-wiki" style="flex:1;min-width:0;font:inherit" spellcheck="false" placeholder="예: C:\Users\...\재난   또는   /mnt/user/appdata/.../재난"><button id="pf-wiki-save" type="button">저장</button></div>
    <div class="row"><span class="note" id="pf-wiki-st">읽는 중…</span></div>
    <h4>데모</h4>
    <div class="demo-list" id="pf-demo"><div class="al-none">읽는 중…</div></div>
    <div class="keys"><kbd>1</kbd>~<kbd>8</kbd> 층 · <kbd>Space</kbd> 재생 · <kbd>←</kbd><kbd>→</kbd> 한 장씩 · <kbd>L</kbd> 패널 · <kbd>A</kbd> 특보 · <kbd>S</kbd> 관측소 · <kbd>V</kbd> 지점 값 · <kbd>B</kbd> 누적 기준 · <kbd>F</kbd> 누적 예상 · <kbd>H</kbd> 최근 1시간 · <kbd>G</kbd> 위 카드 가득 · <kbd>R</kbd> 실시간 감시 · <kbd>Q</kbd> 초단기예측 이미지 · <kbd>W</kbd> 바다 위젯 · <kbd>C</kbd> 지도 위치 · <kbd>P</kbd> 화면 재생 · <kbd>T</kbd> 테스트 · <kbd>?</kbd> 도움말 · <kbd>Ctrl</kbd>+<kbd>,</kbd> 설정</div>
  </div>`;
  prefTabs();
  loadWiki();
  loadKeys();
  loadAlert();
  loadSaver();
  $("prefs").hidden = false;
  $("pf-x").onclick = closePrefs;
  const pickSet = (k, v) => {
    // v 는 문자열(단추 data-v · 드롭다운 value)
    v = (k === "tl_on" || k === "sel_zoom" || k === "aws_live" || k === "al_pre" || k === "gn_off") ? v === "true" : (k === "tl_stat" || k === "panel" || k === "sea_w" || k === "sea_grid") ? v : +v;
    if (k === "aws_live") { setLive(v).then(openPrefs); return; }
    if (k === "gn_off") { setGnOff(v).then(openPrefs); return; }
    if (k === "acc_scale") { setAccScale(v); openPrefs(); return; }
    if (k === "sea_w") { setSw(v); openPrefs(); return; }
    if (k === "sea_rot" || k === "sea_per") { setSwOpt(k, v); openPrefs(); return; }
    SET[k] = v;
    saveSetting({ [k]: v });
    if (k === "tl_on") setTL(v, false);
    if (k === "panel") { CARDS = null; applyTL(true); }
    if (k === "acc_hours") loadCards();
    if (k === "flow_step" || k === "flow_hours") loadFlow();
    if (k === "play_ms" && playing) startPlay();          // 재생 중이면 새 빠르기로 곧바로
    if (k === "qpf_ms" && QPF.play) qpfStart();
    if (k === "tl_stat") buildTL();
    if (k === "sel_zoom") { if (zoomOn()) ensureEmd(); camGo(true); }
    if (k === "sea_grid") draw();
    if (k === "al_pre") renderAlertLegend();
    openPrefs();
  };
  for (const b of $("prefs").querySelectorAll("button[data-k]")) b.onclick = () => pickSet(b.dataset.k, b.dataset.v);
  for (const s of $("prefs").querySelectorAll("select.seg-sel")) s.onchange = () => pickSet(s.dataset.k, s.value);
  for (const b of $("prefs").querySelectorAll("button[data-show]")) b.onclick = () => {
    closePrefs();
    if (b.dataset.show === "open") openShowDlg(SHOW.on ? SHOW.name : undefined); else SHOW.on ? stopShow() : showQuick();
  };
  for (const b of $("prefs").querySelectorAll("button[data-pal]")) b.onclick = async () => { await setPal(b.dataset.pal); openPrefs(); };
  for (const b of $("prefs").querySelectorAll("button[data-cam]")) b.onclick = () => {
    if (b.dataset.cam === "reset") { camReset(); openPrefs(); return; }
    closePrefs(); camEdit(true);
  };
  for (const b of $("prefs").querySelectorAll("button[data-th]")) b.onclick = () => { setTheme(b.dataset.th); openPrefs(); };
  for (const b of $("prefs").querySelectorAll("button[data-tools]")) b.onclick = () => { setTools(b.dataset.tools); openPrefs(); };
  for (const b of $("prefs").querySelectorAll("#pf-rng")) b.onchange = () => { const [f, h] = RNG_OPTS[+b.value]; setRange(f, h); openPrefs(); };
  // 초단기예측 이미지 길이 — 수집 설정(서버 qpf.ahead). 다음 발표분부터 그만큼 받는다
  for (const b of $("prefs").querySelectorAll("button.pf-on")) b.onclick = async () => {
    await putOff(b.dataset.id === "*" ? [] : offList().filter(x => x.id !== b.dataset.id));
    openPrefs();
  };
  for (const b of $("prefs").querySelectorAll("#pf-ahead")) b.onchange = async () => {
    const v = +b.value;
    try {
      const r = await fetch("/api/settings/qpf", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ahead: v }) });
      if (r.ok) QCFG_AHEAD = (await r.json()).qpf.ahead;
    } catch {}
    openPrefs();
  };
  $("prefs").querySelector('.dp button[data-a="date"]').onclick = () => { setRange("date", null, datePicked("pf-date")); openPrefs(); };
  fillDemo($("pf-demo"));
}
/* 오른쪽 위 도구 — 이 화면(브라우저)마다 기억. 기본은 '마우스를 움직이면'(벽면 화면이 깔끔하게) */
let TOOLS = "auto", TOOLS_T = null;
try { TOOLS = localStorage.getItem("gn-map-tools") || "auto"; } catch {}
function setTools(v) {
  TOOLS = v;
  try { localStorage.setItem("gn-map-tools", v); } catch {}
  document.body.classList.toggle("tools-hide", v === "hide");
  document.body.classList.toggle("tools-auto", v === "auto");
}
setTools(TOOLS);
function toolsWake() {                    // 잠깐(2.5초) 보였다가 다시 숨는다
  if (TOOLS !== "auto") return;
  document.body.classList.add("moving");
  clearTimeout(TOOLS_T);
  TOOLS_T = setTimeout(() => document.body.classList.remove("moving"), 2500);
}
document.addEventListener("pointermove", toolsWake);
toolsWake();                               // 처음 뜰 때 한 번 보여 준다 — 거기 있다는 걸 알게
function closePrefs() { $("prefs").hidden = true; }
$("prefs").addEventListener("click", ev => { if (ev.target.id === "prefs") closePrefs(); });

/* ── 업데이트 — 종합 화면 설정 › 업데이트와 같은 API(app/update.py · app/serverupdate.py) ──
   이 PC: /api/update(git fetch) → /api/update/pull(--ff-only) → 화면만이면 새로고침, 파이썬이면 /api/update/restart(run.bat 이 다시 띄운다).
   서버(언레이드 도커): /api/server-update 에 부탁만 한다(state/update/request) — 1분마다 도는 예약 작업이 deploy.sh 로 갱신.
   ⚠️ 확인 실패를 '최신'으로 읽지 않는다 — 인터넷이 막힌 PC 에서 '최신이다'라고 적으면 거짓말이 된다.
   ⚠️ 설정창은 무엇을 누를 때마다 통째로 다시 그린다(openPrefs) — 그래서 상태를 UPD 에 두고 updHtml 이 거기서 그린다 */
const UPD = { srv: null, pc: null, loading: false, msg: "", smsg: "", wait: null };
const escH = t => String(t ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;");
function updHtml() {
  const row = (k, v) => `<div class="row"><span class="k">${k}</span><span class="uv">${v}</span></div>`;
  let h = "";
  const s = UPD.srv;
  if (s?.available) {
    const busy = s.deploying || s.requested, L = s.last;
    h += `<div class="usub">서버(언레이드)</div>`
      + row("지금 판", `<code>${escH(s.version || s.running || "—")}</code>`)
      + row("GitHub", s.remote ? `<code>${escH(s.remote)}</code> <span class="hint">${escH(s.checked_at || "")} 확인</span>` : `<span class="warnx">확인 못 함</span>`)
      + (s.behind ? row("새 판", `<b>${s.behind}개</b> 밀려 있다<div class="hint">${(s.commits || []).map(c =>
          `<div>· <code>${escH(c.h)}</code> ${escH(c.at)} ${escH(c.s)}</div>`).join("")}</div>`)
        : s.remote ? row("상태", "최신이다") : "")
      + (s.updater_stale ? row("주의", `<span class="warnx">갱신 장치가 ${Math.round(s.updater_age_s / 60)}분째 조용하다</span>
          <div class="hint">언레이드 예약 작업이 안 돈다 — <code>bash …/deploy/unraid/updater.sh --install</code></div>`) : "")
      + (busy ? row("진행", `<b>${s.deploying ? "갱신 중… (1~2분, 화면이 잠깐 끊긴다)" : "부탁함 — 1분 안에 시작한다"}</b>`) : "")
      + (L ? row("마지막 갱신", `${L.ok ? "" : `<span class="warnx">실패</span> `}${escH(L.done || L.at)} → <code>${escH(L.version)}</code>
          <details><summary class="hint">기록</summary><pre class="hint">${escH(L.log)}</pre></details>`) : "")
      + row("", `<button class="ubtn" data-upd="srv-check"${busy ? " disabled" : ""}>다시 확인</button><button class="ubtn pri" data-upd="srv-go"${
          busy || s.updater_stale ? " disabled" : ""}>서버 갱신</button><span class="hint">${escH(UPD.smsg || "GitHub 최신 판으로 다시 빌드해 띄운다(시연 :8001 도)")}</span>`);
  }
  const u = UPD.pc;
  if (!u) return h + row("", `<span class="note">${UPD.loading ? "확인하는 중…" : "—"}</span>`);
  if (u.fail) return h + row("이 PC", `<span class="warnx">확인하지 못했다</span> <span class="hint">${escH(u.fail)}</span>`);
  // 서버(도커)는 git 저장소가 아니다 — 서버 갱신 칸이 대신한다. 그때는 이 PC 칸을 비운다
  if (!u.available) return h + (s?.available ? "" : row("", `<span class="note">${escH(u.reason || "업데이트를 쓸 수 없다")}</span>`));
  const hd = u.here || {};
  h += (s?.available ? `<div class="usub">이 PC</div>` : "")
    + row("지금 버전", `<code>${escH(hd.sha || "—")}</code> <span class="hint">${escH(hd.at || "")}</span><div class="hint">${escH(hd.subject || "")}</div>`)
    + (u.error ? row("확인", `<span class="warnx">확인 실패</span><div class="hint">${escH(u.error)}</div>`)
      : u.behind ? row("새 버전", `<b>${u.behind}개</b> 밀려 있다<div class="hint">${(u.incoming || []).map(l => `<div>· ${escH(l)}</div>`).join("")}</div>`)
      : row("상태", `최신이다 <span class="hint">${escH(u.checked_at || "")} 확인</span>`))
    + (u.dirty ? row("주의", `<span class="warnx">이 PC 에서 고친 파일이 있다</span><div class="hint">${(u.dirty_files || []).map(f => `<div>· ${escH(f)}</div>`).join("")}
        새 버전이 <b>같은 파일</b>을 건드리면 받기가 실패한다. 고친 것을 되돌리거나 그대로 두고 쓴다.</div>`) : "")
    + (u.ahead ? row("", `<span class="hint">이 PC 에만 있는 커밋이 ${u.ahead}개 있다</span>`) : "")
    + row("", `<button class="ubtn" data-upd="pc-check"${UPD.loading ? " disabled" : ""}>다시 확인</button><button class="ubtn pri" data-upd="pc-pull"${
        u.behind && !u.error && !UPD.loading ? "" : " disabled"}>지금 받기</button><span class="hint">${UPD.msg}</span>`);
  return h;
}
const updPaint = () => { const b = $("pf-upd"); if (b) b.innerHTML = updHtml(); };
async function loadSrvUpd() {
  try { UPD.srv = await getJson("/api/server-update"); } catch { UPD.srv = null; }
  updPaint();
}
async function loadUpd(check) {
  UPD.loading = true; UPD.msg = ""; updPaint();
  await loadSrvUpd();
  try { UPD.pc = await getJson(`/api/update?check=${!!check}`); } catch (e) { UPD.pc = { fail: e.message }; }
  UPD.loading = false; updPaint();
}
async function askServer(action) {
  const r = await fetch("/api/server-update", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }) });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
  return r.json();
}
async function updAct(a) {
  if (a === "pc-check") return loadUpd(true);
  if (a === "srv-check") {
    try { await askServer("check"); UPD.smsg = "부탁함 — 1분 안에 GitHub 를 본다"; } catch (e) { UPD.smsg = e.message; }
    updPaint(); setTimeout(loadSrvUpd, 65000);
    return;
  }
  if (a === "srv-go") {
    const s = UPD.srv || {};
    if (!confirm((s.behind ? `새 판 ${s.behind}개로 서버를 갱신합니다.` : "새 판이 없습니다. 그래도 서버를 다시 빌드해 띄울까요?")
                 + "\n\n1~2분 동안 서버 화면이 끊깁니다(시연 :8001 도).")) return;
    try { await askServer("deploy"); } catch (e) { UPD.smsg = "부탁하지 못했다: " + e.message; updPaint(); return; }
    const from = s.version || s.running, t0 = Date.now();
    UPD.smsg = "부탁함 — 1분 안에 시작한다";
    await loadSrvUpd();
    clearInterval(UPD.wait);
    // 끝날 때까지 본다 — 도는 동안 서버가 내려가 응답이 끊긴다. 다시 살아나 판이 바뀌면(또는 마지막 갱신이 새로 적히면) 끝
    UPD.wait = setInterval(async () => {
      let j = null;
      try { j = await getJson("/api/server-update"); } catch {}
      UPD.smsg = j ? (j.deploying ? "갱신 중…" : j.requested ? "곧 시작…" : "") : `다시 띄우는 중… ${Math.round((Date.now() - t0) / 1000)}초`;
      if (j) UPD.srv = j;
      if (j && !j.deploying && !j.requested && j.last && (j.version !== from || Date.parse(j.last.done) > t0 - 60000)) {
        clearInterval(UPD.wait); UPD.smsg = "";
        updPaint();
        if (j.last.ok && confirm(`서버를 ${j.version} 으로 갱신했습니다. 화면을 새로고침할까요?`)) location.reload();
        return;
      }
      if (Date.now() - t0 > 6 * 60000) { clearInterval(UPD.wait); UPD.smsg = "6분이 지나도 끝나지 않았다 — 서버를 확인하세요"; }
      updPaint();
    }, 4000);
    return;
  }
  if (a !== "pc-pull") return;
  UPD.loading = true; UPD.msg = "받는 중…"; updPaint();
  let r;
  try { r = await fetch("/api/update/pull", { method: "POST" }).then(x => x.json()); }
  catch (e) { UPD.loading = false; UPD.msg = "받지 못했다: " + escH(e.message); updPaint(); return; }
  UPD.loading = false;
  if (!r.ok) { UPD.msg = `<span class="warnx">${escH(r.error || "받지 못했다")}</span>`; updPaint(); return; }
  try { UPD.pc = await getJson("/api/update?check=false"); } catch {}
  if (!r.changed.length) { UPD.msg = escH(r.note || "이미 최신이다"); updPaint(); return; }
  UPD.msg = `${r.changed.length}개 파일을 받았다`;
  // 새 의존성은 받는 자리에서 서버가 깔았다. 실패했으면 숨기지 않는다 — 다시 띄워도 그 기능만 실패로 남는다
  let depNote = "";
  if (r.deps?.ok) UPD.msg += " · 새 구성요소 설치함";
  else if (r.deps) {
    depNote = "\n\n⚠️ 새 구성요소를 깔지 못했다: " + (r.deps.error || "") + "\n   다시 띄워도 그 기능만 실패로 남는다. run.bat 창을 닫고 새로 띄우면 다시 깐다.";
    UPD.msg += ` · <span class="warnx">새 구성요소 설치 실패</span>`;
  }
  updPaint();
  // 화면만 바뀌었으면 새로고침, 파이썬이 바뀌었으면 서버를 다시 띄운다. ⚠️ 스크립트로 띄우지 않았으면 다시 안 살아난다 — 먼저 묻는다
  if (!r.restart) { if (confirm("화면이 바뀌었습니다. 새로고침할까요?")) location.reload(); return; }
  if (!confirm("서버 코드가 바뀌었습니다. 지금 서버를 다시 띄울까요?\n\n(run.bat / run.command 로 띄운 경우에만 자동으로 다시 살아납니다.\n"
               + " 직접 실행 중이라면 손으로 다시 띄우세요.)" + depNote)) return;
  UPD.msg = "다시 띄우는 중…"; updPaint();
  try { await fetch("/api/update/restart", { method: "POST" }); } catch {}
  for (let i = 0; i < 40; i++) {          // 다시 뜰 때까지 기다렸다가 새로고침한다
    await new Promise(ok => setTimeout(ok, 1000));
    try { await fetch("/api/status", { cache: "no-store" }); location.reload(); return; } catch {}
  }
  UPD.msg = `<span class="warnx">다시 뜨지 않았다 — 창을 확인하세요</span>`; updPaint();
}
/* ── API 절약 모드(설정) — 기상청 호출 간격 ── */
let SAVER = null;
const SV_NAME = { alerts: "특보", rain: "강수", minute: "매분", forecast: "예보", qpf: "예측", bangjae: "스방", short: "단기", grid: "격자", odam: "실황" };
function saverPaint(msg) {
  const st = $("pf-sv-st");
  if (!st || !SAVER) return;
  $("pf-sv-on")?.classList.toggle("on", !!SAVER.on);
  $("pf-sv-off")?.classList.toggle("on", !SAVER.on);
  $("pf-sv-al1")?.classList.toggle("on", !!SAVER.alerts);
  $("pf-sv-al0")?.classList.toggle("on", !SAVER.alerts);
  document.querySelectorAll("#pf-sv-min button").forEach(b => b.classList.toggle("on", +b.dataset.m === SAVER.min));
  const n = $("pf-sv-n"); if (n && document.activeElement !== n) n.value = SAVER.min;
  const f = s => s % 60 ? s + "초" : s / 60 + "분";
  const list = Object.entries(SAVER.intervals || {}).map(([k, v]) => `${SV_NAME[k] || k} ${f(v)}${SAVER.on && v !== SAVER.base[k] ? "↑" : ""}`).join(" · ");
  st.innerHTML = msg || `${SAVER.on ? `<b>켜 둠 — ${SAVER.min}분 이상</b>` : "꺼 둠 — 기본 주기"} · 지금 도는 주기: ${list}`;
}
async function loadSaver() {
  try { SAVER = await getJson("/api/settings/saver"); saverPaint(); }
  catch (e) { const st = $("pf-sv-st"); if (st) st.innerHTML = `<span class="warnx">못 읽었다 — ${escH(e.message)}</span>`; }
}
async function saverPut(body) {
  try {
    const r = await fetch("/api/settings/saver", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.status);
    SAVER = j; saverPaint();
  } catch (e) { saverPaint(`<span class="warnx">${escH(e.message)}</span>`); }
}
$("prefs").addEventListener("click", ev => {
  const t = ev.target, id = t.id;
  if (id === "pf-sv-on") saverPut({ on: true });
  else if (id === "pf-sv-off") saverPut({ on: false });
  else if (id === "pf-sv-al1") saverPut({ alerts: true });
  else if (id === "pf-sv-al0") saverPut({ alerts: false });
  else if (id === "pf-sv-go") { const v = +$("pf-sv-n").value; if (v >= 1 && v <= 60) saverPut({ min: Math.round(v) }); else saverPaint(`<span class="warnx">1~60 분으로 쓴다</span>`); }
  else if (t.closest?.("#pf-sv-min") && t.dataset.m) saverPut({ min: +t.dataset.m });
});
/* ── AI 기준 근접 알림(설정) ── */
let ALERT = null;
function alertPaint(msg) {
  const st = $("pf-al-st");
  if (!st || !ALERT) return;
  $("pf-al-on")?.classList.toggle("on", !!ALERT.on);
  $("pf-al-off")?.classList.toggle("on", !ALERT.on);
  const l = ALERT.last || {};
  st.innerHTML = msg || [ALERT.ready ? "" : `<span class="warnx">텔레그램 키가 없다 — config/api_keys.txt 의 TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID</span>`,
    ALERT.on ? `<b>켜 둠</b>${l.at ? ` — 마지막 확인 ${l.at} · 본 것 ${l.seen}건 · 보낸 것 ${l.sent}건` : " — 아직 한 번도 안 돌았다(5분 안에)"}` : "꺼 둠",
    l.err ? `<span class="warnx">마지막 오류: ${escH(l.err)}</span>` : ""].filter(Boolean).join(" · ");
}
async function loadAlert() {
  try { ALERT = await getJson("/api/settings/ai-alert"); alertPaint(); }
  catch (e) { const st = $("pf-al-st"); if (st) st.innerHTML = `<span class="warnx">못 읽었다 — ${escH(e.message)}</span>`; }
}
$("prefs").addEventListener("click", async ev => {
  const id = ev.target.id;
  if (id !== "pf-al-on" && id !== "pf-al-off" && id !== "pf-al-test") return;
  const st = $("pf-al-st");
  try {
    if (id === "pf-al-test") {
      st.textContent = "보내는 중…";
      const r = await fetch("/api/ai/alert-test", { method: "POST" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.status);
      alertPaint("시험 알림을 보냈다 — 텔레그램을 확인한다");
      return;
    }
    const r = await fetch("/api/settings/ai-alert", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ on: id === "pf-al-on" }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.status);
    ALERT = j; alertPaint();
  } catch (e) { alertPaint(`<span class="warnx">${escH(e.message)}</span>`); }
});
/* ── AI 위키 폴더(설정) ── */
function wikiPaint(w, msg) {
  const st = $("pf-wiki-st");
  if (!st) return;
  st.innerHTML = msg || (w.ok ? `<b>쓰는 중</b> — ${escH(w.path)} · 문서 ${w.md}개 · 우려지역 CSV ${w.csv ? "있음" : "없음"} · 출처 ${w.source}`
    : `<span class="warnx">못 쓴다</span> — ${escH(w.path)} (${!w.dir ? "폴더가 없다" : !w.lookup ? "tools/lookup.py 가 없다" : "문서가 없다"}) · 출처 ${w.source}`);
}
async function loadWiki() {
  try {
    const w = await getJson("/api/settings/ai-wiki");
    if ($("pf-wiki")) { $("pf-wiki").value = w.source === "설정" ? w.path : ""; $("pf-wiki").placeholder = `비우면 ${w.source === "설정" ? "기본" : w.source}`; }
    wikiPaint(w);
  } catch (e) { wikiPaint(null, `<span class="warnx">못 읽었다 — ${escH(e.message)}</span>`); }
}
$("prefs").addEventListener("click", async ev => {
  if (ev.target.id !== "pf-wiki-save") return;
  const b = ev.target;
  b.disabled = true;
  try {
    const res = await fetch("/api/settings/ai-wiki", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ path: $("pf-wiki").value }) });
    const j = await res.json();
    if (!res.ok) throw new Error(j.detail || res.status);
    wikiPaint(j);
    if (AIW.open) aiLoad();
  } catch (e) { wikiPaint(null, `<span class="warnx">저장하지 않았다 — ${escH(e.message)}</span>`); }
  b.disabled = false;
});
/* API 키 — 서버 config/api_keys.txt 를 고친다. 값은 받아 오지 않고 설정 여부 · 끝 네 글자만 */
function keysPaint(j, msg = "") {
  const box = $("pf-keys");
  if (!box) return;
  box.innerHTML = (j?.keys || []).map(k => `<div class="row" data-key="${k.name}"><span class="k" style="width:190px" title="${escH(k.use)}">${escH(k.label)}</span>
      <span class="note" style="width:84px">${k.set ? `설정됨${k.tail ? ` ···${escH(k.tail)}` : ""}` : "없음"}</span>
      <input type="password" autocomplete="off" spellcheck="false" placeholder="새 값" style="flex:1;min-width:0;font:inherit"${j.demo ? " disabled" : ""}>
      <button type="button" data-ks="save"${j.demo ? " disabled" : ""}>저장</button>${k.set ? `<button type="button" data-ks="del"${j.demo ? " disabled" : ""}>지우기</button>` : ""}</div>`).join("")
    + (msg ? `<div class="row"><span class="note">${msg}</span></div>` : "");
}
async function loadKeys() {
  try { keysPaint(await getJson("/api/keys")); } catch (e) { keysPaint(null, `<span class="warnx">못 읽었다 — ${escH(e.message)}</span>`); }
}
$("prefs").addEventListener("click", async ev => {
  const b = ev.target.closest?.("button[data-ks]");
  if (!b) return;
  const row = b.closest("[data-key]"), name = row.dataset.key, del = b.dataset.ks === "del";
  const value = del ? "" : row.querySelector("input").value.trim();
  if (!del && !value) { keysPaint(await getJson("/api/keys"), "새 값을 넣고 저장한다(지우려면 '지우기')."); return; }
  b.disabled = true;
  try {
    const res = await fetch("/api/keys", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ name, value }) });
    const j = await res.json();
    if (!res.ok) throw new Error(j.detail || res.status);
    keysPaint(j, del ? "지웠다." : "저장했다 — 바로 쓰인다.");
  } catch (e) { b.disabled = false; keysPaint(await getJson("/api/keys").catch(() => null), `<span class="warnx">저장하지 않았다 — ${escH(e.message)}</span>`); }
});
$("prefs").addEventListener("click", ev => { const b = ev.target.closest?.("button[data-upd]"); if (b && !b.disabled) updAct(b.dataset.upd); });


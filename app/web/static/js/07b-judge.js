"use strict";
/* ── 상황판단(X) — 별도 창(map.html?sj). 듀얼 모니터면 한쪽은 지도, 한쪽은 이 창 — 시군 선택은 두 창이 서로 맞춘다(BroadcastChannel).
   가운데: 할 일 상자 — 읍면동 · 유형으로 묶어(지오코딩 전이라 같은 묶음은 % 가 같다) '결정 필요 → 곧 넘음 → 결정함 → 지켜볼 곳' 순서.
   오른쪽: 고른 지구 상세 — 조건마다 지금/필요, 두 강수 기준, 담당 전화 · 문자, 결정(판단 기록에만 남긴다).
   왼쪽: 지금 할 일(규칙 보고) · 위키 매뉴얼 · 물어보기 · 판단 기록 탭.
   연락처는 /api/contacts(잠금 뒤) — AI 물어보기에는 넘기지 않는다. */
const SJ_SOLO = new URLSearchParams(location.search).has("sj");
const SJ = { open: false, sg: "all", k: 1, addH: 0, add24: 0, basis: "grid", cut: { on: true, pct: 70 }, d: null, log: [], st: null,
  ct: null, q: [], llm: null, rep: null, seq: 0, sel: new URLSearchParams(location.search).get("r"), tab: "단계판", more: false, ai: false, wopen: false, msgs: [] };
try { Object.assign(SJ.cut, JSON.parse(localStorage.getItem("gn-sj-cut") || "{}")); SJ.basis = localStorage.getItem("gn-sj-basis") || "grid"; } catch {}
SJ.pane = { l: true, r: true };                          // 왼쪽(매뉴얼) · 오른쪽(상세) 패널 — [ · ] 키
try { Object.assign(SJ.pane, JSON.parse(localStorage.getItem("gn-sj-pane") || "{}")); } catch {}
function sjPane(k, on = !SJ.pane[k]) {
  SJ.pane[k] = on;
  try { localStorage.setItem("gn-sj-pane", JSON.stringify(SJ.pane)); } catch {}
  $("sj").classList.toggle("nol", !SJ.pane.l); $("sj").classList.toggle("nor", !SJ.pane.r);
  document.querySelectorAll("#sj [data-pane]").forEach(b => b.classList.toggle("on", SJ.pane[b.dataset.pane]));
}
const SJ_STG = ["통제", "사전대피", "긴급대피"];
const SJ_ACT = { 통제: "통제 지시", 사전대피: "사전대피 권고", 긴급대피: "대피명령 요청" };
const SJ_BN = { grid: "기상청 격자", aws: "AWS" };
const SJ_BC = "BroadcastChannel" in window ? new BroadcastChannel("gn-sel") : null;
let SJ_REMOTE = false;                                   // 다른 창에서 온 선택 — 되돌려 보내지 않는다
const sjLv = p => (p >= 100 ? 100 : p >= 90 ? 90 : p >= 80 ? 80 : p >= 70 ? 70 : p >= 50 ? 50 : 0);
const sjPin = () => { try { return localStorage.getItem("gn-ct-pin") || ""; } catch { return ""; } };
const sjDash = s => !s || /^[–-]$/.test(String(s).trim());
const sjName = d => (!sjDash(d.name) && !/[구군시]$/.test(d.name) ? d.name : !sjDash(d.ri) ? d.ri : d.jibun ? `${d.emd} ${d.jibun}` : d.emd || "이름 없음");   // 창원은 지구명 칸이 구 이름 · 빈 칸(–)이면 리로
const sjAddr = d => [d.emd, sjName(d) === d.ri || sjDash(d.ri) ? "" : d.ri, sjName(d).endsWith(d.jibun) ? "" : d.jibun].filter(Boolean).join(" ");
const sjB = r => r.b[SJ.basis] || r.b.grid;
const sjEtaTxt = c => (c.met ? "넘음" : c.unk ? "모름" : c.eta ? `${c.eta}시` : "—");
/* 열기 — 지도 창에서는 새 창으로(막히면 이 창 안에), 상황판단 창에서는 늘 열려 있다 */
function sjToggle(on = !SJ.open) {
  if (!SJ_SOLO && on) {
    const w = window.open(`/map.html?sj=1${SELS[0] ? `&sig=${encodeURIComponent(SELS[0])}` : ""}`, "gn-judge", "popup=1,width=1680,height=1000");
    if (w) { w.focus(); return; }
  }
  if (SJ_SOLO && !on) return;
  SJ.open = on;
  $("sj").hidden = !on;
  document.body.classList.toggle("sj-on", on);
  if (!on) return;
  SJ.sg = SELS[0] || SJ.sg || "all";
  sjLoad();
}
async function sjLoad(onlyData) {
  const my = ++SJ.seq, sg = SJ.sg, qs = new URLSearchParams({ sigun: sg, k: SJ.k, add_h: SJ.addH, add_24: SJ.add24, series: 1, sb: SJ.basis });
  if (!onlyData) {   // 처음 모을 때는 수십 초 걸린다 — 멈춘 것처럼 보이지 않게 움직이는 줄 · 지난 초 · 자리 잡은 뼈대
    $("sj-c").innerHTML = `<div class="sj-ld" role="status"><div class="ldbar"><i></i></div><b>${sg === "all" ? "경남 전체 18개 시군" : escH(sg)} 지구 판정을 모으는 중</b>
      <small>강수 격자 · 지구별 대피 기준 · 판단 기록을 맞춰 본다 — 처음에는 수십 초 걸릴 수 있다 · <span class="sec">0</span>초째</small>${'<div class="sk"></div>'.repeat(6)}</div>`;
    const t0 = Date.now(), tick = setInterval(() => { const e = $("sj-c").querySelector(".sj-ld .sec"); if (e) e.textContent = Math.round((Date.now() - t0) / 1000); else clearInterval(tick); }, 1000);
  }
  $("sj").classList.add("busy");
  try {
    const one = sg === "all" ? "" : `?sigun=${encodeURIComponent(sg)}`;
    const [d, lg, ct, rp] = await Promise.all([getJson(`/api/judge?${qs}`), getJson(`/api/ai/decisions${one}`),
      onlyData ? null : fetch(`/api/contacts?sigun=${encodeURIComponent(sg)}`, { headers: { "x-pin": sjPin() }, cache: "no-store" }),
      onlyData ? null : getJson(`/api/ai/report${one}`).catch(() => null)]);
    if (my !== SJ.seq) return;
    Object.assign(SJ, { d, log: lg.rows });
    SJ.geo = await getJson("/api/geocode").catch(() => null);
    if (ct) SJ.ct = ct.status === 401 ? { pin: true } : ct.status === 429 ? { err: "잠금 번호를 여러 번 틀렸다 — 5분 뒤" } : await ct.json();
    if (rp) Object.assign(SJ, { q: rp.questions || [], llm: rp.llm ?? null, rep: rp });
  } catch (e) { if (my === SJ.seq) $("sj-c").innerHTML = `<div class="sj-ld">못 모았다 — ${escH(e.message)}</div>`; $("sj").classList.remove("busy"); return; }
  $("sj").classList.remove("busy");
  if (!SJ.d.rows.some(r => r.id === SJ.sel)) SJ.sel = null;
  sjRender();
}
/* 묶음 — 시군 · 읍면동 · 유형. 상태: 결정 필요(넘었는데 기록 없음) · 곧(3시간 안) · 결정함 · 지켜볼 곳 */
function sjGroups() {
  const by = new Map();
  for (const r of SJ.d?.rows || []) {
    if (!r.b[SJ.basis]) continue;
    const k = `${r.sigun}|${r.emd}|${r.fam}`;
    if (!by.has(k)) by.set(k, { k, sigun: r.sigun, emd: r.emd, fam: r.fam, rows: [] });
    by.get(k).rows.push(r);
  }
  const out = [];
  for (const g of by.values()) {
    // 지구마다 자리 비가 달라 % 도 다르다 — 묶음 머리는 단계마다 가장 많이 찬 지구 것, 칩은 많이 찬 순서
    g.rows.sort((a, b) => sjB(b).top - sjB(a).top);
    g.st = Object.fromEntries(SJ_STG.map(s => [s, g.rows.map(r => sjB(r).st[s]).filter(Boolean).sort((a, b) => b.pct - a.pct)[0]]).filter(([, v]) => v));
    const b = { st: g.st };
    g.top = Math.max(...g.rows.map(r => sjB(r).top));
    g.dec = SJ.log.filter(x => x.sigun === g.sigun && x.emd === g.emd && x.fam === g.fam);
    g.met = SJ_STG.some(s => b.st[s]?.met);
    g.soon = Math.min(99, ...SJ_STG.map(s => (!b.st[s] || b.st[s].met ? 99 : b.st[s].eta_h ?? 99)));
    g.sec = g.met && !g.dec.length ? 0 : g.dec.length ? 2 : g.soon <= 3 ? 1 : 3;
    if (g.sec < 3 || !SJ.cut.on || g.top >= SJ.cut.pct) out.push(g);
  }
  return out.sort((a, b) => a.sec - b.sec || b.top - a.top || a.soon - b.soon);
}
const SJ_SOIL = { met: "충족", check: "확인 필요", no: "미충족", unknown: "모름" };
const SJ_SEC = ["결정 필요 — 기준을 넘었는데 아직 기록이 없다", "곧 넘음 — 3시간 안", "결정함", "지켜볼 곳"];
function sjPct(c) { return c ? `<b class="pc t${sjLv(c.pct)}">${c.unk ? "모름" : `${c.pct}%`}</b>` : `<b class="pc">—</b>`; }
/* 지역 여건 꼬리표(app/terrain.py) — 눈여겨볼 것(lv w)만 n 개. 판정 % 와 별개 */
const sjTfChips = (t, n = 9) => (t?.flags || []).filter(f => f.lv === "w").slice(0, n).map(f => `<em class="tf" title="지역 여건 — 판정 % 와 별개">${escH(f.t)}</em>`).join("");
TIPS.set("sj-terrain", `<div class="doc">
<h3>지역 여건 — 값마다 어디서 왔나</h3>
<p class="lead">판정 %(강우 기준)는 이 값으로 바꾸지 않는다 — 함께 보는 여건이다. 경고 꼬리표는 목록에도, 참고는 상세에만 나온다.</p>
<h4>지형</h4>
<dl>
<dt>표고</dt><dd><ul>
  <li><b>원본</b> AWS 공개 지형 타일(Terrarium · SRTM 등, 확대 12 ≈ 30m 격자)</li>
  <li><b>계산</b> 지구 좌표(위키 지번 필지 중심 · 서버에서 고친 좌표)에서 보간 — <code>tools/build_dz_terrain.py</code></li>
  <li><b>꼬리표</b> 저지대 10m 이하 — 지도 '저지대' 레이어와 같은 문턱</li>
  <li class="note">위키에 수치는 없다(대피판단 기준은 '배수 불량 저지대'를 여건으로 볼 뿐) — <u>이 앱이 정한 값</u></li></ul></dd>
<dt>경사</dt><dd><ul>
  <li><b>원본</b> 국토지리정보원 연속수치지형도 <b>등고선</b>(1:5,000 · 5m 간격, 브이월드). 없으면 30m 표고(둘레 ±90m 7×7 점)</li>
  <li><b>계산</b> 등고선 점에 평면을 맞춘 기울기 — 지구 자리(반지름 50m) · <b>둘레 가장 가파른 곳</b>(40m 떨어진 8곳, 반지름 30m)</li>
  <li><b>꼬리표</b> 급경사 <b>30° 이상</b>(산사태 지구만) — 위키 [[산사태 유형과 발생 원인]] "30~35°에서 가장 많이, 20° 이하는 적다"</li>
  <li class="note">축대 · 옹벽 같은 인공 비탈(급경사지법: 높이 5m · 34°)은 등고선에도 없다 — 그런 곳은 붕괴위험지역 꼬리표가 근거. 자세히는 도움말 › 자료 출처</li></ul></dd>
<dt>붕괴위험</dt><dd><ul>
  <li><b>원본</b> 국토교통부 연속주제도 '급경사재해예방/붕괴위험지역'(브이월드, 경남 92곳, 2026-10) — 급경사지법으로 지정 · 고시된 구역</li>
  <li><b>꼬리표</b> 지구 자리가 안이면 경고 · 300m 안이면 참고(1km 밖은 안 적음)</li></ul></dd>
</dl>
<h4>물</h4>
<dl>
<dt>하천</dt><dd><ul>
  <li><b>원본</b> 국토지리정보원 하천중심선(국가 · 지방하천) + 실폭하천 면 테두리(브이월드)</li>
  <li><b>계산</b> 25m 간격 점 중 가장 가까운 곳, 높이 = 지구 표고 − 하천 점 표고(30m)</li>
  <li><b>꼬리표</b> 200m 안 · 높이 5m 안 — <u>이 앱이 정한 범위</u>. 하천 유형 지구(교량 · 둔치)는 참고로만</li></ul></dd>
<dt>개울</dt><dd><ul><li>같은 하천중심선의 소하천 등(세류는 뺌) 500m 안</li></ul></dd>
<dt>저수지</dt><dd><ul>
  <li><b>원본</b> 연속수치지형도 호수/저수지(1ha 이상)</li>
  <li><b>계산</b> 2km 안 가장 가까운 물가, 높이 = 물가 표고 − 지구 표고</li>
  <li><b>꼬리표</b> 300m 안 · 10m 이상 낮음 — <u>이 앱이 정한 범위</u></li></ul></dd>
<dt>해안</dt><dd><ul><li>30m 표고 0m 이하 땅까지(100m 간격, 3km 까지)</li></ul></dd>
</dl>
<h4>사람 · 기록</h4>
<dl>
<dt>건물</dt><dd><ul><li>국토교통부 GIS건물통합정보(브이월드, 경남 전체) 건물 중심점 수 — 100m · 300m 안</li></ul></dd>
<dt>침수흔적</dt><dd><ul>
  <li><b>원본</b> 행정안전부 침수흔적도(재난안전데이터공유플랫폼, 7일마다)</li>
  <li><b>꼬리표</b> 지구 자리가 안이면 경고 · 100m 안이면 참고</li></ul></dd>
</dl>
<h4>지금 값 (실시간)</h4>
<dl>
<dt>수위</dt><dd><ul>
  <li><b>원본</b> 홍수통제소 수위관측소(이 앱 '하천 · 댐', 10분) 중 기준 수위가 있는 곳</li>
  <li><b>고르기</b> ① <b>같은 하천</b> 20km 안(지구 2km 안 이름 있는 하천 = 관측소 300m 안 하천중심선 이름) ② 없으면 아무 하천 5km 안 — '다른 하천일 수 있음'</li>
  <li><b>꼬리표</b> 관심 수위 이상</li></ul></dd>
<dt>위험저수지</dt><dd><ul>
  <li><b>원본</b> 재난안전데이터공유플랫폼 위험저수지 계측기 경보(30분)</li>
  <li><b>고르기</b> 3km 안, 그 자리 표고(125m 격자)가 지구보다 5m 이상 높은 것</li>
  <li><b>꼬리표</b> 발령 중(해제 없이 72시간 넘으면 기록만) — 위키 [[저수지 재난 시군 사전대피와 주민대피 준비 (진주시 매뉴얼)]] '하류부 · 저지대 거주자'</li></ul></dd>
</dl>
</div>`);
/* 상세 — 지역 여건 칸. 숫자는 지구 자리 기준(지형 30m · 하천 · 저수지 국토지리정보원 · 건물 국토교통부 · 침수흔적 행정안전부) */
function sjTerrain(r) {
  const t = r.terrain;
  if (!t) return `<div class="dsec"><h5>지역 여건</h5><p class="mute">${r.pos ? "이 지구는 지형 표를 만든 뒤 좌표가 생겼다 — tools/build_dz_terrain.py 를 다시 돌린다" : "지구 좌표가 없어 지형을 못 본다"}</p></div>`;
  const row = (k, v) => v ? `<div class="tr"><span>${k}</span><b>${v}</b></div>` : "";
  const rv = t.rv, lk = t.lk;
  return `<div class="dsec"><h5>지역 여건 <i class="inf" data-tip="sj-terrain" aria-label="값마다 출처">i</i><span class="mute">판정 % 와 별개, 함께 본다</span></h5>
    ${t.flags?.length ? `<div class="tfs">${t.flags.map(f => `<em class="tf${f.lv === "w" ? "" : " i"}">${escH(f.t)}</em>`).join("")}</div>` : ""}
    <div class="tt">${row("표고", t.el != null ? `${t.el.toFixed(0)}m${t.el <= 10 ? " · 저지대" : ""}` : "")}
      ${row("경사", t.sl50 != null ? `등고선 — 둘레 가장 가파른 곳 ${t.sl50}° · 지구 자리 ${t.sl5}° <span class="mute">(30m 표고로는 ${t.sl}°)</span>` : t.sl != null ? `둘레 100m 가장 가파른 곳 ${t.sl}° · 지구 자리 ${t.sl0}°` : "")}
      ${row("붕괴위험", t.cz ? `${t.cz.d === 0 ? "지구 자리가 붕괴위험지역 안" : `붕괴위험지역까지 ${t.cz.d}m`}${t.cz.n ? ` — ${escH(t.cz.n)}` : ""}${t.cz.dt ? ` · 고시 ${escH(t.cz.dt.replace(/(\d{4})(\d\d)(\d\d)/, "$1.$2.$3"))}` : ""}` : "")}
      ${row("하천", rv ? `${escH(rv.n || (rv.g === 1 ? "국가하천" : "지방하천"))} ${rv.d}m · 지구가 ${rv.dh >= 0 ? `${rv.dh.toFixed(0)}m 높음` : `${(-rv.dh).toFixed(0)}m 낮음`}` : "")}
      ${row("개울", t.st != null ? `소하천 · 개울 ${t.st}m` : "")}
      ${row("저수지", lk ? `${escH(lk.n || "이름 없음")} ${lk.d}m · ${lk.dh >= 0 ? `물가가 ${lk.dh.toFixed(0)}m 높음` : `물가가 ${(-lk.dh).toFixed(0)}m 낮음`}` : "")}
      ${row("해안", t.cs != null ? `바다(표고 0m)까지 ${t.cs}m` : "")}
      ${row("건물", t.b300 != null ? `100m 안 ${t.b100}동 · 300m 안 ${t.b300}동` : "")}
      ${row("수위", t.wl ? `${escH(t.wl.n)}${t.wl.rn ? `(${escH(t.wl.rn)})` : ""}${t.wl.same ? "" : " · 다른 하천일 수 있음"} ${t.wl.d >= 1000 ? `${(t.wl.d / 1000).toFixed(1)}km` : `${t.wl.d}m`} · 지금 ${escH(t.wl.stn)}${t.wl.v != null ? ` ${t.wl.v.toFixed(2)}m` : ""}${t.wl.gap != null ? ` · ${escH(t.wl.nx)}까지 ${t.wl.gap}m` : ""}${t.wl.stale ? " · ⚠ 오래된 값" : ""}` : "")}
      ${row("위험저수지", t.rs ? `${escH(t.rs.n)} — 지구보다 ${t.rs.dh}m 높은 곳 ${t.rs.d}m · ${escH(t.rs.lvn)} ${t.rs.on ? "발령 중" : "해제"}(${escH(t.rs.at)})` : "")}
      ${row("침수흔적", t.fl ? `${t.fl.in ? "지구 자리가 흔적 안" : "100m 안에 흔적"} — ${escH(String(t.fl.yr || ""))} ${escH(t.fl.nm || "")}` : "")}</div>
    <p class="mute">값마다 출처 · 계산 · 문턱 근거는 ⓘ — 지형 표 ${escH(SJ.d?.terrain_built || "")}</p></div>`;
}
function sjGroup(g) {
  const sel = g.rows.some(r => r.id === SJ.sel), all = SJ.sg === "all";
  const subs = g.rows.slice(0, sel ? 99 : 4).map(r => {
    const b = sjB(r), p0 = SJ.ct?.people?.[r.id]?.[0];
    return `<button class="sb${r.id === SJ.sel ? " on" : ""}" data-r="${escH(r.id)}"><b>${escH(sjName(r))}</b><span>${escH(sjAddr(r).replace(`${r.emd} `, ""))}</span>`
      + `<em><i class="t${sjLv(b.top)}" title="${r.where === "지구" ? "이 지구 자리 비로 판정" : "읍면동 기준"}">${b.top}%${r.where === "지구" ? "" : "*"}</i> ${b.site != null ? `지구 기준 <i class="t${sjLv(b.site)}">${b.site_slide ? (b.site >= 100 ? "발령 중" : "발령 없음") : `${b.site}%`}</i>` : ""}</em>`
      + (r.soil ? `<em class="soil s-${r.soil.st}" title="지구 기준의 토양함수 ${r.soil.need}% — 산림청 예측정보(시군)로">토양 ${SJ_SOIL[r.soil.st]}</em>` : "")
      + sjTfChips(r.terrain, 2)
      + `<small>${p0 ? escH((p0.who || "").replace(/담당부서\s*/g, "")) : ""}</small></button>`;
  }).join("") + (!sel && g.rows.length > 4 ? `<button class="sb mr" data-r="${escH(g.rows[4].id)}">외 ${g.rows.length - 4}곳</button>` : "");
  const done = g.dec.length ? `<span class="dn">✔ ${escH(g.dec[0].act)} ${g.dec[0].at.slice(11, 16)}</span>` : "";
  return `<div class="gp l${sjLv(g.top)}${sel ? " on" : ""}"><button class="gh" data-r="${escH(g.rows[0].id)}">
      <span class="gn">${all ? `<i>${escH(g.sigun)}</i>` : ""}${escH(g.emd)} <em>${escH(g.fam)}</em></span>
      ${SJ_STG.map(s => sjPct(g.st[s])).join("")}<span class="et">${g.met ? "넘음" : g.soon < 99 ? `${g.soon}시간 뒤` : "—"}</span>
      <span class="gc">${g.rows.length}곳${done}</span></button><div class="sbs">${subs}</div></div>`;
}
/* 조건 막대 — 지금/필요. '그리고'로 묶인 조건은 가장 덜 찬 것이 그 기준의 % */
const sjParts = ps => ps.map(p => `<div class="pt"><span>${escH(p.label || "")}</span><i><u class="b${sjLv(p.pct ?? 0)}" style="width:${Math.min(100, p.pct ?? 0)}%"></u></i>
  <b>${p.now == null ? "모름" : `${p.now}`}<small>/${p.need}${escH(p.unit || "")}</small></b><em class="t${sjLv(p.pct ?? 0)}">${p.pct == null ? "" : `${p.pct}%`}</em></div>`).join("");
function sjDetail() {
  const r = (SJ.d?.rows || []).find(x => x.id === SJ.sel);
  if (!r) return sjTimeline();                           // 지구를 안 골랐으면 단계 시간표(07d)
  const b = sjB(r), o = r.b[SJ.basis === "grid" ? "aws" : "grid"], recs = SJ.log.filter(x => x.sigun === r.sigun && x.emd === r.emd && x.fam === r.fam);
  const stg = SJ_STG.map(s => {
    const c = b.st[s];
    if (!c) return "";
    return `<div class="sx"><div class="sxh"><b>${s}</b>${sjPct(c)}<span>${sjEtaTxt(c) === "넘음" ? "기준 넘음" : c.eta ? `${c.eta}시 도달 예상` : c.unk ? "자료 없음" : "내일 24시까지 안 닿음"}</span></div>
      <div class="rl">${escH(c.rule)}${c.partial ? " · 모르는 조건은 빼고 계산" : ""}</div>${sjParts(c.parts || [])}</div>`;
  }).join("");
  const ppl = SJ.ct?.people?.[r.id] || [];
  const msg = encodeURIComponent(`${r.sigun} ${r.emd} ${sjName(r)} ${r.fam} 강우 기준 근접 — 통제 · 사전대피 여부 판단 바랍니다. (경남 재난안전상황실)`);
  const who = SJ.ct?.pin ? `<form class="sj-pin"><input type="password" inputmode="numeric" autocomplete="off" placeholder="연락처 잠금 번호"><button>열기</button></form>`
    : SJ.ct?.err ? `<p class="mute">${escH(SJ.ct.err)}</p>` : SJ.ct?.on === false ? `<p class="mute">연락처 파일이 없다</p>`
    : ppl.map((p, n) => `<div class="ps"><span>${escH((p.who || "").replace(/담당부서\s*/g, "") || `담당${n + 1}`)}</span>${p.tel ? `<a class="tel" href="tel:${escH(p.tel.replace(/[^0-9-]/g, ""))}" data-ct="${n + 1}|전화">📞 ${escH(p.tel)}</a>` : `<em class="mute">번호 없음</em>`}`
      + (/^01/.test(p.tel || "") ? `<a class="sms" href="sms:${escH(p.tel.replace(/[^0-9]/g, ""))}?body=${msg}" data-ct="${n + 1}|문자">✉ 문자</a>` : "") + `</div>`).join("") || `<p class="mute">이 지구 담당자가 표에 없다</p>`;
  const acts = [...SJ_STG.map(s => [SJ_ACT[s], s]), ["보류", ""]].map(([a, s]) => {
    const on = recs.find(x => x.act === a && (x.note || "").includes(sjName(r)));
    return `<button class="ac${on ? " on" : ""}" data-act="${a}" data-s="${s}">${on ? "✔ " : ""}${a}</button>`;
  }).join("");
  const sl = r.slide && (r.slide.fcst || r.slide.pred);
  return `<button class="bk" data-unsel>← 단계 시간표</button><div class="dt"><div class="dh"><b>${escH(sjName(r))}</b><span>${escH(r.sigun)} ${escH(sjAddr(r))}</span><span>${escH(r.kind || r.fam)}${r.shelter && r.shelter !== "–" ? ` · 대피 ${escH(r.shelter)}` : ""}</span>
      ${sl ? `<span class="slb">산사태${escH((r.slide.fcst || r.slide.pred).kind)} ${r.slide.fcst ? "예보" : "예측"} 발령 중</span>` : ""}</div>
    <div class="dsec"><h5>위치</h5>${r.pos ? `<p>${r.pos[0].toFixed(5)}, ${r.pos[1].toFixed(5)} <span class="mute">— 지번 필지 중심</span></p>` : ""}
      <p class="mute">${r.where === "지구" ? "판정 비 = 이 지구 자리(둘레 1.5km 가장 많이 온 칸) · 예보는 읍면동"
        : `${r.pos ? "지구 자리 비를 아직 못 받아" : SJ.geo?.state === "받는 중" ? `지구 위치 받는 중(${SJ.geo.done}/${SJ.geo.total}) —` : "지구 위치가 없어"} 읍면동에서 가장 많이 온 칸으로 판정`}</p></div>
    ${sjTerrain(r)}
    <div class="dsec"><h5>결정 — 판단 기록에 남는다</h5><div class="acs">${acts}</div></div>
    <div class="dsec"><h5>담당</h5>${who}</div>
    <div class="dsec"><h5>판정 · ${SJ_BN[SJ.basis]} 기준 <span class="mute">(조건이 '그리고'면 가장 덜 찬 것이 그 기준의 %)</span></h5>${stg}
      ${o ? `<p class="mute">${SJ_BN[SJ.basis === "grid" ? "aws" : "grid"]} 기준이면 ${SJ_STG.map(s => o.st[s] ? `${s} ${o.st[s].pct}%` : "").filter(Boolean).join(" · ")}</p>` : ""}</div>
    ${r.rule ? `<div class="dsec"><h5>지구 기준 (원문) ${b.site != null ? sjPct({ pct: b.site }) : ""}</h5><div class="rl">${escH(r.rule)}</div>
      ${b.series?.site?.length ? `<p><b>${escH(siteText(b.series.site, SJ.d?.regions?.[r.fam]).replace("이 지구 자체 기준: ", "숫자로: "))}</b></p>` : ""}
      ${b.site_slide ? `<p class="mute">산사태 예보 발령이 기준 — ${b.site >= 100 ? "발령 중" : "발령 없음"}</p>` : sjParts(b.site_parts || [])}
      ${r.soil ? `<div class="soilx s-${r.soil.st}"><b>토양함수 ${r.soil.need}% — ${SJ_SOIL[r.soil.st]}</b><span>${r.soil.now ? `산림청 예측정보(${escH(r.sigun)} 시군 단위): 지수 ${escH(r.soil.now)}` : "산림청 예측정보를 받지 못함(호우 · 태풍 특보 때만 받는다)"}</span>
        ${r.soil.st === "check" ? `<span>80~100% 사이라 이 숫자로는 못 가린다 — 산사태정보시스템에서 이 읍면동 지수 확인</span>` : ""}</div>` : ""}
      <p class="mute">원문 조건 중 가장 많이 찬 것을 % 로 — 토양함수는 산림청 예측정보(주의보 80% · 경보 100%)로 명백한 것만</p></div>` : ""}
    <div class="dsec"><h5>강수 (누적 · 시간당)</h5>${["grid", "aws"].map(k => r.b[k] ? `<div class="rn${k === SJ.basis ? " on" : ""}"><span>${SJ_BN[k]}</span><b>${r.b[k].rain["24h"] ?? "—"}㎜ · ${r.b[k].rain["1h"] ?? "—"}㎜/h</b><em>3시간 ${r.b[k].rain["3h"] ?? "—"}㎜</em></div>` : "").join("")}
      ${r.fc6h != null ? `<div class="rn"><span>앞으로</span><b>6시간 ${r.fc6h}㎜</b><em>${r.later ? `그 뒤 오늘 ${r.later.today} · 내일 ${r.later.tomorrow}㎜` : ""}</em></div>` : ""}</div>
    ${recs.length ? `<div class="dsec"><h5>이 묶음 기록</h5>${recs.slice(0, 6).map(x => `<div class="lg"><time>${x.at.slice(11, 16)}</time><b>${escH(x.act)}</b> ${escH(x.stage || "")} ${escH(x.note || "")}<i data-del="${x.id}">✕</i></div>`).join("")}</div>` : ""}</div>`;
}
/* 왼쪽 탭 — 지금 할 일(규칙 보고) · 위키 문서(문서 서식) · 물어보기 · 판단 기록 */
const SJ_PG = {};
const sjTabs = () => ["단계판", "지금 할 일", "위기경보와 비상단계", "통제·대피 기준", "시군 상황관리반 행동매뉴얼",
  ...(SJ.sg === "거제" ? ["거제시 단계별 업무"] : SJ.sg === "통영" ? ["통영시 단계별 업무"] : []), "판단 기록"];   // 물어보기는 떠 있는 AI 창(07d)
/* 왼쪽 탭 아이콘 — 한 줄에 다 들어가게. 고른 탭만 이름까지, 마우스를 대면 전체 이름 */
const SJ_TI = {
  단계판: '<rect x="1.5" y="2" width="3.5" height="12" rx="1"/><rect x="6.25" y="2" width="3.5" height="8" rx="1"/><rect x="11" y="2" width="3.5" height="5" rx="1"/>',
  "지금 할 일": '<path d="M2 4l1.3 1.3L5.6 3M2 8.5l1.3 1.3 2.3-2.3M2 13l1.3 1.3 2.3-2.3M8 4.2h6M8 8.7h6M8 13.2h6"/>',
  "위기경보와 비상단계": '<path d="M8 1.8L15 14H1z"/><path d="M8 6.2v3.6M8 11.6v.4"/>',
  "통제·대피 기준": '<path d="M6 2h7v12H6M9 8H1.5M4 5.5L1.5 8 4 10.5"/>',
  "시군 상황관리반 행동매뉴얼": '<circle cx="5.5" cy="5" r="2.2"/><circle cx="11" cy="5.6" r="1.8"/><path d="M1.5 13.5c0-2.4 1.8-4 4-4s4 1.6 4 4M10 9.6c2.4-.4 4.5 1 4.5 3.9"/>',
  "판단 기록": '<circle cx="8" cy="8" r="6.2"/><path d="M8 4.5V8l2.5 1.6"/>',
  book: '<path d="M2 2.5h4.5A1.5 1.5 0 018 4v10a1.5 1.5 0 00-1.5-1.5H2zM14 2.5H9.5A1.5 1.5 0 008 4v10a1.5 1.5 0 011.5-1.5H14z"/>',
};
const SJ_TN = { "위기경보와 비상단계": "비상단계", "통제·대피 기준": "통제·대피", "시군 상황관리반 행동매뉴얼": "상황관리반", "거제시 단계별 업무": "거제 매뉴얼", "통영시 단계별 업무": "통영 매뉴얼" };
const sjIn = s => escH(s).replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '<span class="wk">$2</span>').replace(/\[\[([^\]]+)\]\]/g, '<span class="wk">$1</span>')
  .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/&lt;br\s*\/?(&gt;|>)/g, "<br>");
function sjMd(md) {
  const L = String(md || "").split(/\r?\n/), out = [];
  for (let i = 0; i < L.length; i++) {
    const l = L[i];
    if (/^\s*\|/.test(l)) {                                 // 표 — 둘째 줄(---)은 건너뛴다
      const rows = [];
      while (i < L.length && /^\s*\|/.test(L[i])) rows.push(L[i++].trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim()));
      i--;
      const body = rows.filter((r, n) => !(n === 1 && r.every(c => /^:?-{2,}:?$/.test(c))));
      out.push(`<table><thead><tr>${body[0].map(c => `<th>${sjIn(c)}</th>`).join("")}</tr></thead><tbody>${body.slice(1).map(r => `<tr>${r.map(c => `<td>${sjIn(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    const co = /^>\s*\[!(\w+)\]\s*(.*)$/.exec(l);
    if (co || /^>\s?/.test(l)) {                             // 콜아웃 · 인용 — 이어진 '>' 줄을 한 덩어리로
      const box = [];
      if (co) i++;
      while (i < L.length && /^>\s?/.test(L[i])) box.push(L[i++].replace(/^>\s?/, ""));
      i--;
      out.push(`<div class="co ${co ? escH(co[1].toLowerCase()) : "q"}">${co && co[2] ? `<b class="ct">${sjIn(co[2])}</b>` : ""}${sjMd(box.join("\n"))}</div>`);
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(l), li = /^(\s*)([-*]|\d+[.)])\s+(.*)$/.exec(l);
    if (h) out.push(`<h${Math.min(6, h[1].length + 2)}>${sjIn(h[2])}</h${Math.min(6, h[1].length + 2)}>`);
    else if (li) out.push(`<div class="li${li[1].length ? " sub" : ""}"><i>${/\d/.test(li[2]) ? escH(li[2]) : "·"}</i><span>${sjIn(li[3])}</span></div>`);
    else if (l.trim() && !/^\s*(-{3,}|\*{3,})\s*$/.test(l)) out.push(`<p>${sjIn(l)}</p>`);
  }
  return out.join("");
}
async function sjTab(name) {
  SJ.tab = name;
  const box = $("sj-l");
  box.querySelectorAll("[data-tab]").forEach(b => b.classList.toggle("on", b.dataset.tab === name));
  const bd = box.querySelector(".mbd");
  if (name === "단계판") { bd.innerHTML = sjBoard(); return; }
  if (name === "지금 할 일") {
    const r = SJ.rep;
    bd.innerHTML = r ? `${r.flash ? `<div class="co warning"><b class="ct">속보</b><p>${sjIn(r.flash.text)}</p></div>` : ""}` + (r.sections || []).map(s => `<h4>${sjIn(s.h)}</h4>`
      + s.items.map(x => `<div class="li"><i>·</i><span>${sjIn(x)}</span></div>`).join("")).join("") : `<p class="mute">보고를 만드는 중…</p>`;
    return;
  }
  if (name === "판단 기록") {
    bd.innerHTML = (SJ.log.map(x => `<div class="lg"><time>${x.at.slice(5, 16).replace("T", " ")}</time><b>${escH(x.act)}</b> ${escH(x.sigun)} ${escH(x.emd || "")} ${escH(x.fam || "")} ${escH(x.stage || "")}${x.pct != null ? ` ${x.pct}%` : ""}${x.note ? ` — ${escH(x.note)}` : ""}<i data-del="${x.id}">✕</i></div>`).join("")
      || `<p class="mute">아직 없다 — 지구를 골라 오른쪽에서 결정하면 시각 · 도달률과 함께 남는다(서버 공유)</p>`) + `<form id="sj-note"><input maxlength="300" placeholder="메모 남기기"><button>남기기</button></form>`;
    return;
  }
  bd.innerHTML = `<p class="mute">읽는 중…</p>`;
  try { SJ_PG[name] ||= await getJson(`/api/wiki/page?name=${encodeURIComponent(name)}`); }
  catch (e) { bd.innerHTML = `<p class="mute">못 읽었다 — ${escH(e.message)}</p>`; return; }
  if (SJ.tab !== name) return;
  bd.innerHTML = `<div class="src">${escH(SJ_PG[name].src || "")}${SJ_PG[name].date ? ` · 기준일 ${escH(SJ_PG[name].date)}` : ""}</div>${sjMd(SJ_PG[name].text)}`;
}
function sjRender() {
  const d = SJ.d;
  if (!d) return;
  const all = SJ.sg === "all", h = d.head, gs = sjGroups(), n100 = gs.filter(g => g.met).length;
  const RVN = ["정상", "관심", "주의보", "경보", "심각"];
  const hud = [["특보", all ? "" : (h?.alerts || []).join(" · ") || "없음"], ["넘은 묶음", `${n100}`],
    ...(h?.river ? [[h.river.name.replace(/^[가-힣]+[시군]\(|\)$/g, ""), `${(+h.river.v).toFixed(2)}m ${RVN[h.river.stage] || ""}`]] : []),
    ...(h ? [["앞으로 6시간", `${h.fc6h}㎜`], ["오늘 · 내일 더", `${h.later.today} · ${h.later.tomorrow}㎜`]] : [])].filter(x => x[1])
    .map(([k, v]) => `<div><em>${escH(k)}</em><b>${escH(String(v))}</b></div>`).join("");
  $("sj-top").innerHTML = `<h2><select id="sj-sg" aria-label="시군">${["all", ...ORDER_GN()].map(s => `<option value="${s}"${s === SJ.sg ? " selected" : ""}>${s === "all" ? "경남 전체" : s}</option>`).join("")}</select></h2>
    <div class="ttl">상황판단<br><span>${d.tm ? `${+d.tm.slice(4, 6)}.${+d.tm.slice(6, 8)}. ${d.tm.slice(8, 10)}:${d.tm.slice(10, 12)} 실황` : ""}${window.GN_SNAP?.fake ? " · 가상 시연" : ""}</span></div>
    <div class="hud">${hud}</div>
    <span class="seg">${["grid", "aws"].map(k => `<button data-bs="${k}" class="${SJ.basis === k ? "on" : ""}">${SJ_BN[k]}</button>`).join("")}</span>
    <label class="cut"><input type="checkbox" id="sj-cut"${SJ.cut.on ? " checked" : ""}><input type="number" id="sj-cutp" min="10" max="100" step="5" value="${SJ.cut.pct}">% 이상</label>
    <div class="wif"><b>만약에</b><span class="wt">${[SJ.addH && `매시간 +${SJ.addH}㎜`, SJ.add24 && `24시간 +${SJ.add24}㎜`].filter(Boolean).join(" · ")}</span>
      <input type="range" id="sj-k" min="50" max="300" step="10" value="${Math.round(SJ.k * 100)}" title="초단기 · 단기예보 시우량 배수"><i>×${SJ.k.toFixed(1)}</i>
      <button class="cog" id="sj-cog" title="만약에 설정 — 매시간 · 24시간 더 오는 비" aria-label="만약에 설정">⚙</button>
      <div class="pop" id="sj-wpop"${SJ.wopen ? "" : " hidden"}><div class="kn"><span>매시간 더</span><input type="number" id="sj-addh" min="0" max="100" step="5" value="${SJ.addH}"><span>㎜ · 앞으로 24시간</span></div>
        <div class="kn"><span>24시간 안에 더</span><input type="number" id="sj-add24" min="0" max="500" step="10" value="${SJ.add24}"><span>㎜ · 고루 나눠</span></div>
        <div class="kn"><span></span><button id="sj-k0" class="g">처음대로</button><button id="sj-wok" class="g">닫기</button></div></div></div>
    <button class="aib${SJ.ai ? " on" : ""}" id="sj-aib" title="AI 묻기 — 떠 있는 창">AI 묻기</button>
    <span class="pn"><button data-pane="l" class="${SJ.pane.l ? "on" : ""}" title="왼쪽 패널(단계판 · 매뉴얼) 열기 · 닫기 — [" aria-label="왼쪽 패널 열기 · 닫기">◧</button><button data-pane="r" class="${SJ.pane.r ? "on" : ""}" title="오른쪽 패널(시간표 · 지구 상세) 열기 · 닫기 — ]" aria-label="오른쪽 패널 열기 · 닫기">◨</button></span>
    ${SJ_SOLO ? "" : `<button class="x" id="sj-x" aria-label="닫기 (Esc)">✕</button>`}`;
  sjPane("l", SJ.pane.l); sjPane("r", SJ.pane.r);
  let cur = -1, body = "";
  const shown = SJ.more ? gs : gs.filter((g, i) => g.sec < 3 || i < 60);
  for (const g of shown) {
    if (g.sec !== cur) { cur = g.sec; body += `<div class="sec s${cur}"><b>${SJ_SEC[cur]}</b><span>${gs.filter(x => x.sec === cur).length}</span></div>`; }
    body += sjGroup(g);
  }
  $("sj-c").innerHTML = `<div class="sjp" id="sj-plot">${sjPlotInner()}</div><div class="lh"><span>읍면동 · 유형</span><span>통제</span><span>사전대피</span><span>긴급대피</span><span>도달</span><span>지구</span></div>`
    + (body || `<div class="sj-ld">${SJ.cut.on ? `${SJ.cut.pct}% 이상인 곳이 없다` : "지구가 없다"}</div>`)
    + (gs.length > shown.length ? `<button class="more" id="sj-more">나머지 ${gs.length - shown.length}묶음 더 보기</button>` : "")
    + `<p class="mute foot">좌표가 있는 지구는 그 자리 비, 없으면(*) 읍면동 최대 칸 · 예보는 읍면동 · 색: 50 · 70 · 80 · 90 · 100% 이상</p>`;
  $("sj-d").innerHTML = sjDetail();
  if (!$("sj-l").querySelector(".mtab")) $("sj-l").innerHTML = `<div class="mtab"></div><div class="mbd"></div>`;
  $("sj-l").querySelector(".mtab").innerHTML = sjTabs().map(n => `<button data-tab="${escH(n)}" data-tip="${escH(n)}" aria-label="${escH(n)}">`
    + `<svg viewBox="0 0 16 16" aria-hidden="true">${SJ_TI[n] || SJ_TI.book}</svg><span>${escH(SJ_TN[n] || n)}</span></button>`).join("");
  sjTab(sjTabs().includes(SJ.tab) ? SJ.tab : "단계판");
  if (SJ.ai) sjAiDraw();
}
async function sjDecide(body) {
  try {
    const r = await fetch("/api/ai/decisions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.status);
    SJ.log = SJ.sg === "all" ? (await getJson("/api/ai/decisions")).rows : j.rows;
    sjRender();
    toast(`기록함 — ${body.act}${body.emd ? ` · ${body.emd}` : ""}`);
  } catch (e) { toast(`기록하지 못했다 — ${e.message}`); }
}
async function sjAsk(body, label) {
  const i = SJ.msgs.push(`<div class="msg me">${escH(label)}</div><div class="msg ai"><span class="mute">답을 찾는 중…${body.text ? " (AI — 로컬이면 1분쯤)" : ""}</span></div>`) - 1;
  SJ.ai = true; sjAiDraw(); $("sj-aib")?.classList.add("on");
  let a;
  try {
    const res = await fetch("/api/ai/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sigun: SJ.sg === "all" ? null : SJ.sg, ...body }) });
    a = await res.json();
    if (!res.ok) throw new Error(a.detail || res.status);
  } catch (e) { a = { sections: [{ h: "답", items: ["못 받았다 — " + e.message] }] }; }
  SJ.msgs[i] = `<div class="msg me">${escH(label)}</div><div class="msg ai">${a.text ? `<div class="mdt">${aiMd(a.text)}</div>` : aiSections(a.sections || [])}<div class="mute">${escH(a.source || "")}</div></div>`;
  if (SJ.ai) sjAiDraw();
}
function sjPick(sg, remote) {
  SJ.sg = sg; SJ.more = false; SJ.sel = null;
  if (!remote) { if (sg === "all") selectSig(null); else setSel([sg]); }   // 다른 창(지도)에도 간다 — setSel → sjSync
  sjLoad();
}
/* 두 창 맞추기 — 시군을 바꾸면 다른 창도 */
function sjSync(sel) { if (!SJ_REMOTE) SJ_BC?.postMessage({ sel }); }
if (SJ_BC) SJ_BC.onmessage = ev => {
  if (ev.data?.dzt != null) { if (!SJ_SOLO && typeof dzTime === "function") dzTime(ev.data.dzt, ev.data.lab); return; }
  const sel = ev.data?.sel;
  if (!Array.isArray(sel)) return;
  SJ_REMOTE = true;
  if (SJ_SOLO) { if ((sel[0] || "all") !== SJ.sg) sjPick(sel[0] || "all", true); }
  else if (sel.join() !== SELS.join()) setSel(sel);
  SJ_REMOTE = false;
};
$("sj").addEventListener("click", async ev => {
  const t = ev.target;
  if (t.closest("#sj-x")) return sjToggle(false);
  const pn = t.closest("[data-pane]");
  if (pn) return sjPane(pn.dataset.pane);
  const bs = t.closest("[data-bs]");
  if (bs) { SJ.basis = bs.dataset.bs; try { localStorage.setItem("gn-sj-basis", SJ.basis); } catch {} return sjLoad(true); }   // 시간별 줄은 그 기준만 받는다
  const cr = t.closest("[data-sg]");
  if (cr) return sjPick(cr.dataset.sg);
  const rr = t.closest("[data-r]");
  if (rr) { SJ.sel = rr.dataset.r; return sjRender(); }
  const tb = t.closest("[data-tab]");
  if (tb) return sjTab(tb.dataset.tab);
  const ac = t.closest("[data-act]");
  if (ac) {
    const r = SJ.d.rows.find(x => x.id === SJ.sel), s = ac.dataset.s, c = s ? sjB(r).st[s] : null;
    const old = SJ.log.find(x => x.sigun === r.sigun && x.emd === r.emd && x.fam === r.fam && x.act === ac.dataset.act && (x.note || "").includes(sjName(r)));
    if (old) { await fetch(`/api/ai/decisions/${old.id}`, { method: "DELETE" }); SJ.log = SJ.log.filter(x => x.id !== old.id); toast(`지움 — ${old.act}`); return sjRender(); }
    return sjDecide({ sigun: r.sigun, emd: r.emd, fam: r.fam, stage: s || null, act: ac.dataset.act, pct: c?.pct ?? sjB(r).top, eta: c?.eta || null, note: `지구 ${sjName(r)}` });
  }
  const ct = t.closest("[data-ct]");
  if (ct) { const r = SJ.d.rows.find(x => x.id === SJ.sel), [who, how] = ct.dataset.ct.split("|"); sjDecide({ sigun: r.sigun, emd: r.emd, fam: r.fam, act: "메모", note: `연락(${how}) — 지구 ${sjName(r)} 담당${who}` }); return; }
  if (t.closest("#sj-more")) { SJ.more = true; return sjRender(); }
  if (t.closest("#sj-cog") || t.closest("#sj-wok")) { SJ.wopen = t.closest("#sj-cog") ? !SJ.wopen : false; $("sj-wpop").hidden = !SJ.wopen; return; }
  if (t.closest("#sj-k0")) { Object.assign(SJ, { k: 1, addH: 0, add24: 0 }); return sjLoad(true); }
  const del = t.closest("[data-del]");
  if (del) { await fetch(`/api/ai/decisions/${del.dataset.del}`, { method: "DELETE" }); SJ.log = SJ.log.filter(x => String(x.id) !== del.dataset.del); return sjRender(); }
  const q = t.closest("[data-q]");
  if (q) sjAsk({ q: q.dataset.q }, q.textContent);
});
$("sj").addEventListener("submit", ev => {
  ev.preventDefault();
  const inp = ev.target.querySelector("input"), v = inp.value.trim();
  if (!v) return;
  inp.value = "";
  if (ev.target.classList.contains("sj-pin")) { try { localStorage.setItem("gn-ct-pin", v); } catch {} sjLoad(); return; }
  if (ev.target.id === "sj-note") sjDecide({ sigun: SJ.sg === "all" ? "경남" : SJ.sg, act: "메모", note: v });
  else sjAsk({ text: v }, v);
});
let SJ_KT = 0;
$("sj").addEventListener("change", ev => {
  const id = ev.target.id;
  if (id === "sj-sg") return sjPick(ev.target.value);
  if (id === "sj-cut" || id === "sj-cutp") {
    SJ.cut = { on: $("sj-cut").checked, pct: Math.max(10, Math.min(100, +$("sj-cutp").value || 70)) };
    try { localStorage.setItem("gn-sj-cut", JSON.stringify(SJ.cut)); } catch {}
    return sjRender();
  }
  if (id === "sj-addh" || id === "sj-add24") {
    SJ.addH = Math.max(0, +$("sj-addh").value || 0); SJ.add24 = Math.max(0, +$("sj-add24").value || 0);
    sjLoad(true);
  }
});
$("sj").addEventListener("input", ev => {
  if (ev.target.id !== "sj-k") return;
  SJ.k = +ev.target.value / 100;
  ev.target.nextElementSibling.textContent = `×${SJ.k.toFixed(1)}`;
  clearTimeout(SJ_KT);
  SJ_KT = setTimeout(() => sjLoad(true), 450);
});
$("b-sj").onclick = () => sjToggle(true);
document.addEventListener("keydown", ev => {
  if ($("sj").hidden || ev.ctrlKey || ev.metaKey || ev.altKey || ev.target.closest?.("input, textarea, select")) return;
  if (ev.key === "[") { ev.preventDefault(); sjPane("l"); }
  if (ev.key === "]") { ev.preventDefault(); sjPane("r"); }
});
if (SJ_SOLO) { document.title = "상황판단 — 경남"; setTimeout(() => sjToggle(true), 1200); }

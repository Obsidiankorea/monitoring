"use strict";
/* ── 폭염 화면 · 기온 표시 ─────────────────────────────────────────────────
   제목 앞 아이콘(🌧️ ↔ ☀️, M)으로 바꾼다. 같은 지도에 시군을 기온 색으로 칠하고 오른쪽 패널만 폭염 카드로.
   레이어 '기온'(E)은 호우 화면에서 시군 이름 밑에 기온만 곁들인다.
   기온은 /api/heat(AWS 정시 관측)만 실제 값. 체감온도 · 사흘 예보는 자료를 붙일 때까지 빈 칸으로 둔다 —
   틀을 미리 보도록 '예시' 단추로만 예시 값을 쓴다(화면에 예시임을 늘 적는다). */
let HEAT = false, HT = null, HT_T = 0, HT_EX = false, HT_AL = null;
const HT_ST = [25, 28, 31, 33, 35, 37];
const HT_C = ["#3A4A5E", "#6B6A4E", "#A5823A", "#D69A2C", "#EE7A22", "#E2401F", "#D6154A"];
const HT_LO = 20, HT_HI = 40, HT_WATCH = 33, HT_WARN = 35;          // 33 · 35 = 폭염주의보 · 경보 일 최고 체감(2일 이상)
const htCol = v => HT_C[HT_ST.filter(s => v >= s).length];
const htX = v => Math.max(0, Math.min(1, (v - HT_LO) / (HT_HI - HT_LO))) * 100;
const HT_DAY = ["오늘", "내일", "모레"], HT_LV = ["watch", "warn", "severe"];
function htExample() {
  const v = { 밀양: 37.1, 창녕: 36.8, 합천: 36.2, 함안: 36, 의령: 35.9, 김해: 35.6, 진주: 35.4, 양산: 35.2, 산청: 34.9, 창원: 34.8,
              함양: 34.6, 거창: 34.1, 하동: 33.6, 고성: 33.1, 사천: 32.9, 남해: 32.2, 통영: 31.8, 거제: 31.5 };
  const rows = Object.entries(v).map(([s, ta], i) => ({ sigun: s, stn: s, ta, hi: ta + .3, dt: +(((i * 7) % 11 - 4) / 10).toFixed(1),
    d: Array.from({ length: 24 }, (_, h) => +(ta - 8.5 + 8.5 * Math.sin(Math.PI * Math.min(h, 23) / 30)).toFixed(1)) }));
  return { tm: "2026-08-01 15:00", n: 53, rows, ex: true,
    fc: [["밀양", 37, 38, 36], ["창녕", 37, 37, 35], ["합천", 36, 37, 35], ["함안", 36, 36, 34], ["의령", 36, 35, 34], ["김해", 35, 35, 33]] };
}
const htData = () => (HT_EX ? htExample() : HT);
const htAlerts = () => (HT_EX ? [{ name: "폭염경보", lv: "warn", where: ["밀양", "창녕", "합천", "함안"] }, { name: "폭염주의보", lv: "watch", where: ["진주", "의령", "김해", "양산"] }]
  : (HT_AL?.land || []).filter(g => /폭염/.test(g.name)));
async function loadHeat() {
  clearTimeout(HT_T);
  if (!HEAT && !OV.has("temp")) { HT = null; drawHeat(); return; }
  try { HT = await getJson("/api/heat"); } catch (e) { HT = { err: e.message, rows: [] }; }
  if (HEAT) {
    try { const j = test ? testAlerts() : await getJson("/api/alerts"); HT_AL = parseAlerts(j); } catch { HT_AL = null; }
  }
  drawHeat(); renderHeat();
  HT_T = setTimeout(loadHeat, 5 * 60 * 1000);
}
/* 화면을 바꿀 때 한 번 — 폭염으로: 붉게 달아오르며 해가 돈다 · 호우로: 화면 가득 빗줄기. 누를 때만(켤 때 · 저장 없이 맞출 때는 안 한다) */
function modeFx(heat) {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  $("modefx")?.remove();
  const fx = document.createElement("div");
  fx.id = "modefx";
  fx.className = heat ? "sun" : "rain";
  fx.innerHTML = heat
    ? `<svg viewBox="-60 -60 120 120"><g class="ray">${Array.from({ length: 12 }, (_, i) => `<rect x="-3" y="-56" width="6" height="18" rx="3" transform="rotate(${i * 30})"/>`).join("")}</g><circle r="30"/></svg>`
    : Array.from({ length: 90 }, () => `<i style="left:${(Math.random() * 100).toFixed(1)}%;animation-delay:${(Math.random() * .7).toFixed(2)}s;animation-duration:${(.45 + Math.random() * .35).toFixed(2)}s;height:${(40 + Math.random() * 70).toFixed(0)}px"></i>`).join("");
  document.body.appendChild(fx);
  $("mode").classList.remove("spin"); void $("mode").offsetWidth; $("mode").classList.add("spin");
  setTimeout(() => fx.remove(), 1700);
}
function setHeat(on, save = true) {
  if (save && !!on !== HEAT) modeFx(!!on);
  HEAT = !!on;
  if (save) { try { localStorage.setItem("gn-map-heat", HEAT ? "1" : "0"); } catch {} }
  document.body.classList.toggle("heat", HEAT);
  const m = $("mode");
  m.textContent = HEAT ? "☀️" : "🌧️";
  m.title = `${HEAT ? "폭염" : "호우"} 화면 — 눌러서 ${HEAT ? "호우" : "폭염"} 화면으로 (M)`;
  m.setAttribute("aria-label", m.title);
  loadHeat();
  renderHeat();
  if (!HEAT) drawHeat();
  if (V) placeSw();
}
/* 지도 — 폭염 화면이면 시군 면 + 큰 숫자, 호우 화면에서 '기온'을 켰으면 시군 이름 밑에 작은 숫자 */
function drawHeat() {
  const t = $("tempg");
  if (!t) return;
  const D = htData(), by = Object.fromEntries((D?.rows || []).map(r => [r.sigun, r]));
  const gn = FEAT.filter(ft => ft.properties.kind !== "nb" && by[ft.properties.sigun]);
  const lvOf = {};                                        // 시군 → 가장 높은 폭염특보(주의보 뒤에 경보가 덮는다)
  for (const g of [...htAlerts()].sort((a, b) => HT_LV.indexOf(a.lv) - HT_LV.indexOf(b.lv)))
    for (const s of g.regs?.map(r => r[0]) ?? g.where) lvOf[s] = g.lv;
  // 면 · 특보 둘레는 GL 층 'heat*'(01b) — 둘레는 면 위 층이라 옆 시군 면에 묻히지 않는다
  const fill = HEAT ? gn.map(ft => [ft, htCol(by[ft.properties.sigun].ta), lvOf[ft.properties.sigun] || ""]) : [];
  glData("heat", fill.map(([ft, c, lv]) => ft.properties.sigun + c + lv).join(), () => fill.map(([ft, col, lv]) => glF(ft.geometry, { col, lv })));
  t.innerHTML = !(HEAT || OV.has("temp")) ? "" : gn.map(ft => {
    const p = ft.properties, r = by[p.sigun], st = nameStack(p.sigun), fs = FSN * (HEAT ? .78 : .52) * (st.n ? 0.85 : 1), x = V.toX(p.lx);
    const y = (HEAT || !st.n ? V.toY(p.ly) + FSN * .62 : st.below(p.ly)) + fs * .62;   // 호우 화면이면 딱지들 밑(05 nameStack)
    return `<text class="${HEAT ? "b" : ""}" x="${x.toFixed(1)}" y="${y.toFixed(1)}" style="font-size:${fs.toFixed(1)}px;stroke-width:${(fs * .2).toFixed(1)}px${HEAT ? "" : `;fill:${r.ta >= HT_ST[3] ? htCol(r.ta) : "var(--ink)"}`}">${r.ta.toFixed(1)}°</text>`;
  }).join("");
}
function htSpark(d) {
  const pts = d.map((v, i) => (v == null ? null : [i / Math.max(1, d.length - 1) * 100, 24 - htX(v) * .24])).filter(Boolean);
  const y33 = 24 - htX(HT_WATCH) * .24;
  return `<svg viewBox="0 0 100 24" preserveAspectRatio="none" aria-hidden="true"><line class="w" x1="0" x2="100" y1="${y33}" y2="${y33}"/>`
    + `<polyline points="${pts.map(p => p.map(n => n.toFixed(1)).join(",")).join(" ")}"/></svg>`;
}
function renderHeat() {
  if (!HEAT) return;
  const D = htData(), rows = [...(D?.rows || [])].sort((a, b) => b.ta - a.ta), k = V?.k || 1;
  $("ht-mark").hidden = !HT_EX;
  $("ht-ex").classList.toggle("on", HT_EX); $("ht-ex").setAttribute("aria-pressed", HT_EX);
  const tm = D?.tm ? D.tm.slice(11, 16) : "—";
  $("ht-bt").textContent = D?.tm ? `${tm} 관측` : "—";
  $("ht-time").textContent = D?.tm ? `${tm} 관측 · AWS ${D.n}곳${HT_EX ? "" : " · 기온 기준(체감온도 연결 전)"}` : "관측 기온 없음";
  // 아래 두 카드를 먼저 채운다 — 그래야 지금 기온 카드에 남는 높이로 줄 수를 잰다
  $("ht-fb").innerHTML = !D?.fc ? `<div class="ht-none"><b>체감온도 예보 연결 전</b><span>단기예보 기온 · 습도를 받으면 시군별 사흘 최고 체감과 2일 지속 여부가 이 표에 나온다.</span></div>`
    : `<div class="ht-tb"><div class="h"><span></span>${HT_DAY.map(d => `<span>${d}</span>`).join("")}<span>2일 지속</span></div>`
      + D.fc.map(([s, ...d]) => {
        const two = c => d.slice(0, -1).some((v, i) => v >= c && d[i + 1] >= c);
        const lab = two(HT_WARN) ? ["경보선", "w"] : two(HT_WATCH) ? ["주의선", "a"] : ["—", ""];
        return `<div><b>${s}</b>${d.map(v => `<i style="background:${htCol(v)}">${v}</i>`).join("")}<em class="${lab[1]}">${lab[0]}</em></div>`;
      }).join("") + `</div>`;
  const al = htAlerts();
  $("ht-ab").innerHTML = (al.length ? al.map(g => `<div class="ht-al ${g.lv}"><b>${escH(g.name)}</b><span>${g.where.map(escH).join(" · ")}</span></div>`).join("")
      : `<div class="ht-none s"><b>발효 중인 폭염특보 없음</b></div>`)
    + `<div class="ht-crit">주의보 일 최고 체감 33° · 경보 35° — 2일 이상 지속 예상</div>`;
  const body = $("ht-b");
  if (!rows.length) body.innerHTML = `<div class="ht-none"><b>기온 자료가 아직 없다</b><span>${D?.err ? escH(D.err) : "AWS 정시 수집이 돌면 시군별 기온이 여기 나온다."}</span></div>`;
  else {
    const top = rows[0], n33 = rows.filter(r => r.ta >= HT_WATCH).length, n35 = rows.filter(r => r.ta >= HT_WARN).length;
    const kpi = [[`${top.ta.toFixed(1)}°`, `최고 · ${top.sigun}`, top.ta >= HT_WATCH ? htCol(top.ta) : ""], [n35, "35° 이상 시군", n35 ? HT_C[5] : ""], [n33, "33° 이상 시군", n33 ? HT_C[4] : ""]]
      .map(([v, l, c]) => `<div><b${c ? ` style="color:${c}"` : ""}>${v}</b><span>${l}</span></div>`).join("");
    const room = body.clientHeight - 92 * k, rh = Math.max(24 * k, Math.min(38 * k, room / rows.length));
    const all = Math.floor(room / rh) >= rows.length, nr = all ? rows.length : Math.max(1, Math.floor((room - 22 * k) / rh));
    body.innerHTML = `<div class="ht-kpi">${kpi}</div>`
      + `<div class="ht-ax"><span></span><div><i class="l" style="left:${htX(HT_WATCH)}%">주의 33</i><i style="left:${htX(HT_WARN)}%">35 경보</i></div><span></span><span>24시간</span></div>`
      + rows.slice(0, nr).map((r, i) => `<div class="hr det" data-s="${r.sigun}" style="height:${rh.toFixed(1)}px" title="${r.sigun} ${escH(r.stn)} — 지금 ${r.ta.toFixed(1)}℃ · 오늘 최고 ${r.hi.toFixed(1)}℃">`
        + `<div class="nm2">${i < 3 ? `<span class="rk">${i + 1}</span>` : ""}<small>${r.sigun}</small>${escH(r.stn)}</div>`
        + `<div class="hb"><u style="width:${htX(r.ta).toFixed(1)}%;background:${htCol(r.ta)}"></u></div>`
        + `<b>${r.ta.toFixed(1)}<em class="${r.dt > 0 ? "up" : r.dt < 0 ? "dn" : ""}">${r.dt == null ? "" : `${r.dt > 0 ? "▲" : r.dt < 0 ? "▼" : "–"}${Math.abs(r.dt).toFixed(1)}`}</em></b>${htSpark(r.d)}</div>`).join("")
      + (nr < rows.length ? `<div class="case-note">외 ${rows.length - nr}곳 — 낮은 순이라 생략</div>` : "");
    rowEvents(body);
  }
  $("ht-lg").innerHTML = `<b>기온 ℃</b>` + [...HT_ST].reverse().map(s => `<div><i style="background:${htCol(s)}"></i>${s}${s === HT_WARN ? "<em>경보선</em>" : s === HT_WATCH ? "<em>주의선</em>" : ""}</div>`).join("")
    + `<div><i style="background:${HT_C[0]}"></i>25 미만</div>`;
}
$("mode").onclick = () => setHeat(!HEAT);
$("ht-ex").onclick = () => { HT_EX = !HT_EX; drawHeat(); renderHeat(); };
function heatBoot() {
  $("mode").hidden = !!CASE;
  let on = Q.get("heat") === "1";
  if (!Q.has("heat") && !CASE) { try { on = localStorage.getItem("gn-map-heat") === "1"; } catch {} }
  setHeat(on, false);
}

"use strict";
/* ── 우려지역 지구(U) — 위키 인명피해 우려지역 지구를 배지로: 동그라미 색 = 위험도(상황판단 기준 %), 안의 그림 = 유형 ──
   그림: 산사태 = 산과 구르는 돌 · 하천 = 물결 · 지하공간 = 지하차도 굴 · 침수·해안 = 집과 물 · 야외·기타 = 텐트.
   색: 상황판단과 같은 단계(50 · 70 · 80 · 90 · 100%), 50 아래 · 모름은 회색. % 는 /api/judge?sigun=all(5분마다) — 지도 기준(AWS · 격자)을 따른다.
   자료: /api/districts/all(좌표가 있는 지구) · /api/districts/shapes(필지 모양, 처음 켤 때 한 번). 배지 · 면은 GL 층(1,500곳 넘음).
   누르면 상황판단 창(map.html?sj)에서 그 지구를 연다. shortcut: 배지 그림은 색을 구워 넣는다 — 테마를 바꾸면 다음 갱신(5분)에 바뀐다. */
let DZ = null, DZ_SH = null, DZ_PCT = null, DZ_T = 0, DZ_TI = 0, DZ_TL = "";   // DZ_TI = 상황판단 창 재생 위치(0 = 지금)
const DZ_FAM = ["산사태", "하천", "지하공간", "침수·해안", "야외·기타"];
const DZ_LV = [0, 50, 70, 80, 90, 100];
const dzLv = p => (p == null ? 0 : p >= 100 ? 100 : p >= 90 ? 90 : p >= 80 ? 80 : p >= 70 ? 70 : p >= 50 ? 50 : 0);
const dzColVar = lv => (lv ? `var(--t${lv})` : "var(--dz-etc)");
GL_LAYERS.push(
  // 필지 모양 — 경남 전체에선 너무 작아 안 보이고, 시군을 확대하면 드러난다(위험도 색)
  { id: "dz-shape", type: "fill", source: "dzshape", paint: { "fill-color": ["get", "col"], "fill-opacity": 0.3 } },
  { id: "dz-edge", type: "line", source: "dzshape", paint: { "line-color": ["get", "col"], "line-width": 1.2, "line-opacity": 0.9 } },
  { id: "dz", type: "symbol", source: "dz",
    layout: { "icon-image": ["get", "ic"], "icon-allow-overlap": true, "icon-ignore-placement": true, "symbol-sort-key": ["get", "lv"],
              "icon-size": ["interpolate", ["linear"], ["zoom"], 8, 0.62, 11, 0.9, 14, 1.15] } },
);
/* 배지 그림 — 40×40(화면 20px, 2배 해상도). 동그라미(위험도 색 · 어두운 테두리) 안에 흰 그림 */
function dzGlyph(c, fam) {
  c.fillStyle = c.strokeStyle = "#fff"; c.lineWidth = 3; c.lineCap = c.lineJoin = "round";
  c.beginPath();
  if (fam === "산사태") {                                // 산 + 구르는 돌
    c.moveTo(8, 29); c.lineTo(18, 12); c.lineTo(24, 21); c.lineTo(27, 17); c.lineTo(32, 29); c.closePath(); c.fill();
    c.beginPath(); c.arc(29.5, 11.5, 2.6, 0, 7); c.fill();
  } else if (fam === "하천") {                           // 물결 두 줄
    for (const y of [16, 25]) { c.moveTo(8, y); c.bezierCurveTo(12, y - 5, 16, y + 5, 20, y); c.bezierCurveTo(24, y - 5, 28, y + 5, 32, y); }
    c.stroke();
  } else if (fam === "지하공간") {                       // 지하차도 굴 + 길
    c.moveTo(9, 29); c.lineTo(9, 20); c.arc(20, 20, 11, Math.PI, 0); c.lineTo(31, 29); c.stroke();
    c.beginPath(); c.moveTo(20, 23); c.lineTo(20, 29); c.stroke();
  } else if (fam === "침수·해안") {                      // 집 + 물
    c.moveTo(11, 18); c.lineTo(20, 10); c.lineTo(29, 18); c.lineTo(29, 23); c.lineTo(11, 23); c.closePath(); c.fill();
    c.beginPath(); c.moveTo(8, 29); c.bezierCurveTo(12, 25, 16, 33, 20, 29); c.bezierCurveTo(24, 25, 28, 33, 32, 29); c.stroke();
  } else {                                               // 텐트(야영장 · 낚시터 · 기타)
    c.moveTo(8, 29); c.lineTo(20, 10); c.lineTo(32, 29); c.closePath(); c.fill();
    c.globalCompositeOperation = "destination-out"; c.beginPath(); c.moveTo(20, 18); c.lineTo(15, 29); c.lineTo(25, 29); c.closePath(); c.fill();
    c.globalCompositeOperation = "source-over";
  }
}
function dzIcons() {
  for (const fam of DZ_FAM) for (const lv of DZ_LV) {
    const id = `dz-${fam}-${lv}`;
    if (GL.hasImage(id)) continue;
    const cv = document.createElement("canvas"); cv.width = cv.height = 40;
    const c = cv.getContext("2d");
    const g = document.createElement("canvas"); g.width = g.height = 40;
    dzGlyph(g.getContext("2d"), fam);
    c.beginPath(); c.arc(20, 20, 17.5, 0, 7);
    c.fillStyle = cssVal(dzColVar(lv)); c.fill();
    c.lineWidth = 2.5; c.strokeStyle = cssVal("var(--dz-ring)"); c.stroke();
    c.drawImage(g, 0, 0);
    GL.addImage(id, c.getImageData(0, 0, 40, 40), { pixelRatio: 2 });
  }
}
async function loadDistrict() {
  clearTimeout(DZ_T);
  if (!OV.has("district") || CASE) { DZ = null; drawDistrict(); districtLegend(); return; }
  try { DZ = await getJson("/api/districts/all"); } catch (e) { DZ = { fail: e.message }; }
  if (!DZ_SH && !DZ.fail) { try { DZ_SH = await getJson("/api/districts/shapes"); } catch { DZ_SH = { features: [] }; } }
  drawDistrict(); districtLegend(); renderLyIcons();
  try {                                                  // 위험도 — 경남 전체 판정은 몇 초 걸린다(뒤에 칠한다)
    const j = await getJson("/api/judge?sigun=all&series=1");
    DZ_PCT = Object.fromEntries(j.rows.map(r => [r.id, { grid: [r.b.grid?.top, ...(r.b.grid?.series?.v || [])],
                                                         aws: [r.b.aws?.top, ...(r.b.aws?.series?.v || [])], where: r.where }]));
  } catch { DZ_PCT = DZ_PCT || {}; }
  drawDistrict(); districtLegend();
  DZ_T = setTimeout(loadDistrict, 5 * 60 * 1000);
}
const dzRows = () => (OV.has("district") && DZ?.rows ? DZ.rows.filter(r => selHas(r.sigun)) : []);
const dzPct = r => { const v = DZ_PCT?.[r.id]?.[ACC_BASIS === "grid" ? "grid" : "aws"]; return v ? v[Math.min(DZ_TI, v.length - 1)] ?? null : null; };
/* 상황판단 창이 재생 위치를 보냈다 — 배지 색을 그 시각으로(0 이면 지금) */
function dzTime(i, lab) { DZ_TI = +i || 0; DZ_TL = DZ_TI ? lab || "" : ""; drawDistrict(); districtLegend(); }
function drawDistrict() {
  if (!GL_OK) return;
  const rows = dzRows(), on = OV.has("district") && DZ?.rows;
  if (on) dzIcons();
  const key = on ? `${DZ.rows.length}|${SELS.join()}|${ACC_BASIS}|${DZ_PCT ? Object.keys(DZ_PCT).length : 0}|${DZ_T}|${DZ_TI}` : "";
  const lv = new Map(rows.map(r => [r.id, dzLv(dzPct(r))]));
  glData("dz", key, () => rows.map(r => glF({ type: "Point", coordinates: LCCF(r.pos[1], r.pos[0]) },
    { id: r.id, lv: lv.get(r.id), ic: `dz-${DZ_FAM.includes(r.fam) ? r.fam : "야외·기타"}-${lv.get(r.id)}` })));
  glData("dzshape", key && DZ_SH ? key : "", () => (DZ_SH?.features || []).filter(f => lv.has(f.properties.id))
    .map(f => glF(glPoly(f.geometry.coordinates.map(ring => ring.map(p => LCCF(p[0], p[1])))),
      { id: f.properties.id, col: cssVal(dzColVar(lv.get(f.properties.id))) })));
}
/* 마우스 — 배지가 먼저, 아니면 필지 면 */
function districtAt(mx, my) {
  if (!OV.has("district") || !GL_OK || !DZ?.rows) return null;
  const f = GL.queryRenderedFeatures([[mx - 5, my - 5], [mx + 5, my + 5]], { layers: ["dz"] })[0]
    || GL.queryRenderedFeatures([mx, my], { layers: ["dz-shape"] })[0];
  const r = f && DZ.rows.find(x => x.id === f.properties.id);
  return r ? { dz: r } : null;
}
function districtTip(r) {
  const where = [r.ri, r.jibun].filter(x => x && x !== "–").join(" ");
  const name = r.name && !/구$/.test(r.name) && r.name !== "–" ? r.name : where || r.emd;
  const p = dzPct(r), w = DZ_PCT?.[r.id]?.where;
  return `<b>${escH(name)}</b> · ${escH(r.kind || r.fam)}${p != null ? ` · <b style="color:${dzColVar(dzLv(p))}">${p}%</b>` : ""}`
    + `<div class="d">${escH(r.sigun)} ${escH(r.emd)} ${escH(where)}</div>`
    + (p != null ? `<div class="d">기준 대비 가장 높은 단계 — ${ACC_BASIS === "grid" ? "격자" : "AWS"} 기준${w === "읍면동" ? " · 좌표 없이 읍면동 값" : ""}</div>` : "")
    + (r.approx ? `<div class="d">위치는 근사 — 지번으로 못 찾아 그 리 · 읍면동 가운데(판정은 읍면동 기준)</div>` : "")
    + (r.rule ? `<div class="d">대피기준 ${escH(r.rule)}</div>` : "")
    + (r.shelter && r.shelter !== "–" ? `<div class="d">대피장소 ${escH(r.shelter)}</div>` : "")
    + `<div class="d">누르면 상황판단 창에서 이 지구</div>`;
}
function districtOpen(r) {
  const u = `/map.html?sj=1&sig=${encodeURIComponent(r.sigun)}&r=${encodeURIComponent(r.id)}`;
  if (!window.open(u, "gn-judge", "popup=1,width=1680,height=1000")) toast("팝업이 막혔다 — 이 사이트의 팝업을 허용한다");
}
TIPS.set("district-now", `위키 인명피해 우려지역 지구. 동그라미 색은 상황판단의 기준 % 중 가장 높은 단계(지도 기준 AWS · 격자를 따른다, 5분마다), 안의 그림은 유형.<br>
  좌표는 연속지적도(국가공간정보포털) 필지 중심, 못 찾은 곳은 브이월드. 넓은 필지(하천 · 도로 · 임야)는 중심 한 점이라 실제 위험 지점과 다를 수 있다 — 위키 data/지구좌표_수동.csv 에 적으면 그것을 쓴다.`);
/* 배지 그림 한 장(data URL) — 범례 · 상황판단 차트가 같은 그림을 쓴다 */
const DZ_URL = {};
function dzBadgeUrl(fam, lv) {
  fam = DZ_FAM.includes(fam) ? fam : "야외·기타";
  const k = `${fam}-${lv}`;
  if (DZ_URL[k]) return DZ_URL[k];
  const cv = document.createElement("canvas"); cv.width = cv.height = 40;
  const c = cv.getContext("2d");
  c.beginPath(); c.arc(20, 20, 17.5, 0, 7); c.fillStyle = cssVal(dzColVar(lv)); c.fill();
  c.lineWidth = 2.5; c.strokeStyle = cssVal("var(--dz-ring)"); c.stroke();
  const g = document.createElement("canvas"); g.width = g.height = 40; dzGlyph(g.getContext("2d"), fam); c.drawImage(g, 0, 0);
  return (DZ_URL[k] = cv.toDataURL());
}
const dzBadge = (fam, lv) => `<img src="${dzBadgeUrl(fam, lv)}" width="20" height="20" alt="" style="flex:none">`;
function districtLegend() {
  const box = $("ly-district");
  if (!box) return;
  if (!OV.has("district")) { box.hidden = true; return; }
  box.hidden = LY_OPEN !== "district";
  if (box.hidden) return;
  const rows = dzRows(), g = DZ?.geo;
  const hot = rows.filter(r => (dzPct(r) ?? 0) >= 70).length;
  const body = !DZ ? `<div class="nt">읽는 중…</div>` : DZ.fail ? `<div class="nt w">불러오지 못했다 — ${escH(DZ.fail)}</div>`
    : DZ_FAM.map(f => `<div class="rr">${dzBadge(f, 0)}<b>${f}</b><span>${rows.filter(r => r.fam === f).length}곳</span></div>`).join("")
      + `<div class="sec">색 = 기준 대비 % (${ACC_BASIS === "grid" ? "격자" : "AWS"})${DZ_TI ? ` · <b>${escH(DZ_TL)} 예상</b>(상황판단 재생)` : ""}</div>`
      + `<div class="keys2">${DZ_LV.map(lv => `<span><i class="dt" style="background:${dzColVar(lv)}"></i>${lv ? `${lv}%↑` : "50 아래"}</span>`).join("")}</div>`
      + `<div class="nt">${DZ_PCT ? `70% 넘은 지구 ${hot}곳` : "위험도 계산 중…"} · ${selOn() ? `고른 시군 ${rows.length}곳` : `경남 ${rows.length}곳`}${g ? ` · 좌표 ${g.found}/${g.total}` : ""} — 확대하면 필지 모양</div>`;
  box.innerHTML = `<div class="hd2" title="눌러서 닫기"><b>우려지역 지구</b><i class="inf" data-tip="district-now">i</i></div>` + body;
  box.querySelector(".hd2").onclick = ev => { if (!ev.target.closest(".inf")) setLyOpen(null); };
}

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
/* 표시 방식 — icon: 동그라미 배지 + 그림(가까이서) / shape: 작은 도형 + 색(경남 전체에서 덜 겹친다). 범례에서 바꾼다(이 브라우저 기억)
   도형 = 유형(산사태 ▲ · 하천 ● · 지하공간 ■ · 침수·해안 ◆ · 야외·기타 ✚), 색 = 위험도(50 아래는 흰색 — 청색 강수 위에서 보이게) */
let DZ_STYLE = "icon", DZ_TIP = true;                  // DZ_TIP — 마우스를 올리면 지구 카드를 띄운다(끄면 눌렀을 때만)
try { DZ_TIP = localStorage.getItem("gn-dz-tip") !== "0"; } catch {}
try { DZ_STYLE = localStorage.getItem("gn-dz-style") || "icon"; } catch {}
if (["icon", "shape", "off"].includes(new URLSearchParams(location.search).get("dz"))) DZ_STYLE = new URLSearchParams(location.search).get("dz");   // ?dz=shape — 벽면 화면용
const DZ_SHAPE_LOW = "#F2F5FA";
function dzShape(c, fam, col) {
  c.fillStyle = col; c.strokeStyle = "#0B0F17"; c.lineWidth = 2.6; c.lineJoin = "round";
  c.beginPath();
  if (fam === "산사태") { c.moveTo(14, 3); c.lineTo(25, 23); c.lineTo(3, 23); c.closePath(); }
  else if (fam === "하천") c.arc(14, 14, 9.5, 0, 7);
  else if (fam === "지하공간") c.rect(5, 5, 18, 18);
  else if (fam === "침수·해안") { c.moveTo(14, 2); c.lineTo(26, 14); c.lineTo(14, 26); c.lineTo(2, 14); c.closePath(); }
  else { c.moveTo(10, 3); c.lineTo(18, 3); c.lineTo(18, 10); c.lineTo(25, 10); c.lineTo(25, 18); c.lineTo(18, 18); c.lineTo(18, 25);
    c.lineTo(10, 25); c.lineTo(10, 18); c.lineTo(3, 18); c.lineTo(3, 10); c.lineTo(10, 10); c.closePath(); }
  c.stroke(); c.fill();
}
const dzShapeCol = lv => (lv ? cssVal(`var(--t${lv})`) : DZ_SHAPE_LOW);
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
    const sid = `dzs-${fam}-${lv}`;
    if (!GL.hasImage(sid)) {
      const cv = document.createElement("canvas"); cv.width = cv.height = 28;
      dzShape(cv.getContext("2d"), fam, dzShapeCol(lv));
      GL.addImage(sid, cv.getContext("2d").getImageData(0, 0, 28, 28), { pixelRatio: 2 });
    }
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
  drawDistrict(); districtLegend(); renderLyIcons(); loadVuln();
  try {                                                  // 위험도 — 경남 전체 판정은 몇 초 걸린다(뒤에 칠한다)
    // 경남 전체는 지금 % 만(빠르다), 시군을 골랐으면 그 시군은 시간별 줄까지(마우스 글 그래프 · 재생) — 경남 전체 시간별은 수십 초 걸렸다
    const sb = ACC_BASIS === "grid" ? "grid" : "aws";
    const [j, ...sj] = await Promise.all([getJson("/api/judge?sigun=all"), ...SELS.map(sg => getJson(`/api/judge?sigun=${encodeURIComponent(sg)}&series=1&sb=${sb}`).catch(() => null))]);
    for (const x of sj.filter(Boolean)) {
      const by = new Map(x.rows.map(r => [r.id, r]));
      j.rows = j.rows.map(r => by.get(r.id) || r);
      j.regions = x.regions;
    }
    const one = dzOne;
    DZ_REG = j.regions || DZ_REG;
    DZ_PCT = Object.fromEntries(j.rows.map(r => [r.id, { grid: one(r.b.grid), aws: one(r.b.aws), where: r.where }]));
  } catch { DZ_PCT = DZ_PCT || {}; }
  drawDistrict(); districtLegend();
  DZ_T = setTimeout(loadDistrict, 5 * 60 * 1000);
}
const dzOne = b => b && { v: [b.top, ...(b.series?.v || [])], xy: b.series?.xy || {}, t: b.series?.t || [], pl: b.series?.pl || [], pp: b.series?.pp || [], site: b.series?.site || [], fc: b.fc, obs: b.obs };
/* 고르지 않은 시군 지구에 마우스를 올리면 — 그 시군 시간별 줄을 그때 받는다(경남 전체 시간별은 수십 초라 미리 받지 않는다). 시군마다 5분에 한 번 */
const DZ_SQ = new Map();
function dzSerLoad(sg) {
  const t = DZ_SQ.get(sg);
  if (t && (t.ing || Date.now() - t.at < 5 * 60e3)) return;
  DZ_SQ.set(sg, { ing: true, at: Date.now() });
  getJson(`/api/judge?sigun=${encodeURIComponent(sg)}&series=1&sb=${ACC_BASIS === "grid" ? "grid" : "aws"}`).then(j => {
    DZ_REG = j.regions || DZ_REG; DZ_PCT = DZ_PCT || {};
    for (const r of j.rows) DZ_PCT[r.id] = { grid: dzOne(r.b.grid), aws: dzOne(r.b.aws), where: r.where };
    DZ_SQ.set(sg, { at: Date.now() });
    if (TIP_PIN?.sigun === sg) { const t = $("tip"), l = t.style.left, tp = t.style.top; tipPin(TIP_PIN, 0, 0); t.style.left = l; t.style.top = tp; }
  }).catch(() => DZ_SQ.delete(sg));
}
const dzRows = () => (OV.has("district") && DZ?.rows ? DZ.rows.filter(r => selHas(r.sigun)) : []);
const dzSer = r => DZ_PCT?.[r.id]?.[ACC_BASIS === "grid" ? "grid" : "aws"];
const dzPct = r => { const v = dzSer(r)?.v; return v ? v[Math.min(DZ_TI, v.length - 1)] ?? null : null; };
/* ── 단계 영역 평면(06e · 07c 같이 쓴다) — 가로 누적(지하공간은 15분) ㎜ × 세로 시우량 ㎜/h 위에 통제 · 사전대피 · 긴급대피 영역.
   '그리고' = 그 점에서 오른쪽 위 네모, '또는' = 영역을 합친 의자(ㄱ) 모양(서버 ai.regions). 70% 자리에 옅은 점선 테두리(근접).
   지구 원문 기준(자홍 흐르는 점선)도 같은 평면에. 지구의 비는 한 줄 — 시간색(흰 지금 → 보라 내일). 축 끝을 넘는 값은 끝에 붙인다.
   앞으로의 15분은 예보가 없다 — 지하공간은 시우량 ÷ 4 로 어림(점선) */
let DZ_REG = null;
// 평면은 밝은 회색 바탕(불투명) — 어두운 지도 위에서도 또렷하게(11-07). 단계 색: 통제 노랑 · 사전대피 파랑 · 긴급대피 빨강.
// 면은 불투명한 연한 색, 높은 단계가 위에 덮는다(겹친 곳 = 더 높은 단계). 테두리는 진한 같은 색.
const STG_COL = { 통제: "#C99A00", 사전대피: "#1F63D6", 긴급대피: "#D21F1F", "지구 기준": "#1F2430" };
const STG_FILL = { 통제: "#FFF0B3", 사전대피: "#CFE1FF", 긴급대피: "#FFCFCF" };
const PP_BG = "#F2F4F7", PP_INK = "#1F2430", PP_INK3 = "#6B7280", PP_LINE = "#C5CBD5", PP_SITE = "#C026D3";
/* 평면에 보일 단계 — 지도 범례 · 상황판단 창이 같이 쓴다(이 브라우저 기억) */
let PP_SHOW = new Set(["통제", "사전대피", "긴급대피"]);
try { const v = JSON.parse(localStorage.getItem("gn-pp-st") || "null"); if (Array.isArray(v)) PP_SHOW = new Set(v); } catch {}
function ppToggle(st) {
  PP_SHOW.has(st) ? PP_SHOW.delete(st) : PP_SHOW.add(st);
  try { localStorage.setItem("gn-pp-st", JSON.stringify([...PP_SHOW])); } catch {}
}
const ppChips = () => ["통제", "사전대피", "긴급대피"].map(st => `<button data-pps="${st}" class="ppc${PP_SHOW.has(st) ? " on" : ""}" style="--c:${STG_COL[st]};--f:${STG_FILL[st]}">${st}</button>`).join("");
function ppScale(reg, W, H, L = 34, B = 20, T = 8, R = 8) {
  const ar = reg.areas.length ? reg.areas : reg.site || [];   // 공통 영역이 없는 유형(침수·해안 · 야외·기타)은 지구 기준으로 축을 잡는다
  const xs = ar.map(a => a.x).filter(v => v != null), ys = ar.map(a => a.y).filter(v => v != null);
  const xm = Math.ceil(Math.max(...xs, 10) * 1.3 / 10) * 10, ym = Math.ceil(Math.max(...ys, 10) * 1.4 / 5) * 5;
  return { xm, ym, L, B, T, R, W, H, X: v => L + Math.min(Math.max(v ?? 0, 0), xm) / xm * (W - L - R), Y: v => T + (1 - Math.min(Math.max(v ?? 0, 0), ym) / ym) * (H - T - B) };
}
const STG_ORD = { 통제: 0, 사전대피: 1, 긴급대피: 2 };
function ppAreas(reg, S, o = {}) {
  const { X, Y, xm, ym, L, T, W, H, B } = S, x1 = X(xm), y0 = Y(0);
  const shape = (a, k = 1) => a.kind === "rect" ? `M${X(a.x * k)},${Y(ym)}H${x1}V${Y(a.y * k)}H${X(a.x * k)}Z`
    : a.kind === "band" ? `M${L},${Y(ym)}H${x1}V${Y(a.y * k)}H${L}Z` : `M${X(a.x * k)},${Y(ym)}H${x1}V${y0}H${X(a.x * k)}Z`;
  const shown = reg.areas.filter(a => PP_SHOW.has(a.stage)).sort((p, q) => STG_ORD[p.stage] - STG_ORD[q.stage]);
  let s = `<rect x="0" y="0" width="${W}" height="${H}" fill="${PP_BG}"/>`;
  // 면(낮은 단계부터 — 높은 단계가 위에 덮는다). 취약시간 띠는 면 없이 점선만
  for (const a of shown) if (!a.night) s += `<path d="${shape(a)}" fill="${STG_FILL[a.stage]}"/>`;
  for (const a of shown) {
    const c = STG_COL[a.stage];
    s += `<path d="${shape(a)}" fill="none" stroke="${c}" stroke-width="${a.night ? 1.4 : 1.8}"${a.night ? ' stroke-dasharray="5 3"' : ""}/>`
      + (a.night ? "" : `<path d="${shape(a, 0.7)}" fill="none" stroke="${c}" stroke-opacity=".55" stroke-dasharray="2 4"/>`);
  }
  // 지구 자체 기준 — 단계 색(노 · 파 · 빨)과 겹치지 않는 자홍 굵은 점선 + 흰 테두리(움직이면 눈이 아프다 해서 멈춘 선)
  const site = (o.site || []).filter(a => a.kind !== "text");
  for (const a of site) s += `<path d="${shape(a)}" fill="none" stroke="#fff" stroke-width="5" stroke-opacity=".9"/>`
    + `<path d="${shape(a)}" fill="none" stroke="${PP_SITE}" stroke-width="2.6" stroke-dasharray="9 5" stroke-linecap="round"/>`;
  // 띠마다 원래 창(3시간 90㎜ …) — 가로축과 창이 다른 조건이 같은 축에 놓이므로 무엇의 선인지 적는다
  site.forEach((a, i) => { if (a.lab) s += `<text x="${(a.kind === "band" ? L : X(a.x)) + 4}" y="${a.kind === "band" ? Y(a.y) - 4 : T + 10 + i * ((o.fs || 10) + 1)}" fill="${PP_SITE}" stroke="#fff" stroke-width="3" paint-order="stroke" font-size="${(o.fs || 10) - 1}" font-weight="700">${a.lab}</text>`; });
  const all = [...shown, ...site];
  // 눈금 글자가 붙으면(250 · 270) 겹쳐 읽히지 않는다 — 앞 글자와 가로 22px · 세로 11px 안이면 뺀다(선은 그대로)
  const thin = (vs, P, gap) => { let last = -1e9; return vs.filter(v => { const ok = Math.abs(P(v) - last) >= gap; if (ok) last = P(v); return ok; }); };
  const tx = thin([...new Set(all.map(a => a.x).filter(v => v != null))].sort((a, b) => a - b), X, 22 * (o.fs || 10) / 10),
        ty = thin([...new Set(all.map(a => a.y).filter(v => v != null))].sort((a, b) => a - b), Y, 11 * (o.fs || 10) / 10);
  s += `<line x1="${L}" x2="${x1}" y1="${y0}" y2="${y0}" stroke="${PP_INK3}"/><line x1="${L}" x2="${L}" y1="${T}" y2="${y0}" stroke="${PP_INK3}"/>`
    + tx.map(v => `<text x="${X(v)}" y="${H - B + 13}" text-anchor="middle" fill="${PP_INK}" font-size="${o.fs || 10}" font-weight="600">${v}</text>`).join("")
    + ty.map(v => `<text x="${L - 3}" y="${Y(v) + 3}" text-anchor="end" fill="${PP_INK}" font-size="${o.fs || 10}" font-weight="600">${v}</text>`).join("");
  return s;
}
/* 영역 색 범례 한 줄 */
const ppKey = (reg, site) => [...new Set(reg.areas.map(a => a.stage))].filter(st => PP_SHOW.has(st)).map(st => `<span><i style="background:${STG_FILL[st]};border:2px solid ${STG_COL[st]}"></i>${st}</span>`).join("")
  + (site?.length ? `<span><i class="sk"></i>지구 기준</span>` : "") + (reg.areas.some(a => a.night && PP_SHOW.has(a.stage)) ? `<span><i class="nk"></i>취약시간</span>` : "");
const ppPt = (reg, p) => (p ? [reg.x === "15분" ? (p[2] ?? (p[1] != null ? p[1] / 4 : null)) : p[0], p[1]] : null);
/* 밝은 바탕용 시간색 — 진한 검정(지금) → 빨 · 주 · 노 · 초 · 파 · 남 · 보(내일), 명도를 낮춰 흰 바탕에서도 보이게 */
const ppTimeCol = f => (f <= 0 ? "#111827" : `hsl(${Math.round(270 * f)} 90% 40%)`);
/* 한 지구 자취 — full 이면 끝까지 시간색, 아니면 ti 까지 옅은 선. 15분 어림 구간은 점선 */
/* 지구 자체 기준 한 줄 — 조건마다 원래 창 그대로, '또는'으로. 평면에 못 그린 것(12시간 등)은 글로만이라고 적는다 */
function siteText(site) {
  if (!site?.length) return "";
  const off = site.filter(a => a.kind === "text").length;
  return `이 지구 자체 기준: ${site.map(a => a.lab).join(" 또는 ")}${off ? ` — ${site.filter(a => a.kind === "text").map(a => a.lab).join(" · ")}는 그림에 없음` : ""}`;
}
function ppTrail(reg, S, pl, ti, full, col) {
  const pts = pl.map((p, i) => [ppPt(reg, p), i]).filter(([p]) => p && p[0] != null && p[1] != null), n = pl.length, end = full ? n - 1 : ti;
  let s = "";
  for (let k = 1; k < pts.length; k++) {
    const [a] = pts[k - 1], [b, i] = pts[k];
    if (i > end) break;
    const dash = reg.x === "15분" && pl[i]?.[2] == null ? ' stroke-dasharray="3 3"' : "";
    s += `<line x1="${S.X(a[0]).toFixed(1)}" y1="${S.Y(a[1]).toFixed(1)}" x2="${S.X(b[0]).toFixed(1)}" y2="${S.Y(b[1]).toFixed(1)}" stroke="${col || ppTimeCol(i / (n - 1))}" stroke-width="${col ? 1.4 : 2.6}" stroke-opacity="${col ? 0.6 : 1}" stroke-linecap="round"${dash}/>`;
  }
  return s;
}
/* 마우스 글 — 단계 사다리. 위키 [[통제·대피 기준]]: 통제 → 사전대피 → 긴급대피 순으로 올라간다(사전대피는 예보, 긴급대피는 실황).
   ① 지금 단계 줄(평시 · 통제 · 사전대피 · 긴급대피 — 지금 칸 채움, 다음 칸 점선) ② 세 단계 막대(70 근접 · 100 도달 눈금, 도달 시각)
   ③ 다음 단계 하나의 조건 평면. 국지성 폭우는 단계를 건너뛸 수 있어 — 뒤 단계가 다음 단계보다 많이 찼으면 경고를 붙이고 그 평면을.
   축 끝은 PLANE_MAX(143%) — 100% 가 축의 70% 자리. 넘으면 끝에 붙인다(100 넘은 뒤는 의미가 적다).
   자취 색 = 시간: 흰색(지금) → 빨 · 주 · 노 · 초 · 파 · 남 · 보(내일 23시). 어두운 바탕이라 밝은 색으로 */
const dzTimeCol = f => (f <= 0 ? "#FFFFFF" : `hsl(${Math.round(270 * f)} 95% 68%)`);
const DZ_STG = ["통제", "사전대피", "긴급대피"], PLANE_MAX = 143;
const dzStageP = p => (p ? Math.round(Math.min(p[0] ?? 0, p[1] ?? 0)) : null);
function dzPhase(s, ti) {
  const st = DZ_STG.filter(x => s?.xy?.[x]), at = (x, i) => dzStageP(s.xy[x][Math.min(i, s.xy[x].length - 1)]);
  const met = st.filter(x => (at(x, ti) ?? 0) >= 100), cur = met.length ? met[met.length - 1] : null;
  const next = st.find(x => DZ_STG.indexOf(x) > DZ_STG.indexOf(cur) && (at(x, ti) ?? 0) < 100) || null;
  const skip = next && st.find(x => DZ_STG.indexOf(x) > DZ_STG.indexOf(next) && (at(x, ti) ?? 0) >= 70 && (at(x, ti) ?? 0) > (at(next, ti) ?? 0));   // 뒤 단계가 근접(70↑)이면서 더 찼을 때만
  const eta = x => { const j = s.xy[x].findIndex((p, k) => k >= ti && (dzStageP(p) ?? 0) >= 100); return j < 0 ? null : j; };
  return { st, at, cur, next, skip, eta, plane: skip || next || cur };
}
function dzMiniPlane(r) {
  const s = dzSer(r);
  if (!s?.xy) return "";
  const ph = dzPhase(s, DZ_TI);
  if (!ph.st.length) return "";
  const T = ["지금", ...(s.t || [])], at = i => (i <= 0 ? "지금" : `${T[i]}시`);
  // ① 지금 단계 줄
  const strip = ["평시", ...DZ_STG].map(x => {
    const on = (ph.cur || "평시") === x, nx = ph.next === x;
    return `<span class="${on ? "on" : nx ? "nx" : ""}${on && x !== "평시" ? ` s${DZ_STG.indexOf(x)}` : ""}">${on ? "▶ " : ""}${x}</span>`;
  }).join("");
  // ② 세 단계 막대 — 0~143% 를 막대 너비로, 70 · 100 눈금
  const BW = 150, bx = v => Math.min(v ?? 0, PLANE_MAX) / PLANE_MAX * BW;
  const bars = ph.st.map(x => {
    const v = ph.at(x, DZ_TI), j = ph.eta(x), lv = dzLv(v);
    return `<div class="dzb"><span>${x}</span><svg width="${BW}" height="10"><rect width="${BW}" height="10" fill="var(--line)"/>`
      + `<rect width="${bx(v).toFixed(1)}" height="10" fill="${dzColVar(lv)}"/><line x1="${bx(70)}" x2="${bx(70)}" y1="0" y2="10" stroke="var(--t70)"/>`
      + `<line x1="${bx(100)}" x2="${bx(100)}" y1="0" y2="10" stroke="var(--t100)" stroke-width="1.5"/></svg>`
      + `<em style="color:${dzColVar(lv)}">${v ?? "—"}%</em><small>${v >= 100 ? "넘음" : j != null ? `${at(j)} 도달` : "안 닿음"}</small></div>`;
  }).join("");
  // ③ 오른쪽 — 단계 영역 평면(셋을 한 평면에, 지금 다음 단계를 진하게) · 지구 원문 기준 자홍 흐르는 점선 · 비가 아닌 조건은 글로
  const reg = DZ_REG?.[r.fam], n = (s.pl || []).length;
  let plane = "";
  if (reg && n) {
    const S = ppScale({ ...reg, site: s.site }, 230, 190, 30, 22, 8, 8), cur = Math.min(DZ_TI, n - 1), pn = ppPt(reg, s.pl[cur]);
    // 지난 자취(검은 선) — 지도 누적 구간만큼(지난 6시간 누적이면 6시간 전부터 지금까지). 15분 축은 지난 15분 값이 없어 그리지 않는다
    const H = Math.min(48, Math.max(1, accSpan().H || 6)), past = reg.x === "15분" ? [] : (s.pp || []).slice(-H);
    const xy = p => { const q = ppPt(reg, p); return q && q[0] != null && q[1] != null ? [+S.X(q[0]).toFixed(1), +S.Y(q[1]).toFixed(1)] : null; };
    const pxy = [...past, s.pl[0]].map(xy).filter(Boolean);
    const run = [...past.map((p, i) => [xy(p), `${past.length - i}시간 전`]), ...s.pl.map((p, i) => [xy(p), at(i)])].filter(([q]) => q);
    const black = pxy.length > 1 ? `<polyline points="${pxy.map(q => q.join(",")).join(" ")}" fill="none" stroke="#111827" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>`
      + pxy.slice(0, -1).map(q => `<circle cx="${q[0]}" cy="${q[1]}" r="1.8" fill="#111827"/>`).join("") : "";
    plane = `<div class="ppbox" data-run="${escH(JSON.stringify(run)).replace(/"/g, "&quot;")}"><div class="ppk">${ppKey(reg, s.site)}</div><svg width="230" height="190" viewBox="0 0 230 190">${ppAreas(reg, S, { site: s.site })}${black}${ppTrail(reg, S, s.pl, cur, true)}`
      + (pn && pn[0] != null && pn[1] != null ? `<circle cx="${S.X(pn[0])}" cy="${S.Y(pn[1])}" r="5" fill="#111827" stroke="#fff" stroke-width="1.5"/>` : "")
      + `<circle class="pp-run" r="6" fill="#fff" stroke="#111827" stroke-width="2" visibility="hidden"/><text class="pp-lab" x="40" y="14" fill="#111827" font-size="11" font-weight="700"></text>`
      + `<text x="225" y="${190 - 4}" text-anchor="end" fill="${PP_INK3}" font-size="9.5">${reg.x}(㎜) →</text></svg>`
      + `<div class="dzk lt">${run.length > 1 ? `<button class="pp-play" type="button" title="지난 ${past.length}시간 → 지금 → 예보 끝까지 점이 움직인다">▶</button>` : ""}${past.length ? `<span class="pk">━ 지난 ${past.length}시간</span>` : ""}<span>지금</span><i></i><span>${escH(at(n - 1))}</span></div></div>`;
  }
  const texts = (reg?.texts || []).map(x => `<div class="d">· ${escH(x.stage)}: ${escH(x.text)}</div>`).join("");
  const head = ph.skip ? `<b style="color:var(--t100)">⚠ ${ph.skip}가 ${ph.next}보다 더 찼다 — 단계를 건너뛸 수 있음(국지성 폭우)</b>`
    : ph.next ? `다음 단계 <b>${ph.next}</b>${ph.eta(ph.next) != null ? ` · ${at(ph.eta(ph.next))} 도달 예상` : " · 내일까지 안 닿음"}` : `<b style="color:var(--t100)">${ph.cur} 기준까지 넘음</b>`;
  const site = s.site?.length ? siteText(s.site, reg).replace("이 지구 자체 기준: ", "") : "";
  // 도달 시점으로 가른 두 줄(지금 값만) — 예보로 닿는 것과 실제 내린 비로 닿은 것은 무게가 다르다(예보 = 권고, 실황 = 실행)
  const one = (k, v) => `<div class="dz2" title="${escH(v?.rule || "")}"><span>${k}</span>${v ? `<b style="color:${dzColVar(dzLv(v.pct))}">${v.pct}%</b><small>${STG_EMO[v.stage] || ""} ${v.stage}${v.met ? " 충족" : ""}</small>` : `<small>견줄 값 없음</small>`}</div>`;
  const two = DZ_TI === 0 && (s.fc || s.obs) ? one("예보 기준", s.fc) + one("실황 기준", s.obs) : "";
  return { strip, bars, head, texts, plane, site, two };
}
/* 상황판단 창이 재생 위치를 보냈다 — 배지 색을 그 시각으로(0 이면 지금) */
function dzTime(i, lab) { DZ_TI = +i || 0; DZ_TL = DZ_TI ? lab || "" : ""; drawDistrict(); districtLegend(); }
function drawDistrict() {
  if (!GL_OK) return;
  const rows = dzRows(), on = OV.has("district") && DZ?.rows;
  if (on) dzIcons();
  const key = on ? `${DZ.rows.length}|${SELS.join()}|${ACC_BASIS}|${DZ_PCT ? Object.keys(DZ_PCT).length : 0}|${DZ_T}|${DZ_TI}|${DZ_STYLE}` : "";
  const lv = new Map(rows.map(r => [r.id, dzLv(dzPct(r))]));
  glData("dz", key, () => DZ_STYLE === "off" ? [] : rows.map(r => glF({ type: "Point", coordinates: LCCF(r.pos[1], r.pos[0]) },
    { id: r.id, lv: lv.get(r.id), ic: `${DZ_STYLE === "shape" ? "dzs" : "dz"}-${DZ_FAM.includes(r.fam) ? r.fam : "야외·기타"}-${lv.get(r.id)}` })));
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
/* 지구 마우스 카드(게임 HUD 처럼) — ① 머리: 유형 배지 · 이름 · 큰 % ② 단계 트랙 ③ 왼쪽 단계 막대 · 다음 목표 · 비가 아닌 조건 / 오른쪽 조건 평면
   ④ 지구 자체 기준(평면의 자홍 선과 같은 색 띠) ⑤ 대피기준 · 대피장소 표. #tip 에 .hudtip 을 붙여 줄바꿈 · 너비를 카드에 맡긴다(11-misc) */
/* 평면 재생(▶) — 지난 자취 → 지금 → 예보 끝까지 점을 한 시간씩 옮긴다. 고정한 카드 · 상황판단 창에서 누른다 */
function ppPlay(box) {
  const run = JSON.parse(box.dataset.run || "[]"), c = box.querySelector(".pp-run"), lab = box.querySelector(".pp-lab");
  if (!run.length || !c) return;
  const btn = box.querySelector(".pp-play"), stop = () => { clearInterval(box._t); box._t = null; if (btn) btn.textContent = "▶"; };
  if (box._t) { stop(); return; }                        // 도는 중에 누르면 멈춤 — 다시 누르면 그 자리부터
  let i = box._i < run.length ? box._i || 0 : 0;         // 끝까지 갔으면 처음부터
  const step = () => {
    const [[x, y], t] = run[i];
    c.setAttribute("cx", x); c.setAttribute("cy", y); c.setAttribute("visibility", "visible"); lab.textContent = t;
    box._i = ++i;
    if (i >= run.length) stop();
  };
  if (btn) btn.textContent = "⏸";
  box._t = setInterval(step, Math.max(120, Math.min(400, 6000 / run.length))); step();
}
document.addEventListener("click", ev => {
  const b = ev.target.closest?.(".pp-play");
  if (b) { ev.stopPropagation(); ppPlay(b.closest(".ppbox")); }
}, true);
/* 지형 칸(서버 /api/districts/all 의 tg — app/terrain.py 값) — 카드 왼쪽 빈자리에 */
function dzTerrainRows(g) {
  if (!g) return "";
  const m = v => `${Math.round(v).toLocaleString()}m`, row = (k, v) => v ? `<div class="tr"><span>${k}</span><b>${v}</b></div>` : "";
  return row("표고", g.el != null ? `${g.el.toFixed(0)}m${g.el <= 10 ? " · 저지대" : ""}` : "")
    + row("경사", g.sl != null ? `${g.sl}°${g.sl >= 30 ? " · 급경사" : g.sl < 20 ? " · 완만" : ""}` : "")
    + row("하천", g.rv ? `${escH(g.rv.n || "하천")} ${m(g.rv.d)}${g.rv.dh != null ? ` · ${g.rv.dh >= 0 ? `${g.rv.dh.toFixed(0)}m 위` : `${(-g.rv.dh).toFixed(0)}m 아래`}` : ""}` : "")
    + row("저수지", g.lk ? `${escH(g.lk.n || "저수지")} ${m(g.lk.d)}${g.lk.dh != null ? ` · 지구가 ${Math.abs(g.lk.dh).toFixed(0)}m ${g.lk.dh >= 0 ? "낮음" : "높음"}` : ""}` : "")
    + row("해안", g.cs != null && g.cs <= 3000 ? m(g.cs) : "")
    + row("건물", g.b300 ? `${g.b300.toLocaleString()}동(300m)` : "")
    + row("취약지역", g.sv ? `산사태취약지역(${escH(g.sv.ty)}) ${g.sv.d}m${g.sv.n > 1 ? ` · 300m 안 ${g.sv.n}곳` : ""}` : "")
    + row("노후", g.bk ? `<span title="사용승인 30년 넘은 목 · 벽돌 · 블록 · 조적 · 석 구조 — 300m 안, 건축물대장이 붙은 ${g.bk}동 가운데(대장 없는 옛집은 못 센다)">오래된 약한 구조 ${g.bo || 0}동${g.bb ? ` · 지하층 ${g.bb}동` : ""} <small>/ 대장 ${g.bk}동</small></span>` : "");
}
/* 담당자 연락처 — 고정한 카드에서만(상황판단과 같은 /api/contacts · 잠금 번호). AI 쪽 코드는 부르지 않는다 */
const DZ_CT = new Map();
async function dzContacts(r) {
  const box = $("tip").querySelector(".ctb");
  if (!box) return;
  let c = DZ_CT.get(r.sigun);
  if (!c || Date.now() - c.at > 60e3) {
    try {
      const res = await fetch(`/api/contacts?sigun=${encodeURIComponent(r.sigun)}`, { headers: { "x-pin": sjPin() }, cache: "no-store" });
      c = { at: Date.now(), ...(res.status === 401 ? { pin: true } : res.status === 429 ? { err: "잠금 번호를 여러 번 틀렸다 — 5분 뒤" } : await res.json()) };
      if (!c.pin && !c.err) DZ_CT.set(r.sigun, c);
    } catch (e) { c = { err: e.message }; }
  }
  if (!$("tip").contains(box)) return;
  const ppl = c.people?.[r.id] || [];
  box.innerHTML = c.pin ? `<form class="dz-pin"><input type="password" inputmode="numeric" autocomplete="off" placeholder="연락처 잠금 번호"><button>열기</button></form>`
    : c.err ? `<span class="mute">${escH(c.err)}</span>` : c.on === false ? `<span class="mute">연락처 파일이 없다</span>`
    : ppl.map((p, n) => `<div class="tr"><span>${escH((p.who || "").replace(/담당부서\s*/g, "") || `담당${n + 1}`)}</span>${p.tel ? `<a class="tel" href="tel:${escH(p.tel.replace(/[^0-9-]/g, ""))}">📞 ${escH(p.tel)}</a>` : `<em class="mute">번호 없음</em>`}</div>`).join("")
      || `<span class="mute">이 지구 담당자가 표에 없다</span>`;
  box.querySelector(".dz-pin")?.addEventListener("submit", ev => {
    ev.preventDefault();
    try { localStorage.setItem("gn-ct-pin", ev.target.querySelector("input").value); } catch {}
    DZ_CT.delete(r.sigun); dzContacts(r);
  });
}
function districtTip(r, pin = false) {
  const where = [r.ri, r.jibun].filter(x => x && x !== "–").join(" ");
  const name = r.name && !/구$/.test(r.name) && r.name !== "–" ? r.name : where || r.emd;
  const p = dzPct(r), w = DZ_PCT?.[r.id]?.where, col = dzColVar(dzLv(p)), m = dzMiniPlane(r);
  const row = (k, v) => v && v !== "–" ? `<dt>${k}</dt><dd>${escH(v)}</dd>` : "";
  return `<div class="hud${m ? "" : " sm"}">`
    + `<div class="hd"><span class="bdg">${escH(r.kind || r.fam)}</span><div class="nm"><b>${escH(name)}</b><small>${escH(r.sigun)} ${escH(r.emd)} ${escH(where)}</small></div>`
    + (p != null ? `<div class="pc" style="--c:${col}"><b>${p}<i>%</i></b><small>${ACC_BASIS === "grid" ? "격자" : "AWS"} 기준${w === "읍면동" ? " · 읍면동 값" : ""}</small></div>` : "") + `</div>`
    + (m ? `<div class="dzs">${m.strip}</div>`
      + `<div class="bd"><div class="lf">${m.bars}${m.two}<div class="goal">${m.head}</div>`
      + (m.texts ? `<div class="sub">비가 아닌 조건</div>${m.texts}` : "")
      + (r.tg ? `<div class="sub">지형</div><div class="tgs">${dzTerrainRows(r.tg)}</div>` : "")
      + (pin ? `<div class="sub">담당</div><div class="ctb tgs"><span class="mute">불러오는 중…</span></div>` : "") + `</div><div class="rt">${m.plane}</div></div>`
      + (m.site ? `<div class="site"><span>지구 기준</span><b>${escH(m.site)}</b></div>` : "")
      : `<div class="d">${(dzSerLoad(r.sigun), DZ_SQ.get(r.sigun)?.ing) ? "단계 그래프 받는 중… (마우스를 다시 올리면 나온다)" : DZ_FAM.slice(0, 3).includes(r.fam) ? "단계 그래프를 그릴 자료가 없다 — 예보를 못 받았다" : "단계 그래프가 없다 — 이 유형은 행안부 지침 별표 4(산사태 · 하천 · 지하공간)에 없고, 이 지구의 시군 기준도 비의 양으로 읽히지 않는다"}</div>`)
    + (r.tf?.length ? `<div class="tfs">${r.tf.map(f => `<em class="tf${f.lv === "w" ? "" : " i"}">${escH(f.t)}</em>`).join("")}</div>` : "")   // 지역 여건(app/terrain.py)
    + (r.approx ? `<div class="d warn">위치는 근사 — 지번으로 못 찾아 그 리 · 읍면동 가운데(판정은 읍면동 기준)</div>` : "")
    + (r.rule || r.shelter ? `<dl>${row("대피기준", r.rule)}${row("대피장소", r.shelter)}</dl>` : "")
    + (!m && r.tg ? `<div class="sub pad">지형</div><div class="tgs pad">${dzTerrainRows(r.tg)}</div>` : "")
    + (!m && pin ? `<div class="sub pad">담당</div><div class="ctb tgs pad"><span class="mute">불러오는 중…</span></div>` : "")
    + `<div class="ft">${pin ? "고정 — 밖을 누르거나 Esc 로 닫기 · ▶ 지난 자취부터 재생 · " : "왼쪽 클릭 — 고정(담당 연락처) · "}오른쪽 클릭 — 상황판단 모드 · 카카오맵${pin ? `<button class="x" data-unpin title="닫기 (Esc)">✕</button>` : ""}</div></div>`;
}
function districtOpen(r) {
  const u = `/map.html?sj=1&sig=${encodeURIComponent(r.sigun)}&r=${encodeURIComponent(r.id)}`;
  if (!window.open(u, "gn-judge", "popup=1,width=1680,height=1000")) toast("팝업이 막혔다 — 이 사이트의 팝업을 허용한다");
}
TIPS.set("vuln-now", `<b>산사태취약지역</b> — 산사태 · 토석류로 인명 · 재산 피해가 우려돼 <b>「산림재난방지법」 제22조</b>(옛 「산림보호법」 제45조의8)에 따라 지정 · 고시한 곳. 소관은 산림청 · 도 산림휴양과 · 시군 산림부서.<br>
  <b>우려지역 지구와 무엇이 다른가</b><br>
  · 우려지역 지구(동그라미 배지) — 행안부 「인명피해우려지역 지정 · 관리 지침」으로 시군 재난부서가 올린 지구. 대피 · 통제 기준이 붙어 있어 판정 % 와 알림이 나온다.<br>
  · 산사태취약지역(마름모) — 산림청 기초조사(5년마다) → 시군 · 지방산림청 실태조사(현장 70 + 해석 30점) → 지정위원회 심의 → 30일 이상 공고 · 이의신청 → 지정 · 고시. 기준 % 가 없어 <b>위치만</b> 보인다.<br>
  <b>두 종류</b><br>
  · 산사태 — 비탈이 무너질 우려(위험사면 가까이 집 · 보호시설). 산지사방을 먼저 한다.<br>
  · 토석류 — 계곡을 따라 흙 · 돌 · 물이 쏟아질 우려(계류 아래 인가). 사방댐 · 계류보전을 먼저 한다.<br>
  <b>지정되면</b> 사방사업 우선 시행, 연 2회 이상 현지점검(대피소 포함), 대피소 · 표지판 설치, 위험할 때 사용 제한 · 안전조치 명령(법 제22조 · 제25조).<br>
  <b>빠지는 것</b> 급경사지 · 붕괴위험지역(급경사지법), 도로 · 접도구역(도로법), 시설물(시설물안전법)은 대상이 아니다 — 아파트 뒤 인공 비탈면 같은 곳은 여기에 없다.<br>
  <b>겹침(이 지도에서 잰 것)</b> 산사태 유형 우려지역 지구 712곳 중 457곳은 300m 안에 취약지역이 있다. 거꾸로 취약지역 2,528곳 중 산사태 우려지역 지구가 300m 안에 있는 곳은 486곳뿐이다.<br>
  <b>지정 밖에서도 난다</b> 2016~2026 경남 산사태 복구 지점 중 위치를 아는 267건에서 취약지역 300m 안은 23건(9%)이었다(복구비가 집행된 지점 기준 · 필지 가운데 좌표라 어림).<br>
  <b>자료</b> 공공데이터포털 「경상남도_산사태취약지역지정현황」 2026-05-01 — 2,591곳 중 지번이 좌표로 바뀐 2,528곳. 자리는 필지 가운데쯤이라 실제 위험 사면 · 계류와 수백 m 어긋날 수 있다. 마우스를 올리면 지번 · 지정면적 · 지정대피소. 켜고 끄기는 이 패널에서(산사태 레이어 J 를 켜도 같이 보인다).`);
TIPS.set("district-now", `위키 인명피해 우려지역 지구. 동그라미 색은 상황판단의 기준 % 중 가장 높은 단계(지도 기준 AWS · 격자를 따른다, 5분마다), 안의 그림은 유형.<br>
  좌표는 연속지적도(국가공간정보포털) 필지 중심, 못 찾은 곳은 브이월드. 넓은 필지(하천 · 도로 · 임야)는 중심 한 점이라 실제 위험 지점과 다를 수 있다 — 위키 data/지구좌표_수동.csv 에 적으면 그것을 쓴다.<br>필지 모양: 시군을 눌러 확대한 뒤 그 안 읍면동을 누르면 더 확대되어 필지가 면으로 보인다(Ctrl+클릭 여러 곳, Esc 로 한 단계씩).`);
/* 배지 그림 한 장(data URL) — 범례 · 상황판단 차트가 같은 그림을 쓴다 */
const DZ_URL = {};
function dzBadgeUrl(fam, lv, col) {                     // col 을 주면 위험도 대신 그 색(상황판단 차트의 유형 색)
  fam = DZ_FAM.includes(fam) ? fam : "야외·기타";
  const k = `${fam}-${lv}-${col || ""}`;
  if (DZ_URL[k]) return DZ_URL[k];
  const cv = document.createElement("canvas"); cv.width = cv.height = 40;
  const c = cv.getContext("2d");
  c.beginPath(); c.arc(20, 20, 17.5, 0, 7); c.fillStyle = col || cssVal(dzColVar(lv)); c.fill();
  c.lineWidth = 2.5; c.strokeStyle = cssVal("var(--dz-ring)"); c.stroke();
  const g = document.createElement("canvas"); g.width = g.height = 40; dzGlyph(g.getContext("2d"), fam); c.drawImage(g, 0, 0);
  return (DZ_URL[k] = cv.toDataURL());
}
function dzShapeUrl(fam, lv) {
  const k = `s-${fam}-${lv}`;
  if (DZ_URL[k]) return DZ_URL[k];
  const cv = document.createElement("canvas"); cv.width = cv.height = 28;
  dzShape(cv.getContext("2d"), DZ_FAM.includes(fam) ? fam : "야외·기타", dzShapeCol(lv));
  return (DZ_URL[k] = cv.toDataURL());
}
const dzBadge = (fam, lv) => `<img src="${DZ_STYLE === "shape" ? dzShapeUrl(fam, lv) : dzBadgeUrl(fam, lv)}" width="${DZ_STYLE === "shape" ? 14 : 20}" height="${DZ_STYLE === "shape" ? 14 : 20}" alt="" style="flex:none">`;
function districtLegend() {
  const box = $("ly-district");
  if (!box) return;
  if (!OV.has("district")) { box.hidden = true; return; }
  box.hidden = LY_OPEN !== "district";
  if (box.hidden) return;
  const rows = dzRows(), g = DZ?.geo;
  const hot = rows.filter(r => (dzPct(r) ?? 0) >= 70).length;
  const body = !DZ ? `<div class="nt">읽는 중…</div>` : DZ.fail ? `<div class="nt w">불러오지 못했다 — ${escH(DZ.fail)}</div>`
    : `<div class="seg dzst">${[["icon", "아이콘"], ["shape", "도형"], ["off", "끔"]].map(([k, l]) => `<button data-dzs="${k}" class="${DZ_STYLE === k ? "on" : ""}">${l}</button>`).join("")}</div>`
      + `<label class="nt" style="display:flex;gap:6px;align-items:center;cursor:pointer"><input type="checkbox" data-dztip ${DZ_TIP ? "checked" : ""}>마우스를 올리면 지구 카드 띄우기 <span class="mute">(끄면 눌러야 뜬다)</span></label>`
      + DZ_FAM.map(f => `<div class="rr">${dzBadge(f, 0)}<b>${f}</b><span>${rows.filter(r => r.fam === f).length}곳</span></div>`).join("")
      + `<div class="sec">산사태취약지역 <i class="inf" data-tip="vuln-now">i</i></div>`
      + `<label class="nt" style="display:flex;gap:6px;align-items:center;cursor:pointer"><input type="checkbox" data-vuln ${SAF_VON ? "checked" : ""}>지도에 마름모로 보이기 <span class="mute">${SAF_V ? `${SAF_V.filter(s => selHas(s.sg)).length}곳` : ""}</span></label>`
      + `<div class="keys2"><span><i class="dt" style="background:var(--sf-slide);transform:rotate(45deg);border-radius:0"></i>토석류</span><span><i class="dt" style="background:#E08A2B;transform:rotate(45deg);border-radius:0"></i>산사태</span></div>`
      + `<div class="nt">산림부서가 「산림재난방지법」으로 지정한 곳 — 위 우려지역 지구(재난부서, 행안부 지침)와 <b>다른 명단</b>이다. 위치만 보이고 판정 % · 알림은 없다.</div>`
      + `<div class="sec">색 = 기준 대비 % (${ACC_BASIS === "grid" ? "격자" : "AWS"})${DZ_TI ? ` · <b>${escH(DZ_TL)} 예상</b>(상황판단 재생)` : ""}</div>`
      + `<div class="keys2">${DZ_LV.map(lv => `<span><i class="dt" style="background:${dzColVar(lv)}"></i>${lv ? `${lv}%↑` : "50 아래"}</span>`).join("")}</div>`
      + `<div class="nt">${DZ_PCT ? `70% 넘은 지구 ${hot}곳` : "위험도 계산 중…"} · ${selOn() ? `고른 시군 ${rows.length}곳` : `경남 ${rows.length}곳`}${g ? ` · 좌표 ${g.found}/${g.total}` : ""}</div>`
      + `<div class="nt">필지 모양 보기: 시군을 누르고 → 그 안 읍면동을 누르면 확대 · 오른쪽 클릭 → 상황판단</div>`
      + `<div class="nt"><button class="lk" data-crit>유형별 판정 기준표 ↗</button> · <button class="lk" data-dzg>좌표 확인 · 고치기${g ? ` (없음 ${g.total - g.found})` : ""} ↗</button></div>`
      + (DZ_STYLE === "off" ? `<div class="nt">표시 끔 — 필지 면만 남긴다(시군 · 읍면동을 확대하면 보인다)</div>` : "");
      + `<div class="sec">마우스 글 단계 그래프에 보일 단계</div><div class="ppcs">${ppChips()}</div>`;
  box.innerHTML = `<div class="hd2" title="눌러서 닫기"><b>우려지역 지구</b><i class="inf" data-tip="district-now">i</i></div>` + body;
  box.querySelector(".hd2").onclick = ev => { if (!ev.target.closest(".inf")) setLyOpen(null); };
  box.querySelector("[data-crit]")?.addEventListener("click", () => openHelp("crit"));
  box.querySelector("[data-dzg]")?.addEventListener("click", () => dzDlg(true));
  box.querySelector("[data-vuln]")?.addEventListener("change", ev => {
    SAF_VON = ev.target.checked;
    try { localStorage.setItem("gn-vuln", SAF_VON ? "1" : "0"); } catch {}
    if (SAF_VON && !SAF_V) loadVuln(); else { drawSafety(); districtLegend(); }
  });
  box.querySelector("[data-dztip]")?.addEventListener("change", ev => {
    DZ_TIP = ev.target.checked;
    try { localStorage.setItem("gn-dz-tip", DZ_TIP ? "1" : "0"); } catch {}
  });
  for (const b of box.querySelectorAll("[data-pps]")) b.onclick = () => { ppToggle(b.dataset.pps); districtLegend(); };
  for (const b of box.querySelectorAll("[data-dzs]")) b.onclick = () => {
    DZ_STYLE = b.dataset.dzs;
    try { localStorage.setItem("gn-dz-style", DZ_STYLE); } catch {}
    drawDistrict(); districtLegend();
  };
}

/* ── 좌표 확인 · 고치기 — 근사(리 · 읍면동 가운데) · 좌표 없는 지구를 목록으로, 위도 · 경도를 넣거나 지도에서 찍는다 ──
   넣은 값은 서버 DB(dz_pos)에 — 가장 먼저 쓰인다(위키 파일은 PC 에서 보내면 덮어써져서). 지우면 원래(지적도 · 브이월드)로.
   시군 담당자에게 확인한 자리를 넣는 용도. 시연 서버는 바꾸지 않는다 */
let DZG = null, DZ_PICK = null;
const DZ_DLG = { f: "need", q: "", sg: "", focus: null }, DZ_EDIT = {};
const dzDlgOpen = () => !!$("dzdlg") && !$("dzdlg").hidden;
async function dzDlg(open = true, focus = null) {
  let el = $("dzdlg");
  if (!el) {
    el = document.createElement("div");
    el.id = "dzdlg"; el.hidden = true;
    document.body.appendChild(el);
    el.addEventListener("click", dzDlgClick);
    el.addEventListener("input", ev => { if (ev.target.id === "dzg-q") { DZ_DLG.q = ev.target.value; dzDlgList(); } });
    el.addEventListener("change", ev => { if (ev.target.id === "dzg-sg") { DZ_DLG.sg = ev.target.value; dzDlgList(); } });
  }
  el.hidden = !open;
  if (!open) return;
  if (focus) Object.assign(DZ_DLG, { focus, f: "all", q: "", sg: "" });
  if (!DZG) {
    el.innerHTML = `<div class="box"><p class="mute">읽는 중…</p></div>`;
    try { DZG = await getJson("/api/districts/geo"); } catch (e) { el.innerHTML = `<div class="box"><p>못 읽었다 — ${escH(e.message)}</p></div>`; return; }
  }
  const need = DZG.rows.filter(r => !r.pos || r.approx).length, sgs = [...new Set(DZG.rows.map(r => r.sigun))];
  el.innerHTML = `<div class="box" role="dialog" aria-label="지구 좌표 확인 · 고치기">
    <div class="top"><b>지구 좌표 확인 · 고치기</b><span class="mute">확인 필요 ${need}곳 / ${DZG.rows.length}곳</span><span class="sp"></span><button data-x title="닫기 (Esc)">✕</button></div>
    <div class="bar"><span class="seg">${[["need", "확인 필요(근사 · 없음)"], ["all", "전체"]].map(([k, l]) => `<button data-f="${k}" class="${DZ_DLG.f === k ? "on" : ""}">${l}</button>`).join("")}</span>
      <select id="dzg-sg"><option value="">시군 전체</option>${sgs.map(s => `<option${s === DZ_DLG.sg ? " selected" : ""}>${escH(s)}</option>`).join("")}</select>
      <input id="dzg-q" type="search" placeholder="지구 · 읍면동 · 리 · 지번 찾기" value="${escH(DZ_DLG.q)}" autocomplete="off"></div>
    <p class="mute">시군 담당자에게 확인한 자리를 넣는다 — 위도 · 경도(예: 35.12345 · 128.12345)를 적거나 '지도에서 찍기' 뒤 지도에서 그 자리를 누른다.
      넣은 값이 가장 먼저 쓰이고(지도 · 지구별 비 판정), '지우기'를 누르면 원래 좌표로 돌아간다.${DZG.demo ? " <b>시연 서버에서는 저장되지 않는다.</b>" : ""}</p>
    <div class="list" id="dzg-list"></div></div>`;
  dzDlgList();
}
function dzDlgList() {
  const box = $("dzg-list");
  if (!box || !DZG) return;
  const q = DZ_DLG.q.trim();
  let rows = DZG.rows.filter(r => (DZ_DLG.f === "all" || !r.pos || r.approx) && (!DZ_DLG.sg || r.sigun === DZ_DLG.sg)
    && (!q || [r.name, r.emd, r.ri, r.jibun, r.kind].some(x => (x || "").includes(q))));
  if (DZ_DLG.focus) rows = [...rows.filter(r => r.id === DZ_DLG.focus), ...rows.filter(r => r.id !== DZ_DLG.focus)];
  const more = rows.length > 200;
  const nm = r => (r.name && !/구$/.test(r.name) && r.name !== "–" ? r.name : "");
  box.innerHTML = `<table><thead><tr><th>시군</th><th>읍면동</th><th>지구</th><th>리 · 지번</th><th>유형</th><th>지금 좌표</th><th>위도</th><th>경도</th><th>메모</th><th></th></tr></thead><tbody>`
    + rows.slice(0, 200).map(r => {
      const e = DZ_EDIT[r.id], p = e ? [e.lat, e.lon] : r.pos || ["", ""];
      return `<tr data-id="${escH(r.id)}" class="${r.id === DZ_DLG.focus ? "on" : ""}${e ? " ed" : ""}"><td>${escH(r.sigun)}</td><td>${escH(r.emd)}</td><td>${escH(nm(r))}</td>
        <td>${escH([r.ri, r.jibun].filter(x => x && x !== "–").join(" "))}</td><td>${escH(r.kind || r.fam)}</td>
        <td class="${!r.pos ? "w" : r.approx ? "a" : ""}">${r.pos ? `${(+r.pos[0]).toFixed(5)}, ${(+r.pos[1]).toFixed(5)}` : "없음"}<small>${escH(r.src || "")}${r.approx ? " · 근사" : ""}</small></td>
        <td><input class="la" value="${p[0] === "" ? "" : (+p[0]).toFixed(6)}" inputmode="decimal" aria-label="위도"></td>
        <td><input class="lo" value="${p[1] === "" ? "" : (+p[1]).toFixed(6)}" inputmode="decimal" aria-label="경도"></td>
        <td><input class="nt2" value="${escH(r.note || "")}" placeholder="확인한 사람 · 날짜" aria-label="메모"></td>
        <td class="ac"><button data-pick title="지도에서 그 자리를 눌러 위도 · 경도를 채운다">지도에서 찍기</button><button data-save class="pri">저장</button>${r.src === "직접 입력" ? `<button data-del title="넣은 값을 지우고 원래 좌표로">지우기</button>` : ""}</td></tr>`;
    }).join("") + `</tbody></table>` + (more ? `<p class="mute">${rows.length}곳 중 200곳만 — 시군 · 찾기로 좁힌다</p>` : rows.length ? "" : `<p class="mute">해당하는 지구가 없다</p>`);
}
async function dzDlgClick(ev) {
  const t = ev.target, tr = t.closest("tr[data-id]"), id = tr?.dataset.id;
  if (t.closest("[data-x]") || t === $("dzdlg")) return dzDlg(false);
  const f = t.closest("[data-f]");
  if (f) { DZ_DLG.f = f.dataset.f; DZ_DLG.focus = null; return dzDlg(true); }
  if (!id) return;
  if (t.closest("[data-pick]")) {
    DZ_PICK = id; dzDlg(false);
    toast("지도에서 그 지구 자리를 누른다 — 확대해서 누르면 정확하다 · Esc 취소");
    return;
  }
  const save = t.closest("[data-save]"), del = t.closest("[data-del]");
  if (!save && !del) return;
  const body = del ? { id, lat: "", lon: "" } : { id, lat: tr.querySelector(".la").value.trim(), lon: tr.querySelector(".lo").value.trim(), note: tr.querySelector(".nt2").value.trim() };
  if (save && (!body.lat || !body.lon)) { toast("위도 · 경도를 둘 다 넣는다"); return; }
  try {
    const r = await fetch("/api/districts/geo", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.status);
    const row = DZG.rows.find(x => x.id === id);
    Object.assign(row, { pos: j.pos, src: del ? "되돌리는 중" : "직접 입력", approx: false, note: del ? "" : body.note });
    delete DZ_EDIT[id];
    toast(del ? "지웠다 — 원래 좌표로 되돌린다(몇 초)" : "저장했다 — 지도 · 판정에 바로 쓰인다");
    dzDlgList();
    loadDistrict();
    if (del) setTimeout(async () => { try { DZG = await getJson("/api/districts/geo"); if (dzDlgOpen()) dzDlgList(); } catch {} loadDistrict(); }, 4000);
  } catch (e) { toast(`저장하지 못했다 — ${e.message}`); }
}
/* 지도에서 찍기 — 다음 지도 클릭 자리(경위도)를 그 줄 입력 칸에 넣고 창을 다시 연다(저장은 사람이 누른다) */
function dzPicked(gx, gy) {
  const [lon, lat] = LCC(gx, gy), id = DZ_PICK;
  DZ_PICK = null;
  DZ_EDIT[id] = { lat, lon };
  dzDlg(true, id);
}

/* 고른 시군 · 기준(AWS · 격자)이 바뀌었다 — 그 시군 시간별 줄만 다시 받아 붙인다(경남 전체는 그대로) */
let DZ_ST = 0;
function dzSeries() {
  clearTimeout(DZ_ST);
  DZ_ST = setTimeout(async () => {
    if (!OV.has("district") || !DZ_PCT || !SELS.length) return;
    const sb = ACC_BASIS === "grid" ? "grid" : "aws";
    const one = dzOne;
    for (const sg of SELS) {
      try {
        const j = await getJson(`/api/judge?sigun=${encodeURIComponent(sg)}&series=1&sb=${sb}`);
        DZ_REG = j.regions || DZ_REG;
        for (const r of j.rows) DZ_PCT[r.id] = { grid: one(r.b.grid), aws: one(r.b.aws), where: r.where };
      } catch {}
    }
    drawDistrict(); districtLegend();
  }, 400);
}

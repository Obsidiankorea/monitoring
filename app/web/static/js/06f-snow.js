"use strict";
/* ── 눈 · 적설 — 기상청 적설관측(경남 55곳 남짓, /api/snow · 10분마다 수집) ──
   레이어 '눈 · 적설': 강수량 색은 그대로 두고 겹으로만 — 지금 눈이 오는 읍면동(동네예보 실황 강수형태) 흰 빗금 · 비/눈은 성긴 빗금 · 눈 쌓인 지점 ❄ cm(산지는 ▲ · 해발) ·
   강수 누적 줄 ❄ 칩 · 범례 옆 적설 표(지금 · 3시간 · 24시간). 눈이 관측되거나 대설특보가 나면 저절로 켠다(끄면 이 창에서는 그대로 끔).
   하위 '눈만 보기': 비 색을 거의 지우고 시군을 쌓인 눈 깊이로 칠한다. 지점은 0cm 까지 다 — 서부경남은 눈만 오는 날이 있어 시군을 확대해 볼 때.
   SNOW = { tm, active, alert: [시군], falling: [시군], pty: {시군: {snow, mix, rain: [읍면동]}}, stations: [{stn, name, sigun, lon, lat, ht, mt, sd, d3, d24, day}], siguns: {시군: {sd, d3, d24, stn}} }
   ?snow=sample · 테스트(T)는 샘플(실제 관측 아님) */
const SNOW_SAMPLE = {
  tm: "샘플", sample: true, active: true, alert: ["거창"], falling: ["거창", "함양", "산청"],
  pty: { 거창: { snow: ["북상면", "위천면", "고제면", "주상면", "웅양면", "가북면", "거창읍", "마리면"], mix: ["남상면", "남하면", "신원면", "가조면"], rain: [] },
         함양: { snow: ["서상면", "서하면", "안의면"], mix: ["함양읍", "수동면"], rain: [] }, 산청: { snow: [], mix: ["시천면", "삼장면"], rain: ["단성면"] } },
  siguns: { 거창: { sd: 4.2, d3: 3.1, d24: 5.5, stn: "거창" }, 함양: { sd: 2.5, d3: 2.0, d24: 3.0, stn: "함양군" },
            산청: { sd: 1.0, d3: 0, d24: 1.0, stn: "산청" }, 합천: { sd: 0.5, d3: 0.5, d24: 0.5, stn: "합천" } },
  stations: [
    { stn: "946", name: "북상", sigun: "거창", lon: 127.8183, lat: 35.7798, ht: 325, sd: 7.5, d3: 4.0, d24: 8.0 },
    { stn: "284", name: "거창", sigun: "거창", lon: 127.9099, lat: 35.6674, ht: 228, sd: 4.2, d3: 3.1, d24: 5.5 },
    { stn: "264", name: "함양군", sigun: "함양", lon: 127.7454, lat: 35.5114, ht: 152, sd: 2.5, d3: 2.0, d24: 3.0 },
    { stn: "289", name: "산청", sigun: "산청", lon: 127.8791, lat: 35.4130, ht: 138, sd: 1.0, d3: 0, d24: 1.0 },
    { stn: "285", name: "합천", sigun: "합천", lon: 128.1699, lat: 35.5650, ht: 33, sd: 0.5, d3: 0.5, d24: 0.5 },
    { stn: "872", name: "지리산", sigun: "산청", lon: 127.7563, lat: 35.3191, ht: 865, mt: true, sd: 12.0, d3: 3.0, d24: 9.0 },
    { stn: "192", name: "진주", sigun: "진주", lon: 128.0400, lat: 35.1638, ht: 30, sd: 0, d3: 0, d24: 0 },
  ],
};
let SNOW = Q.get("snow") === "sample" || test ? SNOW_SAMPLE : null, SNOW_OFF = false;
const snowOn = () => !!(SNOW && OV.has("snow") && !CASE);
const snowOnly = () => snowOn() && OV.has("snowonly");
const snowTxt = v => (v >= 10 ? v.toFixed(0) : v.toFixed(1)).replace(/\.0$/, "");
const SNOW_ST = [0.5, 1, 3, 5, 10, 20, 30];                       // 눈만 보기 시군 색 — cm(대설 기준 5 · 20 · 산지 30 을 끊는다)
const SNOW_COL = ["#DCE9F8", "#B9D3F1", "#8DB6E6", "#5E93D6", "#3A6FC0", "#2A4FA0", "#5B3A9E"];
const snowCol = v => { let c = null; SNOW_ST.forEach((t, i) => { if (v >= t) c = SNOW_COL[i]; }); return c; };

async function loadSnow() {
  if (SNOW?.sample || CASE || window.GN_SNAP) return;
  try { SNOW = await getJson("/api/snow"); } catch { return; }
  if (SNOW.active && !SNOW_OFF && !OV.has("snow")) OV.add("snow");   // 눈 · 대설특보 — 저절로 켠다(설정에는 남기지 않는다)
  renderLayers(); drawSnow(); buildLegend(); glLate(); modeIcon();
  if (CARDS && !CARDS.err) renderCards();
}
setInterval(loadSnow, 300e3);

function drawSnow() {
  const g = $("wsnow");
  if (!g) return;
  if (!snowOn() || !V || !V.s) { g.innerHTML = ""; return; }
  const only = snowOnly(), sc = V.u / 3.3, gap = Math.max(6, 7 * sc), dim = sg => selOn() && !isSel(sg) ? " dim" : "";
  const defs = `<defs><pattern id="snh" width="${gap.toFixed(1)}" height="${gap.toFixed(1)}" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <line x1="0" y1="0" x2="0" y2="${gap.toFixed(1)}" class="snl"/></pattern>
    <pattern id="snm" width="${(gap * 2.2).toFixed(1)}" height="${(gap * 2.2).toFixed(1)}" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
      <line x1="0" y1="0" x2="0" y2="${(gap * 2.2).toFixed(1)}" class="snl"/></pattern></defs>`;
  // 지금 눈이 오는 곳 — 읍면동 경계가 있으면 읍면동마다, 받는 동안은 시군째(눈이 하나라도 있으면 촘촘히)
  const pty = SNOW.pty || {};
  if (Object.keys(pty).length && !ETOPO && !drawSnow.w) drawSnow.w = ensureEmd().then(drawSnow);   // 한 번만 — 못 받으면 시군째로 남는다
  const fallArea = Object.entries(pty).map(([sg, v]) => {
    const kinds = [["snow", "snh"], ["mix", "snm"]].filter(([k]) => v[k]?.length);
    if (!kinds.length) return "";
    if (!ETOPO) { const ft = FEAT.find(f => f.properties.sigun === sg); return ft ? `<path class="sna${dim(sg)}" d="${PATH(ft)}" fill="url(#${kinds[0][1]})"/>` : ""; }
    return kinds.map(([k, pat]) => ETOPO.objects.emd.geometries.filter(g => g.properties.sigun === sg && v[k].includes(g.properties.name))
      .map(g => `<path class="sna${dim(sg)}" d="${PATH(topojson.feature(ETOPO, g))}" fill="url(#${pat})"/>`).join("")).join("");
  }).join("");
  const areas = Object.entries(SNOW.siguns || {}).map(([sg, s]) => {
    const ft = FEAT.find(f => f.properties.sigun === sg);
    if (!ft) return "";
    const c = only && snowCol(s.sd || 0);
    return c ? `<path class="snf${dim(sg)}" d="${PATH(ft)}" style="fill:${c}"/>` : "";
  }).join("");
  const r = Math.max(10, Math.min(16, V.u * 1.3)), fs = Math.max(13, Math.min(19, V.u * 2.3));
  // 눈만 보기 · 시군을 골랐으면 0cm 지점도(어디서 재는지) — 아니면 쌓인 곳만
  const pick = s => (s.sd > 0) || (only && s.sd === 0 && (!selOn() || isSel(s.sigun)));
  const marks = (SNOW.stations || []).filter(pick).sort((a, b) => (a.sd || 0) - (b.sd || 0)).map(s => {
    const [cx, cy] = LCCF(s.lon, s.lat), x = V.toX(cx), y = V.toY(cy), zero = !(s.sd > 0), rr = zero ? r * 0.45 : r;
    const shape = s.mt ? `<path d="M${x.toFixed(1)},${(y - rr * 1.1).toFixed(1)}L${(x + rr).toFixed(1)},${(y + rr * 0.8).toFixed(1)}L${(x - rr).toFixed(1)},${(y + rr * 0.8).toFixed(1)}Z"/>`
      : `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${rr.toFixed(1)}"/>`;
    const lab = zero ? (selOn() && isSel(s.sigun) ? `${s.name} 0` : "") : `${s.name}${s.mt ? `(${Math.round(s.ht)}m)` : ""} ${snowTxt(s.sd)}cm`;
    const w = lab.length * fs * 0.62 + 8;
    return `<g class="snp${zero ? " z" : ""}${s.mt ? " mt" : ""}${dim(s.sigun)}">${shape}
      ${zero ? "" : `<text class="ic" x="${x.toFixed(1)}" y="${(y + r * 0.36).toFixed(1)}" text-anchor="middle" style="font-size:${(r * 1.05).toFixed(1)}px">${s.mt ? "" : "❄"}</text>`}
      ${lab ? `<rect x="${(x + rr + 3).toFixed(1)}" y="${(y - fs * 0.65).toFixed(1)}" width="${w.toFixed(1)}" height="${(fs * 1.3).toFixed(1)}" rx="${(fs * 0.3).toFixed(1)}"/>
      <text x="${(x + rr + 7).toFixed(1)}" y="${(y + fs * 0.36).toFixed(1)}" style="font-size:${fs.toFixed(1)}px">${escH(lab)}</text>` : ""}
      <title>${escH(`${s.name}(${s.sigun}${s.mt ? ` · 산지 ${Math.round(s.ht)}m` : ""}) 적설 ${s.sd == null ? "결측" : snowTxt(s.sd) + "cm"}`
        + (s.d3 > 0 ? ` · 3시간 동안 ${snowTxt(s.d3)}cm 쌓임` : "") + (s.d24 > 0 ? ` · 24시간 신적설 ${snowTxt(s.d24)}cm` : ""))}</title></g>`;
  }).join("");
  g.innerHTML = defs + areas + fallArea + marks;
}
/* 범례 옆 — 빗금 뜻(눈만 보기면 깊이 색) · 적설 표(많이 쌓인 곳부터, 산지는 ▲) · 관측 시각 */
function snowLegend() {
  if (!snowOn()) return "";
  const st = (SNOW.stations || []).filter(s => s.sd > 0).sort((a, b) => b.sd - a.sd).slice(0, 7);
  const tm = /^\d{12}$/.test(SNOW.tm || "") ? `관측 ${SNOW.tm.slice(8, 10)}:${SNOW.tm.slice(10)}` : "";
  return `<div class="snlg">
    ${snowOnly() ? `<div class="snsc">${SNOW_ST.map((t, i) => `<span><b style="background:${SNOW_COL[i]}"></b>${t}</span>`).join("")}<span>cm</span></div>` : ""}
    <div class="sw"><b class="snk"></b>지금 눈이 오는 곳(실황)</div><div class="sw"><b class="snk m"></b>비와 눈이 섞여 오는 곳</div>
    ${st.length ? `<table><tr><th>적설</th><th>지금</th><th>3시간</th><th>24시간</th></tr>${st.map(s => `<tr${(s.d24 || 0) >= 5 ? ' class="ov"' : ""}><td>${s.mt ? "▲" : ""}${escH(s.name)}</td><td>${snowTxt(s.sd)}cm</td><td>${s.d3 > 0 ? `+${snowTxt(s.d3)}` : "—"}</td><td>${s.d24 > 0 ? snowTxt(s.d24) : "—"}</td></tr>`).join("")}</table>`
      : `<div class="note">쌓인 눈 없음${SNOW.alert?.length ? ` · 대설특보 ${SNOW.alert.join(" · ")}` : ""}</div>`}
    <div class="note">${SNOW.sample ? "샘플 — 실제 관측이 아님" : `${tm}${tm ? " · " : ""}24시간 5cm 넘으면 굵게(대설주의보 기준)`}</div></div>`;
}
/* 왼쪽 위 화면 단추(#mode) — 지금 오는 것(동네예보 실황 강수형태)을 한눈에.
   비만 · 아무것도 없음 🌧️ · 눈만 🌨️ · 비와 눈이 함께(또는 비/눈) 🌧️ 에 ❄ 배지. 폭염 화면은 ☀️ */
function snowNow() {
  const p = (!CASE && SNOW?.pty) || {}, sg = k => Object.keys(p).filter(s => p[s][k]?.length);
  const snow = [...new Set([...sg("snow"), ...sg("mix")])], rain = [...new Set([...sg("rain"), ...sg("mix")])];
  return { snow, rain, kind: snow.length && rain.length ? "both" : snow.length ? "snow" : "rain" };
}
function modeIcon() {
  const m = $("mode");
  if (!m) return;
  const n = HEAT ? null : snowNow(), k = n?.kind || "rain";
  m.className = m.className.replace(/\bw-\w+/g, "").trim() + ` w-${HEAT ? "heat" : k}`;
  m.innerHTML = HEAT ? "☀️" : k === "snow" ? "🌨️" : k === "both" ? `🌧️<b class="mb" aria-hidden="true">❄</b>` : "🌧️";
  const what = !n || k === "rain" ? "" : k === "snow" ? ` · 지금 눈(${n.snow.join(" · ")})` : ` · 지금 비와 눈(눈 ${n.snow.join(" · ")})`;
  m.title = `${HEAT ? "폭염" : "호우"} 화면${what} — 눌러서 ${HEAT ? "호우" : "폭염"} 화면으로 (M)`;
  m.setAttribute("aria-label", m.title);
}
/* 강수 누적 줄의 적설 칩 — 그 시군에 쌓인 눈(cm, 산지 뺀 최대). 비만 오는 시군은 없다 */
function snowChip(sig) {
  const s = snowOn() && SNOW.siguns?.[sig];
  return s && s.sd > 0 ? `<em class="snc" title="${escH(`${sig} 적설 ${snowTxt(s.sd)}cm(${s.stn})${s.d3 > 0 ? ` · 3시간 동안 ${snowTxt(s.d3)}cm 쌓임` : ""}${s.d24 > 0 ? ` · 24시간 ${snowTxt(s.d24)}cm` : ""}`)}">❄${snowTxt(s.sd)}</em>` : "";
}

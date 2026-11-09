"use strict";
/* ── 지도 그리기(MapLibre GL, WebGL) — 땅 · 경계 · 강수 격자는 GPU 가, 글자 · 점 · 강조는 그 위 SVG(#over)가 그린다.
   지도 평면 = 500m 격자 평면: 칸 (col, row) 를 메르카토르 세계 좌표에 선형으로 얹는다(gll). 그래서 V.toX · fromX · PATH 같은
   칸 좌표 계산이 예전 그대로 정확하고, 격자 그림은 네 모서리만 주면 칸이 꼭 맞는다(진짜 경위도로 얹으면 한 장이 ~800m 어긋난다).
   shortcut: MapLibre 쪽 경위도는 진짜 경위도가 아니다 — 경위도 자료는 LCCF 로 칸으로 바꿔 gll 에 넣는다.
             바탕 지도 타일(진짜 경위도)을 깔 일이 생기면 그때 gll 을 LCC 역변환으로 바꾸고 격자는 조각내 얹는다.

   새 레이어 더하기: GL_LAYERS 에 한 줄(아래 → 위 순서). 소스는 층의 source 이름으로 저절로 생긴다(GeoJSON) —
   자료는 glData(소스, 열쇠, () => [glF(...), ...]) 로 넣는다(열쇠가 같으면 다시 올리지 않는다).
   색은 "var(--이름)" 으로 적는다 — 테마를 바꾸면 glTheme() 이 CSS 변수를 다시 읽어 칠한다.
   점 · 글자(이름 · 라벨 · 관측소 · 하천 · 조위 표식)는 위 SVG 에 둔다 — 점마다 모양이 다르고(수위 막대 · 댐) 글자가
   서로 피해 가는 자리 잡기(LABELBOX)를 같이 쓴다. 점이 수천 개로 느는 레이어가 생기면 그 레이어만 GL 로. */
const GE = 500 / 40075016.686;                         // 칸 하나 = 세계 좌표(적도 500m)
const GC = [1328, 942];                                // 경남 가운데 칸 — 세계 좌표 (0.5, 0.5) 에 놓는다
const gll = (gx, gy) => new maplibregl.MercatorCoordinate(0.5 + (gx - GC[0]) * GE, 0.5 - (gy - GC[1]) * GE).toLngLat().toArray();
/* GeoJSON geometry(칸 좌표) → MapLibre 좌표 */
const glGeom = g => {
  const f = c => typeof c[0] === "number" ? gll(c[0], c[1]) : c.map(f);
  return { type: g.type, coordinates: f(g.coordinates) };
};
const glFC = features => ({ type: "FeatureCollection", features });
const glF = (geometry, properties = {}) => ({ type: "Feature", properties, geometry: glGeom(geometry) });
/* 구멍 있는 면 — 바깥 고리와 구멍 고리의 감는 방향을 서로 반대로 맞춘다.
   ⚠️ MapLibre 는 감는 방향으로 구멍을 가린다 — 바깥과 같은 방향이면 구멍이 아니라 새 면이 돼 메워졌다(고른 시군까지 어두워졌다) */
const ringArea = r => r.reduce((a, p, i) => { const q = r[(i + 1) % r.length]; return a + p[0] * q[1] - q[0] * p[1]; }, 0);
const glPoly = rings => ({ type: "Polygon", coordinates: rings.map((r, i) => (ringArea(r) > 0) === (i === 0) ? r : [...r].reverse()) });

/* 경계 — 선 밑에 반대색 테두리(bd-halo)를 깐다. ⚠️ 시군 경계색이 강수 청색과 명도가 비슷해 넓게 칠해지면 묻혔다(10-25 굵게 · 밝게) */
const BD_DASH_ZN = [9 / 2.6, 6 / 2.6], BD_DASH_SB = [3 / 1.5, 5 / 1.5];   // SVG dasharray(px) → 선 굵기 배수
const GL_LAYERS = [
  { id: "land", type: "fill", source: "land", paint: { "fill-color": ["case", ["get", "nb"], "var(--land-nb)", "var(--land)"] } },
  { id: "rain", type: "raster", source: "rain", paint: { "raster-resampling": "nearest", "raster-fade-duration": 0, "raster-opacity-transition": { duration: 300 } } },
  { id: "ghost", type: "raster", source: "ghost", paint: { "raster-resampling": "nearest", "raster-fade-duration": 0, "raster-opacity": 0 } },
  { id: "hatch", type: "raster", source: "hatch", paint: { "raster-fade-duration": 0 } },
  // 지형(레이어 relief · low) — 강수 위 · 경계 밑. 미리 만든 그림 한 장씩(tools/build_terrain.py)
  // 경남 전체(지도 줌 10 아래)는 한 장 그림, 확대하면 조각(-t, 서버 /terrain/t — 30m 자료 · 줌 12부터 등고선)
  { id: "low", type: "raster", source: "low", maxzoom: 10, layout: { visibility: "none" }, paint: { "raster-fade-duration": 0 } },
  { id: "low-t", type: "raster", source: "low-t", minzoom: 10, layout: { visibility: "none" }, paint: { "raster-fade-duration": 0 } },
  { id: "relief", type: "raster", source: "relief", maxzoom: 10, layout: { visibility: "none" }, paint: { "raster-fade-duration": 0 } },
  { id: "relief-t", type: "raster", source: "relief-t", minzoom: 10, layout: { visibility: "none" }, paint: { "raster-fade-duration": 0 } },
  // 건물 밀도(레이어 bldg, 국토교통부 GIS건물통합정보 — tools/build_bldg.py). 지형과 같이 한 장 그림 → 확대하면 조각
  { id: "bldg", type: "raster", source: "bldg", maxzoom: 10, layout: { visibility: "none" }, paint: { "raster-fade-duration": 0 } },
  { id: "bldg-t", type: "raster", source: "bldg-t", minzoom: 10, layout: { visibility: "none" }, paint: { "raster-fade-duration": 0 } },
  // 강 · 호수 · 저수지(레이어 water, 국토지리정보원 연속수치지형도 — tools/build_water.py). 면은 옅게 — 그 위 비 색이 묻히지 않게. o = 경남 밖 — 회색으로 흐리게
  // 강 선 g = 1 국가하천(굵게) · 2 지방하천 · 3 소하천 등(시군을 고른 확대에서만)
  { id: "water", type: "fill", source: "water", filter: ["==", ["get", "k"], "water"], layout: { visibility: "none" },
    paint: { "fill-color": ["case", ["has", "o"], "#2A3440", "#0B2F4E"], "fill-opacity": ["case", ["has", "o"], 0.35, 0.55] } },
  { id: "water-ln", type: "line", source: "water", filter: ["all", ["==", ["get", "k"], "water"], ["!", ["has", "r"]]], layout: { visibility: "none" },
    paint: { "line-color": ["case", ["has", "o"], "#8A97A6", "#7DDCFF"], "line-width": ["interpolate", ["linear"], ["zoom"], 8, 0.8, 11, 1.4], "line-opacity": ["case", ["has", "o"], 0.3, 0.9] } },
  // 실폭하천(넓은 강 · 개울의 물 면) 테두리 — 경남 전체에서는 잔 테두리가 화면을 덮어 시군 확대에서만
  { id: "water-r-ln", type: "line", source: "water", minzoom: 9.4, filter: ["all", ["==", ["get", "k"], "water"], ["has", "r"]], layout: { visibility: "none" },
    paint: { "line-color": ["case", ["has", "o"], "#8A97A6", "#7DDCFF"], "line-width": ["interpolate", ["linear"], ["zoom"], 8, 0.8, 11, 1.4], "line-opacity": ["case", ["has", "o"], 0.3, 0.9] } },
  { id: "river-s", type: "line", source: "water", minzoom: 9.4, filter: ["all", ["==", ["get", "k"], "river"], ["==", ["get", "g"], 3]], layout: { visibility: "none", "line-join": "round", "line-cap": "round" },
    paint: { "line-color": ["case", ["has", "o"], "#8A97A6", "#7DDCFF"], "line-width": ["interpolate", ["linear"], ["zoom"], 9.4, 0.4, 11, 0.9], "line-opacity": ["case", ["has", "o"], 0.2, 0.55] } },
  { id: "river", type: "line", source: "water", filter: ["all", ["==", ["get", "k"], "river"], ["<", ["get", "g"], 3]], layout: { visibility: "none", "line-join": "round", "line-cap": "round" },
    paint: { "line-color": ["case", ["has", "o"], "#8A97A6", "#7DDCFF"],
             "line-width": ["interpolate", ["linear"], ["zoom"], 8, ["case", ["==", ["get", "g"], 1], 1.8, 0.7], 11, ["case", ["==", ["get", "g"], 1], 3.2, 1.6]],
             "line-opacity": ["case", ["has", "o"], 0.3, 0.9] } },
  { id: "bd-halo", type: "line", source: "bd", filter: ["in", ["get", "t"], ["literal", ["sg", "cs"]]],
    layout: { "line-join": "round" }, paint: { "line-color": "var(--bd-halo)", "line-width": 4 } },
  { id: "bd-halo-z", type: "line", source: "bd", filter: ["in", ["get", "t"], ["literal", ["zn", "sb"]]],
    layout: { "line-join": "round" }, paint: { "line-color": "var(--bd-halo)", "line-width": 5.5 } },
  { id: "bd-sg", type: "line", source: "bd", filter: ["==", ["get", "t"], "sg"],
    layout: { "line-join": "round" }, paint: { "line-color": "var(--bd)", "line-width": 1.6 } },
  { id: "bd-cs", type: "line", source: "bd", filter: ["==", ["get", "t"], "cs"],
    layout: { "line-join": "round" }, paint: { "line-color": "var(--coast)", "line-width": 1.5 } },
  { id: "bd-sb", type: "line", source: "bd", filter: ["==", ["get", "t"], "sb"],
    layout: { "line-join": "round" }, paint: { "line-color": "var(--zone)", "line-width": 1.5, "line-dasharray": BD_DASH_SB, "line-opacity": 0.8 } },
  { id: "bd-zn", type: "line", source: "bd", filter: ["==", ["get", "t"], "zn"],
    layout: { "line-join": "round", "line-cap": "round" }, paint: { "line-color": "var(--zone)", "line-width": 2.6, "line-dasharray": BD_DASH_ZN } },
];
GL_LAYERS.push(
  // 폭염 화면 — 시군 면 + 폭염특보 둘레(주의보 점선 · 경보 · 중대)
  { id: "heat", type: "fill", source: "heat", paint: { "fill-color": ["get", "col"], "fill-opacity": 0.62 } },
  { id: "heat-watch", type: "line", source: "heat", filter: ["==", ["get", "lv"], "watch"], layout: { "line-join": "round" },
    paint: { "line-color": "var(--lv-watch)", "line-width": 2, "line-dasharray": [2.5, 1.5] } },
  { id: "heat-warn", type: "line", source: "heat", filter: ["==", ["get", "lv"], "warn"], layout: { "line-join": "round" },
    paint: { "line-color": "var(--lv-warn)", "line-width": 2.5 } },
  { id: "heat-severe", type: "line", source: "heat", filter: ["==", ["get", "lv"], "severe"], layout: { "line-join": "round" },
    paint: { "line-color": "var(--lv-severe)", "line-width": 3 } },
  // 고른 시군 읍면동 사이 선(확대했을 때)
  { id: "emd", type: "line", source: "emd", layout: { "line-join": "round" }, paint: { "line-color": "var(--ink-2)", "line-width": 1.1, "line-opacity": 0.55 } },
  // 고른 시군 밖을 어둡게
  { id: "selmask", type: "fill", source: "selmask", paint: { "fill-color": "var(--sea)", "fill-opacity": 0.5 } },
  // 침수흔적 면(안전 레이어)
  { id: "flood", type: "fill", source: "flood", paint: { "fill-color": "var(--sf-flood)", "fill-opacity": 0.22 } },
  { id: "flood-line", type: "line", source: "flood", paint: { "line-color": "var(--sf-flood)", "line-opacity": 0.5, "line-width": 0.6 } },
);
const TER_IDS = ["relief", "low", "bldg"];   // 지형 체계 그림(terrain/*.png + /terrain/t/ 조각)
const CANVAS_SRC = ["rain", "ghost", "hatch", "low", "relief", "bldg"];   // 격자 그림 — 이미지 소스(low · relief 는 파일 그림)
const BLANK_PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=";

/* "var(--x)" → 지금 테마의 값. 식(배열) 안도 찾아 바꾼다 */
const cssVal = v => typeof v === "string" && v.startsWith("var(")
  ? getComputedStyle(document.documentElement).getPropertyValue(v.slice(4, -1)).trim()
  : Array.isArray(v) ? v.map(cssVal) : v;
const glPaint = L => Object.fromEntries(Object.entries(L.paint || {}).map(([k, v]) => [k, cssVal(v)]));

let GL = null, GL_OK = false;      // GL_OK = 스타일이 섰다(층 · 소스를 만질 수 있다)
/* 지도를 만든다. WebGL 을 못 쓰면 던진다(boot 가 까닭을 띄운다). 스타일은 뒤에 선다 — 그 전 GL 부르기는 그냥 지나가고,
   서면 지금 상태로 한 번 다 그린다. ⚠️ 스타일 · 'load' 는 requestAnimationFrame 을 기다려 창이 가려진 채 열면 오지 않는다 —
   기다리면 boot 가 멈췄다(자료 받기 · 카드까지) */
function glInit() {
  const q = document.createElement("canvas").getContext("webgl2") || document.createElement("canvas").getContext("webgl");
  if (!q) throw new Error("이 PC 브라우저에서 WebGL 을 쓸 수 없다 — 그래픽 가속(하드웨어 가속)을 켜거나 다른 브라우저로");
  const sources = Object.fromEntries(GL_LAYERS.map(L => [L.source, { type: "geojson", data: glFC([]) }]));
  const corner = [gll(GC[0], GC[1]), gll(GC[0] + 1, GC[1]), gll(GC[0] + 1, GC[1] - 1), gll(GC[0], GC[1] - 1)];
  for (const id of CANVAS_SRC) sources[id] = { type: "image", url: BLANK_PNG, coordinates: corner };
  for (const id of TER_IDS) sources[id + "-t"] = { type: "raster", tiles: [`/terrain/t/${id}/{z}/{x}/{y}.png`], tileSize: 256, minzoom: 11, maxzoom: 13 };
  GL = new maplibregl.Map({
    container: "gl", interactive: false, attributionControl: false, fadeDuration: 0, renderWorldCopies: false,
    center: gll(...GC), zoom: 8, maxZoom: 22,
    style: { version: 8, sources, layers: GL_LAYERS.map(L => ({ ...L, paint: glPaint(L) })) },
  });
  GL.once("style.load", () => { GL_OK = true; if (V) { buildBase(); glCam(); draw(); } glTerrain(); glWater(); });
}
/* 지형 · 건물 그림 — 켜진 것만 보인다. 처음 켤 때 terrain.json(bbox)을 읽고 그림을 한 번 올린다 */
let TERRAIN = null;
async function glTerrain() {
  srcAttr();
  if (!GL_OK) return;
  const want = TER_IDS.filter(id => OV.has(id));
  if (want.length && !TERRAIN) {
    TERRAIN = {};
    try {
      const j = await getJson("terrain/terrain.json"), b = j.bbox;
      TERRAIN.meta = j;
      const c = [gll(b.i0 - 0.5, b.j1 + 0.5), gll(b.i1 + 0.5, b.j1 + 0.5), gll(b.i1 + 0.5, b.j0 - 0.5), gll(b.i0 - 0.5, b.j0 - 0.5)];
      for (const id of TER_IDS) GL.getSource(id).updateImage({ url: `terrain/${id}.png?v=${j.built || ""}`, coordinates: c });
      TERRAIN.ok = true;
    } catch (e) { TERRAIN = null; console.warn("지형 그림을 못 읽었다", e); return; }
  }
  for (const id of TER_IDS) for (const L of [id, id + "-t"]) GL.setLayoutProperty(L, "visibility", OV.has(id) && TERRAIN?.ok ? "visible" : "none");
}
/* 지도 오른쪽 아래 출처 — 켠 레이어의 자료 출처만(국토지리정보원 · 국토교통부 자료 — 브이월드 CC BY, 출처 표시 의무) */
function srcAttr() {
  const a = [OV.has("water") && `강 · 호수 · 저수지 © 국토지리정보원 연속수치지형도(브이월드)`,
             OV.has("bldg") && `건물 © 국토교통부 GIS건물통합정보(브이월드)`].filter(Boolean);
  $("osm-attr").hidden = !a.length;
  $("osm-attr").innerHTML = a.join(" · ");
}
/* 강 · 호수 · 저수지 — 처음 켤 때 water.json(칸 좌표)을 받아 올린다. 켜면 출처(#osm-attr)도 */
let WATER = null;
async function glWater() {
  const on = OV.has("water");
  srcAttr();
  if (!GL_OK) return;
  if (on && !WATER) {
    WATER = "loading";
    try {
      WATER = (await getJson("water/water.json")).features;
      glSet("water", glFC(WATER.map(f => glF(f.geometry, f.properties))));
    } catch (e) { WATER = null; console.warn("강 · 호수 자료를 못 읽었다", e); return; }
  }
  for (const L of ["water", "water-ln", "water-r-ln", "river", "river-s"]) GL.setLayoutProperty(L, "visibility", OV.has("water") && Array.isArray(WATER) ? "visible" : "none");
}
/* 마우스 자리 표고(m) — 지형 레이어를 켰을 때만. 125m 칸 표고(elev.i16.gz, 2MB)를 처음 물을 때 받는다. 아직이면 null */
let ELEV = null;
function elevAt(gx, gy) {
  const m = TERRAIN?.meta;
  if (!m) return null;
  if (!ELEV) {
    ELEV = "loading";
    fetch("terrain/elev.i16.gz").then(r => r.arrayBuffer()).then(async buf => {
      let u = new Uint8Array(buf);
      if (u[0] === 0x1f && u[1] === 0x8b) u = new Uint8Array(await new Response(new Blob([u]).stream().pipeThrough(new DecompressionStream("gzip"))).arrayBuffer());
      ELEV = new Int16Array(u.buffer, 0, m.w * m.h);
    }).catch(() => { ELEV = null; });
    return null;
  }
  if (!(ELEV instanceof Int16Array)) return null;
  const b = m.bbox, px = Math.floor((gx - b.i0 + 0.5) * m.S), py = Math.floor((b.j1 + 0.5 - gy) * m.S);
  return px < 0 || py < 0 || px >= m.w || py >= m.h ? null : ELEV[py * m.w + px];
}
/* 테마가 바뀌었다 — CSS 변수를 다시 읽어 칠한다 */
function glTheme() {
  if (!GL_OK) return;
  for (const L of GL_LAYERS) for (const [k, v] of Object.entries(glPaint(L))) if (!k.endsWith("-transition")) GL.setPaintProperty(L.id, k, v);
}
const glSet = (id, data) => GL.getSource(id).setData(data);
/* 자료가 바뀌었을 때만 소스에 올린다 — 카메라가 멈출 때마다 buildBase 가 다시 불러도 같은 열쇠면 그냥 지나간다 */
const GL_KEY = {};
function glData(id, key, make) {
  if (!GL_OK || GL_KEY[id] === key) return;
  GL_KEY[id] = key;
  glSet(id, glFC(make()));
}

/* 시군 땅 · 경계 — 모양이 바뀌지 않아 한 번만 올린다 */
let GL_BASE = false;
function glBase() {
  if (GL_BASE || !GL_OK) return;
  GL_BASE = true;
  glSet("land", glFC(FEAT.map(ft => ({ type: "Feature", properties: { nb: ft.properties.kind === "nb" }, geometry: glGeom(ft.geometry) }))));
  const P = g => g.properties, obj = TOPO.objects.sigun;
  const mesh = (t, fn) => ({ type: "Feature", properties: { t }, geometry: glGeom(topojson.mesh(TOPO, obj, fn)) });
  glSet("bd", glFC([
    mesh("sg", (a, b) => a !== b),                                                       // 시군 사이
    mesh("cs", (a, b) => a === b),                                                       // 해안 · 바깥
    mesh("zn", (a, b) => a !== b && P(a).zone !== P(b).zone),                            // 권역이 바뀌는 곳
    mesh("sb", (a, b) => a !== b && P(a).zone === P(b).zone && P(a).sub !== P(b).sub),
  ]));
}

/* 카메라 — V(칸 → 화면 틀 s · ox · oy)를 그대로 지도에. 화면 가운데 칸이 center, 칸 하나 s px 이 zoom */
function glCam() {
  if (!GL_OK || !V?.s) return;
  const c = GL.getContainer();
  if (c.clientWidth !== GL.transform.width || c.clientHeight !== GL.transform.height) GL.resize();
  GL.jumpTo({ center: gll(V.X0 + (V.W / 2 - V.ox) / V.s, V.Y1 - (V.H / 2 - V.oy) / V.s), zoom: Math.log2(V.s / (512 * GE)) });
}

/* 격자 그림 o(offscreen) 을 캔버스 소스에. 네 모서리 = 픽셀 (0,0) (w,0) (w,h) (0,h) 의 칸 좌표(5km 는 아핀을 거친다) */
function gridCorners(gr) {
  const g = META.grids, b = g[gr.grid];
  const [A, B, C] = gr.grid === "hr" ? [1, 0, 0] : g.dfs_to_hr.col;
  const [Dd, E, F] = gr.grid === "hr" ? [0, 1, 0] : g.dfs_to_hr.row;
  const at = (px, py) => { const x = b.i0 - 0.5 + px, y = b.j0 + gr.h - 0.5 - py; return gll(A * x + B * y + C, Dd * x + E * y + F); };
  return [at(0, 0), at(gr.w, 0), at(gr.w, gr.h), at(0, gr.h)];
}
/* 격자 그림 id 를 w×h 캔버스에 paint(ctx) 로 그려 PNG 로 이미지 소스에 올린다. paint 가 없으면 감춘다.
   ⚠️ 처음엔 MapLibre 캔버스 소스(play · pause)였다 — 어떤 PC · 브라우저에선 텍스처가 끝내 안 올라가 비 격자만 검게 남았다(2026-11).
      이미지 소스는 브라우저가 그림을 다 읽은 뒤 올리므로 그런 타이밍 문제가 없다 */
const GL_CV = {}, GL_GEN = {}, GL_URL = {};
function glCanvas(id, w, h, paint, coords) {
  GL.setLayoutProperty(id, "visibility", paint ? "visible" : "none");
  if (!paint) return;
  const cv = GL_CV[id] ||= document.createElement("canvas");
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  const c = cv.getContext("2d");
  c.globalCompositeOperation = "source-over"; c.clearRect(0, 0, w, h);
  paint(c);
  const my = GL_GEN[id] = (GL_GEN[id] || 0) + 1;
  cv.toBlob(b => {
    if (!b || GL_GEN[id] !== my) return;                  // 그사이 새 그림이 왔다
    const old = GL_URL[id], u = GL_URL[id] = URL.createObjectURL(b);
    GL.getSource(id).updateImage({ url: u, coordinates: coords });
    if (old) setTimeout(() => URL.revokeObjectURL(old), 3000);   // 앞 그림은 다 읽은 뒤에 버린다
  });
}
const copyOf = img => c => c.drawImage(img, 0, 0);
/* 결측 빗금 — 결측 칸 그림(miss)을 S 배로 키운 캔버스에 사선을 긋고 결측 칸 모양으로 도려낸다.
   S = 500m 칸 하나에 4 픽셀(5km 칸은 40) — 경남 전체에서 화면 7px 남짓 간격. 확대하면 빗금도 같이 커진다 */
let HATCH_OF = null;
const hatchPaint = (miss, S) => c => {
  const w = miss.width * S, h = miss.height * S, n = 11;
  c.strokeStyle = cssVal("var(--hatch)"); c.lineWidth = 2.2;
  c.beginPath();
  for (let d = -h; d < w; d += n) { c.moveTo(d, h); c.lineTo(d + h, 0); }
  c.stroke();
  c.globalCompositeOperation = "destination-in"; c.imageSmoothingEnabled = false;
  c.drawImage(miss, 0, 0, w, h);
};
let GL_COORDS = null;
function glRain(o, gr, fade) {
  if (!GL_OK) return;
  if (fade && GL_COORDS && GL.getLayoutProperty("rain", "visibility") !== "none") {
    // 앞 그림을 잠깐 남겨 겹쳐 사라지게 — 재생 · 끌기로 프레임이 넘어갈 때 뚝뚝 끊기지 않게
    const prev = GL_CV.rain;
    glCanvas("ghost", prev.width, prev.height, copyOf(prev), GL_COORDS);
    GL.setPaintProperty("ghost", "raster-opacity-transition", { duration: 0 });
    GL.setPaintProperty("ghost", "raster-opacity", 1);
    requestAnimationFrame(() => {
      GL.setPaintProperty("ghost", "raster-opacity-transition", { duration: 300 });
      GL.setPaintProperty("ghost", "raster-opacity", 0);
    });
  }
  GL_COORDS = o ? gridCorners(gr) : null;
  glCanvas("rain", gr?.w, gr?.h, o && copyOf(o.img), GL_COORDS);
  const S = gr?.grid === "hr" ? 4 : 40;
  if (!o?.miss) { HATCH_OF = null; glCanvas("hatch"); }
  else if (HATCH_OF !== o.miss) { HATCH_OF = o.miss; glCanvas("hatch", gr.w * S, gr.h * S, hatchPaint(o.miss, S), GL_COORDS); }
  glLate();
}
/* 자료 지연이면 격자를 옅게(#stage.late) */
const glLate = () => GL_OK && GL.setPaintProperty("rain", "raster-opacity", $("stage").classList.contains("late") ? 0.4 : 1);

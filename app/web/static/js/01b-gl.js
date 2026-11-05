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
const CANVAS_SRC = ["rain", "ghost", "hatch"];          // 격자 그림 — 2D 캔버스에 그려 텍스처로 올린다

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
  const blank = () => { const c = document.createElement("canvas"); c.width = c.height = 1; return c; };
  const sources = Object.fromEntries(GL_LAYERS.map(L => [L.source, { type: "geojson", data: glFC([]) }]));
  const corner = [gll(GC[0], GC[1]), gll(GC[0] + 1, GC[1]), gll(GC[0] + 1, GC[1] - 1), gll(GC[0], GC[1] - 1)];
  for (const id of CANVAS_SRC) sources[id] = { type: "canvas", canvas: blank(), coordinates: corner, animate: false };
  GL = new maplibregl.Map({
    container: "gl", interactive: false, attributionControl: false, fadeDuration: 0, renderWorldCopies: false,
    center: gll(...GC), zoom: 8, maxZoom: 22,
    style: { version: 8, sources, layers: GL_LAYERS.map(L => ({ ...L, paint: glPaint(L) })) },
  });
  GL.once("style.load", () => { GL_OK = true; if (V) { buildBase(); glCam(); draw(); } });
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
/* 캔버스 소스 id 를 w×h 로 맞추고 paint(ctx) 로 그린 뒤 한 번만 텍스처로 올린다. paint 가 없으면 감춘다 */
function glCanvas(id, w, h, paint, coords) {
  const s = GL.getSource(id), cv = s.getCanvas();
  GL.setLayoutProperty(id, "visibility", paint ? "visible" : "none");
  if (!paint) return;
  if (cv.width !== w || cv.height !== h) { cv.width = w; cv.height = h; }
  const c = cv.getContext("2d");
  c.globalCompositeOperation = "source-over"; c.clearRect(0, 0, w, h);
  paint(c);
  s.setCoordinates(coords);
  // 다음 한 장 동안만 '재생' — 그 장에서 텍스처를 올리고 멈춘다. ⚠️ play 바로 뒤 pause 는 setCoordinates 직후라
  //    타일이 아직 없어 올리지 못하고, 그 뒤로는 크기가 안 바뀌면 다시 올리지 않았다(격자가 안 보였다)
  s.play(); GL.once("render", () => s.pause());
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
    const prev = GL.getSource("rain").getCanvas();
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

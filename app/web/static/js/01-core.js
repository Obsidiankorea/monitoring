"use strict";
const Q = new URLSearchParams(location.search);
const $ = id => document.getElementById(id);
const MISSING = 65535;

/* ── 층 ───────────────────────────────────────────────────────────────
   색 단계는 7칸(--rain-1 ~ --rain-7). 0 은 칠하지 않는다.
   면을 칠하므로 '지금 오는 비' 표보다 한 칸 아래(0.1㎜)부터 보인다.
   15분치와 60분치는 크기가 다른 값이라 단계를 따로 둔다 — 같은 눈금이면 15분에 8㎜
   (시간당 32㎜의 기세)가 옅은 색으로 묻힌다. ×4 로 보면 60분 단계를 쓴다(index.html 과 같은 규칙). */
const STEPS = {
  m15: [0.1, 0.5, 2, 5, 8, 12, 18],
  m60: [0.1, 1, 5, 10, 20, 30, 50],
  day: [0.1, 5, 10, 30, 50, 80, 150],
  // 재현 사례 누적 — 이틀에 900㎜ 가 오는 비라 하루 눈금(150㎜ 끝)으로는 거제가 통째로 한 색이 된다
  event: [1, 50, 100, 200, 300, 500, 700],
};
/* 누적(격자 · AWS) 눈금 — **자료 크기에 맞춰 자동으로 고른다.** 일곱 자 중 하나.
   고르는 값 = 지금 그린 면의 경남 시군 최대 중 가장 큰 것(hi). hi 가 끝 눈금의 1.25배 안에 드는 가장 작은 자.
   커질 때는 곧바로 올라가고, 작아질 때는 끝 눈금 안에 다 들 때만 내려간다(경계에서 갱신마다 깜빡이지 않게).
   ⚠️ 예전에는 0.1·5·10·30·50·80·150 하나였다 — 30㎜ 안팎 비는 두세 색에 묻히고, 900㎜ 호우는 거의 한 색이었다.
   재현 사례는 사례 눈금(event) 그대로 — 재생하면서 자가 바뀌면 시각끼리 견줄 수 없다 */
const ACC_LADDER = [
  [0.1, 1, 2, 4, 7, 10, 15],
  [0.1, 2, 5, 10, 15, 20, 30],
  [0.1, 5, 10, 20, 30, 45, 60],
  [0.1, 10, 20, 40, 60, 90, 120],
  [0.1, 20, 50, 80, 120, 180, 250],
  [1, 30, 80, 150, 250, 350, 500],
  [1, 50, 150, 300, 450, 600, 800],
];
const ACC_TIER = {}, ACC_HI = {};                       // 층마다(acc · aws) 고른 자 · 그때 hi
/* 누적 눈금 고정 — 범례 오른쪽 클릭(또는 설정 › 화면). 서버 설정 acc_scale(끝 눈금 ㎜, 0 = 자동). 화면 모두 같이.
   자동이 갱신마다 자를 바꾸면 시각끼리 · 화면끼리 견주기 어렵다 — 그럴 때 하나로 묶어 둔다. 재현 사례도 고정이 먼저 */
const ACC_FIXED = {
  30: [0.1, 2, 5, 10, 15, 20, 30],
  60: [0.1, 5, 10, 20, 30, 45, 60],
  150: [0.1, 5, 10, 30, 50, 80, 150],         // 기상청 일강수 눈금 — 자동 이전에 하나뿐이던 자
  300: [1, 20, 50, 100, 150, 200, 300],
  800: [1, 50, 150, 300, 450, 600, 800],      // 극한호우(이틀 900㎜ 급)
};
const ACC_FIXED_NOTE = { 30: "약한 비", 60: "보통 비", 150: "기상청 일강수 눈금", 300: "호우", 800: "극한호우 — 이틀 900㎜ 급" };
// 고정 끝 눈금 — 화면 재생의 '따로 쓰는 범례'(SLIDE_SC, 이 화면에서만)가 먼저, 아니면 서버 설정 acc_scale
const scTop = () => SLIDE_SC || +SET.acc_scale || 0;
const accFix = () => ACC_FIXED[scTop()] || null;
/* 끝 눈금 T 의 칸 — 청색 7칸 · 기상청 색 열 칸 남짓 · 다양한 색조 스무 칸 남짓 */
const scSteps = T => (richOn() ? richSteps(T) : fine(ACC_FIXED[T]));
const accSteps = k => accFix() || ACC_LADDER[ACC_TIER[k] ?? 3];
/* 지금 그린 누적 면(CURSTAT)으로 자를 고른다. 바뀌었으면 true(범례를 다시 그린다) */
function updScale() {
  if (CASE || !ACCK.has(kind) || !CURSTAT) return false;
  const vals = CURSTAT.rows.filter(r => r.kind === "gn" && r.max != null).map(r => r.max);
  const hi = vals.length ? Math.max(...vals) : 0, top = i => ACC_LADDER[i].at(-1);
  if (accFix()) { const was = ACC_HI[kind]; ACC_HI[kind] = hi; return was !== hi; }   // 고정 — 범례의 '최대' 글자만
  // 다양한 색조 — 끝 눈금을 자료에 바짝(RICH_TOPS). 커지면 곧바로, 작아지면 지금 끝의 60% 아래로 내려갈 때만(깜빡이지 않게)
  let rich = false;
  if (PAL === "rich") {
    let r = RICH_TOPS.find(x => x >= hi) ?? RICH_TOPS.at(-1);
    const rc = RICH_TOP[kind];
    if (rc && r < rc && hi > rc * 0.6) r = rc;
    rich = r !== rc; RICH_TOP[kind] = r;
  }
  let t = ACC_LADDER.findIndex((_, i) => hi <= top(i) * 1.25);
  if (t < 0) t = ACC_LADDER.length - 1;
  const cur = ACC_TIER[kind];
  if (cur != null && t < cur && hi > top(t)) t = Math.min(cur, t + 1);
  const was = ACC_HI[kind];
  ACC_HI[kind] = hi;
  if (t === cur) return rich || was !== hi;            // 범례의 '최대' 글자만 바뀐다
  ACC_TIER[kind] = t;
  return true;
}
/* 색 — 청색 램프(기본) ↔ 기상청 레이더 색. **범례 색 띠를 누르면** 바뀐다(서버 설정 `pal` — 화면 모두 같이, ?pal= 이 먼저).
   ⚠️ 기상청 색은 흉내 내지 않는다. 서버가 기상청 예측 분포(QPF) 그림 범례에서 그대로 뽑아 둔 24단계를 받아 쓴다
      (/api/qpf/legend — 종합 화면 예측 분포 범례와 같은 것. 레이더 영상과 같은 0.1·0.5·1·…·110㎜/h 단계).
      아직 못 뽑았으면 청색 그대로 두고 범례에 그렇게 적는다 — 조용히 다른 색을 쓰지 않는다.
   시간 강수(60분 · 실황 · 초단기, 15분은 ×4)는 레이더와 **같은 경계**로 칠한다 — 10㎜ 면 레이더의 10㎜/h 색.
   누적(누적 · AWS 누적 · 단기 오늘/내일 · 사례)은 레이더에 같은 자가 없다. 기상청 색이면 눈금을 열 칸 남짓으로 잘게
   나누고(ACC_FINE — 끝 눈금은 같다) 색을 레이더 범례에서 고르게 빌린다 — 누적 30㎜ 가 레이더 30㎜/h 색이라는 뜻이 아니다.
   ⚠️ 예전에는 7칸에 7색만 빌려 지도에 색이 몇 가지뿐이었다(10-24).
   약한 쪽(맨 아래 칸, 1㎜ 아래 칸)은 땅 색 쪽으로 섞어 바탕에 가깝게 — 거의 안 온 곳이 묻히고 오는 곳이 솟게(청색 --map-r* 과 같은 뜻).
   ⚠️ 레이더 색에는 노랑 · 빨강 · 보라가 있어 특보 예약색(주의보 노랑 · 경보 빨강 · 중대경보 보라)과 겹친다 — 그래서 기본은 청색 */
let PAL = "blue";
let KMA_LG = null;                                      // { steps[], cols[] } — 약한 것부터. 겹친 0.1 은 뒤 칸(0.1 이상)
const KMA_TICKS = [0.1, 1, 5, 10, 20, 30, 50, 110];     // 범례 눈금(종합 화면 예측 분포와 같다)
/* 기상청 색으로 볼 때 누적 눈금 — 끝 눈금(자동 · 고정 · 일강수 · 사례)마다 열 칸 남짓 */
const ACC_FINE = {
  15: [0.1, 0.5, 1, 2, 3, 4, 5, 7, 10, 12, 15],
  30: [0.1, 1, 2, 3, 5, 7, 10, 15, 20, 25, 30],
  60: [0.1, 1, 3, 5, 10, 15, 20, 25, 30, 40, 50, 60],
  120: [0.1, 1, 5, 10, 20, 30, 40, 50, 60, 80, 100, 120],
  150: [0.1, 1, 5, 10, 20, 30, 50, 70, 90, 110, 130, 150],
  250: [0.1, 5, 10, 20, 40, 60, 80, 100, 150, 200, 250],
  300: [1, 10, 20, 50, 80, 100, 150, 200, 250, 300],
  500: [1, 10, 30, 50, 80, 100, 150, 200, 250, 300, 400, 500],
  700: [1, 20, 50, 100, 150, 200, 300, 400, 500, 600, 700],
  800: [1, 20, 50, 100, 150, 200, 300, 400, 500, 600, 700, 800],
};
const fine = st => (kmaOn() && ACC_FINE[st.at(-1)]) || st;
/* 다양한 색조(10-24) — 기상청 QPF 범례처럼 한 색에 서너 색조(파랑 3 · 초록 4 · 노랑 5 · 빨강 4 · 보라 4)를 다 쓴다.
   누적 눈금은 0.1 다음부터 고른 간격(끝 눈금 ÷ 20 남짓 — 100 이면 5㎜ 단위)으로 스무 칸 남짓, 끝 눈금은 자료를 바짝 따른다
   (RICH_TOPS — 자동이면 경남 시군 최대가 드는 가장 작은 것, 작아질 땐 한참 작아질 때만). 시간 강수는 레이더 경계 그대로 */
const RICH_TOPS = [10, 15, 20, 30, 40, 50, 60, 80, 100, 120, 150, 200, 250, 300, 400, 500, 600, 800, 1000];
const RICH_TOP = {};                                    // 층마다 고른 끝 눈금
const RICH_D = [0.5, 1, 1.5, 2, 2.5, 3, 4, 5, 6, 7.5, 8, 10, 12.5, 15, 20, 25, 30, 35, 40, 50];
function richSteps(T) {
  const d = RICH_D.find(x => T / x <= 21 && Math.abs(T / x - Math.round(T / x)) < 1e-9) || T / 20;
  const out = [0.1];
  for (let i = 1; i * d <= T + 1e-9; i++) out.push(+(i * d).toFixed(2));
  return out;
}
/* 누적 층 눈금 — 청색 7칸 · 기상청 색 열 칸 남짓(ACC_FINE) · 다양한 색조 스무 칸 남짓 */
function accStepsOf(k) {
  if (richOn()) return richSteps(accFix() ? scTop() : CASE && k === "acc" ? 700 : RICH_TOP[k] || accSteps(k).at(-1));
  return fine(k === "acc" && CASE ? accFix() || STEPS.event : accSteps(k));
}
const HOURLY = new Set(["obs15", "obs60", "aws60", "odam", "vsrt"]);
// 기상청 색 · 다양한 색조 둘 다 레이더 범례 색을 쓴다(시간 강수는 레이더 경계 그대로). 다른 것은 누적의 눈금 · 색 고르기
const kmaOn = () => (PAL === "kma" || PAL === "rich") && !!KMA_LG;
const richOn = () => PAL === "rich" && !!KMA_LG;
const PAL_NAME = { blue: "청색", kma: "기상청 색", rich: "다양한 색조" };
async function loadKmaLegend() {
  try {
    const lg = await getJson("/api/qpf/legend");
    const steps = [], cols = [];
    lg.bounds.forEach((v, i) => {
      // 기상청 범례는 약한 쪽에 0.1 을 두 번 찍는다 — 앞 칸은 0.1 미만(칠하지 않는 자리)이라 뒤 칸을 쓴다
      if (steps.length && steps[steps.length - 1] === +v) cols[cols.length - 1] = lg.colors[i];
      else { steps.push(+v); cols.push(lg.colors[i]); }
    });
    KMA_LG = steps.length >= 7 && steps.length === cols.length ? { steps, cols } : null;
  } catch { KMA_LG = null; }
  KCOL.clear();
}
/* 약한 쪽을 땅 색 쪽으로 — 맨 아래 칸은 35%, 그다음 칸도 1㎜ 아래면 65%만 그 색(테마마다 땅 색이 달라 테마마다 따로) */
const KCOL = new Map();
function fadeLow(cols, steps, key) {
  const k = key + "|" + document.documentElement.dataset.theme;
  if (KCOL.has(k)) return KCOL.get(k);
  const land = cssColor("--land");
  const mix = (c, t) => "#" + hexRgb(c).map((x, i) => Math.round(land[i] + (x - land[i]) * t).toString(16).padStart(2, "0")).join("");
  const out = cols.map((c, i) => (i === 0 ? mix(c, 0.35) : i === 1 && steps[1] <= 1 ? mix(c, 0.65) : c));
  KCOL.set(k, out);
  return out;
}
const kmaHour = () => fadeLow(KMA_LG.cols, KMA_LG.steps, "h" + KMA_LG.cols.join(""));
/* 누적 n칸 — 레이더 범례에서 서로 또렷이 갈리는 색만 골라(KMA_SEQ, 레이더 단계 ㎜/h) 그 사이를 고르게.
   ⚠️ 범례 23색을 고르게 뽑았더니 짙은 초록(#005a00)이 어두운 바탕에 묻히고 노랑이 셋 붙었다 — 하늘 · 파랑 · 초록 · 노랑 ·
   주황 · 빨강 · 보라 차례로. 레이더 색 그 자체는 서버가 뽑은 것(색을 흉내 내지 않는다) */
// 끝은 60(짙은 보라) — 70㎜/h 색(#b3b4de 옅은 남보라)은 끝 눈금을 넘은 많은 비가 물 · 약한 비처럼 보여 뺐다(11-10)
const KMA_SEQ = [0.1, 0.5, 1, 2, 3, 6, 8, 15, 20, 25, 40, 50, 60];
function kmaPick(steps) {
  // 다양한 색조 — 범례 색을 다 쓴다. 어두운 · 회색 바탕에서는 맨 위 짙은 남색 둘(90 · 110㎜/h)이 묻혀 뺀다(밝은 테마는 다)
  const seq = richOn() ? KMA_LG.cols.slice(0, document.documentElement.dataset.theme === "light" ? undefined : -2)
    : KMA_SEQ.map(v => KMA_LG.cols[Math.max(0, stepIdx(v, KMA_LG.steps) - 1)]);
  const n = steps.length, L = seq.length - 1;
  const cols = steps.map((_, i) => seq[n >= seq.length ? Math.min(L, i) : Math.round(i * L / Math.max(1, n - 1))]);
  return fadeLow(cols, steps, (richOn() ? "r" : "a") + steps.join(",") + KMA_LG.cols.join(""));
}
/* 이 층의 단계 → 색(CSS). 청색은 지도 램프 --map-r1~7, 기상청은 원본 색(약한 쪽만 바탕 쪽으로) */
const colsOf = k => !kmaOn() ? [1, 2, 3, 4, 5, 6, 7].map(i => `var(--map-r${i})`) : HOURLY.has(k) ? kmaHour() : kmaPick(stepsOf(k));
/* 값 → 색(없으면 null). hourly = 시간 강수(㎜/h) — 기상청 색이면 레이더 경계로. 패널 칸 · 막대 · 타임라인 점도
   지도와 같은 색이 되게 이것 하나로 칠한다 */
function rampColor(v, steps, hourly) {
  if (kmaOn() && hourly) { const i = stepIdx(v, KMA_LG.steps); return i ? kmaHour()[i - 1] : null; }
  const i = stepIdx(v, steps);
  return i ? (kmaOn() ? kmaPick(steps)[i - 1] : `var(--map-r${Math.min(7, i)})`) : null;
}
/* 청색 칸 위 글자 — 5단계(--map-r5)부터 밝은 칸이라 짙은 글자 */
const inkBlue = i1 => (i1 >= 5 ? "var(--on-accent)" : "var(--ink)");
/* 기상청 색 위 글자 — 밝은 칸(노랑 · 연두 · 하늘)엔 검은 글자, 어두운 칸엔 흰 글자.
   ⚠️ 기준을 150 으로 두니 #00ff00(휘도 149.7)에 흰 글자가 얹혀 안 읽혔다 — 140(3일 기온표와 같다) */
function inkOn(hex) {
  const [r, g, b] = hexRgb(hex);
  return 0.299 * r + 0.587 * g + 0.114 * b > 140 ? "#0B1016" : "#FFFFFF";
}

/* 재현 사례(?case=) — 지난 호우를 격자 그대로 되돌려 본다(data/demo/map/). 실황 설정은 건드리지 않는다 */
const CASE = /^[a-z0-9-]{1,64}$/.test(Q.get("case") || "") ? Q.get("case") : null;
let CASEM = null;                                       // 사례 meta(시군 시계열·산출 특보)
/* 실황의 '누적'(acc)은 오른쪽 강수 누적 카드와 **같은 구간**(지난 N시간 · 오늘/어제 0시부터)을 같은 격자 합으로 그린다 —
   카드에서 구간을 바꾸면 지도도 따라 바뀐다. 예전 '오늘 누적'(obsday)은 이것의 '오늘 0시부터'다(설정에 남은 obsday 는 acc 로) */
/* 'AWS 누적'(aws) — 같은 구간을 **관측소 값만으로** 메운 면(기상청 AWS + 경남 AWS, IDW). 격자 분석값을 쓰지 않는다 */
/* 'AWS 1시간'(aws60) — 정시 한 시간 몫을 같은 관측소 · 같은 IDW 로. 재생 흐름의 AWS 실측이다 */
const KINDS = CASE ? ["obs60", "acc"] : ["obs15", "obs60", "aws60", "acc", "aws", "odam", "vsrt", "shrt_today", "shrt_tomorrow"];
const ACCK = new Set(["acc", "aws"]);                  // 강수 누적 카드 구간을 따르는 층
const FLOWK = new Set(CASE ? ["obs60", "acc"] : ["obs60", "aws60", "vsrt"]);   // 재생 흐름에 드는 층
const OBSK = new Set(["obs60", "aws60"]);              // 재생 흐름의 실측 — 격자 60분 | AWS 1시간
/* 층 메뉴는 '무엇을 보나' 다섯 줄이다(15분 · 1시간 · 누적 / 초단기 · 단기). 1시간 · 누적 줄은 **자료**(격자 500m | AWS)에
   따라 다른 층을 그린다 — 자료는 오른쪽 '강수 누적' 카드 기준과 한 몸(ACC_BASIS, B 키 · 메뉴 머리 스위치).
   ⚠️ 예전에는 지도의 '누적 / AWS 누적' 층과 카드의 AWS↔격자 기준이 따로 놀아 둘이 다른 값을 보일 수 있었다 */
const SRCK = { h1: { grid: "obs60", aws: "aws60" }, acc: { grid: "acc", aws: "aws" } };
const SRC_OF = { obs60: "grid", acc: "grid", aws60: "aws", aws: "aws" };
const rowOf = k => (k === "obs60" || k === "aws60" || k === "odam") ? "h1" : ACCK.has(k) ? "acc" : k.startsWith("shrt") ? "shrt" : k;
const srcKind = row => SRCK[row][ACC_BASIS === "grid" ? "grid" : "aws"];
/* 지금 자료에 맞는 층 — 1시간(5km 실황은 그대로) · 누적은 자료를 따른다 */
const normKind = k => CASE || !SRC_OF[k] ? k : srcKind(rowOf(k));
/* 숫자 키 — 1 15분 · 2 1시간 · 3 누적 · 4 초단기 · 5 단기 오늘 · 6 단기 내일 (사례는 1 1시간 · 2 누적) */
const keyKind = i => CASE ? KINDS[i] : ["obs15", srcKind("h1"), srcKind("acc"), "vsrt", "shrt_today", "shrt_tomorrow"][i];
/* 재생 흐름의 실측 — 지금 보는 실측 층을 따르고, 실측이 아니면 자료(격자 | AWS)를 따른다 */
const flowSrc = () => OBSK.has(kind) ? SRC_OF[kind] : ACC_BASIS === "aws" ? "aws" : "grid";
const NOWL = CASE ? "끝" : "지금";
const COLLECT_OF = { obs15: "grid", obs60: "grid", obsday: "grid", acc: "grid", aws: "rain", aws60: "rain", odam: "odam", vsrt: "forecast",
                     shrt_today: "short", shrt_tomorrow: "short" };
const SET_DEFAULT = { flow_step: 10, flow_hours: 6, play_ms: 1200, tl_on: false, tl_stat: "max",
                      panel: "cards", acc_hours: 12, acc_from: "hours", acc_basis: "aws", sel_zoom: true, acc_fc: true, acc_h1: true,
                      acc_per: 1, acc_full: false, aws_live: false, acc_qpf: false, qpf_ms: 600, acc_date: "", acc_hdr_pin: true, acc_tone: false, sea_grid: "dim", al_pre: true, aws_off: [], gn_off: false, acc_scale: 0, sea_w: "fc", sea_rot: 0, sea_per: 1, shows: [] };

let META = null, TOPO = null, GEO = null, MSIG = null, MEMD = null, EMDN = null;
let SET = { ...SET_DEFAULT };
// 화면 재생(P) 상태 — 아래 '화면 재생' 칸. saveSetting 이 먼저 본다(재생 중엔 서버 설정을 건드리지 않는다)
const SHOW = { on: false, name: "", items: [], i: 0, timer: null, paused: false, prev: null };
let SLIDE_SC = 0;                         // 화면 재생 — 그 화면만 따로 쓰는 범례 끝 눈금(0 = 지도 설정 그대로)
const awsLive = () => !test && !CASE && !!SET.aws_live;      // AWS 실시간 감시(R) — setLive
let kind = "obs60", vsrtN = 1, x4 = false;
let OBS_TM = null;                      // 60분 층을 지난 시각으로 볼 때(재생·끌기)
let test = Q.get("test") === "1";
let CUR = null, CURSTAT = null;          // 지금 그리는 격자, 시군 통계
let FLOW = null;                        // /api/grid/flow — 재생 프레임과 시군 시계열
let playing = null;
let tlOn = false;
const GRIDS = new Map(), STATS = new Map();
let V = null;                           // 화면 틀(지도 칸 좌표 → 화면)
let MT = { tx: 0, ty: 0, sc: 1 };       // 타임라인이 나와 지도를 옮긴 만큼
let CAM = null;                         // 시군을 확대해 둔 틀 { s, ox, oy } — null 이면 경남 전체(MT 로 비켜선다)
let CAMU = null;                        // 사람이 옮긴 경남 전체 틀(지도 위치 C) — V 에 얹혀 있으면 그 틀, 아니면 null
let ZA = null;                          // 확대 애니메이션 중 { T, raf }
let GEN = null;                         // 위 SVG 를 마지막으로 그린 틀 — 날아가는 동안 CSS transform 으로 이 틀을 옮긴다(camFrame)
let NAMEBOX = [];
let FEAT = null;                        // 시군 GeoJSON(강조용)

const layerKey = () => kind === "vsrt" ? `vsrt+${vsrtN}` : kind;
const metaOf = k => (META?.layers || []).find(x => x.id === k) || {};
const stepsOf = k => (kmaOn() && HOURLY.has(k)) ? KMA_LG.steps
  : ACCK.has(k) ? accStepsOf(k) : k === "obs15" ? (x4 ? STEPS.m60 : STEPS.m15)
  : (k === "obsday" || k.startsWith("shrt")) ? (SLIDE_SC ? scSteps(SLIDE_SC) : richOn() ? richSteps(150) : fine(STEPS.day)) : STEPS.m60;
/* 15분 ×4 — 기상청 색이면 늘 ×4 다(레이더 색은 시간당 ㎜/h 의 자다) */
const factor = () => (kind === "obs15" && (x4 || kmaOn())) ? 4 : 1;
const tOf = key => new Date(+key.slice(0, 4), +key.slice(4, 6) - 1, +key.slice(6, 8),
                            +key.slice(8, 10) || 0, +key.slice(10, 12) || 0).getTime();

async function getJson(u) {
  const r = await fetch(u, { cache: "no-cache" });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
  return r.json();
}

/* ── 테마 — index.html 과 같은 자리(gn-theme)에 둔다. 한쪽에서 바꾸면 둘 다 따라간다. ── */
function applyTheme(t) {
  let th = t || Q.get("theme");
  if (!th) { try { th = localStorage.getItem("gn-theme"); } catch {} }
  th = th === "light" || th === "gray" ? th : "dark";
  document.documentElement.dataset.theme = th;
  return th;
}
function setTheme(th) {
  applyTheme(th);
  try { localStorage.setItem("gn-theme", th); } catch {}
  LUTS.clear(); OFF.clear();
  glTheme(); draw(); buildLegend(); buildPlay(); buildTL();
}

/* ── 투영(칸 → 경위도). 마우스를 올렸을 때 좌표만 쓴다 — 그리기에는 쓰지 않는다.
   app/domain/gridproj.py 와 같은 식: GRS80 타원체 람베르트, 30°·60°, 126°E·38°N. ── */
const LCC = (() => {
  const D = Math.PI / 180, a = 6378137, f = 1 / 298.257222101, e = Math.sqrt(f * (2 - f));
  const m = p => Math.cos(p) / Math.sqrt(1 - e * e * Math.sin(p) ** 2);
  const t = p => Math.tan(Math.PI / 4 - p / 2) / ((1 - e * Math.sin(p)) / (1 + e * Math.sin(p))) ** (e / 2);
  const p1 = 30 * D, p2 = 60 * D, p0 = 38 * D;
  const n = (Math.log(m(p1)) - Math.log(m(p2))) / (Math.log(t(p1)) - Math.log(t(p2)));
  const AF = a * m(p1) / (n * t(p1) ** n), rho0 = AF * t(p0) ** n;
  return (col, row) => {
    const x = (col - 880) * 500, y = (row - 1540) * 500, dy = rho0 - y;
    const rho = Math.hypot(x, dy), th = Math.atan2(x, dy), tt = (rho / AF) ** (1 / n);
    let phi = Math.PI / 2 - 2 * Math.atan(tt);
    for (let i = 0; i < 15; i++) {
      const s = Math.sin(phi);
      phi = Math.PI / 2 - 2 * Math.atan(tt * ((1 - e * s) / (1 + e * s)) ** (e / 2));
    }
    return [th / n / D + 126, phi / D];
  };
})();

/* ── 화면 틀: 칸 좌표 → 화면 ─────────────────────────────────────────── */
function gnBounds() {
  let x0 = 1e9, x1 = -1e9, y0 = 1e9, y1 = -1e9;
  for (const ft of FEAT) {
    if (ft.properties.kind !== "gn") continue;
    // 섬이 없는 시군은 mapshaper 가 Polygon 으로 내보낸다
    const polys = ft.geometry.type === "Polygon" ? [ft.geometry.coordinates] : ft.geometry.coordinates;
    for (const poly of polys) for (const ring of poly) for (const [x, y] of ring) {
      if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
  }
  return { x0, x1, y0, y1 };
}
let GNB = null;
function layout() {
  const k = Math.max(1, Math.min(innerWidth / 1920, innerHeight / 1080));
  document.documentElement.style.setProperty("--k", k.toFixed(3));
  const r = $("stage").getBoundingClientRect();
  const W = r.width, H = r.height, dpr = window.devicePixelRatio || 1;
  const m = 5;                                  // 칸 — 경남 바깥으로 2.5km 여유
  const X0 = GNB.x0 - m, X1 = GNB.x1 + m, Y0 = GNB.y0 - m, Y1 = GNB.y1 + m;
  const s = Math.min(W / (X1 - X0), H / (Y1 - Y0));
  const ox = (W - (X1 - X0) * s) / 2, oy = (H - (Y1 - Y0) * s) / 2;
  // s·ox·oy = 지금 틀(시군을 확대하면 바뀐다), b = 경남 전체 틀, u = 글자·점 크기 기준(확대해도 그대로)
  V = { W, H, dpr, k, s, ox, oy, X0, X1, Y0, Y1, u: s, b: { s, ox, oy },
        toX: gx => V.ox + (gx - X0) * V.s, toY: gy => V.oy + (Y1 - gy) * V.s,
        fromX: x => X0 + (x - V.ox) / V.s, fromY: y => Y1 - (y - V.oy) / V.s };
  if (ZA) { cancelAnimationFrame(ZA.raf); ZA = null; }
  CAM = null; CAMU = null;
  $("stage").classList.remove("zooming", "zoomed");
  $("over").setAttribute("viewBox", `0 0 ${W} ${H}`);
  $("over").style.transform = "";
  glCam();
  buildBase();
  applyTL(false);
}

/* ── 경계(땅 · 선은 GL, 위 SVG 는 이름 · 강조 · 표식) ───────────────────────────────────── */
let PATH = null;
function buildBase() {
  const G = GEN = { s: V.s, ox: V.ox, oy: V.oy };
  PATH = d3.geoPath(d3.geoTransform({ point(x, y) { this.stream.point(G.ox + (x - V.X0) * G.s, G.oy + (V.Y1 - y) * G.s); } }));
  const P = g => g.properties;
  glBase();                                                             // 땅 · 경계선은 GL(01b) — 한 번만 올린다
  const fs = Math.max(15, Math.min(64, V.u * 7));
  FSN = fs;
  NAMEBOX = [];
  const names = FEAT.map(ft => {
    const p = P(ft), x = V.toX(p.lx), y = V.toY(p.ly), nb = p.kind === "nb";
    const f = nb ? fs * 0.72 : fs;
    NAMEBOX.push({ x0: x - p.sigun.length * f * 0.52, x1: x + p.sigun.length * f * 0.52,
                   y0: y - f * 0.6, y1: y + f * 0.6 });
    return `<text class="nm ${nb ? "nb" : ""}" data-s="${p.sigun}" x="${x.toFixed(1)}" y="${y.toFixed(1)}"
      style="font-size:${f.toFixed(1)}px;stroke-width:${(f * 0.16).toFixed(1)}px">${p.sigun}</text>`;
  }).join("");
  $("over").innerHTML =
    `<g id="walerts"></g><path id="hl"/><path id="selh"/><path id="sel"/><g id="emdn"></g><g id="wlab"></g><g id="stns"></g><g id="safg"></g><g id="rivr"></g><g id="tidr"></g><g id="labels"></g><g id="names">${names}</g><g id="tempg"></g>`
    + `<g id="wbadge"></g><g id="ranks"></g><g id="hot"></g>`;
  HL = null;
  drawAlerts();
  drawRanks();
  drawHeat();
  drawSel();
  drawEmd();
  paintWatch();
}
let FSN = 20;                           // 시군명 글자 크기(순위 표식 자리 잡는 데 쓴다)

/* 한 시군 강조 — 타임라인 줄과 지도가 서로를 가리킨다 */
let HL = null;
function highlight(name) {
  if (HL === name) return;
  HL = name;
  const p = $("hl");
  if (p) {
    const ft = name && FEAT.find(f => f.properties.sigun === name);
    if (ft) p.setAttribute("d", PATH(ft));
    p.classList.toggle("on", !!ft);
  }
  for (const r of document.querySelectorAll(".tl-row, .ar, .mr, .fr, #sw .nw, #sw .av"))
    r.classList.toggle("hov", !!name && r.dataset.s === name);
}

/* ── 색 ─────────────────────────────────────────────────────────────── */
function hexRgb(v) {
  const h = v.trim().replace("#", "");
  return [parseInt(h.slice(0, 2), 16), parseInt(h.slice(2, 4), 16), parseInt(h.slice(4, 6), 16)];
}
function cssColor(name) {
  return hexRgb(getComputedStyle(document.documentElement).getPropertyValue(name));
}
/* 'var(--rain-3)' 이든 '#ffdc1f' 든 RGB 로 */
const rgbOf = c => c.startsWith("var(") ? cssColor(c.slice(4, -1)) : hexRgb(c);
const LUTS = new Map();
/* 0.1㎜ 정수값 → RGBA(Uint32, 리틀엔디언 ABGR). 65536 칸짜리 표를 한 번 만들어 둔다. */
function lut(steps, fac, css) {
  const key = steps.join(",") + "|" + fac + "|" + css.join(",") + "|" + document.documentElement.dataset.theme;
  if (LUTS.has(key)) return LUTS.get(key);
  const cols = css.map(rgbOf).map(([r, g, b]) => (255 << 24 | b << 16 | g << 8 | r) >>> 0);
  const t = new Uint32Array(65536);
  const th = steps.map(x => x * 10 / fac - 1e-6);   // 0.1㎜ 정수값 기준
  let k = -1;
  for (let v = 0; v < 65535; v++) {
    while (k + 1 < th.length && v >= th[k + 1]) k++;
    t[v] = k < 0 ? 0 : cols[k];
  }
  LUTS.set(key, t);
  return t;
}
/* 값 → 색 단계(1~7, 0 = 칠하지 않음). 타임라인 점도 지도와 **같은 색**이 되게 같은 단계를 쓴다. */
function stepIdx(v, steps) {
  let k = 0;
  if (v == null) return 0;
  steps.forEach((t, i) => { if (v >= t) k = i + 1; });
  return k;
}

/* 5km 칸마다 '땅이 조금이라도 걸치나' — 결측 빗금은 땅에만 긋는다.
   경남 bbox 안의 결측은 거의 다 분석 영역 밖 바다(늘 같은 칸)라 빗금을 치면 바다가 온통 회색이 된다. */
let LAND5 = null;
function landMask(grid, h, w) {
  if (grid === "hr") return MSIG;
  if (LAND5) return LAND5;
  const g = META.grids, hb = g.hr, db = g.dfs, [A, B, C] = g.dfs_to_hr.col, [Dd, E, F] = g.dfs_to_hr.row;
  LAND5 = new Uint8Array(h * w);
  for (let r = 0; r < h; r++) for (let c = 0; c < w; c++) {
    let on = 0;
    for (let a = -2; a <= 2 && !on; a++) for (let b = -2; b <= 2 && !on; b++) {
      const x5 = db.i0 + c + a / 5, y5 = db.j0 + r + b / 5;
      const cc = Math.round(A * x5 + B * y5 + C) - hb.i0, rr = Math.round(Dd * x5 + E * y5 + F) - hb.j0;
      if (cc >= 0 && cc < hb.w && rr >= 0 && rr < hb.h && MSIG[rr * hb.w + cc]) on = 1;
    }
    LAND5[r * w + c] = on;
  }
  return LAND5;
}

/* 바다 격자 — 경남 · 부산 · 울산 땅(시군 칸 지도) 밖 칸(바다 · 그 너머)은 옅게 칠한다(서버 설정 sea_grid).
   ⚠️ 바다 위 비도 땅과 같은 세기로 칠했더니 해안선이 묻혀 땅 · 바다가 갈리지 않았다(10-25). 다가오는 비 띠는 보이게 끄지는 않는다(기본) */
const SEA_A = { full: 1, dim: 0.35, off: 0 };
const seaA = () => SEA_A[SET.sea_grid] ?? SEA_A.dim;
/* 격자 한 장을 칸 = 픽셀인 작은 그림으로. 층·눈금·테마마다 한 번만 만든다. */
const OFF = new Map();
function offscreen(gr) {
  const steps = stepsOf(kind), fac = factor(), css = colsOf(kind), sa = seaA();
  const key = gr.ck + "|" + steps.join(",") + "|" + fac + "|" + css.join(",") + "|" + document.documentElement.dataset.theme + "|" + sa;
  if (OFF.has(key)) return OFF.get(key);
  const { h, w, u, grid } = gr;
  const table = lut(steps, fac, css), land = landMask(grid, h, w);
  const img = document.createElement("canvas"); img.width = w; img.height = h;
  const ic = img.getContext("2d"), id = ic.createImageData(w, h), px = new Uint32Array(id.data.buffer);
  const miss = document.createElement("canvas"); miss.width = w; miss.height = h;
  const mc = miss.getContext("2d"), md = mc.createImageData(w, h), mp = new Uint32Array(md.data.buffer);
  let nmiss = 0;
  for (let r = 0; r < h; r++) {
    const src = r * w, dst = (h - 1 - r) * w;                // 행 남→북 → 그림은 위가 북
    for (let c = 0; c < w; c++) {
      const v = u[src + c];
      if (v === MISSING) {
        if (land[src + c]) { mp[dst + c] = 0xff000000; nmiss++; }
      } else if (land[src + c] || sa === 1) px[dst + c] = table[v];
      else if (sa) { const t = table[v]; px[dst + c] = (t & 0xffffff) | (Math.round((t >>> 24) * sa) << 24); }
    }
  }
  ic.putImageData(id, 0, 0);
  mc.putImageData(md, 0, 0);
  const o = { img, miss: nmiss ? miss : null, nmiss };
  if (OFF.size > 120) OFF.clear();
  OFF.set(key, o);
  return o;
}

let RENDER_MS = 0;
/* 격자를 GL 캔버스 소스로(01b glRain), 위에 시군 최대 라벨. 카메라만 움직일 때는 부르지 않는다 — GL 이 알아서 따라간다.
   fade: 재생·끌기로 프레임이 넘어갈 때 앞 그림을 잠깐 남겨 겹쳐 사라지게 한다(뚝뚝 끊기지 않게). */
function draw(fade = false) {
  const t0 = performance.now();
  glRain(CUR && V?.s ? offscreen(CUR) : null, CUR, fade);
  drawLabels();
  RENDER_MS = performance.now() - t0;
}

/* ── 시군 최대 라벨 — 값이 있는 시군만. 이름·앞 라벨과 겹치면 자리를 옮긴다. ── */
function drawLabels() {
  const g = $("labels");
  if (!g) return;
  if (!CURSTAT || !V || !V.s) { g.innerHTML = ""; LABELBOX = NAMEBOX.concat(ALERTBOX); drawStations(); return; }
  const fac = factor(), min = stepsOf(kind)[0];
  const rows = CURSTAT.rows.filter(r => r.kind === "gn" && r.max != null && r.max * fac >= min && r.where)
    .sort((a, b) => b.max - a.max);
  const fs = Math.max(14, Math.min(58, V.u * 6.2)), fs2 = fs * 0.62;
  // 다른 시군의 점 바로 옆에 붙으면 누구 값인지 헷갈린다 — 점 자리도 미리 비워 둔다
  const pr = fs * 0.45;
  const placed = NAMEBOX.concat(ALERTBOX, rows.map(r => {
    const x = V.toX(r.where.col), y = V.toY(r.where.row);
    return { x0: x - pr, x1: x + pr, y0: y - pr, y1: y + pr };
  })), out = [];
  const hit = b => placed.some(p => b.x0 < p.x1 && b.x1 > p.x0 && b.y0 < p.y1 && b.y1 > p.y0);
  const inside = b => b.x0 >= 4 && b.y0 >= 4 && b.x1 <= V.W - 4 && b.y1 <= V.H - 4;
  for (const r of rows) {
    const ax = V.toX(r.where.col), ay = V.toY(r.where.row);
    const val = (r.max * fac).toFixed(1);
    const emd = r.where.emd || "";
    const w = Math.max(val.length * fs * 0.62, emd.length * fs2 * 1.02) + 4, h = fs + fs2 + 2;
    const pad = pr + 3;                      // 제 점 자리(pr)는 건너뛴다
    let best = null;
    for (const k of [1, 1.9, 3]) {
      const d = pad * k;
      for (const [dx, dy] of [[d, -h / 2], [-d - w, -h / 2], [-w / 2, -d - h], [-w / 2, d],
                              [d, -h - d / 2], [d, d / 2], [-d - w, -h - d / 2], [-d - w, d / 2]]) {
        const b = { x0: ax + dx, y0: ay + dy, x1: ax + dx + w, y1: ay + dy + h };
        if (inside(b) && !hit(b)) { best = b; break; }
      }
      if (best) break;
    }
    // 끝내 빈자리가 없으면 오른쪽에 그냥 둔다 — 극값은 가리더라도 빼지 않는다
    best = best || { x0: ax + pad, y0: ay - h / 2, x1: ax + pad + w, y1: ay + h / 2 };
    placed.push(best);
    const cx = Math.max(best.x0, Math.min(ax, best.x1)), cy = Math.max(best.y0, Math.min(ay, best.y1));
    const far = Math.hypot(cx - ax, cy - ay) > pad * 1.3;
    out.push(
      (far ? `<line class="lead" x1="${ax}" y1="${ay}" x2="${cx}" y2="${cy}"/>` : "")
      + `<circle class="pin" cx="${ax.toFixed(1)}" cy="${ay.toFixed(1)}" r="${Math.max(3, fs * 0.17).toFixed(1)}" stroke-width="${Math.max(1.5, fs * 0.08).toFixed(1)}"/>`
      + `<text class="mx" x="${(best.x0 + 2).toFixed(1)}" y="${(best.y0 + fs * 0.86).toFixed(1)}"
          style="font-size:${fs.toFixed(1)}px;stroke-width:${(fs * 0.16).toFixed(1)}px">${val}</text>`
      + (emd ? `<text class="mxw" x="${(best.x0 + 2).toFixed(1)}" y="${(best.y0 + fs + fs2 * 0.86).toFixed(1)}"
          style="font-size:${fs2.toFixed(1)}px;stroke-width:${(fs2 * 0.18).toFixed(1)}px">${emd}</text>` : ""));
  }
  g.innerHTML = out.join("");
  LABELBOX = placed;                     // 관측소 글자가 피해 갈 자리(이름·특보 딱지·최대 라벨)
  drawStations();
}

/* ── 범례 ─────────────────────────────────────────────────────────── */
const BAND_H = 182;                                   // 색 띠 높이(px) — 청색 7칸 × 26
function buildLegend() {
  const st = stepsOf(kind), css = colsOf(kind), lg = $("legend"), kma = kmaOn(), many = st.length > 13;
  const radar = kma && HOURLY.has(kind);                 // 레이더 23칸 — 눈금은 종합 화면 예측 분포와 같은 자리만
  const unit = (kind === "obsday" || ACCK.has(kind) || kind.startsWith("shrt")) ? "㎜ 누적" : factor() === 4 ? "㎜/h 환산" : "㎜";
  const cells = css.map(c => `<i style="background:${c}"></i>`).join("");
  // 레이더 23칸은 눈금을 띄엄띄엄(종합 화면 예측 분포와 같은 자리) — 칸마다 적으면 글자가 겹친다.
  // 띠도 조금 늘린다: 182px 로는 10·20·30·50 이 두 칸(16px)씩이라 글자가 붙었다
  // 기상청 색 누적(열 칸 남짓)은 칸마다 21px — 눈금을 다 적는다
  // 다양한 색조 누적(스무 칸 남짓)은 칸마다 11px(레이더 띠와 같은 높이 — 왼쪽 특보 줄 자리를 남긴다) — 눈금은 두세 칸 건너 하나(맨 위는 늘)
  const bh = radar ? 230 : many ? st.length * 11 : st.length > 7 ? st.length * 21 : BAND_H, ch = bh / st.length;
  const every = many && !radar ? Math.ceil(st.length / 10) : 1;
  const ticks = st.map((v, i) => (radar ? KMA_TICKS.includes(v) : !many || i % every === 0 || i === st.length - 1)
    ? `<span style="bottom:${(i * ch).toFixed(1)}px">${v}</span>` : "").join("");
  const tip = richOn() && !HOURLY.has(kind) ? "다양한 색조 — 기상청 QPF 범례 색을 다 쓴다(한 색에 서너 색조). 누적 눈금은 스무 칸 남짓 고른 간격, 끝 눈금은 자료를 바짝 따른다. 누르면 청색 · 오른쪽 클릭으로 고르기"
    : kma ? (HOURLY.has(kind) ? `기상청 레이더 색(예측 분포 그림 범례에서 뽑은 색 · 같은 ㎜/h 경계)${richOn() ? " — 다양한 색조도 시간 강수는 레이더 경계 그대로" : ""} — 누르면 ${richOn() ? "청색" : "다양한 색조"}`
                                      : "기상청 레이더 색 — 누적은 레이더에 같은 자가 없어 눈금을 열 칸 남짓으로 잘게 나누고 색을 레이더 범례에서 고르게 빌렸다(약한 쪽은 바탕 쪽으로). 누르면 다양한 색조")
                  : "누르면 기상청 레이더 색으로(노랑 · 빨강 · 보라가 특보 선 색과 겹친다)";
  // 15분: 기상청 색이면 늘 ×4(레이더는 시간당 자) — 단추는 켠 채 잠근다
  const x4b = kind !== "obs15" ? "" : kma
    ? `<button id="b-x4" class="on" disabled title="기상청 레이더 색은 시간당(㎜/h) 자라 15분 값을 ×4 로 본다 — 청색으로 돌리면 고를 수 있다">×4 환산</button>`
    : `<button id="b-x4" class="${x4 ? "on" : ""}" title="15분 값을 ×4 — 시간당 기세로 60분치·특보 기준과 같은 자로 본다">${x4 ? "×4 환산" : "그대로"}</button>`;
  lg.innerHTML = `<div class="lt">${unit}${x4b}</div>
    <div class="rows"><div class="band" title="${tip}" style="height:${bh}px">${cells}</div><div class="ticks">${ticks}</div></div>
    ${PAL !== "blue" && !kma ? `<div class="note">기상청 색을 아직 못 받았다 — 예측 분포 그림을 한 번 받으면 생긴다. 지금은 청색</div>` : ""}
    ${ACCK.has(kind) && (!CASE || accFix()) ? `<div class="note" title="${accFix() ? `눈금을 ${scTop()}㎜ 끝으로 고정했다(${ACC_FIXED_NOTE[scTop()]})${SLIDE_SC ? " — 화면 재생에서 이 화면만" : " — 화면 모두 같이"}. ` : "누적 눈금은 자료 크기에 맞춰 자동으로 고른다 — 경남 시군 최대 중 가장 큰 값이 끝 눈금 근처에 오게. 갱신해서 커지면 곧바로, 작아지면 다 들 때 바뀐다. "}범례를 오른쪽 클릭하면 색(청색 · 기상청 색 · 다양한 색조)과 눈금(자동 · 30 · 60 · 150 · 300 · 800㎜)을 고른다">${accFix() ? `고정 눈금 ${scTop()}㎜${SLIDE_SC ? " · 이 화면" : ""}` : richOn() ? `자동 눈금 · 끝 ${st.at(-1)}` : "자동 눈금"}${ACC_HI[kind] != null && !CASE ? ` · 최대 ${(+ACC_HI[kind]).toFixed(ACC_HI[kind] >= 100 ? 0 : 1)}㎜` : ""}</div>` : ""}
    <div class="sw"><b class="h"></b>결측(땅)</div>
    <div class="sw"><b style="background:var(--land)"></b>0 · 비 없음</div>`;
  const b = $("b-x4");
  if (b && !kma) b.onclick = () => { x4 = !x4; saveSetting({ x4 }); buildLegend(); draw(); paintHead(); };
  lg.querySelector(".band").onclick = togglePal;
  fitAlCol();
}
/* 범례 색 띠를 누르면 청색 ↔ 기상청 레이더 색. 지도 · 범례 · 관측소 · 타임라인 · 패널 칸이 같이 바뀐다 */
/* 색 띠를 누르면 청색 → 기상청 색 → 다양한 색조 → 청색. 오른쪽 클릭 메뉴 · 설정 › 화면에서 바로 고른다 */
const togglePal = () => setPal({ blue: "kma", kma: "rich", rich: "blue" }[PAL] || "blue");
async function setPal(p) {
  if (p !== "blue" && !KMA_LG) await loadKmaLegend();
  PAL = p;                             // 기상청 범례를 못 받았으면 범례에 그렇게 적고 청색으로 남는다(다음에 다시 받는다)
  if (p !== "blue" && !KMA_LG) { buildLegend(); PAL = "blue"; return; }
  saveSetting({ pal: PAL });
  updScale();                          // 다양한 색조는 끝 눈금을 자료에 바짝 — 바꾼 자리에서 고른다
  buildLegend(); draw(); paintHead(); buildTL();
  if (CARDS && !CARDS.err) renderCards();
}
/* 누적 눈금 고르기 — 누적 층(격자 · AWS) 범례를 오른쪽 클릭. 자동 + 고정 다섯(ACC_FIXED) */
function setAccScale(v) {
  SET.acc_scale = v;
  saveSetting({ acc_scale: v });
  updScale(); buildLegend(); draw(); paintHead(); buildTL();
  if (CARDS && !CARDS.err) renderCards();
}
function lgPop(ev) {
  const pop = $("lg-pop");
  if (!ev) { pop.classList.remove("open"); pop.hidden = true; return; }
  const cur = accFix() ? SET.acc_scale : 0, acc = ACCK.has(kind);
  const auto = CASE ? STEPS.event : ACC_LADDER[ACC_TIER[kind] ?? 3];
  // 눈금 줄 — 지금 색으로 실제 칸(다양한 색조는 스무 칸 남짓이라 앞 · 뒤만)
  const show = (v, st) => { const a = richOn() ? richSteps(v || st.at(-1)) : fine(st); return a.length > 12 ? `${a.slice(0, 4).join(" · ")} … ${a.slice(-2).join(" · ")} (${a.length}칸)` : a.join(" · "); };
  const opt = (v, l, st) => `<button data-s="${v}" class="${cur === v ? "on" : ""}">${l}<small class="st">${show(v, st)}</small></button>`;
  const pal = p => `<button data-p="${p}" class="${PAL === p ? "on" : ""}">${PAL_NAME[p]}<small>${{ blue: "한 색 · 약한 비는 바탕 쪽", kma: "레이더 색 · 누적 열 칸 남짓", rich: "QPF 범례 색 다 · 한 색에 서너 색조" }[p]}</small></button>`;
  pop.innerHTML = `<div class="g">지도 색</div>` + ["blue", "kma", "rich"].map(pal).join("")
    + (acc ? `<div class="sep"></div><div class="g">누적 눈금</div>`
      + opt(0, `자동 — ${CASE ? "사례 눈금" : richOn() ? "자료에 바짝" : "자료 크기에 맞춰"}`, richOn() && !CASE ? [RICH_TOP[kind] || auto.at(-1)] : auto)
      + Object.entries(ACC_FIXED).map(([v, st]) => opt(+v, `${v}㎜ <small>${ACC_FIXED_NOTE[v]}</small>`, st)).join("")
      + `<div class="note">AWS 누적 · 격자 누적이 같이 바뀐다 — 화면 모두 같이(서버 설정). 설정(Ctrl+,) › 화면에도 있다</div>` : "");
  // 범례 오른쪽 옆에 — 색 띠를 덮지 않게(고르면서 띠를 본다). 밑은 범례 밑에 맞춘다
  const rc = $("stage").getBoundingClientRect(), lg = $("legend").getBoundingClientRect(), k = V?.k || 1;
  pop.hidden = false;
  const pw = pop.offsetWidth * k, ph = pop.offsetHeight * k;
  pop.style.left = Math.max(4, Math.min(lg.right - rc.left + 10, rc.width - pw - 8)) / k + "px";
  pop.style.top = Math.max(4, Math.min(lg.bottom - rc.top - ph, rc.height - ph - 8)) / k + "px";
  void pop.offsetWidth; pop.classList.add("open");
  for (const b of pop.querySelectorAll("button")) b.onclick = e => {
    e.stopPropagation(); lgPop(null);
    if (b.dataset.p) { if (b.dataset.p !== PAL) setPal(b.dataset.p); return; }
    if (+b.dataset.s !== cur) setAccScale(+b.dataset.s);
  };
}
// 오른쪽 클릭 — 색은 모든 층, 눈금은 누적 층만(시간 강수는 시우량 눈금 하나)
$("legend").addEventListener("contextmenu", ev => { ev.preventDefault(); lgPop(ev); });
document.addEventListener("pointerdown", ev => { if (!$("lg-pop").hidden && !ev.target.closest?.("#lg-pop")) lgPop(null); });

/* ── 머리 ─────────────────────────────────────────────────────────── */
/* 지금 시각 — 시연(스냅숏)이면 서버가 멈춰 둔 그 시각(/api/clock.js 가 맨 먼저 window.GN_NOW 를 둔다) */
const NOWD = () => (window.GN_NOW ? new Date(window.GN_NOW) : new Date());
/* 시연 서버(:8001 — 언레이드 gn-demo · PC python -m app.main --demo) 주소. 실황은 8000.
   ⚠️ PC 가 서버에서 받는 중이면 시연도 그 서버의 것이다 — 이 PC 의 8001 이 아니라 서버의 8001 */
let SNAP_HOST = location.hostname;
if (!window.GN_SNAP) getJson("/api/origin").then(o => { if (o.mode === "server" && o.url) SNAP_HOST = new URL(o.url).hostname; }).catch(() => {});
const SNAP_URL = (path = "") => `${location.protocol}//${SNAP_HOST}:8001${path}`;
/* 그 시연으로 연다 — 시연 서버가 다른 것을 띄우고 있으면 갈아 탄다(몇 초) */
const SNAP_OPEN = (name, to) => SNAP_URL(`/snap/${encodeURIComponent(name)}?to=${encodeURIComponent(to)}`);
const LIVE_URL = (path = "") => `${location.protocol}//${location.hostname}:8000${path}`;
const hm = t => t ? `${t.slice(8, 10)}:${t.slice(10, 12)}` : "—";
const md = t => t ? `${+t.slice(4, 6)}.${+t.slice(6, 8)}.` : "";
function when(gr) {
  if (!gr || !gr.tm) return "";
  const t = gr.tm;
  switch (kind) {
    case "aws":
    case "acc": {
      // 첫 칸은 그 앞 한 시간 몫이다(01:00 = 00~01시) — 시작은 한 시간 앞으로 적는다
      const f0 = gr.from ? new Date(tOf(gr.from) - 3600e3) : null;
      const fs = f0 ? `${f0.getMonth() + 1}.${f0.getDate()}. ${String(f0.getHours()).padStart(2, "0")}:00` : "";
      return `${fs}부터 ${md(t)} ${hm(t)}까지`;
    }
    case "obs15": return `${md(t)} ${hm(t)} · 15분`;
    case "obs60": return `${md(t)} ${hm(t)} · 60분`;
    case "aws60": return gr.live ? `${md(t)} ${hm(t)} · 직전 1시간(매분)` : `${md(t)} ${hm(t)} · 1시간(정시)`;
    case "obsday": return `${md(t)} 00:00~${hm(t)}`;
    case "odam": return `${md(t)} ${hm(t)} · 1시간`;
    case "vsrt": return `${hm(gr.tmfc)} 발표 → ${+t.slice(8, 10)}시까지 1시간 (+${vsrtN}h)`;
    default: {
      const [a, b] = gr.hours || [];
      const from = a ? +a.slice(8, 10) - 1 : "", to = b ? (+b.slice(8, 10) || 24) : "";
      return `${gr.tmfc ? +gr.tmfc.slice(8, 10) + "시 발표 · " : ""}${md(t)} ${from}~${to}시 합`;
    }
  }
}
function isPast() {                     // 일부러 지난 시각을 보는 중 — 지연이 아니다
  return !CASE && (pinned(kind) || (OBSK.has(kind) && OBS_TM && OBS_TM !== metaOf(kind).tm));
}
/* 층 이름 — 실황 누적은 카드 구간으로 부른다('어제 0시부터 누적') */
const labelOf = k => (k === "acc" && !CASE) ? `${accSpan().label} 누적`
  : k === "aws" ? `AWS ${accSpan().label} 누적` : (metaOf(k).label || k);
function paintHead() {
  const L = metaOf(kind);
  const nm = labelOf(kind), el = $("lname");
  if (el.textContent !== nm) {             // 층이 바뀌면 제목이 스며 올라온다
    el.textContent = nm;
    el.classList.remove("swap"); void el.offsetWidth; el.classList.add("swap");
  }
  $("ltime").textContent = when(CUR);
  $("lsrc").textContent = test ? "합성 격자 — 실제 자료 아님"
    : (kind === "aws" || kind === "aws60") && CUR?.n
      ? `AWS ${CUR.n}곳 관측소 값만으로 메운 면(IDW, 가까운 8곳) · ${kind === "aws"
          ? (CUR.live ? "정시 강수량 합 + 정시 뒤 지금까지(매분)" : "정시 강수량 합")
          : (CUR.live ? "기상청 매분자료 직전 60분 — 경남 AWS 는 정시 자료라 정시 칸에만" : "정시 1시간 강수량")}`
    : kind === "acc" && CUR?.live ? `${L.src || ""} + 정시 뒤 ${hm(CUR.live)}까지(일강수 차)` : (L.src || "");
  const b = [];
  const past = isPast();
  if (window.GN_SNAP) b.push(`<span class="badge snap" title="${window.GN_SNAP.title} — ${window.GN_SNAP.note || ""}">${window.GN_SNAP.fake ? "가상 시연(실제 아님)" : "시연"} · ${md(window.GN_SNAP.now)} ${hm(window.GN_SNAP.now)} 저장</span>`);
  if (CASE) b.push(`<span class="badge past">재현 · ${CASEM?.title || CASE}</span>`);
  else if (test) b.push(`<span class="badge test">테스트</span>`);
  else if (pinned(kind)) b.push(`<span class="badge past">지난 시각 보기 (tm=${PIN_TM})</span>`);
  else if (past) b.push(`<span class="badge past">지난 시각</span>`);
  else {
    const col = META?.collect?.[COLLECT_OF[kind]];
    if (col && !col.ok) b.push(`<span class="badge warn" title="${(col.detail || "").replace(/"/g, "'")}">수집 실패 · 마지막 정상 ${col.ok_at ? col.ok_at.slice(11, 16) : "없음"}</span>`);
    if (L.stale) b.push(`<span class="badge warn">자료 지연${L.age_min != null ? ` · ${Math.round(L.age_min)}분 전` : ""}</span>`);
    if (CUR && +CUR.capped > 0) b.push(`<span class="badge" title="단기예보 PCP 는 30 에서 막힌다 — 30㎜ 이상">30㎜ 이상 든 칸 ${CUR.capped} · 합계는 하한</span>`);
  }
  if (kind === "obs15" && factor() === 4) b.push(`<span class="badge">×4 환산</span>`);
  if (awsLive() && (kind === "aws" || kind === "aws60"))
    b.push(`<span class="badge live" data-a="live" title="AWS 실시간 감시 — 1분마다(마지막 정시 뒤 매분자료까지). 누르거나 R 로 끈다"><i></i>실시간 감시</span>`);
  $("badges").innerHTML = b.join(" ") + (ORIGIN_BADGE ? " " + ORIGIN_BADGE : "");
  const lb = $("badges").querySelector('[data-a="live"]');
  if (lb) lb.onclick = () => setLive(false);
  $("stage").classList.toggle("late", !test && !past && !!L.stale);
  glLate();
  $("testrib").hidden = !test;
  $("stage").classList.toggle("test", test);
  $("b-tl").classList.toggle("on", tlOn);
}

/* ── 층 메뉴 — 지도 위 제목을 누르면 내려온다. 실측(15분 · 1시간 · 누적) / 예측(초단기 · 단기), 숫자 키 1~6 ── */
const LDESC = { obs15: "격자 500m · 15분 합", obs60: "격자 500m · 1시간 합", obsday: "격자 500m · 0시부터 오늘 합",
  odam: "동네예보 실황 5km · 1시간", vsrt: "초단기예보 5km · 앞으로 6시간", shrt_today: "단기예보 5km · 오늘 합",
  shrt_tomorrow: "단기예보 5km · 내일 합", acc: CASE ? "사례 처음부터 칸마다 더함" : "격자 500m · 강수 누적 카드와 같은 구간",
  aws: "AWS 관측소만으로 메운 면 · 카드와 같은 구간",
  aws60: "AWS 관측소만으로 메운 면 · 1시간" };
const tmLabel = L => !L.tm ? "아직 없음" : L.tm.length >= 12 ? hm(L.tm) : L.tm.length === 10 ? `${+L.tm.slice(8, 10)}시` : md(L.tm);
function buildMenu() {
  let i = 0;
  /* 줄 하나 — k: 이 줄을 누르면 고를 층(지금 보이는 층), key: 숫자 키, label · chips: 줄 안의 작은 단추들 */
  const item = (k, key, label, on, chips = "") => {
    const L = metaOf(k);
    const cls = ["it", on ? "on" : "", !L.tm ? "none" : "", L.stale ? "late" : ""].join(" ");
    const tip = (L.src || "") + (L.stale ? " · 자료 지연" : "")
      + (k.startsWith("shrt") && on ? " · 한 번 더 누르면 풀고 앞 층(강수 누적)으로" : "");
    return `<button class="${cls}" role="menuitemradio" aria-checked="${on}" data-k="${k}" style="--i:${i++}" title="${tip}">
      <span><b>${label || labelOf(k)}</b><small>${LDESC[k] || L.short || ""}</small>${chips}</span>
      <span class="t">${tmLabel(L)}</span><kbd>${key}</kbd></button>`;
  };
  const chip = (k, txt, on, title = "") => `<span class="chip${on ? " on" : ""}" role="button" data-k="${k}" title="${title}">${txt}</span>`;
  const grp = label => `<div class="g">${label}</div>`;
  let html;
  if (CASE) html = grp("재현") + KINDS.map((k, j) => item(k, j + 1, "", k === kind)).join("");
  else {
    const row = rowOf(kind), h1 = row === "h1" ? kind : srcKind("h1"), sk = row === "shrt" ? kind : "shrt_today";
    const src = `<span class="src" title="1시간 · 누적 층과 오른쪽 '강수 누적' 카드가 같은 자료를 본다 — B 키로도 바꾼다">`
      + `<b data-b="grid" class="${ACC_BASIS === "grid" ? "on" : ""}">격자 500m</b><b data-b="aws" class="${ACC_BASIS === "aws" ? "on" : ""}">AWS</b><kbd>B</kbd></span>`;
    const lv = `<span class="live${awsLive() ? " on" : ""}" role="switch" aria-checked="${awsLive()}"
      title="AWS 실시간 감시 — 끄면 AWS 누적 · 1시간이 정시마다, 켜면 1분마다(마지막 정시 뒤 매분자료까지). R 키로도"><i></i>실시간<kbd>R</kbd></span>`;
    html = grp(`실측${src}${test ? "" : lv}`)
      + item("obs15", 1, "15분 강수량", kind === "obs15")
      + item(h1 === "odam" ? "odam" : h1, 2, "1시간 강수량", row === "h1",
             `<span class="chips">${chip(kind === "odam" ? srcKind("h1") : "odam", "5km 실황", kind === "odam",
                                          "동네예보 실황 5km — 다시 누르면 위 자료(격자 · AWS)로")}</span>`)
      + item(srcKind("acc"), 3, `${accSpan().label} 누적`, row === "acc")
      + grp("예측")
      + item("vsrt", 4, "초단기 예측", kind === "vsrt")
      + item(sk, "5·6", "단기 예보", row === "shrt",
             `<span class="chips">${chip("shrt_today", "오늘 <kbd>5</kbd>", kind === "shrt_today")}${chip("shrt_tomorrow", "내일 <kbd>6</kbd>", kind === "shrt_tomorrow")}</span>`);
  }
  $("lmenu").innerHTML = html
    + `<div class="foot" style="--i:${i}"><button data-a="tl">패널 <kbd>L</kbd></button><button data-a="help">도움말 <kbd>?</kbd></button>`
    + `<button data-a="prefs">설정 <kbd>Ctrl ,</kbd></button></div>`;
  for (const b of $("lmenu").querySelectorAll(".it"))
    b.onclick = () => { stopPlay(); lmenu(false); pickLayer(b.dataset.k); };
  for (const c of $("lmenu").querySelectorAll(".chip"))
    c.onclick = ev => { ev.stopPropagation(); stopPlay(); lmenu(false); pickLayer(c.dataset.k); };
  // 자료 스위치 — 메뉴는 열어 둔 채(무엇이 바뀌었나 줄에서 바로 보이게)
  for (const b of $("lmenu").querySelectorAll(".src b"))
    b.onclick = ev => { ev.stopPropagation(); if (b.dataset.b !== ACC_BASIS) toggleBasis(); };
  for (const b of $("lmenu").querySelectorAll(".g .live"))
    b.onclick = ev => { ev.stopPropagation(); setLive(!awsLive()); };
  for (const b of $("lmenu").querySelectorAll(".foot button")) b.onclick = () => {
    lmenu(false);
    if (b.dataset.a === "tl") setTL(!tlOn); else if (b.dataset.a === "help") openHelp(); else openPrefs();
  };
}
let LM_KB = -1;
function lmenu(open = !$("lmenu").classList.contains("open")) {
  const m = $("lmenu");
  if (open) { buildMenu(); void m.offsetWidth; LM_KB = -1; }   // 줄을 새로 그린 뒤 열어야 하나씩 따라 들어온다
  m.classList.toggle("open", open);
  $("ttl").setAttribute("aria-expanded", String(open));
}
$("ttl").onclick = () => lmenu();
document.addEventListener("pointerdown", ev => {
  if ($("lmenu").classList.contains("open") && !ev.target.closest?.(".ttl-wrap")) lmenu(false);
});
/* 메뉴가 열렸으면 ↑↓ 로 고르고 Enter, Esc 로 닫는다 */
function lmenuKey(ev) {
  if (!$("lmenu").classList.contains("open")) return false;
  const its = [...$("lmenu").querySelectorAll(".it")];
  if (ev.key === "Escape") { lmenu(false); return true; }
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
    LM_KB = (Math.max(-1, LM_KB) + (ev.key === "ArrowDown" ? 1 : its.length - 1)) % its.length;
    its.forEach((b, j) => b.classList.toggle("kb", j === LM_KB));
    ev.preventDefault(); return true;
  }
  if (ev.key === "Enter" && LM_KB >= 0) { its[LM_KB].click(); ev.preventDefault(); return true; }
  return false;
}
/* 층 고르기 — 단기 오늘·내일은 켜고 끄는 단추다. 켠 것을 한 번 더 누르면 풀고 그 앞에 보던 층으로
   (오른쪽 위 카드도 '단기 내일' → '강수 누적'으로 돌아간다). 앞 층이 없으면 60분 */
let PREVK = null;
function pickLayer(k) {
  if (k === kind && k.startsWith("shrt")) { choose(PREVK && KINDS.includes(PREVK) ? normKind(PREVK) : srcKind("h1"), true); return; }
  if (k.startsWith("shrt") && !kind.startsWith("shrt")) PREVK = kind;
  choose(k, true);
}

function saveSetting(body) {
  if (CASE) return;                       // 재현을 보는 동안 고른 것은 실황 설정에 남기지 않는다
  if (SHOW.on) return;                    // 화면 재생 중 — 화면마다 바꾸는 층 · 구간은 이 화면 것일 뿐(다른 화면 설정을 흔들지 않게)
  fetch("/api/settings/map", { method: "PUT", headers: { "Content-Type": "application/json" },
                               body: JSON.stringify(body) }).catch(() => {});
}


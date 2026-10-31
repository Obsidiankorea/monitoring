"use strict";
/* ── 오른쪽 카드 — 종합 화면(강수 모니터링)의 세 판을 작게 ─────────────────────
   실제 자료는 종합 화면과 **같은 API·같은 규칙**이다 — 숫자가 두 화면에서 같아야 한다.
     강수 누적  /api/rain(스방 → 비면 기상청) 시군마다 다우지점(자료 있는 지점 중 합계 최대)
                + /api/forecast 6시간 합(연한 막대 — 아래 '예측 상위'와 같은 값). 합으로 줄 세운다
     지금 오는 비 /api/minute — 15분·60분 상위
     예측 상위  /api/forecast 시군 — 6시간 합 순
   테스트 모드는 합성 흐름(/api/grid/flow?test=1)에서 뽑는다 — 지도와 같은 값이 나오게. */
let CARDS = null;
/* 예상 합 — 초단기 RN1 을 **그대로** 더한다(아래 '예측 상위' 칸 · 합과 같은 값, 0.1㎜ 로 맞춤).
   ⚠️ 예전에는 시간마다 0·5·10·20·30·50 가운데 가까운 값으로 바꿔 더했다 — 3㎜ 가 5, 2㎜ 가 0 이 되어 거제(시간 3㎜)가
   위 카드에는 +25 인데 예측 상위(그대로 합 15)에는 없었다. 재난상황보고서 예측 표도 RN1 을 그대로(정수로) 쓴다 */
const fcSum = a => Math.round(sumv(a) * 10) / 10;
const fcTxt = v => (+v).toFixed(v % 1 ? 1 : 0);
const ORDER_GN = () => GEO.sigun.filter(s => s.kind === "gn").map(s => s.name);
const sumv = a => a.reduce((x, v) => x + (typeof v === "number" ? v : 0), 0);

/* 시각 글자('12', '13', …, '23:36') → 시각(ms). 끝에서부터 거슬러 올라가며 날을 넘긴다 */
function labelTimes(labels, lastHM) {
  const out = new Array(labels.length), now = NOWD();
  const [lh, lm] = (lastHM || `${now.getHours()}:00`).split(":").map(Number);
  const t = new Date(now); t.setHours(lh, lm || 0, 0, 0);
  if (t - now > 3600e3) t.setDate(t.getDate() - 1);
  out[labels.length - 1] = t.getTime();
  for (let i = labels.length - 2; i >= 0; i--) {
    const c = new Date(out[i + 1]);
    c.setHours(+labels[i].slice(0, 2), labels[i].length > 2 ? +labels[i].slice(3, 5) : 0, 0, 0);
    if (c.getTime() >= out[i + 1]) c.setDate(c.getDate() - 1);
    out[i] = c.getTime();
  }
  return out;
}
function nextHours(labels, after) {          // 예측 '00','01',… → after 뒤의 시각들
  const out = [];
  let prev = after;
  for (const l of labels) {
    const c = new Date(prev); c.setHours(+l.slice(0, 2), 0, 0, 0);
    if (c.getTime() <= prev) c.setDate(c.getDate() + 1);
    out.push(c.getTime()); prev = c.getTime();
  }
  return out;
}

/* 누적 구간 — 지난 6·12·24·48시간 / 오늘 0시부터 / 어제 0시부터(서버 설정 acc_from · acc_hours).
   AWS 는 '지금' 칸까지라 시간 수를 여기서 센다(0시부터 지금 시각까지 H 칸, 진행 중인 칸은 따로 붙는다).
   격자는 마지막 정시 격자에서 세야 맞아서 since 를 서버에 넘긴다.
   받은 매시 값은 DB(AWS obs_hourly) · 파일(격자 obs60)에 남는다 — 구간을 늘리면 없는 시각만 한 번 받는다 */
/* 날짜 지정 누적 — 그날 0시부터 'YYYYMMDD' · 그날 HH시부터 'YYYYMMDDHH'(10-24 '어제 18시부터'). 오늘부터 7일 앞까지(서버 ACC_DATE_DAYS) */
const ACC_DATE_DAYS = 7;
const dateOf = d => new Date(+d.slice(0, 4), +d.slice(4, 6) - 1, +d.slice(6, 8), d.length === 10 ? +d.slice(8, 10) : 0);
const ymd = t => `${t.getFullYear()}${String(t.getMonth() + 1).padStart(2, "0")}${String(t.getDate()).padStart(2, "0")}`;
/* 'YYYYMMDD(HH)' → '어제 18시부터' · '10.20. 0시부터'(사흘 앞부터는 날짜로) */
function dateLabel(d) {
  const t = NOWD(), back = Math.round((new Date(t.getFullYear(), t.getMonth(), t.getDate()) - dateOf(d.slice(0, 8))) / 864e5);
  const day = ["오늘", "어제", "그제"][back] || `${+d.slice(4, 6)}.${+d.slice(6, 8)}.`;
  return `${day} ${d.length === 10 ? +d.slice(8, 10) : 0}시부터`;
}
function accSpan() {
  const f = SET.acc_from || "hours", h = NOWD().getHours();
  if (f === "date" && /^\d{8}(\d{2})?$/.test(SET.acc_date || "")) {
    const d = SET.acc_date;
    return { H: Math.max(1, Math.min(24 * (ACC_DATE_DAYS + 1), Math.floor((NOWD() - dateOf(d)) / 3600e3))),
             since: d, label: dateLabel(d) };
  }
  if (f === "today") return { H: Math.max(1, h), since: "today", label: "오늘 0시부터" };
  if (f === "yesterday") return { H: 24 + h, since: "yesterday", label: "어제 0시부터" };
  return { H: SET.acc_hours, since: null, label: SET._accLabel || `지난 ${SET.acc_hours}시간` };
}
/* 날짜 · 시 고르기 — 날짜는 목록(오늘 · 어제 · 그제 … 7일 전, 칠 필요 없이), 시는 0~23시. 처음엔 어제 0시.
   ⚠️ 예전에는 <input type=date> 라 연도부터 쳐야 했다(10-24) */
const WD = "일월화수목금토";
function datePick(id) {
  const cur = SET.acc_from === "date" && /^\d{8}(\d{2})?$/.test(SET.acc_date || "") ? SET.acc_date : null, t = NOWD();
  const selD = cur ? cur.slice(0, 8) : ymd(new Date(t.getFullYear(), t.getMonth(), t.getDate() - 1));
  const selH = cur && cur.length === 10 ? +cur.slice(8, 10) : 0;
  const days = [...Array(ACC_DATE_DAYS + 1).keys()].map(i => {
    const d = new Date(t.getFullYear(), t.getMonth(), t.getDate() - i);
    return [ymd(d), `${["오늘", "어제", "그제"][i] || `${i}일 전`} ${d.getMonth() + 1}.${d.getDate()}.(${WD[d.getDay()]})`];
  });
  return `<select id="${id}-d" title="날짜">${days.map(([k, l]) => `<option value="${k}"${k === selD ? " selected" : ""}>${l}</option>`).join("")}</select>`
    + `<select id="${id}-h" title="몇 시부터">${[...Array(24).keys()].map(h => `<option value="${h}"${h === selH ? " selected" : ""}>${h}시</option>`).join("")}</select>`;
}
/* 고른 날짜 · 시 → 'YYYYMMDD'(0시) · 'YYYYMMDDHH'. 아직 안 온 시각이면 지금 시로 */
function datePicked(id) {
  const d = $(`${id}-d`).value, t = NOWD();
  let h = +$(`${id}-h`).value;
  if (d === ymd(t) && h > t.getHours()) h = t.getHours();
  return h ? `${d}${String(h).padStart(2, "0")}` : d;
}
const RNG_OPTS = [["hours", 6, "지난 6시간"], ["hours", 12, "지난 12시간"], ["hours", 24, "지난 24시간"],
                  ["hours", 48, "지난 48시간"], ["today", null, "오늘 0시부터"], ["yesterday", null, "어제 0시부터"]];
const rngOn = ([f, h]) => (SET.acc_from || "hours") === f && (f !== "hours" || +SET.acc_hours === h);
function setRange(f, h, date) {
  SET.acc_from = f;
  const body = { acc_from: f };
  if (h) { SET.acc_hours = h; body.acc_hours = h; }
  if (f === "date") { SET.acc_date = date; body.acc_date = date; }
  saveSetting(body);
  CARDS = null; loadCards();
  if (ACCK.has(kind) && !CASE) show(true);       // 지도 누적 · AWS 누적 층도 같은 구간으로
}
function rangePop(open = $("acc-rng").hidden) {
  const pop = $("acc-rng");
  if (!open) { pop.classList.remove("open"); pop.hidden = true; return; }
  const dOn = SET.acc_from === "date";
  pop.innerHTML = `<div class="g">누적 구간</div>` + RNG_OPTS.map((o, i) =>
    `<button data-i="${i}" class="${rngOn(o) ? "on" : ""}" style="--i:${i}">${o[2]}</button>`).join("")
    + `<div class="sep"></div><div class="dt${dOn ? " on" : ""}">날짜 지정 ${datePick("acc-date")}<button type="button" class="go" data-a="date">부터</button>
         <small>${dOn ? `지금 ${accSpan().label} · ` : ""}그날 그 시각부터 지금까지(${ACC_DATE_DAYS}일 앞까지)</small></div>`;
  const sb = $("acc-sub").getBoundingClientRect(), cb = $("c-acc").getBoundingClientRect();
  pop.style.left = (sb.left - cb.left) / V.k + "px"; pop.style.top = (sb.bottom - cb.top + 4) / V.k + "px";
  pop.hidden = false; void pop.offsetWidth; pop.classList.add("open");
  for (const b of pop.querySelectorAll("button")) b.onclick = ev => {
    ev.stopPropagation();
    if (b.dataset.a === "date") { const d = datePicked("acc-date"); rangePop(false); setRange("date", null, d); return; }
    const [f, h] = RNG_OPTS[+b.dataset.i];
    rangePop(false); setRange(f, h);
  };
  for (const sl of pop.querySelectorAll("select")) sl.onclick = sl.onpointerdown = ev => ev.stopPropagation();
}
/* 줄 세우기(위 카드 우클릭) — 시군당 n곳(1~3) · 0 = 시군 무관(전 지점 순위). 종합 화면 강수 타임라인 우클릭과 같은 말.
   시군을 골랐으면 그 시군 지점 · 읍면동 전부라 쓰지 않는다 */
const accPer = () => { const n = +SET.acc_per; return [0, 1, 2, 3].includes(n) ? n : 1; };
const perLabel = (unit = "곳") => accPer() ? `시군당 ${accPer()}${unit}` : "시군 무관 순위";
const ALLSIG = "all";                    // 서버가 경남 열여덟 시군 전부로 읽는다
/* 후보 줄 → 시군마다 큰 순 n곳(관제순으로 묶어) 또는 전부. 화면 정렬은 renderAcc 가 한다 */
function perSigun(list, val) {
  const per = accPer(), sorted = list.slice().sort((a, b) => val(b) - val(a));
  if (!per) return sorted;
  const by = {};
  for (const r of sorted) { const a = (by[r.sig] ||= []); if (a.length < per) a.push(r); }
  return ORDER_GN().flatMap(s => by[s] || []);
}
/* 위 카드가 지도를 따른다 — 누적이면 강수 누적, 단기면 그날 합, 15분 · 1시간 · 실황 · 초단기면 '그 시각' 값 */
// ACC_HOLD — 강수 누적 선 그래프에서 오른쪽 클릭으로 그 시각 1시간 지도로 갔을 때는 카드를 강수 누적에 붙들어 둔다
// (그 시각 카드는 재생 흐름 몇 시간만 있어 지난 시각이면 빈 카드가 됐다 — 선 그래프에 지도 시각 세로선이 그어진다).
// 층을 다시 고르면(메뉴 · 숫자 키 · 화면 재생) 풀린다
let ACC_HOLD = false;
const momentK = () => !CASE && !ACC_HOLD && (kind === "obs15" || kind === "odam" || FLOWK.has(kind));
const cardKey = () => isDay() ? kind : momentK() ? "moment" : "acc";
async function cardsFromApi() {
  const { H } = accSpan();
  // 시군당 2곳 이상 · 시군 무관이면 읍면동 예측도 다 받는다(줄마다 그 읍면동 예상을 붙이려고)
  // 바다 위젯 예측 상위를 시군당 2곳으로 보면 그것도(읍면동 예측이 다 있어야 시군마다 둘을 고른다)
  const fq = selOn() ? `&sigun=${encodeURIComponent(selQ())}`
    : (accPer() !== 1 && !momentK() && !isDay()) || (swOn() && +SET.sea_per === 2) ? `&sigun=${ALLSIG}` : "";
  const [fc, now] = await Promise.all([getJson(`/api/forecast?hours=6${fq}`), selOn() ? nowEmd() : nowMinute()]);
  const acc = isDay() ? await accDay() : momentK() ? await accMoment() : ACC_BASIS === "grid" ? await accGrid(H, fc) : await accAws(H, fc);
  // 시군을 골랐으면 '지금 오는 비'·'예측 상위'도 그 시군(들) 읍면동 — 누적 카드와 같은 단위로 맞춘다
  return {
    acc, now,
    fc: isDay() ? await fcDay() : {
          det: selOn(), labels: fc.labels || [], ft: acc.ft || [], bt: fc.tmfc ? `${hm(fc.tmfc)} 발표` : "—",
          rows: selOn() ? (fc.emd_sigun || []).map(e => ({ sig: e.sigun, label: e.emd, tag: multi() ? e.sigun : "", d: e.d.slice(0, 6), sum: e.sum }))
                        : (fc.sigun || []).map(s => ({ sig: s.sigun, emd: s.emd, d: s.d.slice(0, 6), sum: s.sum })),
          emdAll: !selOn() && fc.emd_sigun ? fc.emd_sigun : null },
  };
}
/* 지도가 단기 오늘·내일이면 '예측 상위'도 그날로 — 읍면동마다 그날 합과 6시간씩(06·12·18·24시 끝) 합.
   초단기(앞으로 6시간)는 그날 비를 담지 못한다(지도는 내일 40㎜ 인데 카드는 '예상 강수 없음'이었다).
   고른 시군이 없으면 경남 읍면동 상위, 있으면 그 시군(들) 읍면동. ⚠️ 5km 격자라 이웃 읍면동이 같은 값이 많다 */
const isDay = () => !CASE && kind.startsWith("shrt");
let DAYJ = null;                         // { url, at, p } — 위 카드와 '단기 상위'가 같은 응답을 쓴다
function dayJson() {
  const p = new URLSearchParams({ layer: kind });
  if (selOn()) p.set("sigun", selQ());
  if (test) p.set("test", "1");
  const url = `/api/grid/emdday?${p}`;
  if (!DAYJ || DAYJ.url !== url || Date.now() - DAYJ.at > 30e3) DAYJ = { url, at: Date.now(), p: getJson(url) };
  return DAYJ.p;
}
/* 위 카드 — 그날 예보 합. 시군을 안 골랐으면 시군마다 합이 가장 큰 읍면동(지도 라벨과 같은 값),
   골랐으면 그 시군(들) 읍면동 전부. 선 그래프는 그 읍면동의 매시 값(단기 PCP 1시간) */
async function accDay() {
  const dayW = kind === "shrt_today" ? "오늘" : "내일";
  const base = { day: true, title: `단기 ${dayW}`, basis: "grid", fell: false, src: test ? "테스트" : "단기 5km", rows: [] };
  let j;
  try { j = await dayJson(); }
  catch (e) { return { ...base, bt: "—", sub: e.message }; }
  // ⚠️ 화면(정적 파일)은 저장소에서 바로 읽히는데 서버는 다시 켜야 바뀐다 — 옛 서버면 매시 값(times·h)이 없다
  if (!Array.isArray(j.times) || !j.rows.every(r => Array.isArray(r.h)))
    return { ...base, bt: "—", sub: "서버를 다시 켜야 나온다",
             note: "대시보드 서버가 이 화면보다 옛 버전이다(단기 매시 값이 없다) — 대시보드(run.bat)를 닫았다 다시 켜면 된다" };
  const dt = j.times.map(tOf), dd = `${+j.day.slice(4, 6)}.${+j.day.slice(6, 8)}.`;
  const row = r => ({ sig: r.sig, stn: r.name, d: r.h, dt, fcd: [], ft: [], sum: r.sum ?? 0, fc: 0,
                      pos: r.col != null ? { x: r.col, y: r.row } : null });
  let rows;
  if (selOn()) rows = j.rows.map(r => ({ ...row(r), tag: multi() ? r.sig : "", det: true }));
  else if (accPer() !== 1) rows = perSigun(j.rows.map(r => ({ ...row(r), tag: r.sig })), r => r.sum ?? 0);
  else {
    const best = {};
    for (const r of j.rows) if (!best[r.sig] || (r.sum ?? 0) > (best[r.sig].sum ?? 0)) best[r.sig] = r;
    rows = ORDER_GN().filter(s => best[s]).map(s => ({ ...row(best[s]), tag: s }));
  }
  const span = `${dd} ${String(+j.times[0].slice(8, 10) - 1).padStart(2, "0")}~24시 합`;
  return { ...base, rows, sel: selOn() ? selName() : null, per: selOn() ? 1 : accPer(),
    bt: j.test ? "합성" : `${+j.tmfc.slice(8, 10)}시 발표`,
    sub: selOn() ? `${selName()} 읍면동 ${rows.length} · ${span}` : accPer() !== 1 ? `읍면동 ${perLabel()} · ${span}` : `시군 최대 읍면동 · ${span}`,
    note: kind === "shrt_today" ? "오늘은 발표 뒤 남은 시간만 더한다" : "" };
}
async function fcDay() {
  const day = kind === "shrt_today" ? "오늘" : "내일";
  let j;
  try { j = await dayJson(); }
  catch (e) { return { mode: "day", title: `단기 ${day} 상위`, sub: e.message, labels: [], ft: [], rows: [], bt: "—", det: selOn() }; }
  return { mode: "day", det: selOn(), title: `단기 ${day} 상위`,
    sub: `${selOn() ? selName() + " " : ""}읍면동 · 그날 합 · 6시간씩`,
    labels: j.labels.map((l, i) => (j.hours[i] ? l : `<s>${l}</s>`)), ft: [],
    bt: j.test ? "테스트" : `${+j.tmfc.slice(8, 10)}시 발표`,
    empty: `${day} 예상 강수 없음`,
    rows: j.rows.filter(r => r.sum != null).map(r => ({ sig: r.sig, label: r.name, tag: !selOn() || multi() ? r.sig : "",
      d: r.w, sum: r.sum, pos: r.col != null ? { x: r.col, y: r.row } : null })) };
}
/* 지금 오는 비 — 경남 전체는 기상청 매분자료(지점, 가장 빠르다) */
async function nowMinute() {
  // 스무 곳까지 — 오른쪽 카드는 줄 수만큼, 바다 위젯 '지금 오는 비'는 장소 + 시우량 칩으로 더 많이
  const mn = await getJson(`/api/minute?n=20`);
  const pick = l => (l || []).slice(0, 20).map(x => ({ sig: x.sigun, name: x.name, mm: x.mm }));
  return { r15: pick(mn.r15), r60: pick(mn.r60), tm: mn.tm, sub: null };
}
/* 시군을 고르면 500m 격자 읍면동 최대(15분·60분 최신 칸) — 매분자료 지점은 한 시군에 두세 곳뿐이라
   읍면동 줄을 다 채우지 못한다. 줄마다 그 칸 자리를 달아 둔다(올리면 지도에 고리) */
async function nowEmd() {
  const q = l => `/api/grid/emd?sigun=${encodeURIComponent(selQ())}&layer=${l}${test ? "&test=1" : ""}`;
  const [a, b] = await Promise.all([getJson(q("obs15")), getJson(q("obs60"))]);
  return { r15: emdTop(a.rows), r60: emdTop(b.rows), tm: hm(b.tm || a.tm), det: true,
           sub: `${selName()} 읍면동 · 격자 500m` };
}
const emdTop = (rows, n = 20) => rows.filter(r => r.max != null).sort((x, y) => y.max - x.max).slice(0, n)
  .map(r => ({ sig: r.sig, name: r.name, tag: multi() ? r.sig : "", mm: r.max, pos: r.col != null ? { x: r.col, y: r.row } : null }));
// 읍면동 이름은 시군마다 겹친다(중앙동 등) — 시군|읍면동 으로 찾는다
const fcMaps = fc => [Object.fromEntries((fc.sigun || []).map(s => [s.sigun, s])),
                      Object.fromEntries((fc.emd_sigun || []).map(e => [`${e.sigun}|${e.emd}`, e]))];
const sitePos = stn => { const s = SITEBY.get(stn); return s ? { x: s.x, y: s.y } : null; };

/* AWS 기준 — 스방 265(내부망) → 비면 기상청 56. 시군 줄은 다우지점, 시군을 고르면 그 시군 지점 전부.
   지점 줄의 예상(빗금)은 그 지점이 든 읍면동 예측 — 위치를 아는 지점(기상청 지점)만 붙인다. */
async function accAws(H, fc) {
  let rain, fell = false;
  if (test) rain = await getJson(`/api/grid/testrain?hours=${H}`);   // 합성 — 기상청 지점 + 스방 흉내 지점(위치 없음)
  else {
    // 실시간 감시를 끈 동안은 정시까지만(tail=0) — 지도 AWS 누적이 정시마다라 위 카드도 같은 시각에 선다
    const tq = awsLive() ? "" : "&tail=0";
    rain = await getJson(`/api/rain?hours=${H}&src=bangjae${tq}`);
    // 스방이 멈췄거나 계정이 없으면 빈 응답이다 — 기상청으로 물러서고, 물러섰다고 적는다(종합 화면과 같다)
    if (!(rain.rows || []).length) { rain = await getJson(`/api/rain?hours=${H}&src=kma${tq}`); fell = true; }
  }
  const lastHM = rain.labels.at(-1).includes(":") ? rain.labels.at(-1) : rain.base_hour;
  const dt = labelTimes(rain.labels, lastHM), ft = nextHours(fc.labels || [], dt.at(-1));
  const [FC, FE] = fcMaps(fc);
  const live = r => r.bad < r.d.length;              // 자료를 아예 안 주는 지점이 0으로 1등이 되지 않게
  const base = { H, ft, basis: "aws", fell, bt: `${lastHM} 실측`,
                 src: test ? "테스트" : fell ? "경남 AWS 안 됨 → 기상청 AWS 56곳" : rain.src === "bangjae" && !SET.gn_off ? `경남+기상청 AWS ${rain.count}곳` : "기상청 AWS 56곳",
                 // 경남AWS / 기상청AWS 토글 — 내부망이 아니라 경남 AWS 가 안 오면(fell) 기상청으로 고정
                 gnSel: test ? null : (fell || SET.gn_off ? "kma" : "gn"), gnLock: !test && fell && !SET.gn_off };
  const own = rain.src === "bangjae" || rain.src === "test";      // 경남 AWS(스방, 내부망)까지 든 자료
  /* 관리기관 — 서버가 준 org(경남 AWS 목록 · 기상청 지점번호), 없으면 기상청 지점번호면 기상청 */
  const orgOf = r => r.org || (SITEBY.has(r.stn) || !own ? "kma" : "gn");
  // 지점 한 줄 — 기상청 지점은 읍면동 · 위치 · 예상이 붙는다. 경남 AWS 는 위치를 몰라 **이름이 가리키는 읍면동 가운데에
  // 임시로** 둔다(서버 sites.position, est). sel = 시군을 고른 상세(그 시군 지점 전부)
  const stRow = (r, sel) => {
    const site = SITEBY.get(r.stn), emd = site?.emd || r.pos?.emd, e = emd ? FE[`${r.sigun}|${emd}`] : null;
    const fcd = e ? e.d.slice(0, 6) : [];
    const tag = !sel ? r.sigun : site ? (site.emd || "기상청") : own ? (r.pos?.emd || "경남") : "";
    return { sig: r.sigun, tag: sel && multi() ? `${r.sigun} ${tag}` : tag, stn: r.name, d: r.d, dt, fcd,
             ft: fcd.length ? ft : [], sum: r.sum, fc: fcSum(fcd), bad: r.bad, dead: !live(r), kma: !!site, h1: r.m60, org: orgOf(r),
             pos: sitePos(r.stn) || (r.pos ? { x: r.pos.x, y: r.pos.y, est: r.pos.est } : null), det: sel };
  };
  if (!selOn() && accPer() !== 1) {
    // 시군당 2·3곳 · 시군 무관 — 지점마다 한 줄(예상은 그 지점 읍면동 것). 자료를 안 주는 지점은 맨 뒤
    const rows = perSigun(rain.rows.map(r => stRow(r, false)), r => (r.dead ? -1 : r.sum));
    return { ...base, rows, per: accPer(), sub: `다우지점 ${perLabel()} · ${accSpan().label} + 예상 6시간` };
  }
  if (!selOn()) {
    const by = {};
    for (const r of rain.rows) (by[r.sigun] ||= []).push(r);
    const rows = ORDER_GN().filter(s => by[s]).map(s => {
      const st = by[s].slice().sort((a, b) => (live(b) - live(a)) || (b.sum - a.sum))[0];
      const fcd = (FC[s]?.d || []).slice(0, 6);
      return { sig: s, stn: st.name, d: st.d, dt, fcd, ft, sum: st.sum, fc: fcSum(fcd), bad: st.bad, h1: st.m60, org: orgOf(st),
               pos: sitePos(st.stn) || (st.pos ? { x: st.pos.x, y: st.pos.y, est: st.pos.est } : null) };
    });
    return { ...base, rows, sub: `다우지점 · ${accSpan().label} + 예상 6시간` };
  }
  // 그 시군(들) 지점 전부 — 내부망이면 스방 지점이 다 나온다(기상청 지점 포함). 기상청 지점은 읍면동·위치·예상이
  // 붙는다. 스방 자체 지점은 위치를 몰라 **이름이 가리키는 읍면동 가운데에 임시로** 둔다(서버 sites.position, est)
  const rows = rain.rows.filter(r => isSel(r.sigun)).map(r => stRow(r, true));
  const nk = rows.filter(r => r.org === "kma").length, est = rows.filter(r => r.pos?.est).length;
  const nopos = rows.length - rows.filter(r => r.pos).length;
  return { ...base, rows, sel: selName(),
    sub: `${selName()} AWS ${rows.length}곳${own ? ` (기상청 ${nk} · 경남 ${rows.length - nk})` : ""} · ${accSpan().label}`,
    note: [est ? `경남 AWS ${est}곳(${rows.filter(r => r.pos?.est).slice(0, 8).map(r => r.stn).join(" · ")}${est > 8 ? " …" : ""})은 목록에 없어 이름이 가리키는 읍면동 가운데에 임시로 둔다 — <a href="/api/aws/match" target="_blank">짝짓기 점검</a>` : "",
           nopos ? `${nopos}곳은 이름으로 읍면동을 못 찾아 지도에 짚지 않는다` : ""].filter(Boolean).join(" · ") };
}

/* 격자 기준 — 매시 정각 60분 격자를 칸마다 더한 누적. 시군 줄은 시군 누적 최대 칸(+읍면동),
   시군을 고르면 읍면동 줄(그 읍면동 누적 최대 칸). 선 그래프는 그 칸의 매시 값이다. */
async function accGrid(H, fc) {
  const p = new URLSearchParams({ hours: H });
  // 시군당 2곳 이상 · 시군 무관이면 경남 읍면동 전부(읍면동마다 누적 최대 칸)를 받아 고른다
  const emdRows = selOn() || accPer() !== 1;
  if (selOn()) p.set("sigun", selQ());
  else if (emdRows) p.set("sigun", ALLSIG);
  if (test) p.set("test", "1");
  if (accSpan().since) p.set("since", accSpan().since);
  const j = await getJson(`/api/grid/acctable?${p}`);
  const dt = j.frames.map(tOf), ft = nextHours(fc.labels || [], dt.at(-1));
  const [FC, FE] = fcMaps(fc);
  let rows = j.rows.map(r => {
    const fcd = ((emdRows ? FE[`${r.sig}|${r.name}`] : FC[r.sig])?.d || []).slice(0, 6);
    return { sig: r.sig, tag: selOn() ? (multi() ? r.sig : "") : r.sig, stn: emdRows ? r.name : (r.name || "—"), d: r.d, dt, fcd,
             ft: fcd.length ? ft : [], sum: r.sum ?? 0, fc: fcSum(fcd), det: selOn(),
             pos: r.col != null ? { x: r.col, y: r.row } : null, ...(r.h1 != null ? { h1: r.h1 } : {}) };
  });
  if (!selOn() && accPer() !== 1) rows = perSigun(rows, r => r.sum);
  return { rows, H, ft, basis: "grid", fell: false, sel: selOn() ? selName() : null, src: j.test ? "테스트" : "격자 500m",
    // 마지막 칸이 '지금' 칸(정시 뒤 ~ 최근 10분 칸, 일강수 차)이면 그 시각까지 — 빗금(최근 1시간)은 그 시각 60분 격자
    bt: j.tail ? `${hm(j.tm)}까지` : `${hm(j.tm)} 정각까지`, per: selOn() ? 1 : accPer(),
    sub: selOn() ? `${selName()} 읍면동 ${rows.length} · 누적 최대 칸 · ${accSpan().label}`
      : accPer() !== 1 ? `읍면동 누적 최대 칸 ${perLabel()} · ${accSpan().label} + 예상 6시간` : `시군 누적 최대 칸 · ${accSpan().label} + 예상 6시간`,
    note: j.missing ? `정시 격자 ${j.missing}시간 빠짐 — 합은 하한이다(수집기가 한 번에 4장씩 메운다)` : "" };
}

/* 위 카드 — 지도가 15분 · 1시간 · 실황 · 초단기면 **지도와 같은 층 · 같은 시각** 값(재생하면 같이 넘어간다).
   줄은 시군마다 가장 많은 곳(우클릭으로 시군당 n · 시군 무관). AWS 1시간은 관측소(그 정시 한 시간), 그 밖은 격자 읍면동
   최대 칸 — 시군당 1곳이면 지도 시군 라벨(CURSTAT)과 같은 값이다. 선 그래프는 재생 흐름의 그 시군 최대(지도와 같은 면)이고
   세로선이 지도 재생 위치다. 15분 · 실황은 흐름에 없어 막대만.
   ⚠️ 예전에는 지도가 1시간이어도 위 카드는 늘 '강수 누적'이었다 — 지도와 패널이 다른 것을 말했다 */
const EMDC = new Map();                  // /api/grid/emd 응답(층 · 시각 · 시군) — 재생 한 바퀴를 다시 받지 않게
async function emdAt(key, tm, sig) {
  const p = new URLSearchParams({ sigun: sig, layer: key });
  if (tm && !key.startsWith("vsrt")) p.set("tm", tm);      // 초단기는 지도와 같은 최신 발표분
  if (test) p.set("test", "1");
  const u = `/api/grid/emd?${p}`;
  if (!EMDC.has(u)) { if (EMDC.size > 120) EMDC.delete(EMDC.keys().next().value); EMDC.set(u, getJson(u).catch(e => { EMDC.delete(u); throw e; })); }
  return EMDC.get(u);
}
async function accMoment() {
  // 층을 막 바꿨으면 CUR 는 아직 앞 층 것이다(자료 B · 층 단추 → 카드가 먼저 불린다). 그 시각으로 묻지 않는다 —
  // 새 프레임이 오면 show() 가 refreshMoment 로 다시 채운다. ⚠️ 1시간 격자 01:20 으로 AWS 1시간을 물어 404 였다
  const key = layerKey(), fresh = CUR?.key === key, tm = fresh ? CUR.tm || null : null, aws = kind === "aws60", fac = factor();
  const title = { obs15: "15분 강수량", obs60: "1시간 강수량", aws60: "AWS 1시간 강수량", odam: "실황 1시간(5km)",
                  vsrt: `초단기 +${vsrtN}시간` }[kind] || labelOf(kind);
  const bt = !tm ? "—" : kind === "vsrt" ? `${hm(CUR.tmfc)} 발표 → ${+tm.slice(8, 10)}시` : `${hm(tm)} ${isPast() ? "지난 시각" : "실측"}`;
  let cand = [];
  if (aws) {
    const st = tm ? await stnFetch("aws60", tm) : { rows: [] };
    if (st.err) throw new Error(st.err);
    cand = (st.rows || []).filter(r => (r.q === "ok" || r.q === "part") && r.v != null)
      .map(r => ({ sig: r.sigun, stn: r.name, v: r.v, org: r.org || "kma", pos: { x: r.x, y: r.y } }));
  } else if (!selOn() && accPer() === 1 && fresh && CURSTAT) {
    cand = CURSTAT.rows.filter(r => r.kind === "gn" && r.max != null)
      .map(r => ({ sig: r.sigun, stn: r.where?.emd || "—", v: r.max, pos: r.where ? { x: r.where.col, y: r.where.row } : null }));
  } else if (tm) {
    const j = await emdAt(key, tm, selOn() ? selQ() : ALLSIG);
    cand = (j.rows || []).filter(r => r.max != null)
      .map(r => ({ sig: r.sig, stn: r.name, v: r.max, pos: r.col != null ? { x: r.col, y: r.row } : null }));
  }
  if (selOn()) cand = cand.filter(c => isSel(c.sig));
  // 선 그래프 — 재생 흐름(지도와 같은 자료)의 그 시군 최대. 15분 · 실황은 흐름 밖이라 한 점(막대만)
  const spark = FLOWK.has(kind) && !!FLOW?.series?.length;
  const obsI = [], fcI = [];
  if (spark) FLOW.frames.forEach((f, i) => (f.kind === "obs" ? obsI : fcI).push(i));
  const ser = Object.fromEntries((FLOW?.series || []).map(x => [x.sigun, x]));
  const t1 = tm ? tOf(tm) : NOWD().getTime();
  const mk = c => {
    const s = spark ? ser[c.sig] : null;
    return { sig: c.sig, tag: selOn() ? (multi() ? c.sig : "") : c.sig, stn: c.stn,
             d: s ? obsI.map(i => s.max[i]) : [c.v], dt: s ? obsI.map(i => FLOW.tt[i]) : [t1],
             fcd: s ? fcI.map(i => s.max[i] ?? 0) : [], ft: s ? fcI.map(i => FLOW.tt[i]) : [],
             sum: Math.round(c.v * fac * 10) / 10, fc: 0, org: c.org, pos: c.pos, det: selOn() };
  };
  const rows = selOn() ? cand.map(mk) : perSigun(cand.map(mk), r => r.sum);
  const what = aws ? "지점" : "읍면동";
  return { moment: true, stale: !fresh, title, rows, basis: aws ? "aws" : "grid", fell: false, ft: [], H: 1, spark, bt,
    per: selOn() ? 1 : accPer(), sel: selOn() ? selName() : null,
    src: test ? "테스트" : aws ? `AWS ${cand.length}곳` : (kind === "odam" || kind === "vsrt") ? "5km" : "격자 500m",
    sub: `${selOn() ? `${selName()} ${what} 전부` : accPer() === 1 ? `시군 최대 ${what}` : `${what} ${perLabel()}`} · 지도와 같은 시각${fac === 4 ? " · ×4 환산" : ""}` };
}
let MOM_SEQ = 0;
/* 지도 프레임이 바뀌면(재생 · 끌기 · 새 자료) 위 카드도 그 시각으로 — 나머지 카드는 그대로 */
async function refreshMoment() {
  if (!momentK() || !tlOn || SET.panel === "timeline" || !CARDS || CARDS.err) return;
  const my = ++MOM_SEQ;
  let a;
  try { a = await accMoment(); }
  catch (e) { a = { moment: true, title: labelOf(kind), rows: [], bt: "—", basis: ACC_BASIS, note: e.message }; }
  if (my !== MOM_SEQ || !momentK() || !CARDS || CARDS.err) return;
  CARDS.acc = a;
  renderAcc(); drawRanks(); cardsPlayhead();
}

async function cardsFromTest() {
  if (!FLOW) return null;
  const obsI = [], fcI = [];
  FLOW.frames.forEach((f, i) => {
    if (f.kind === "obs" && f.t.endsWith("00")) obsI.push(i);
    if (f.kind === "fcst") fcI.push(i);
  });
  const lastObs = FLOW.frames.reduce((a, f, i) => (f.kind === "obs" ? i : a), -1);
  const dt = obsI.map(i => FLOW.tt[i]), ft = fcI.map(i => FLOW.tt[i]);
  const rows = FLOW.series.map(s => {
    const d = obsI.map(i => s.max[i]), fcd = fcI.map(i => s.max[i] ?? 0);
    return { sig: s.sigun, stn: "격자", d, dt, fcd, ft, sum: Math.round(sumv(d) * 10) / 10, fc: fcSum(fcd) };
  });
  let s15 = null;
  try { s15 = await getJson("/api/grid/sigun?layer=obs15&test=1"); } catch {}
  const top = (arr) => arr.sort((a, b) => b.mm - a.mm).slice(0, 6);
  const r60 = top(FLOW.series.map(s => ({ sig: s.sigun, name: "격자", mm: lastObs >= 0 ? (s.max[lastObs] ?? 0) : 0 })));
  const r15 = s15 ? top(s15.rows.filter(r => r.kind === "gn").map(r => ({ sig: r.sigun, name: r.where?.emd || "격자", mm: r.max ?? 0 }))) : [];
  // 예측(합성 초단기)을 실황 /api/forecast 와 같은 모양으로 — 누적 카드에도 연한 예상 막대가 붙는다
  const fcT = { labels: fcI.map(i => FLOW.frames[i].t.slice(8, 10)),
                sigun: FLOW.series.map(s => ({ sigun: s.sigun, emd: "", d: fcI.map(i => s.max[i] ?? 0) })) };
  let nowE = null;
  // 시군당 2·3곳 · 시군 무관 누적이면 경남 읍면동 예상도 다 읽는다(실황 cardsFromApi 와 같다 — 줄마다 그 읍면동 예상)
  const emdSig = selOn() ? selQ() : accPer() !== 1 && !momentK() && !isDay() ? ALLSIG : null;
  if (emdSig) {
    // 고른 시군 읍면동 — 합성 격자(15분·60분 최신, 초단기 +1~+6)를 읍면동마다 최대로 읽는다
    const q = l => getJson(`/api/grid/emd?sigun=${encodeURIComponent(emdSig)}&layer=${l}&test=1`);
    const [nw, ...fcs] = await Promise.all([selOn() ? nowEmd() : null, ...fcI.map(i => q(`vsrt+${FLOW.frames[i].n}`))]);
    nowE = nw;
    fcT.emd_sigun = (fcs[0]?.rows || []).map((r, j) => ({ sigun: r.sig, emd: r.name, d: fcs.map(f => f.rows[j]?.max ?? 0) }));
  }
  // 누적은 실제와 같은 길로 — AWS 면 합성 지점(기상청 자리 + 스방 흉내, /api/grid/testrain), 격자면 합성 격자 누적.
  // 테스트에서 시군을 누르면 내부망(스방)에서 보일 목록 모양을 미리 본다
  let acc = { rows, H: dt.length, src: "테스트", fell: false, basis: ACC_BASIS, bt: lastObs >= 0 ? `${hm(FLOW.frames[lastObs].t)} 실측` : "—" };
  try {
    acc = isDay() ? await accDay() : momentK() ? await accMoment()
      : ACC_BASIS === "grid" ? await accGrid(accSpan().H, fcT) : await accAws(accSpan().H, fcT);
  } catch (e) { acc.note = e.message; }
  const day = isDay() ? await fcDay() : null;
  if (selOn()) {
    const rowsE = fcT.emd_sigun.map(e => ({ sig: e.sigun, label: e.emd, tag: multi() ? e.sigun : "", d: e.d, sum: sumv(e.d) }));
    return { acc, now: nowE, fc: day || { det: true, rows: rowsE, labels: ft.map(fmtH), ft, bt: FLOW.tmfc ? `${hm(FLOW.tmfc)} 발표` : "—" } };
  }
  return {
    acc,
    now: { r15, r60, tm: lastObs >= 0 ? hm(FLOW.frames[lastObs].t) : "—" },
    fc: day || { rows: FLOW.series.map(s => { const d = fcI.map(i => s.max[i] ?? 0); return { sig: s.sigun, emd: "", d, sum: sumv(d) }; }),
          labels: ft.map(fmtH), ft, bt: FLOW.tmfc ? `${hm(FLOW.tmfc)} 발표` : "—" },
  };
}

let CARD_SEQ = 0;
async function loadCards() {
  if (!tlOn || SET.panel === "timeline") return;
  const my = ++CARD_SEQ;
  let c;
  try { c = CASE ? (CASEM ? await cardsFromCase() : null) : test ? await cardsFromTest() : await cardsFromApi(); }
  catch (e) { c = { err: e.message }; }
  if (my !== CARD_SEQ) return;
  CARDS = c;
  renderCards();
  if (c?.acc?.stale) refreshMoment();       // 앞 층 프레임으로 짠 '그 시각' 카드 — show() 보다 늦게 왔으면 여기서 채운다
}

function rowEvents(el) {
  for (const r of el.querySelectorAll("[data-s]")) {
    const pt = r.dataset.x ? { x: +r.dataset.x, y: +r.dataset.y } : null;
    r.onmouseenter = () => { highlight(r.dataset.s); link(r, r.dataset.s, pt); hot(pt); };
    r.onmouseleave = () => { highlight(null); link(null); hot(null); };
    // 시군 줄을 누르면 그 시군을 고른다(오른쪽 패널이 그 시군 읍면동·지점으로 바뀐다). Ctrl 이면 더한다
    r.onclick = r.classList.contains("det") ? null : ev => pickSig(r.dataset.s, ev.ctrlKey || ev.metaKey);
  }
}

function renderCards() {
  if (!CARDS || !V) return;
  if (CARDS.err) {
    $("acc-b").innerHTML = `<div class="empty-note">불러오지 못했다 — ${CARDS.err}</div>`;
    renderSw();
    return;
  }
  $("fc-h").textContent = CASE ? "호우 기준" : CARDS.fc?.title || "예측 상위";
  $("fc-sub").textContent = CASE ? (selOn() ? `산출 — ${selName()}` : "산출 — 격자 3시간·12시간 합")
    : CARDS.fc?.sub || (CARDS.fc?.det ? `${selName()} 읍면동 · 초단기 6시간` : "초단기 · 앞으로 6시간");
  $("now-sub").textContent = CARDS.now.sub || "기상청 매분자료";
  // 누적 카드는 남는 높이를 다 쓴다 — 다른 둘을 먼저 채운 뒤에 재야 줄 수가 맞는다
  renderNow(); CASE ? renderCrit() : renderFc(); renderAcc();
  drawRanks();
  renderSw();
  cardsPlayhead();
}

/* 강수 누적 — 종합 화면 '강수 타임라인'을 한 줄짜리로 */
function renderAcc() {
  const A = CARDS.acc, k = V.k, body = $("acc-b");
  for (const b of $("acc-h").querySelectorAll(".bs b")) b.classList.toggle("on", b.dataset.b === (A.basis || ACC_BASIS));
  $("acc-sel").hidden = !A.sel;
  $("acc-sel").textContent = A.sel ? `${A.sel} ✕` : "";
  const fcOn = fcShown() && !A.day && !A.moment;
  $("acc-t").textContent = A.title || "강수 누적";
  $("acc-h").classList.toggle("day", !!A.day);
  $("acc-h").title = A.day ? "지도 단기 층의 그날 예보 합 — 실측 층을 고르면 강수 누적으로 돌아간다"
    : A.moment ? "지도와 같은 층 · 같은 시각 — 눌러서 자료 바꾸기(AWS 관측소 ↔ 격자, 지도도 같이). 누적 층을 고르면 강수 누적으로"
    : "눌러서 기준 바꾸기 — AWS 관측소 ↔ 격자(500m)";
  $("acc-fc").hidden = !!CASE || !!A.day || !!A.moment;   // 사례에는 예상이 없다 · 단기는 전부 예보다 · '그 시각'은 한 장이다
  const h1On = h1Shown() && !A.day && !A.moment;
  $("acc-h1").hidden = !!A.day || !!A.moment;
  $("acc-h1").classList.toggle("on", h1On); $("acc-h1").setAttribute("aria-pressed", h1On);
  $("acc-fc").classList.toggle("on", fcOn); $("acc-fc").setAttribute("aria-pressed", fcOn);
  const sub = A.sub || `다우지점 · ${accSpan().label} + 예상 6시간`;
  // 설명을 누르면 누적 구간을 고른다(실황·테스트의 강수 누적만 — 단기·사례는 구간이 정해져 있다)
  $("acc-sub").classList.toggle("pick", !CASE && !A.day && !A.moment);
  $("acc-sub").textContent = fcOn ? sub : sub.replace(" + 예상 6시간", "");
  if (A.basis === "aws" && A.gnSel) {
    // 지금 쓰는 쪽 하나만 보인다 — 글자를 누르면 다른 쪽으로(⇄). 내부망이 아니면 기상청AWS 로 고정(누를 수 없다)
    $("acc-src").innerHTML = `<span class="gsw${A.gnLock ? " lock" : ""}"><b data-v="${A.gnSel === "gn" ? "kma" : "gn"}">${A.gnSel === "gn" ? "경남AWS" : "기상청AWS"}${A.gnLock ? "" : " ⇄"}</b></span>`;
    $("acc-src").title = A.src + (A.gnLock ? " — 이 서버는 내부망(스방)에 닿지 않아 기상청 AWS 로 고정" : ` — 눌러서 ${A.gnSel === "gn" ? "기상청AWS" : "경남AWS"}로`);
    $("acc-src").classList.remove("fell");
  } else { $("acc-src").textContent = A.src; $("acc-src").title = ""; $("acc-src").classList.toggle("fell", !!A.fell); }
  $("acc-bt").textContent = A.bt;
  const val = r => r.sum + r.fc;
  // 예상을 끄면 예상 몫을 뺀다 — 단, '그 시각' 카드의 선 그래프 예측(초단기) 구간은 흐름 그대로 둔다
  const rows = A.rows.map(r => (fcOn || A.moment ? r : { ...r, fc: 0, fcd: [], ft: [] }));
  if (A.per > 1 && !A.sel) {
    // 시군당 n곳 — 시군끼리 묶는다(가장 많은 곳이 큰 시군부터, 시군 안은 큰 순)
    const best = {};
    for (const r of rows) best[r.sig] = Math.max(best[r.sig] ?? -Infinity, val(r));
    rows.sort((a, b) => a.sig === b.sig ? val(b) - val(a)
      : (best[b.sig] - best[a.sig]) || ORDER_GN().indexOf(a.sig) - ORDER_GN().indexOf(b.sig));
  } else rows.sort((a, b) => val(b) - val(a));
  if (!rows.length || !rows[0].dt.length) {
    body.innerHTML = (A.day && A.note ? "" : `<div class="empty-note">${A.sel ? `${A.sel} — ${A.basis === "grid" ? "읍면동" : "지점"} 자료가 없다` : "강수 자료가 아직 없다"}</div>`)
      + (A.note ? `<div class="case-note">${A.note}</div>` : "");
    A.sp = null; return;
  }
  const bh = body.clientHeight - 10 * k - (A.note ? 40 * k : 0) - 22 * k;     // 22 = 맨 아래 막대 범례
  const rh = Math.max(26 * k, Math.min(44 * k, bh / Math.max(1, rows.length)));   // 카드를 꽉 채운다
  // 시군을 골랐으면 줄을 다 그리고 카드 안에서 굴린다 — 내부망(스방)이면 한 시군에 수십 곳이다
  const n = A.sel ? rows.length : Math.max(1, Math.min(rows.length, Math.floor(bh / rh)));
  body.classList.toggle("scroll", !!A.sel);
  body.style.setProperty("--rh", rh + "px");
  const bmax = Math.max(1, ...rows.map(r => r.sum + r.fc));
  let smax = 5;
  for (const r of rows) for (const v of [...r.d, ...r.fcd]) if (typeof v === "number" && v > smax) smax = v;
  // 축 끝은 줄들 가운데 예상이 가장 멀리 간 데까지(예상이 없는 줄이 맨 위여도 다른 줄이 밖으로 새지 않게)
  const t0 = Math.min(...rows[0].dt) - 1800e3, t1 = Math.max(rows[0].dt.at(-1), ...rows.flatMap(r => r.ft));
  const SW = 150 * k, SH = rh * 0.82;
  const sx = t => (t - t0) / Math.max(1, t1 - t0) * SW, sy = v => SH - Math.min(v, smax) / smax * (SH - 3);
  // tn = 실측이 끝나는 '지금'. 단기는 전부 예보라 처음부터(마우스를 올리면 그 6시간 칸을 짚는다)
  A.sp = { t0, t1, SW, sy, tn: A.day ? -Infinity : rows[0].dt.at(-1) };
  A.vis = new Map(rows.slice(0, n).map(r => [`${r.sig}|${r.stn}`, r]));    // 선 그래프에 마우스 — 줄 → 값
  const sline = (ts, vs, from) => {
    let pts = ts.map((t, i) => [t, vs[i]]).filter(([, v]) => typeof v === "number");
    if (from) pts = [from, ...pts];
    if (!pts.length) return { d: "", a: "" };
    const p = pts.map(([t, v]) => `${sx(t).toFixed(1)},${sy(v).toFixed(1)}`);
    return { d: "M" + p.join("L"), a: `M${sx(pts[0][0]).toFixed(1)},${SH}L${p.join("L")}L${sx(pts.at(-1)[0]).toFixed(1)},${SH}Z` };
  };
  const tnow = NOWD().getTime(), xn = A.day ? (tnow > t0 && tnow < t1 ? sx(tnow) : -99) : sx(rows[0].dt.at(-1));
  // 다시 그리기 전 줄 자리 — 예상을 켜고 끄거나(합이 바뀐다) 시각이 바뀌어 순서가 달라지면 새 자리로 미끄러지게
  const before = new Map([...body.querySelectorAll(".ar[data-k]")].map(e => [e.dataset.k, e.getBoundingClientRect().top]));
  const lastNum = d => { for (let j = d.length - 1; j >= 0; j--) if (typeof d[j] === "number") return d[j]; return 0; };
  // 봉우리(최대 시우량) — 줄마다 실측 중 가장 많이 온 시각에 점과 값. **줄마다 다**(0 · 결측은 빼고).
  // ⚠️ 예전에는 봉우리가 큰 5줄만 적었다 — 다른 줄도 보고 싶다는 말에 다 적는다(10-27). 줄마다 제 칸이라 서로 겹치지 않는다
  const peakOf = r => r.d.reduce((a, v, j) => (typeof v === "number" && (!a || v > a[1]) ? [r.dt[j], v] : a), null);
  const peakTag = r => {
    const pk = r.dead ? null : peakOf(r);
    if (!pk || pk[1] < 0.1) return "";
    const [t, v] = pk, x = sx(t), y = sy(v), fs = 10.5 * k, right = x > SW * 0.6;
    const ty = Math.max(fs * 0.8, y + fs * 0.35);
    return `<circle class="sp-pd" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(2.4 * k).toFixed(1)}"/>`
      + `<text class="sp-pk" x="${(right ? x - 4 * k : x + 4 * k).toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="${right ? "end" : "start"}">${v.toFixed(v >= 10 ? 0 : 1)}</text>`;
  };
  // 평균 시우량 — 실측 구간(0 인 시각도 넣어) 칸 값의 평균을 가로 점선으로, 값은 봉우리 반대쪽 끝에(10-27).
  // 글자는 숫자만(흐린 회색 · 가는 글씨) — 봉우리는 흰 굵은 글씨 + 점이라 갈린다. 무엇인지는 맨 아래 범례 '--- 평균 시우량'.
  // ⚠️ '평균 8.5' · 윗첨자 avg · x̄ 를 견줘 보고 숫자만으로(10-27)
  // 누적 ÷ 시간과 같은 말 — '꾸준히 왔나 · 한 번에 쏟았나'를 봉우리와 견준다. 단기(예보 합)에는 긋지 않는다
  let anyAvg = false;
  const avgTag = r => {
    if (A.day || r.dead) return "";
    const pts = r.d.map((v, j) => [r.dt[j], v]).filter(([, v]) => typeof v === "number");
    if (pts.length < 2) return "";
    const m = pts.reduce((a, [, v]) => a + v, 0) / pts.length;
    if (m < 0.1) return "";
    anyAvg = true;
    const x0 = sx(pts[0][0]), x1 = sx(pts.at(-1)[0]), y = sy(m), fs = 10 * k, pk = peakOf(r);
    const left = !pk || sx(pk[0]) > (x0 + x1) / 2;          // 봉우리가 오른쪽이면 글자는 왼쪽 끝
    const ty = y - 3 * k < fs ? y + fs + 1 * k : y - 3 * k;
    return `<line class="sp-avg" x1="${x0.toFixed(1)}" x2="${x1.toFixed(1)}" y1="${y.toFixed(1)}" y2="${y.toFixed(1)}"/>`
      + `<text class="sp-av" x="${(left ? x0 + 2 * k : x1 - 2 * k).toFixed(1)}" y="${ty.toFixed(1)}" text-anchor="${left ? "start" : "end"}">${m.toFixed(m >= 10 ? 0 : 1)}</text>`;
  };
  // 최근 1시간 칩 — 시우량 자(SIU)로 칠한다. 막대 빗금과 같은 단추(H)로 켜고 끈다
  body.classList.toggle("h1c", h1On);
  // 막대 색 — 색조(SET.acc_tone)면 값마다 메인 지도 범례의 그 범주 색. 지도가 누적이면 그 자(자동 눈금 · 고정 눈금 · 다양한 색조 그대로),
  // '그 시각' · 단기 카드면 그 층의 자. 막대를 누르면 한 색 ↔ 색조
  const tone = !!SET.acc_tone, tk = A.day || A.moment || ACCK.has(kind) ? kind : ACC_BASIS === "grid" ? "acc" : "aws";
  const tSteps = stepsOf(tk), tHr = HOURLY.has(tk);
  const tcol = v => { const x = v * (tk === kind ? factor() : 1); return (x >= tSteps[0] && rampColor(x, tSteps, tHr)) || ""; };
  body.classList.toggle("tone", tone);
  const h1Chip = (r, v) => {
    if (r.dead) return `<span class="h1v z" title="결측">—</span>`;
    const c = v >= 0.1 ? rampColor(v, SIU, true) : null;
    if (!c) return `<span class="h1v z" title="최근 1시간 0㎜"><small>1h</small>0</span>`;
    const lv = v >= 20 ? 3 : v >= 10 ? 2 : v >= 5 ? 1 : 0;
    return `<span class="h1v l${lv}" style="--c:${c}" title="최근 1시간 ${v.toFixed(1)}㎜ — 왼쪽 막대는 시우량 색(지도 1시간 · 지금 오는 비와 같은 자), 많을수록 글자가 밝고 굵다"><small>1h</small>${v.toFixed(v >= 10 ? 0 : 1)}</span>`;
  };
  body.innerHTML = rows.slice(0, n).map((r, i) => {
    const tot = r.sum + r.fc, o = r.sum / bmax * 100, f = r.fc / bmax * 100;
    // 실측 중 최근 1시간 — 실측 막대 안의 끝 몫(합을 넘지 않게)
    const h1raw = Math.max(0, typeof r.h1 === "number" ? r.h1 : lastNum(r.d));
    const h1 = !h1On ? 0 : Math.min(r.sum, h1raw), hw = h1 / bmax * 100;
    const inside = o + f > 62;
    const vpos = inside ? `right:calc(${(100 - o - f).toFixed(1)}% + 6px)` : `left:calc(${(o + f).toFixed(1)}% + 6px)`;
    const lastObs = r.d.reduce((a, v, j) => (typeof v === "number" ? [r.dt[j], v] : a), null);
    const po = sline(r.dt, r.d), pf = sline(r.ft, r.fcd, lastObs);
    const rank = i < 3 && tot >= 0.1 ? `<span class="rk">${i + 1}</span>` : "";
    const ge = r.part ? ` title="일부 시각이 빠진 합 — 실제는 이보다 클 수 있다"` : "";
    const at = r.pos ? ` data-x="${r.pos.x}" data-y="${r.pos.y}"` : "";
    const g0 = A.per > 1 && !A.sel && i > 0 && rows[i - 1].sig !== r.sig;
    return `<div class="ar${r.det ? " det" : ""}${g0 ? " g0" : ""}${A.basis === "aws" && r.org === "kma" ? " kma" : ""}" data-s="${r.sig}" data-k="${r.sig}|${r.stn}"${at} title="${r.det ? "" : `${r.sig} — 눌러서 이 시군 ${A.basis === "grid" ? "읍면동" : "지점"} 보기`}">
      <div class="nm2">${rank}<small>${r.tag ?? r.sig}</small>${r.stn}</div>
      <div class="abar" title="막대를 누르면 색 — ${tone ? "한 색으로" : "지도 범례 색조로(값마다 그 범주 색)"}"${tone && tcol(r.sum) ? ` style="--tc:${tcol(r.sum)}"` : ""}><div class="o${A.day ? " dayb" : hw >= o - 0.05 && !r.fc ? " all" : ""}" style="width:${o.toFixed(1)}%"></div>
        ${h1 >= 0.1 ? `<div class="h${r.fc ? "" : " end"}${hw >= o - 0.05 ? " all" : ""}" style="left:${(o - hw).toFixed(1)}%;width:${hw.toFixed(1)}%" title="그중 최근 1시간 ${h1.toFixed(1)}㎜"></div>` : ""}
        ${r.fc ? `<div class="f" style="left:${o.toFixed(1)}%;width:${f.toFixed(1)}%"></div>` : ""}
        <span class="v${r.dead ? " dead" : ""}" style="${vpos}"${ge}>${r.dead ? "결측" : r.sum.toFixed(1)}${r.fc ? `<i>+${fcTxt(r.fc)}</i>` : ""}</span></div>
      <svg viewBox="0 0 ${SW.toFixed(0)} ${SH.toFixed(0)}" preserveAspectRatio="none">
        <path class="sp-a" d="${po.a}"/><path class="sp-l" d="${po.d}"/>
        <path class="sp-fa" d="${pf.a}"/><path class="sp-fl" d="${pf.d}"/>
        <line class="sp-now" x1="${xn}" x2="${xn}" y1="0" y2="${SH}"/>
        <line class="sp-head" x1="0" x2="0" y1="-2" y2="${SH + 2}" style="transform:translateX(-99px);visibility:hidden"/>
        <line class="sp-hov" x1="0" x2="0" y1="-2" y2="${SH + 2}" style="transform:translateX(-99px)"/>${avgTag(r)}${peakTag(r)}<circle class="sp-hd" cx="-99" cy="-99" r="${(3 * k).toFixed(1)}"/></svg>${h1On ? h1Chip(r, h1raw) : ""}</div>`;
  }).join("") + (n < rows.length ? `<div class="case-note">외 ${rows.length - n}${A.basis === "grid" && A.sel ? "개 읍면동" : "곳"} — 적은 순이라 생략</div>` : "")
    + (A.note ? `<div class="case-note">${A.note}</div>` : "")
    + (A.moment ? `<div class="acc-lg">${A.basis === "aws"
          ? (rows.some(r => r.org !== "kma") ? `<span><i class="p"></i>경남 AWS</span>` : "") + (rows.some(r => r.org === "kma") ? `<span><i class="pk"></i>기상청 AWS</span>` : "")
          : `<span><i class="p"></i>격자 최대 칸</span>`}${A.spark ? `<span>선 그래프: 그 시군 최대 · 세로선 = 지도 재생 위치</span>` : ""}${anyAvg ? `<span><i class="av"></i>평균</span>` : ""}</div>`
      : A.day ? `<div class="acc-lg"><span><i class="d"></i>그날 예보 합(단기 PCP 매시 합 · 읍면동 최대)</span><span>선 그래프: 매시 값</span></div>`
      : `<div class="acc-lg">${A.basis === "aws"
          ? (rows.some(r => r.org !== "kma") ? `<span><i class="p"></i>경남 AWS</span>` : "") + (rows.some(r => r.org === "kma") ? `<span><i class="pk"></i>기상청 AWS</span>` : "")
          : `<span><i class="p"></i>실측</span>`}${tone ? `<span title="막대를 누르면 한 색으로"><i class="tn" style="background:linear-gradient(90deg, ${tSteps.map(v => rampColor(v, tSteps, tHr) || "transparent").join(", ")})"></i>지도 범례 색</span>` : ""}${h1On ? `<span><i class="h"></i>그중 최근 1시간</span><span><i class="c1"></i>1h · 많을수록 밝게</span>` : ""}${fcOn && rows.some(r => r.fc) ? `<span><i class="f"></i>앞으로 6시간</span>` : ""}${anyAvg ? `<span title="선 그래프 — 점은 최대 시우량, 점선은 실측 구간 평균 시우량(누적 ÷ 시간)"><i class="av"></i>평균 시우량</span>` : ""}</div>`);
  rowEvents(body);
  hovEvents(body);
  for (const b of body.querySelectorAll(".abar")) b.onclick = ev => {     // 막대 = 색 바꾸기(줄의 나머지는 그대로 시군 고르기)
    ev.stopPropagation();
    SET.acc_tone = !SET.acc_tone; saveSetting({ acc_tone: SET.acc_tone });
    renderAcc();
  };
  slideRows(body, before);
}
/* 줄 순서가 바뀌면 옛 자리에서 새 자리로 미끄러진다(FLIP). 새로 들어온 줄은 서서히 */
function slideRows(body, before) {
  if (!before.size || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const moved = [];
  for (const e of body.querySelectorAll(".ar[data-k]")) {
    const y0 = before.get(e.dataset.k), y1 = e.getBoundingClientRect().top;
    if (y0 == null) { e.style.opacity = "0"; moved.push(e); continue; }
    if (Math.abs(y0 - y1) < 1) continue;
    e.style.transform = `translateY(${(y0 - y1).toFixed(1)}px)`;
    moved.push(e);
  }
  if (!moved.length) return;
  void body.offsetHeight;                          // 옛 자리를 한 번 굳힌 뒤 풀어야 움직인다
  for (const e of moved) {
    e.style.transition = "transform .5s var(--ease), opacity .35s";
    e.style.transform = ""; e.style.opacity = "";
    setTimeout(() => { e.style.transition = ""; }, 600);
  }
}
/* 예상(앞으로 6시간)을 누적 카드에 보이나 — 서버 설정 acc_fc(기본 켬). 사례는 예상이 없다 */
const fcShown = () => !CASE && SET.acc_fc !== false;
const h1Shown = () => SET.acc_h1 !== false;
function toggleAccH1() {
  SET.acc_h1 = !h1Shown();
  saveSetting({ acc_h1: SET.acc_h1 });
  if (CARDS && !CARDS.err && CARDS.acc) renderAcc();
}
function toggleAccFc() {
  if (CASE) return;
  SET.acc_fc = !fcShown();
  saveSetting({ acc_fc: SET.acc_fc });
  if (CARDS && !CARDS.err && CARDS.acc) { renderAcc(); drawRanks(); cardsPlayhead(); }
}
/* 누적 줄 선 그래프 위를 지나가면 — 모든 줄에 그 시각 선, 예상 구간이면 예측 상위의 그 시각 열을 짚는다 */
let HOVT = null;
/* 선 그래프에 마우스 — 그 시각 세로 점선(모든 줄) + 커서 위에 '거제 일운면 19:00 8.2㎜'(그 줄, 가장 가까운 칸).
   오른쪽 클릭 — 그 시각 시우량 지도로(실측은 1시간 층 그 시각, 예상은 초단기 +N). 선 그래프 밖은 카드 메뉴 그대로(10-27) */
const p2 = v => String(v).padStart(2, "0");
const tmStr = t => { const d = new Date(t); return `${d.getFullYear()}${p2(d.getMonth() + 1)}${p2(d.getDate())}${p2(d.getHours())}${p2(d.getMinutes())}`; };
function spPick(body, ev) {
  const sp = CARDS?.acc?.sp, svg = body.querySelector(".ar svg");
  if (!sp || !svg) return null;
  const b = svg.getBoundingClientRect(), x = ev.clientX - b.left;
  if (x < 0 || x > b.width) return null;
  const t = sp.t0 + x / b.width * (sp.t1 - sp.t0);
  const row = ev.target.closest?.(".ar[data-k]"), d = row && CARDS.acc.vis?.get(row.dataset.k);
  let p = null;
  if (d && !d.dead) {
    const near = (ts, vs, fc) => (ts || []).forEach((x, j) => {
      if (typeof vs[j] === "number" && (!p || Math.abs(x - t) < Math.abs(p.t - t))) p = { t: x, v: vs[j], fc };
    });
    near(d.dt, d.d, false); near(d.ft, d.fcd || [], true);
  }
  return { t, row, d, p };
}
function spTip(h, ev) {
  const tip = $("sptip");
  for (const c of document.querySelectorAll("#acc-b .sp-hd.on")) c.classList.remove("on");
  if (!h?.p) { tip.hidden = true; return; }
  const { d, p, row } = h, sp = CARDS.acc.sp, dot = row.querySelector(".sp-hd");
  if (dot) {
    dot.setAttribute("cx", ((p.t - sp.t0) / (sp.t1 - sp.t0) * sp.SW).toFixed(1));
    dot.setAttribute("cy", sp.sy(p.v).toFixed(1));
    dot.classList.add("on");
  }
  const dt = new Date(p.t), today = dt.toDateString() === NOWD().toDateString();
  const tg = d.tag ?? d.sig, nm = tg && tg !== d.stn ? `${tg} ${d.stn}` : d.stn || d.sig;   // 줄 이름과 같게(시군 + 지점 · 읍면동)
  const go = CARDS.acc.day ? "" : `<small>오른쪽 클릭 — 그 시각 ${p.fc && !CASE ? "초단기 예측" : "1시간 강수량"} 지도</small>`;
  tip.innerHTML = `<b>${nm}</b> ${today ? "" : `${dt.getMonth() + 1}.${dt.getDate()}. `}${p2(dt.getHours())}:${p2(dt.getMinutes())}`
    + ` <b class="v">${p.v.toFixed(1)}㎜</b>${p.fc ? ` <i>예상</i>` : ""}${go}`;
  tip.hidden = false;
  const w = tip.offsetWidth, hh = tip.offsetHeight;
  tip.style.left = Math.max(4, Math.min(innerWidth - w - 4, ev.clientX + 14)) + "px";
  tip.style.top = Math.max(4, ev.clientY - hh - 12) + "px";
}
/* 그 시각 시우량 지도로 — 실측은 1시간 층(AWS 기준이면 AWS 1시간, 격자면 60분) 그 시각, 예상은 초단기 +N, 사례는 가장 가까운 장.
   위 카드는 강수 누적 그대로(ACC_HOLD) — 선 그래프에 지금 지도 시각 세로선. 누적 지도로는 층 메뉴 · 숫자 키로 돌아간다 */
function goHour(p) {
  const A = CARDS?.acc;
  if (!A || A.day) return;
  stopPlay();
  highlight(null); link(null); hot(null);              // 줄에 올렸던 빛줄 · 고리 — 줄이 다시 그려져도 남지 않게
  const was = cardKey();
  ACC_HOLD = true;
  if (CASE) {
    const fr = CASEM?.frames || [];
    if (!fr.length) return;
    kind = "obs60";
    OBS_TM = fr.reduce((a, f) => (Math.abs(tOf(f) - p.t) < Math.abs(tOf(a) - p.t) ? f : a));
  } else if (p.fc) {
    kind = "vsrt"; vsrtN = Math.max(1, Math.min(6, Math.round((p.t - A.sp.tn) / 3600e3))); OBS_TM = null;
  } else {
    kind = (A.basis || ACC_BASIS) === "grid" ? "obs60" : "aws60";
    const tm = tmStr(p.t);
    OBS_TM = tm === metaOf(kind).tm ? null : tm;
  }
  $("sptip").hidden = true;
  show(true);
  if (cardKey() !== was) loadCards();
}
function hovEvents(body) {
  body.onmousemove = ev => {
    const sp = CARDS?.acc?.sp;
    if (!sp || !body.querySelector(".ar svg")) return;
    const h = spPick(body, ev), t = h ? h.t : null;
    spTip(h, ev);
    if (t === HOVT) return;
    HOVT = t;
    body.classList.toggle("hovt", t != null);
    const px = t == null ? -99 : (t - sp.t0) / (sp.t1 - sp.t0) * sp.SW;
    for (const l of body.querySelectorAll(".sp-hov")) l.style.transform = `translateX(${px.toFixed(1)}px)`;
    cardsPlayhead();
  };
  body.onmouseleave = () => { HOVT = null; body.classList.remove("hovt"); spTip(null); cardsPlayhead(); };
  body.oncontextmenu = ev => {
    const h = spPick(body, ev);
    if (!h?.p || CARDS?.acc?.day) return;          // 선 그래프 밖 · 단기 — 카드 메뉴(줄 세우기) 그대로
    ev.preventDefault(); ev.stopPropagation();
    goHour(h.p);
  };
}

/* 시우량 범주(㎜/h) — 지금 오는 비 · 예측 상위(초단기) · 지도 1시간 층이 **한 자**를 쓴다(종합 화면 시우량 램프와 같다).
   누적(지도 누적 층 — 자동 눈금)과는 다른 자다 — 카드 머리에 작은 범례로 따로 적는다.
   15분 값은 ×4(시간당 기세)로 이 자에 칠한다 — 15분 8㎜ 는 시간당 32㎜ 의 기세다.
   ⚠️ 예전에는 지금 오는 비가 1·5·10·20·30·50·70, 15분은 0.5·2·5·8·12·18·25 로 따로 칠해 같은 10㎜ 가 지도 · 예측 상위와 다른 색이었다 */
const SIU = STEPS.m60;
/* 카드 머리 작은 범례 — 그 자의 칸마다 색과 값. 기상청 색이면 시우량은 레이더 경계 색 */
function miniLegend(steps, label, hourly = true, tip = "") {
  return `<span class="mlg" title="${tip}"><b>${label}</b>${steps.map((v, i) => {
    const c = rampColor(v, steps, hourly), ink = kmaOn() ? inkOn(c) : inkBlue(i + 1);
    return `<i style="background:${c};color:${ink}">${v}</i>`;
  }).join("")}</span>`;
}
/* 지금 오는 비 · 예측 상위 줄 수 — 패널이 낮으면(FHD 150% = 720px 등) 줄여서 강수 누적 카드에 자리를 남긴다.
   ⚠️ 1280×720 에서 둘이 6줄씩 다 쓰자 강수 누적은 머리만 남았다(본문 11px) */
const cardRows = () => { const h = $("rail")?.clientHeight || 900; return h < 560 ? 3 : h < 800 ? 4 : 6; };
const NOW_T = { bt: "now-bt", lg: "now-lg", b: "now-b" }, FC_T = { bt: "fc-bt", lg: "fc-lg", b: "fc-b" };
const SW_T = { bt: "sw-bt", lg: "sw-lg", b: "sw-b" };     // 바다 위젯 — 같은 그림을 그 판에
function renderNow(t = NOW_T, nRows = cardRows()) {
  const N = CARDS.now;
  $(t.bt).textContent = N.tm || "—";
  const col = (list, kk, steps = SIU) => {
    const mx = Math.max(...list.map(x => x.mm), 0.1);
    if (!list.length || mx <= 0.1 && !list.some(x => x.mm > 0))
      return `<div class="empty-note">비 없음</div>`;
    return list.slice(0, nRows).map(x => {
      // 시우량 자 — 15분은 ×4 로. 사례의 '3시간'은 누적 자(steps 를 따로 준다)
      const c = rampColor(kk === 15 ? x.mm * 4 : x.mm, steps, steps === SIU) || "var(--ink-3)";
      const sm = N.det ? x.tag : x.sig, at = x.pos ? ` data-x="${x.pos.x}" data-y="${x.pos.y}"` : "";
      return `<div class="mr${N.det ? " det" : ""}" data-s="${x.sig}"${at}><span class="bg" style="width:${(x.mm / mx * 100).toFixed(0)}%;background:${c}"></span>
        <span class="nm2">${x.name && x.name !== x.sig ? `${sm ? `<small>${sm}</small>` : ""}${x.name}` : x.sig}</span><b>${x.mm.toFixed(1)}</b></div>`;
    }).join("");
  };
  const colSteps = (list, steps) => col(list, "x", steps);   // 사례 · 시군: 1시간 · 3시간(자를 직접 준다)
  $(t.lg).innerHTML = miniLegend(SIU, "시우량", true, "시우량 범주(㎜/h) — 지도 1시간 · 예측 상위와 같은 자. 15분은 ×4(시간당 기세)로 칠한다. 지도 누적 층의 자와는 다르다");
  $(t.b).innerHTML = N.cols
    ? `<div class="mn">${N.cols.map(c => `<div><h4>${c.title}<span>㎜</span></h4>${colSteps(c.list, c.steps)}</div>`).join("")}</div>`
    : `<div class="mn"><div><h4>15분<span>㎜</span></h4>${col(N.r15, 15)}</div>
    <div><h4>60분<span>㎜</span></h4>${col(N.r60, 60)}</div></div>`;
  rowEvents($(t.b));
}

/* 예측 상위 — 6시간 합 순. 칸은 지도와 같은 색 단계 */
function renderFc(t = FC_T, nRows = cardRows(), rowsIn = null) {
  const F = CARDS.fc;
  $(t.bt).textContent = F.bt;
  const rows = (rowsIn || F.rows).slice().sort((a, b) => b.sum - a.sum).slice(0, nRows);
  const day = F.mode === "day";
  if (!rows.length || rows[0].sum <= 0) {
    $(t.lg).innerHTML = "";
    $(t.b).innerHTML = `<div class="empty-note">${F.empty || "앞으로 6시간 예상 강수 없음"}</div>`;
    return;
  }
  // 칸 색 — 초단기는 시우량(1시간) 자, 단기는 6시간 합이라 하루 눈금(지도 단기 층과 같은 자)
  const steps = day ? STEPS.day : SIU;
  $(t.lg).innerHTML = day ? miniLegend(steps, "6시간 합", false, "단기 6시간 합(㎜) — 지도 단기 층과 같은 자")
    : miniLegend(steps, "시우량", true, "시우량 범주(㎜/h) — 칸은 그 시간 강수량(초단기 RN1). 지도 누적 층의 자와는 다르다");
  const cell = v => {
    if (v == null) return `<i class="na"></i>`;           // 오늘의 지난 구간(발표 앞)
    const k = stepIdx(v, steps), c = rampColor(v, steps, !day);
    const txt = v >= 1 ? (Number.isInteger(v) ? v : v.toFixed(1)) : "";
    const ink = !c ? "" : kmaOn() ? inkOn(c) : inkBlue(k);
    return `<i style="${c ? `background:${c};color:${ink}` : ""}">${txt}</i>`;
  };
  $(t.b).style.setProperty("--n", F.labels.length || 6);
  $(t.b).innerHTML = `<div class="fh"><span>${day && !F.det ? "읍면동" : "시군"}</span><div class="cells">${F.labels.map(l => `<span>${l}</span>`).join("")}</div><span style="text-align:right">합</span></div>`
    + rows.map(r => `<div class="fr${F.det ? " det" : ""}" data-s="${r.sig}"${r.pos ? ` data-x="${r.pos.x}" data-y="${r.pos.y}"` : ""}><span class="nm2">${r.label ? `${r.tag ? `<small class="pre">${r.tag}</small>` : ""}${r.label}` : `${r.sig}<small>${r.emd || ""}</small>`}</span>
      <div class="cells">${r.d.map(cell).join("")}</div><span class="sum">${(+r.sum).toFixed(r.sum % 1 ? 1 : 0)}</span></div>`).join("");
  rowEvents($(t.b));
}

/* 카드 안의 재생 위치 — 누적 줄 선 그래프의 세로선, 예측 칸의 테두리 */
function cardsPlayhead() {
  if (!CARDS || CARDS.err || !tlOn || SET.panel === "timeline") return;
  const ht = headT(), sp = CARDS.acc?.sp;
  for (const l of document.querySelectorAll(".sp-head")) {
    const x = ht != null && sp && ht >= sp.t0 && ht <= sp.t1 ? (ht - sp.t0) / (sp.t1 - sp.t0) * sp.SW : -99;
    l.style.transform = `translateX(${x.toFixed(1)}px)`;
    // ⚠️ 범위 밖이면 감춘다 — svg 가 overflow visible 이라 -99px 에 두면 막대 칸에 세로줄로 보였다
    l.style.visibility = x < 0 ? "hidden" : "";
  }
  // 예측 상위의 그 시각 열 — 누적 줄 선 그래프의 예상 구간에 마우스가 있으면 그 시각, 아니면 재생 위치가
  // 예측(초단기)일 때 그 시각. 실측 구간이면 짚지 않는다
  let j = -1;
  const fts = CARDS.fc?.ft || [];
  const near = t => { let bd = Infinity, k = -1; fts.forEach((x, i) => { const d = Math.abs(x - t); if (d < bd) { bd = d; k = i; } }); return k; };
  if (HOVT != null && CARDS.fc?.mode === "day") {
    const h = new Date(HOVT - 1).getHours();       // 끝 시각 기준 — 18:00 은 12~18시 칸
    j = Math.min(3, Math.floor(h / 6));
  } else if (HOVT != null) { if (sp && HOVT > sp.tn && fts.length) j = near(HOVT); }
  else if (kind === "vsrt" && ht != null && fts.length) j = near(ht);
  for (const r of document.querySelectorAll("#fc-b .fr, #fc-b .fh, #sw-b .fr, #sw-b .fh")) {
    const cs = r.querySelector(".cells");
    cs?.classList.toggle("has-on", j >= 0);
    r.querySelectorAll(".cells > *").forEach((c, i) => c.classList.toggle("on", i === j));
  }
}

/* 지도 위 순위 표식 — 누적 상위 셋. 시군 줄이면 시군명 왼쪽, 시군을 골랐으면 그 지점·칸 자리에 */
function drawRanks() {
  const g = $("ranks");
  if (!g) return;
  if (!tlOn || SET.panel === "timeline" || !CARDS || CARDS.err || !CARDS.acc || !V) { g.innerHTML = ""; return; }
  const det = !!CARDS.acc.sel;
  const tot = r => r.sum + (fcShown() ? r.fc : 0);
  const seen = new Set();                 // 시군당 n · 시군 무관이면 한 시군이 여러 줄 — 시군 이름 옆 원은 시군마다 한 번
  const rows = CARDS.acc.rows.slice().sort((a, b) => tot(b) - tot(a))
    .filter(r => tot(r) >= 0.1 && (det || (!seen.has(r.sig) && seen.add(r.sig)))).slice(0, 3);
  const r0 = FSN * 0.46;
  g.innerHTML = rows.map((r, i) => {
    let x, y;
    if (det) {
      if (!r.pos) return "";
      x = V.toX(r.pos.x) + r0 * 1.15; y = V.toY(r.pos.y) - r0 * 1.15;
    } else {
      const ft = FEAT.find(f => f.properties.sigun === r.sig);
      if (!ft) return "";
      x = V.toX(ft.properties.lx) - r.sig.length * FSN * 0.52 - r0 - 4; y = V.toY(ft.properties.ly);
    }
    return `<g class="rk"><circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r0.toFixed(1)}"/>
      <text x="${x.toFixed(1)}" y="${y.toFixed(1)}" style="font-size:${(FSN * 0.56).toFixed(1)}px">${i + 1}</text></g>`;
  }).join("");
}

/* 줄 ↔ 지도 연결선 — 카드 줄 왼쪽 끝에서 지도 위 그 시군 이름 오른쪽까지, 그어지듯.
   pt(칸 좌표)를 주면 그 자리(지점·누적 최대 칸)까지 긋는다. */
function link(el, sig, pt) {
  const svg = $("links");
  if (!el || !sig || !V) { svg.innerHTML = ""; return; }
  const st = $("stage").getBoundingClientRect(), r = el.getBoundingClientRect();
  const x1 = r.left - st.left - 3, y1 = r.top - st.top + r.height / 2;
  let x2, y2;
  if (pt) {
    x2 = V.toX(pt.x) * MT.sc + MT.tx; y2 = V.toY(pt.y) * MT.sc + MT.ty;
  } else {
    const ft = FEAT.find(f => f.properties.sigun === sig);
    if (!ft) { svg.innerHTML = ""; return; }
    const hw = sig.length * FSN * 0.52 * MT.sc;
    x2 = V.toX(ft.properties.lx) * MT.sc + MT.tx + hw + 8; y2 = V.toY(ft.properties.ly) * MT.sc + MT.ty;
  }
  const dx = Math.max(50, (x1 - x2) * 0.45);
  svg.innerHTML = `<path d="M${x1.toFixed(1)},${y1.toFixed(1)} C${(x1 - dx).toFixed(1)},${y1.toFixed(1)} ${(x2 + dx).toFixed(1)},${y2.toFixed(1)} ${x2.toFixed(1)},${y2.toFixed(1)}"/>
    <circle cx="${x2.toFixed(1)}" cy="${y2.toFixed(1)}" r="5"/>`;
  const p = svg.querySelector("path");
  p.style.setProperty("--len", p.getTotalLength().toFixed(0));
}
/* 줄이 가리키는 자리에 고리 — 지점·누적 최대 칸 */
function hot(pt) {
  const g = $("hot");
  if (!g) return;
  if (!pt || !V) { g.innerHTML = ""; return; }
  const x = V.toX(pt.x).toFixed(1), y = V.toY(pt.y).toFixed(1), r = Math.max(9, V.u * 2.4);
  g.innerHTML = `<circle cx="${x}" cy="${y}" r="${r.toFixed(1)}"/><circle class="c" cx="${x}" cy="${y}" r="${Math.max(3, r * 0.28).toFixed(1)}"/>`;
}


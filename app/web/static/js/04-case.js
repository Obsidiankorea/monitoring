"use strict";
/* ── 재현 사례(?case=) ────────────────────────────────────────────────
   지난 호우를 500m 격자 그대로 되돌려 본다(data/demo/map/, tools/build_map_case.py).
   층은 1시간·사례 누적, 재생은 처음부터 끝까지 매시, 카드·특보도 그 시각에 맞춘다.
   ⚠️ 특보는 **산출**이다 — 격자 3시간·12시간 합에 호우 기준. 이력 API 가 403 이라 실제 발표 내역이 없다.
   ⚠️ 격자는 관측소 값을 그대로 지나지 않는다(객관분석). 확인한 관측소 값을 누적 카드 밑에 같이 적는다. */
async function loadCase() {
  CASEM = await getJson(`/api/grid/case/${CASE}`);
  const src = "기상청 고해상도 격자(500m) · 매시 60분 — 재현";
  META.layers = [
    { id: "obs60", label: "1시간 강수량", short: "1시간", grid: "hr", src, tm: CASEM.end },
    { id: "acc", label: "사례 누적", short: "누적", grid: "hr", src: src + " · 칸마다 더함", tm: CASEM.end },
  ];
  META.collect = {};
}
function caseIdx() {
  if (!CASEM) return -1;
  const i = CASEM.frames.indexOf(CUR?.tm || OBS_TM || CASEM.end);
  return i < 0 ? CASEM.frames.length - 1 : i;
}
const CASEACC = new Map();
async function cardsFromCase() {
  const i = caseIdx(), S = CASEM.series, t = CASEM.frames[i];
  const dt = CASEM.frames.map(tOf);
  const when = `${md(t)} ${hm(t)}`;
  const from = `${md(CASEM.start)} ${String(+CASEM.start.slice(8, 10) - 1).padStart(2, "0")}:00부터`;
  let acc;
  if (ACC_BASIS === "aws") acc = caseAccAws(i, dt, from);
  else if (selOn()) acc = await caseAccGrid(i, dt, from);
  else acc = { rows: S.map(s => ({ sig: s.sigun, stn: s.accw[i] || "", d: s.h1, dt, fcd: [], ft: [], sum: s.acc[i] ?? 0, fc: 0, h1: s.h1[i] ?? 0 })),
               sub: `사례 누적 · 격자 시군 최대 칸 · ${from}`,
               note: "관측소(이틀): " + CASEM.checked.map(c => `${c.name} ${c.sum.toFixed(1)}`).join(" · ")
                     + " — 격자는 관측값을 그대로 지나지 않는다('강수 누적'을 누르면 AWS 기준)" };
  const top = (k, w) => S.map(s => ({ sig: s.sigun, name: (w && s[w][i]) || "", mm: s[k][i] ?? 0 }))
    .sort((a, b) => b.mm - a.mm).slice(0, 6);
  const rank = { warn: 2, watch: 1 };
  const crit = S.filter(s => !selOn() || isSel(s.sigun)).map(s => ({ sig: s.sigun, h3: s.h3[i] ?? 0, h12: s.h12[i] ?? 0, lv: s.lv[i] }))
    .sort((a, b) => ((rank[b.lv] || 0) - (rank[a.lv] || 0)) || (b.h12 - a.h12)).slice(0, 6);
  // 시군을 고르면 1시간·3시간도 그 시군(들) 읍면동 — 격자 그 시각 칸을 읍면동마다 최대로
  let now = { tm: when, sub: "격자 · 1시간 · 3시간",
              cols: [{ title: "1시간", list: top("h1", "h1w"), steps: SIU },
                     { title: "3시간", list: top("h3"), steps: [5, 20, 40, 60, 90, 120, 180] }] };
  if (selOn()) {
    const q = h => getJson(`/api/grid/emd?sigun=${encodeURIComponent(selQ())}&case=${CASE}&tm=${t}&hours=${h}`);
    const [a, b] = await Promise.all([q(1), q(3)]);
    now = { tm: when, det: true, sub: `${selName()} 읍면동 · 격자 1시간 · 3시간`,
            cols: [{ title: "1시간", list: emdTop(a.rows), steps: SIU },
                   { title: "3시간", list: emdTop(b.rows), steps: [5, 20, 40, 60, 90, 120, 180] }] };
  }
  return {
    acc: { H: i + 1, src: "재현", fell: false, bt: when, basis: ACC_BASIS, ...acc },
    now,
    crit: { rows: crit, bt: when },
  };
}
/* 사례 AWS 기준 — 굳혀 둔 매시 RN_HR1(meta.stations)을 그 시각까지 더한다 */
function caseAccAws(i, dt, from) {
  const h1 = CASEM.stations?.h1;
  if (!h1 || !SITES) return { rows: [], sel: selOn() ? selName() : null, sub: "이 사례에는 관측소 자료가 없다", note: "" };
  const all = SITES.stations.filter(s => h1[s.stn]).map(s => {
    const h = h1[s.stn], seg = h.slice(0, i + 1), have = seg.filter(v => v != null);
    return { sig: s.sigun, tag: selOn() ? (multi() ? `${s.sigun} ${s.emd || ""}` : (s.emd || "")) : s.sigun, stn: s.name, d: h, dt, fcd: [], ft: [], h1: h[i] ?? 0,
             sum: Math.round(sumv(seg) * 10) / 10, fc: 0, pos: { x: s.x, y: s.y }, det: selOn(),
             part: have.length > 0 && have.length < seg.length, dead: !have.length };
  });
  const note = "기상청 정시자료(awsh) 매시 1시간 강수의 합" + (all.some(r => r.part) ? " · 일부 시각이 빠진 지점은 있는 시각만 더했다(하한)" : "");
  if (selOn()) {
    const rows = all.filter(r => isSel(r.sig));
    return { rows, sel: selName(), sub: `${selName()} AWS ${rows.length}곳 · ${from}`, note };
  }
  const best = {};
  for (const r of all) if (!best[r.sig] || r.sum > best[r.sig].sum) best[r.sig] = r;
  return { rows: ORDER_GN().filter(s => best[s]).map(s => best[s]), sub: `다우지점 · ${from}`,
           note: note + " — 격자 누적보다 봉우리가 높다(격자는 관측소 사이를 메운 분석값)" };
}
async function caseAccGrid(i, dt, from) {
  const t = CASEM.frames[i], ck = `${t}|${selQ()}`;
  let j = CASEACC.get(ck);
  if (!j) {
    j = await getJson(`/api/grid/acctable?case=${CASE}&tm=${t}&sigun=${encodeURIComponent(selQ())}`);
    if (CASEACC.size > 200) CASEACC.delete(CASEACC.keys().next().value);
    CASEACC.set(ck, j);
  }
  const n = CASEM.frames.length;
  const rows = j.rows.map(r => ({ sig: r.sig, tag: multi() ? r.sig : "", stn: r.name, d: r.d.concat(Array(n - r.d.length).fill(null)), dt,
    fcd: [], ft: [], sum: r.sum ?? 0, fc: 0, det: true, pos: r.col != null ? { x: r.col, y: r.row } : null }));
  return { rows, sel: selName(), sub: `${selName()} 읍면동 ${rows.length} · 누적 최대 칸 · ${from}`, note: "" };
}
function caseAlerts() {
  const i = caseIdx(), bySig = {}, by = {};
  for (const s of CASEM.series) {
    const lv = s.lv[i];
    if (!lv) continue;
    const name = lv === "warn" ? "호우경보" : "호우주의보";
    bySig[s.sigun] = [{ name, lv, sub: "산출" }];
    (by[name] ||= { lv, name, where: [] }).where.push(s.sigun);
  }
  const land = Object.values(by).sort((a, b) => (b.lv === "warn") - (a.lv === "warn"));
  const t = CASEM.frames[i];
  return { base: `${t.slice(0, 4)}-${t.slice(4, 6)}-${t.slice(6, 8)} ${hm(t)}`, bySig, land, sea: [], pending: [], calc: true };
}
function renderCrit() {
  const C = CARDS.crit;
  $("fc-bt").textContent = C.bt;
  const W = CASEM.criteria;
  const g = (v, cap, warnAt) => {
    const w = Math.min(100, v / cap * 100), m = Math.min(100, warnAt / cap * 100);
    return `<div class="g"><i style="width:${w.toFixed(1)}%"></i><s style="left:${m.toFixed(1)}%"></s><span>${v.toFixed(1)}</span></div>`;
  };
  $("fc-b").innerHTML = `<div class="crit h"><span>시군</span><span>3시간 (경보 ${W.warn.h3})</span><span>12시간 (경보 ${W.warn.h12})</span><span style="text-align:right">산출</span></div>`
    + C.rows.slice(0, cardRows()).map(r => `<div class="crit" data-s="${r.sig}"><span class="nm2">${r.sig}</span>
        ${g(r.h3, 180, W.warn.h3)}${g(r.h12, 450, W.warn.h12)}
        <span class="lv ${r.lv || "none"}">${r.lv === "warn" ? "경보" : r.lv === "watch" ? "주의보" : "—"}</span></div>`).join("");
  rowEvents($("fc-b"));
}
/* 데모 — 실황 · 테스트(합성 격자, 비 없는 날 화면 점검) · 재현 사례(지난 호우)를 한 메뉴에.
   실황에서 테스트를 켜고 끄는 것은 다시 띄우지 않고 그 자리에서, 사례는 주소를 바꿔 띄운다. */
function setTest(on) {
  if (CASE) { location.href = on ? "/map.html?test=1" : "/map.html"; return; }
  test = !!on;
  GRIDS.clear(); STATS.clear(); CARDS = null;
  loadFlow().then(() => show());
  loadAlerts();
  if (!test) loadCards();                // 테스트는 loadFlow 가 합성 흐름으로 카드를 다시 뽑는다
}
/* 설정 › 데모 — 실황 · 테스트(합성) · 재현 사례 목록. 예전엔 머리줄에 단추가 따로 있었다 */
/* 시연 한 줄의 설명 — 시각 · 누적 구간 · 특보 · 빠진 것 · 크기 */
const ACCL = a => !a ? "" : a.from === "today" ? "오늘 0시부터" : a.from === "yesterday" ? "어제 0시부터" : `지난 ${a.hours}시간`;
function snapSub(x) {
  return [`${md(x.now)} ${hm(x.now)}`, x.acc ? "누적 " + ACCL(x.acc) : "", (x.alerts || []).join(", "),
          x.mb ? x.mb + "MB" : ""].filter(Boolean).join(" · ")
    + ((x.warn || []).length ? ` <i class="sw">${x.warn.join(" · ")}</i>` : "")
    + (x.note ? `<br>${x.note}` : "");
}
/* 지금 저장 — 서버가 뒤에서 굳힌다(수십 초). 끝날 때까지 /api/snaps 의 job 을 본다 */
async function snapSave(btn, title, acc) {
  const label = btn.textContent;
  btn.disabled = true; btn.textContent = "굳히는 중…";
  const post = overwrite => fetch("/api/snaps", { method: "POST", headers: { "content-type": "application/json" },
    body: JSON.stringify({ title, ...(acc ? { acc } : {}), overwrite }) });
  try {
    let r = await post(false);
    if (r.status === 409) {
      const d = (await r.json().catch(() => ({}))).detail || "";
      if (!/이미 있다/.test(d) || !confirm(d + "\n덮어쓸까요?")) throw new Error(d || "저장하지 않았다");
      r = await post(true);
    }
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.status);
    const t0 = Date.now();
    for (;;) {
      await new Promise(res => setTimeout(res, 1200));
      const j = await getJson("/api/snaps");
      if (!j.job || j.job.done) {
        if (j.job?.error) throw new Error(j.job.error);
        const m = j.job?.meta;
        toast(`시연을 저장했다 — ${m ? m.title : ""}${m?.warn?.length ? " (" + m.warn.join(" · ") + ")" : ""}`);
        return true;
      }
      btn.textContent = `굳히는 중… ${Math.round((Date.now() - t0) / 1000)}초`;
    }
  } catch (e) {
    alert("시연을 저장하지 못했다: " + e.message);
    return false;
  } finally {
    btn.disabled = false; btn.textContent = label;
  }
}
async function snapDel(name, title) {
  if (!confirm(`시연 «${title}» 을 지울까요?\n서버에서 지워져 되돌릴 수 없습니다.`)) return false;
  const r = await fetch(`/api/snaps/${encodeURIComponent(name)}`, { method: "DELETE" });
  if (!r.ok) { alert("지우지 못했다: " + ((await r.json().catch(() => ({}))).detail || r.status)); return false; }
  toast(`시연을 지웠다 — ${title}`);
  return true;
}

async function fillDemo(box) {
  let list = [];
  try { list = (await getJson("/api/grid/cases")).cases; } catch {}
  let snaps = [], job = null, demo = false;
  try { ({ snaps, job, demo } = await getJson("/api/snaps")); } catch {}
  const S = window.GN_SNAP, busy = job && !job.done, ro = S || demo;
  box.innerHTML = (S ? `<a href="${LIVE_URL("/map.html")}"><b>실황(지금)으로</b><small>시연을 끝내고 수집 중인 화면으로(:8000)</small></a>` : "")
    + `<div class="dh">시연 — 그때를 굳혀 둔 것</div>`
    + (ro ? "" : `<div class="snapsave">
        <input id="sv-title" type="text" maxlength="80" placeholder="제목 — 비우면 시각 · 특보로">
        <button id="sv-go" type="button"${busy ? " disabled" : ""}>${busy ? "굳히는 중…" : "지금 저장"}</button>
        <small>지금 실측 · 그전까지 온 비(72시간) · 초단기 · 단기(오늘~모레) · 예측 분포 · 특보 · 이 화면 설정(층 · 누적 구간)을 서버에 굳혀 둔다</small></div>`)
    + (snaps.length ? snaps.map(x => `<div class="snaprow"><a class="${S && S.name === x.name ? "on" : ""}" href="${SNAP_OPEN(x.name, "/map.html")}" target="${S ? "_self" : "gn-snap"}">
        <b>${x.title}</b><small>${snapSub(x)}</small></a>${ro ? "" : `<button class="snapdel" type="button" data-del="${x.name}" title="지우기 — 서버에서 지운다(되돌릴 수 없다)" aria-label="지우기"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5M7 7v4M9 7v4"/></svg></button>`}</div>`).join("")
      : `<div class="al-none" style="padding:6px 10px">굳혀 둔 시연이 없다${ro ? "" : " — 비가 올 때 '지금 저장'"}</div>`)
    + (S ? "" : `<div class="dh">이 화면</div><a href="/map.html" data-live class="${!CASE && !test ? "on" : ""}"><b>실황(지금)</b><small>수집 중인 자료</small></a>`)
    + `
<a href="/map.html?test=1" data-test class="t ${test ? "on" : ""}"><b>테스트 — 합성</b><small>비 없는 날 화면 점검 · 합성 격자 · 특보 · 지점(경남 AWS 흉내) · T 키</small></a>
    <div class="dh">재현 사례 — 지난 호우</div>`
    + list.map(c => `<a class="${c.slug === CASE ? "on" : ""}"
      href="/map.html?case=${c.slug}&layer=acc&tl=1&ov=alerts"><b>${c.title}</b>
      <small>${md(c.start)} ${hm(c.start)} ~ ${md(c.end)} ${hm(c.end)} · 봉우리 ${md(c.peak)} ${hm(c.peak)}</small></a>`).join("")
    + (list.length ? "" : `<div class="al-none" style="padding:8px 10px">사례가 없다</div>`);
  for (const a of box.querySelectorAll("a[data-live], a[data-test]")) a.onclick = ev => {
    if (CASE) return;                    // 사례에서는 주소로 옮긴다
    ev.preventDefault(); closePrefs(); setTest(a.hasAttribute("data-test"));
  };
  const go = box.querySelector("#sv-go");
  if (go) go.onclick = async () => { if (await snapSave(go, box.querySelector("#sv-title").value.trim())) fillDemo(box); };
  for (const b of box.querySelectorAll("[data-del]")) b.onclick = async () => {
    const x = snaps.find(y => y.name === b.dataset.del);
    if (await snapDel(x.name, x.title)) fillDemo(box);
  };
}


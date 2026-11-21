"use strict";
/* ── 재난안전데이터공유플랫폼 — 레이어 셋: 산사태(J) · 위험저수지(K) · 침수흔적(N) ─────────────────────────
   서버가 받아 둔 것(/api/safety · /api/safety/flood)을 그린다. 셋은 따로 켜고 끈다(자료 한 번 받아 나눠 쓴다).
   산사태 — 예보(시장 · 군수 발령) · 예측(산림청)이 걸린 시군에 갈색 테두리 + 이름 위 딱지. 서버는 호우 · 태풍 특보 때(또는 '늘 받기')만 받는다.
   위험저수지 — 계측기 세모(발령 중이면 단계 색). 침수흔적 — 2002~ 과거 침수 구역 옅은 파랑 면. */
let SAF = null, SAF_FL = null, SAF_T = 0, SAF_HIT = [], SAF_V = null;   // SAF_V = 산사태취약지역(한 번만 받는다)
const SAF_IDS = ["slide", "reservoir", "flood"];
const SAF_C = ["var(--ink-3)", "var(--rv-1)", "var(--rv-2)", "var(--rv-3)", "var(--rv-4)", "var(--rv-4)"];   // 저수지 관심 · 주의 · 경계 · 심각 · 대피
const safAny = () => SAF_IDS.some(id => OV.has(id));
/* 산사태취약지역 마름모 — 우려지역 지구 패널에서 켜고 끈다(이 브라우저 기억). 산사태 레이어나 우려지역 지구 레이어가 켜져 있을 때 보인다 */
let SAF_VON = true;
try { SAF_VON = localStorage.getItem("gn-vuln") !== "0"; } catch {}
const vulnOn = () => SAF_VON && !CASE && (OV.has("slide") || OV.has("district"));
async function loadVuln() {
  if (!vulnOn() || SAF_V) return;
  try { SAF_V = (await getJson("/api/slide/vuln")).rows || []; } catch { SAF_V = []; }
  drawSafety(); districtLegend();
}
function safVuln() {                                     // 토석류 노랑 · 산사태 빨강. 고른 시군만(전체면 다) — 2,500곳이라 가려 그린다
  if (!vulnOn() || !SAF_V?.length || !V || !V.s) return "";
  const r = Math.max(2.2, Math.min(5, V.u * 0.55));
  let o = "";
  for (const s of SAF_V) {
    if (!selHas(s.sg)) continue;
    const [c, rr] = LCCF(s.p[1], s.p[0]), x = V.toX(c), y = V.toY(rr);
    o += `<path class="sfv${s.ty === "산사태" ? " s" : ""}" d="M${x.toFixed(1)},${(y - r).toFixed(1)}l${r.toFixed(1)},${r.toFixed(1)}l${(-r).toFixed(1)},${r.toFixed(1)}l${(-r).toFixed(1)},${(-r).toFixed(1)}Z"/>`;
    SAF_HIT.push({ x, y, rr: Math.max(r, 5), v: s });
  }
  return o;
}
/* 침수흔적 깊이 색(범례 토글, 이 브라우저 기억) — 침수심(m) 다섯 단계. 청색 강수 위라 하늘 → 노랑 → 주황 → 빨강 → 자주 */
let SAF_DEP = false;
try { SAF_DEP = localStorage.getItem("gn-flood-dep") === "1"; } catch {}
const FL_DEP = [[0.5, "#7FE3F0", "0.5m 미만"], [1, "#F5E663", "0.5~1m"], [2, "#F5A142", "1~2m"], [3, "#EF5B4C", "2~3m"], [99, "#D05BE6", "3m 이상"]];
const flDepExpr = () => ["case", ["<", ["get", "dep"], 0], "#9AA3B2",
  ["step", ["get", "dep"], FL_DEP[0][1], ...FL_DEP.slice(0, -1).flatMap(([v], k) => [v, FL_DEP[k + 1][1]])]];
async function loadSafety() {
  clearTimeout(SAF_T);
  if (!safAny() || CASE) { SAF = null; drawAlerts(); drawSafety(); renderSafetyLegend(); renderLyIcons(); loadVuln(); return; }
  try { SAF = await getJson("/api/safety"); } catch (e) { SAF = { fail: e.message }; }
  await loadVuln();
  if (OV.has("flood") && !SAF_FL && SAF?.flood) { try { SAF_FL = await getJson("/api/safety/flood"); } catch { SAF_FL = []; } }
  drawAlerts(); drawSafety(); renderSafetyLegend(); renderLyIcons();   // 산사태 딱지가 생기면 특보 딱지 크기 · 기온 자리가 바뀐다
  SAF_T = setTimeout(loadSafety, 5 * 60 * 1000);
}
/* 시군마다 지금 걸린 산사태 예보 · 예측 중 센 것 */
/* 예보(시장 · 군수 발령)와 예측(산림청)을 따로 — 예보는 이름 테두리, 예측은 이름 옆 산 그림 */
function safSlideOf(list) {
  const by = {};
  for (const r of list || []) if (r.on && (!by[r.sigun] || r.lv > by[r.sigun].lv)) by[r.sigun] = r;
  return by;
}
function safSlide() {
  const by = {};
  for (const [src, list] of [["예보", SAF?.fcst], ["예측", SAF?.pred]])
    for (const r of list || []) if (r.on && (!by[r.sigun] || r.lv > by[r.sigun].lv)) by[r.sigun] = { ...r, src };
  return by;
}
const safOn = () => (SAF?.res || []).filter(r => r.on && selHas(r.sigun));
/* 레이어 아이콘 숫자 — 산사태는 걸린 시군 수, 저수지는 발령 중 계측기 수 */
const safCount = id => (id === "slide" ? Object.keys(safSlide()).filter(selHas).length : id === "reservoir" ? safOn().length : 0);
function drawSafety() {
  const g = $("safg");
  if (!g) return;
  SAF_HIT = [];
  // 침수흔적 면은 GL 층 'flood'(01b) — 고리 첫째가 바깥, 나머지는 구멍
  const fl = safAny() && SAF && !SAF.fail && OV.has("flood") ? SAF_FL || null : null;
  glData("flood", fl, () => (fl || []).map((f, i) => glF(glPoly(f.r.map(ring => ring.map(p => LCCF(p[0], p[1])))), { i, dep: isFinite(parseFloat(f.dep)) ? parseFloat(f.dep) : -1 })));
  if (GL_OK) {
    GL.setPaintProperty("flood", "fill-color", SAF_DEP ? flDepExpr() : cssVal("var(--sf-flood)"));
    GL.setPaintProperty("flood", "fill-opacity", SAF_DEP ? 0.5 : 0.22);
    GL.setPaintProperty("flood-line", "line-color", SAF_DEP ? flDepExpr() : cssVal("var(--sf-flood)"));
  }
  if (!safAny() || !V || !V.s || !SAF || SAF.fail) { g.innerHTML = safVuln(); return; }
  const out = [], badges = [], pts = [];
  if (OV.has("slide")) {
    // 예보(발령) — 이름 테두리(시군 경계 갈색 테두리는 호우특보 경계와 헷갈려 뺐다, 11-08). 예측(산림청) — 이름 오른쪽 산 그림. 예전 '산사태주의보(예측)' 글 딱지는 특보 딱지와 겹쳐 뺐다(11-08)
    const fc = safSlideOf(SAF.fcst), pr = safSlideOf(SAF.pred);
    for (const sig of new Set([...Object.keys(fc), ...Object.keys(pr)])) {
      const ft = FEAT.find(f => f.properties.sigun === sig);
      if (!ft) continue;
      const cx = V.toX(ft.properties.lx), cy = V.toY(ft.properties.ly), hw = sig.length * FSN * 0.52 + 4, hh = FSN * 0.74;   // 이름 글자 테두리(halo)보다 바깥
      if (fc[sig]) {
        badges.push(`<rect class="sfn l${fc[sig].lv}" x="${(cx - hw).toFixed(1)}" y="${(cy - hh).toFixed(1)}" width="${(hw * 2).toFixed(1)}" height="${(hh * 2).toFixed(1)}" rx="4"><title>산사태${fc[sig].kind} 발령(시장 · 군수) ${fc[sig].at || ""}</title></rect>`);
      }
      if (pr[sig]) {
        const s = FSN * 0.95 / 24, x = cx + hw + (fc[sig] ? 5 : 1), y = cy - FSN * 0.5;
        badges.push(`<g class="sfm l${pr[sig].lv}" transform="translate(${x.toFixed(1)},${y.toFixed(1)}) scale(${s.toFixed(3)})"><title>산림청 산사태 예측 — ${pr[sig].kind} ${pr[sig].at || ""}</title>`
          + `<rect x="0" y="2" width="24" height="20" rx="4"/><path d="M3 19 9.5 8l3.5 6 2-3 6 8z"/></g>`);
      }
    }
  }
  if (OV.has("reservoir")) {
    const r0 = Math.max(4.5, Math.min(9, V.u));
    for (const s of (SAF.res || []).slice().sort((a, b) => a.on - b.on || a.lv - b.lv)) {
      const [c, rr] = LCCF(s.lon, s.lat), x = V.toX(c), y = V.toY(rr), r = s.on ? r0 : r0 * 0.7;
      const dim = selOn() && s.sigun && !isSel(s.sigun) ? " dim" : "";
      pts.push(`<path class="sfr${s.on ? " on" : ""}${dim}" d="M${x.toFixed(1)},${(y - r).toFixed(1)}L${(x + r * 0.9).toFixed(1)},${(y + r * 0.65).toFixed(1)}L${(x - r * 0.9).toFixed(1)},${(y + r * 0.65).toFixed(1)}Z"`
        + (s.on ? ` style="fill:${SAF_C[s.lv] || SAF_C[0]}"` : "") + "/>");
      SAF_HIT.push({ x, y, rr: Math.max(r, 7), s });
    }
  }
  g.innerHTML = out.join("") + safVuln() + pts.join("") + badges.join("");
  drawHeat();                                  // 기온은 이름 밑 딱지들 다음 줄(05 nameStack)
}
/* 마우스 — 저수지 계측기가 먼저, 아니면 침수흔적 면 */
function safetyAt(mx, my) {
  if (!V || !(OV.has("reservoir") || OV.has("flood") || OV.has("slide") || vulnOn())) return null;
  let best = null, bd = Infinity;
  for (const h of SAF_HIT) {
    const dd = (h.x - mx) ** 2 + (h.y - my) ** 2;
    if (dd <= (h.rr * 1.5) ** 2 && dd < bd) { bd = dd; best = h.v ? { vuln: h.v } : { res: h.s }; }
  }
  if (best) return best;
  const f = OV.has("flood") && GL_OK ? GL.queryRenderedFeatures([mx, my], { layers: ["flood"] })[0] : null;
  return f ? { flood: SAF_FL[f.properties.i] } : null;
}
function safetyTip(h) {
  if (h.vuln) {
    const v = h.vuln;
    return `<b>산사태취약지역 · ${escH(v.ty)}</b><div class="d">${escH(v.sg)} ${escH(v.emd)} ${escH(v.ri)} ${escH(v.jb)}${v.a ? ` · 지정면적 ${v.a.toLocaleString()}㎡` : ""}</div>`
      + (v.sh ? `<div class="d">지정대피소 ${escH(v.sh)}</div>` : "")
      + `<div class="d">「산림재난방지법」 제22조로 지정 · 고시(산림부서 소관) — 인명피해 우려지역 지구와는 다른 명단이고, 판정 % · 알림은 없다</div>`
      + `<div class="d">경상남도 지정현황 2026-05-01(공공데이터포털) — 자리는 지번을 좌표로 바꾼 것이라 필지 가운데쯤이다</div>`;
  }
  if (h.res) {
    const s = h.res;
    return `<b>${escH(s.name)}</b> · ${s.on ? `<b style="color:${SAF_C[s.lv]}">${escH(s.lvn)} 발령 중</b>` : s.old ? `${escH(s.lvn)} 발령 기록 — 해제 없이 ${s.days}일 지남` : `${escH(s.lvn)} 해제`}`
      + `<div class="d">${s.sigun || ""} · 위험저수지 계측기 · ${escH(s.at)} 기준</div>${s.cn ? `<div class="d">${escH(s.cn)}</div>` : ""}`
      + `<div class="d">계측기 고장 등으로 잘못 잴 수 있다 — 해제 기록 없이 72시간 넘은 발령은 지금 발령으로 보지 않는다(산사태 예보와 같은 규칙)</div>`;
  }
  const f = h.flood, d = String(f.d || "").replace(/(\d{4})(\d\d)(\d\d)/g, "$1.$2.$3");
  return `<b>침수흔적 · ${escH(f.yr || "")}</b>${f.dep != null ? ` · 침수심 ${f.dep} m` : ""}<div class="d">${escH(f.nm || "")}</div>`
    + `<div class="d">${f.sigun || ""} · ${escH(d)}${f.cs ? ` · ${escH(f.cs)}` : ""}</div>`;
}
TIPS.set("slide-now", `재난안전데이터공유플랫폼(행정안전부) 자료 — 전국을 다 받아 경남만 남긴다(키마다 하루 1000건).<br>
  <b>산사태 예보</b>는 시장 · 군수가 낸 주의보 · 경보 기록 — 발령 뒤 해제가 없으면 '발령 중'(72시간까지). <b>예측</b>은 산림청 예측정보 — 분석 뒤 하루만 '지금'으로 본다(몇 시간 앞 예측인지는 받지 못한다).<br>
  서버는 <b>경남에 호우 · 태풍 특보가 있을 때만</b> 받는다(예보 10분 · 예측 30분). '늘 받기'를 누르면 특보가 없어도 받는다.`);
TIPS.set("reservoir-now", `재해위험 저수지 계측기(수위계 · 경사계) 경보 — 재난안전데이터공유플랫폼, 30분마다.<br>
  마지막 기록이 발령이면 세모를 단계 색(관심 · 주의 · 경계 · 심각 · 대피)으로, 해제면 회색으로. 계측기 고장으로 잘못 잴 수 있고 해제를 못 받은 발령도 남아 있다 — 시각을 같이 본다.`);
TIPS.set("flood-now", `2002년부터 실제 침수된 구역(행정안전부 침수흔적도) — 옅은 파랑 면. 7일마다 받는다. 면에 마우스를 올리면 해 · 재해 이름 · 침수심 · 원인.`);
function renderSafetyLegend() {
  for (const id of SAF_IDS) safLegend(id);
}
function safLegend(id) {
  const box = $(`ly-${id}`);
  if (!box) return;
  if (!OV.has(id)) { box.hidden = true; return; }
  box.hidden = LY_OPEN !== id;
  if (box.hidden) return;
  const dot = c => `<i class="dt" style="background:${c}"></i>`, SL = ["var(--ink-3)", "var(--lv-watch)", "var(--lv-warn)"];
  const row = (c, b, s, e) => `<div class="rr">${dot(c)}<b>${escH(b)}</b><span>${escH(s)}</span><em>${escH(e)}</em></div>`;
  const KEY = { slide: ["fcst", "pred"], reservoir: ["res"], flood: ["flood"] }[id];
  const TITLE = { slide: "산사태 예보 · 예측", reservoir: "위험저수지 계측기", flood: "침수흔적" }[id];
  let body;
  if (!SAF) body = `<div class="nt">읽는 중…</div>`;
  else if (SAF.fail) body = `<div class="nt w">불러오지 못했다 — ${escH(SAF.fail)}</div>`;
  else if (SAF.demo && !KEY.some(k => SAF.keys?.[k])) body = `<div class="nt w">시연 서버는 이 자료를 받지 않는다(이 시연에 가상 장면이 없다).</div>`;
  else if (!KEY.some(k => SAF.keys?.[k])) body = `<div class="nt w">키가 없다 — 설정 › 시스템 › API 키 › 재난안전데이터 · ${TITLE}.</div>`;
  else {
    const errs = KEY.filter(k => SAF.err?.[k]).map(k => `<div class="nt w">${escH(SAF.err[k])}</div>`).join("");
    if (id === "slide") {
      const sl = SAF.slide || {};
      const fc = (SAF.fcst || []).filter(r => selHas(r.sigun)), fcOn = fc.filter(r => r.on);
      const fcPast = fc.filter(r => !r.on).sort((a, b) => b.at.localeCompare(a.at)).slice(0, 3);
      const pr = (SAF.pred || []).filter(r => selHas(r.sigun)), prOn = pr.filter(r => r.on);
      const got = SAF.at?.fcst ? `마지막으로 받은 때 ${SAF.at.fcst.slice(5, 16).replace("T", " ")}` : "아직 받지 않았다";
      body = `<div class="nt">${sl.why ? `<b>받는 중</b> — ${escH(sl.why)}` : `<b>안 받는 중</b> — 경남에 호우 · 태풍 특보가 없다`} · ${got}</div>`
        + `<div class="seg sfm"><button data-sm="auto" class="${sl.mode !== "on" ? "on" : ""}">특보 때만</button><button data-sm="on" class="${sl.mode === "on" ? "on" : ""}">늘 받기</button></div>`
        + errs
        + `<div class="sec">산사태 예보 (시장 · 군수 발령)</div>`
        + (fcOn.length ? fcOn.map(r => row(SL[r.lv], r.sigun, `산사태${r.kind}`, `발령 ${r.at.slice(5)}`)).join("") : `<div class="nt">발령 중 없음</div>`)
        + fcPast.map(r => row("var(--ink-3)", r.sigun, `${r.kind} ${r.stts}`, r.at.slice(0, 10))).join("")
        + `<div class="sec">산사태 예측 (산림청)</div>`
        + (prOn.length ? prOn.map(r => row(SL[r.lv], r.sigun, r.kind, `분석 ${r.at.slice(5)}`)).join("")
          : `<div class="nt">지금 걸린 곳 없음${pr[0] ? ` · 경남 마지막 분석 ${pr[0].at.slice(0, 10)}(${escH(pr[0].sigun)})` : ""}</div>`);
    } else if (id === "reservoir") {
      const res = (SAF.res || []).filter(r => selHas(r.sigun)), on = res.filter(r => r.on);
      body = errs + `<div class="nt">경남 계측기 ${res.length}곳 · 발령 중 ${on.length}${SAF.at?.res ? ` · ${SAF.at.res.slice(11, 16)} 받음` : ""}</div>`
        + `<div class="keys2">${["관심", "주의", "경계", "심각", "대피"].map((n, i) => `<span>${dot(SAF_C[i + 1])}${n}</span>`).join("")}<span>${dot(SAF_C[0])}해제</span></div>`
        + (on.length ? `<div class="sec">발령 중</div>` + on.slice(0, 10).map(s => row(SAF_C[s.lv], s.name, s.lvn, `${s.sigun || ""} ${s.at.slice(2, 10)}`)).join("") : `<div class="nt">발령 중 없음</div>`);
    } else {
      const fl = SAF_FL || [], yrs = fl.map(f => +f.yr).filter(Boolean);
      body = errs + `<div class="nt">${fl.length ? `${dot("var(--sf-flood)")}과거 침수 구역 ${fl.length}곳 · ${Math.min(...yrs)}~${Math.max(...yrs)}년${SAF.at?.flood ? ` · ${SAF.at.flood.slice(0, 10)} 받음` : ""}`
        : SAF.flood ? "읽는 중…" : "아직 받지 않았다(키를 넣으면 첫 수집에 몇 분)"}</div>`
        + (fl.length ? `<div class="seg sfm"><button data-fd="0" class="${SAF_DEP ? "" : "on"}">한 색</button><button data-fd="1" class="${SAF_DEP ? "on" : ""}">깊이 색</button></div>`
          + (SAF_DEP ? `<div class="keys2">${FL_DEP.map(([, c, n]) => `<span>${dot(c)}${n}</span>`).join("")}<span>${dot("#9AA3B2")}모름</span></div>`
            + `<div class="nt">침수심 = 그때 실제로 잠긴 깊이(침수흔적도). 같은 곳이 여러 해 겹치면 깊은 것이 위로 보이지 않을 수 있다.</div>` : "") : "");
    }
  }
  box.innerHTML = `<div class="hd2" title="눌러서 닫기"><b>${TITLE}</b><i class="inf" data-tip="${id}-now">i</i></div>` + body;
  box.querySelector(".hd2").onclick = ev => { if (!ev.target.closest(".inf")) setLyOpen(null); };
  for (const b of box.querySelectorAll("[data-fd]")) b.onclick = () => {
    SAF_DEP = b.dataset.fd === "1";
    try { localStorage.setItem("gn-flood-dep", SAF_DEP ? "1" : "0"); } catch {}
    drawSafety(); safLegend("flood");
  };
  for (const b of box.querySelectorAll("[data-sm]")) b.onclick = async () => {
    b.disabled = true;
    try {
      const r = await fetch("/api/settings/slide", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ mode: b.dataset.sm }) });
      const j = await r.json();
      if (!r.ok) throw new Error(j.detail || r.status);
      SAF = j;
    } catch (e) { SAF = { ...SAF, err: { ...(SAF?.err || {}), fcst: `바꾸지 못했다 — ${e.message}` } }; }
    drawSafety(); renderSafetyLegend(); renderLyIcons();
  };
}

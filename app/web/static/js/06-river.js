"use strict";
/* ── 하천 · 댐 · 보 — 한강홍수통제소(HRFCO) 자료, 레이어 '하천 · 댐'(D) ────────────────────────────────
   서버가 10분마다 받아 둔 것(/api/river)을 그린다. 경남 수위 관측소는 눈금 막대(물이 찬 만큼 · 단계 색), 댐은 둑, 보는 가로 막대.
   점선 둘레 = 경남으로 흘러드는 낙동강 위쪽(경북 · 대구) 댐 · 보. 값은 T/M 원시값(보정 전) — 공식 판단은 홍수통제소 발표로. */
let RIV = null, RIV_T = 0, RIV_R = 8, RIV_HIT = [];
const RV_C = ["var(--rv-0)", "var(--rv-1)", "var(--rv-2)", "var(--rv-3)", "var(--rv-4)"];
const RV_N = ["정상", "관심", "주의보", "경보", "심각"];
async function loadRiver() {
  clearTimeout(RIV_T);
  if (!OV.has("river") || CASE) { RIV = null; drawRiver(); renderRiverLegend(); renderLyIcons(); return; }
  try { RIV = await getJson("/api/river"); } catch (e) { RIV = { err: e.message }; }
  drawRiver(); renderRiverLegend(); renderLyIcons();
  RIV_T = setTimeout(loadRiver, 5 * 60 * 1000);
}
const rvTop = s => (s.thr || []).filter(Boolean).pop() || null;         // 가장 높은 기준 수위(눈금 막대의 꼭대기)
const rvHm = t => (t ? `${t.slice(8, 10)}:${t.slice(10, 12)}` : "—");
const rvDt = t => (t ? `${+t.slice(6, 8)}일 ${rvHm(t)}` : "—");           // 홍수예보는 하루를 넘겨 이어진다
const rvHi = s => Math.max(s.stage ?? -1, s.fc?.lv ?? -1);               // 지금 수위 · 홍수예보 중 높은 단계
const rvMax = () => Math.max(-1, ...(RIV?.rows || []).filter(s => s.kind === "wl").map(s => s.stage ?? -1));
function drawRiver() {
  drawTide();
  const g = $("rivr");
  if (!g) return;
  RIV_HIT = [];
  if (!OV.has("river") || !V || !V.s || !RIV || !RIV.rows) { g.innerHTML = ""; return; }
  const r = RIV_R = Math.max(5.5, Math.min(11, V.u * 1.2));
  const fs = Math.max(10, Math.min(15, V.u * 2.5));
  const marks = [], boxes = [], labs = [];
  const rows = RIV.rows.filter(s => s.x != null).sort((a, b) => rvHi(a) - rvHi(b) || (a.kind === "wl" ? -1 : 1));
  for (const s of rows) {
    const x = V.toX(s.x), y = V.toY(s.y), st = s.stage ?? -1;
    const dim = selOn() && s.sigun && !isSel(s.sigun) ? " dim" : "";
    let rr = r;
    if (s.kind === "wl") {
      const top = rvTop(s), w = r * 0.6 * (st < 0 ? 0.8 : 1), h = r * 1.15 * (st < 0 ? 0.8 : 1);
      const f = top && s.v > 0 ? Math.max(0.08, Math.min(1, s.v / top)) : 0;
      const col = st >= 0 ? RV_C[st] : "var(--ink-3)";
      const a = h + r * 0.45;                                    // 네모 = 홍수예보 발령 단계, 막대 = 지금 수위 — '지금은 정상, 예보는 주의보'를 한 점에서 가른다
      if (s.fc) marks.push(`<rect class="rvf${dim}" x="${(x - a).toFixed(1)}" y="${(y - a).toFixed(1)}" width="${(2 * a).toFixed(1)}" height="${(2 * a).toFixed(1)}" rx="2" style="stroke:${RV_C[s.fc.lv]}"/>`);
      if (st >= 2) marks.push(`<circle class="rvp" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(r * 0.95).toFixed(1)}" style="stroke:${col}"/>`);
      marks.push(`<g class="rv${st < 0 ? " nt" : ""}${dim}"><rect class="bx" x="${(x - w).toFixed(1)}" y="${(y - h).toFixed(1)}" width="${(2 * w).toFixed(1)}" height="${(2 * h).toFixed(1)}" rx="${(w * 0.45).toFixed(1)}"/>`
        + (f ? `<rect class="fl" x="${(x - w).toFixed(1)}" y="${(y + h - 2 * h * f).toFixed(1)}" width="${(2 * w).toFixed(1)}" height="${(2 * h * f).toFixed(1)}" rx="${(w * 0.45).toFixed(1)}" style="fill:${col}"/>` : "")
        + `</g>`);
      rr = s.fc ? a : h;
      if (s.v != null && rvHi(s) >= 1) labs.push({ s, x, y, pr: 10 + rvHi(s), t: `${s.name.replace(/^[가-힣]+[군시]\(/, "").replace(")", "")} ${s.v.toFixed(2)}m` });
    } else if (s.kind === "dam") {
      const w = r * 1.25, h = r * 0.95, hot = s.rise, col = hot ? "var(--rv-2)" : "var(--rv-dam)";
      if (hot) marks.push(`<circle class="rvp" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${(r * 1.1).toFixed(1)}" style="stroke:var(--rv-2)"/>`);
      marks.push(`<g class="rv dam${s.up ? " up" : ""}${dim}"><path class="bx" d="M${(x - w).toFixed(1)},${(y + h).toFixed(1)}L${(x - w * 0.55).toFixed(1)},${(y - h).toFixed(1)}L${(x + w * 0.55).toFixed(1)},${(y - h).toFixed(1)}L${(x + w).toFixed(1)},${(y + h).toFixed(1)}Z" style="fill:${col}"/>`
        + `<path class="wv" d="M${(x - w * 0.5).toFixed(1)},${y.toFixed(1)}q${(w * 0.25).toFixed(1)},${(-h * 0.5).toFixed(1)} ${(w * 0.5).toFixed(1)},0t${(w * 0.5).toFixed(1)},0"/></g>`);
      rr = w;
      labs.push({ s, x, y, pr: s.rise ? 20 : s.up ? 3 : 8, t: `${s.name}${s.out != null && s.out >= 1 ? ` 방류 ${Math.round(s.out)}` : ""}` });
    } else {                                                   // 보 — 가로 막대
      const w = r * 1.2, h = r * 0.42;
      marks.push(`<g class="rv bo${s.up ? " up" : ""}${dim}"><rect class="bx" x="${(x - w).toFixed(1)}" y="${(y - h).toFixed(1)}" width="${(2 * w).toFixed(1)}" height="${(2 * h).toFixed(1)}" rx="${(h * 0.5).toFixed(1)}" style="fill:var(--rv-dam)"/>`
        + `<path class="wv" d="M${(x - w * 0.9).toFixed(1)},${(y + h * 2).toFixed(1)}h${(w * 1.8).toFixed(1)}"/></g>`);
      rr = w;
      labs.push({ s, x, y, pr: 2, t: s.name });
    }
    RIV_HIT.push({ x, y, rr: Math.max(rr, 7), s });
    boxes.push({ x0: x - rr, x1: x + rr, y0: y - rr, y1: y + rr });
  }
  // 이름 — 센 곳부터 빈자리에만(다른 점 · 시군 이름 · 앞 글자와 겹치지 않게). 많으면 열여섯까지
  const placed = LABELBOX.concat(boxes), txt = [];
  const hit = b => placed.some(p => b.x0 < p.x1 && b.x1 > p.x0 && b.y0 < p.y1 && b.y1 > p.y0);
  for (const l of labs.sort((a, b) => b.pr - a.pr).slice(0, 16)) {
    const w = l.t.length * fs * 0.95 + 4, h = fs * 1.25, gap = RIV_R + 3;
    for (const [dx, dy] of [[gap, -h / 2], [-gap - w, -h / 2], [-w / 2, gap], [-w / 2, -gap - h]]) {
      const b = { x0: l.x + dx, y0: l.y + dy, x1: l.x + dx + w, y1: l.y + dy + h };
      if (b.x0 < 4 || b.y0 < 4 || b.x1 > V.W - 4 || b.y1 > V.H - 4 || hit(b)) continue;
      placed.push(b);
      txt.push(`<text x="${(b.x0 + 2).toFixed(1)}" y="${(b.y0 + h / 2).toFixed(1)}" style="font-size:${fs.toFixed(1)}px;stroke-width:${(fs * 0.2).toFixed(1)}px">${escH(l.t)}</text>`);
      break;
    }
  }
  g.innerHTML = marks.join("") + `<g class="rvl">${txt.join("")}</g>`;
}
function riverAt(mx, my) {
  if (!OV.has("river") || !V || !RIV_HIT.length) return null;
  let best = null, bd = Infinity;
  for (const h of RIV_HIT) {
    const dx = h.x - mx, dy = h.y - my, dd = dx * dx + dy * dy, lim = (h.rr * 1.5) ** 2;
    if (dd <= lim && dd < bd) { bd = dd; best = h.s; }
  }
  return best;
}
/* 작은 꺾은선 — 최근 값(10분 간격, 최대 6시간). 세 점 이상일 때만 */
function rvSpark(h, col) {
  if (!h || h.length < 3) return "";
  const lo = Math.min(...h), hi = Math.max(...h), sp = hi - lo || 1, W = 124, H = 26;
  const pts = h.map((v, i) => `${(i / (h.length - 1) * W).toFixed(1)},${(H - 2 - (v - lo) / sp * (H - 4)).toFixed(1)}`).join(" ");
  return `<svg class="spk" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}"><polyline points="${pts}" style="stroke:${col}"/></svg>`;
}
function rvTrend(d, unit, eps) {
  if (d == null) return "";
  if (Math.abs(d) < eps) return ` · 1시간 변화 없음`;
  return ` · 1시간 ${d > 0 ? "▲ +" : "▼ "}${d}${unit}`;
}
/* 단계 띠 — 제원의 기준 수위로 칸을 나누고 지금 수위를 ▼ 로. 몇 칸 남았는지가 글자보다 빨리 읽힌다 */
function rvBar(s) {
  const top = rvTop(s);
  if (!top || s.v == null) return "";
  const max = Math.max(top * 1.04, s.v), pc = v => (Math.max(0, v) / max * 100).toFixed(1);
  const cuts = (s.thr || []).map((t, i) => [t, i]).filter(x => x[0]);
  let last = -99;                                                        // shortcut: 기준 값이 8% 안에 붙으면 앞 글자를 뺀다, 툴팁이 넓어지면 다 적는다
  const labs = cuts.filter(([t]) => { const ok = t / max * 100 - last >= 8; if (ok) last = t / max * 100; return ok; });
  const segs = [[0, 0], ...cuts.map(([t, i]) => [t, i + 1])].map(([a, c], i, all) =>
    `<i style="flex:${(all[i + 1]?.[0] ?? max) - a};background:${RV_C[c]}"></i>`).join("");
  return `<div class="rvb"><u style="left:${pc(s.v)}%"></u><div class="b">${segs}</div>${labs.map(([t]) => `<span style="left:${pc(t)}%">${t}</span>`).join("")}</div>`;
}
function riverTip(s) {
  const old = s.stale ? " · ⚠ 오래된 값" : "", at = `${rvHm(s.t)} 기준${old}`;
  if (s.kind === "wl") {
    const st = s.stage ?? -1, nm = st < 0 ? "기준 수위 없음" : RV_N[st];
    const thr = (s.thr || []).some(Boolean);
    const nx = st >= 0 && s.next ? ` · ${RV_N[Math.min(4, st + 1)]}수위까지 ${s.gap} m` : "";
    const fc = s.fc ? `<div class="d"><i class="rvk" style="border-color:${RV_C[s.fc.lv]}"></i><b>${escH(s.fc.kind)}</b> · 발표 ${rvDt(s.fc.at)} · 수위 도달 예상 ${rvDt(s.fc.eta)}${s.fc.area && s.fc.area !== "-" ? ` · ${escH(s.fc.area)}` : ""}</div>` : "";
    return `<b>${escH(s.name)} ${s.v == null ? "값 없음" : s.v.toFixed(2) + " m"}</b> · ${nm}${nx}`
      + rvBar(s) + fc
      + `<div class="d">${thr ? "" : "홍수통제소 제원에 기준 수위가 없는 지점 · "}${s.q != null ? `유량 ${s.q} ㎥/s` : ""}${rvTrend(s.d1h, " m", 0.02)}</div>`
      + `<div class="d">${s.sigun ? s.sigun + " · " : ""}${escH(s.agency)} · ${at}</div>${rvSpark(s.hist, st >= 0 ? RV_C[st] : "var(--ink-3)")}`;
  }
  const lim = s.lim != null && s.v != null ? ` (${s.kind === "dam" ? "홍수기 제한수위" : "관리수위"} ${s.lim} − ${(s.lim - s.v).toFixed(1)} m)` : "";
  const out = s.out == null ? "방류 값 없음" : `방류 ${s.out} ㎥/s`;
  const kind = s.kind === "dam" ? "댐" : "보";
  return `<b>${escH(s.name)} ${out}</b>${s.rise ? " · ▲ 방류 늘어나는 중" : ""}`
    + `<div class="d">${kind} 수위 EL ${s.v ?? "—"} m${lim}</div>`
    + `<div class="d">유입 ${s.inf ?? "—"} ㎥/s${s.owl != null ? ` · 하류수위 ${s.owl} m` : ""}${rvTrend(s.d1h, " ㎥/s", 1)}</div>`
    + `<div class="d">${s.up ? "낙동강 위쪽 — 경남으로 흘러든다" : s.sigun || ""} · ${escH(s.agency)} · ${at}</div>${rvSpark(s.hist, "var(--rv-dam)")}`;
}
function renderRiverLegend() {
  const box = $("ly-river");
  if (!box) return;
  if (!OV.has("river")) { box.hidden = true; return; }
  box.hidden = LY_OPEN !== "river";
  if (box.hidden) return;
  const dot = c => `<i class="dt" style="background:${c}"></i>`;
  let body;
  if (!RIV) body = `<div class="nt">읽는 중…</div>`;
  else if (RIV.err) body = `<div class="nt w">불러오지 못했다 — ${escH(RIV.err)}</div>`;
  else if (!RIV.on) body = `<div class="nt w">${RIV.demo ? "시연 서버는 하천 자료를 받지 않는다." : "키가 없다 — 설정 › 시스템 › API 키 › 홍수통제소(HRFCO)."}</div>`;
  else if (!RIV.rows?.length) body = `<div class="nt">${RIV.at ? "받은 지점이 없다." : "첫 수집을 기다린다(켠 뒤 1분 안)."}</div>`;
  else {
    const wl = RIV.rows.filter(s => s.kind === "wl"), cnt = [0, 0, 0, 0, 0];
    wl.forEach(s => { if ((s.stage ?? -1) >= 0) cnt[s.stage]++; });
    const nthr = wl.filter(s => (s.stage ?? -1) < 0).length;
    const chips = RV_N.map((n, i) => `<span>${dot(RV_C[i])}${n} ${cnt[i]}</span>`).join("");
    const hi = wl.filter(s => (s.stage ?? -1) >= 1).sort((a, b) => b.stage - a.stage || (a.gap ?? 9) - (b.gap ?? 9));
    const near = wl.filter(s => (s.stage ?? -1) === 0 && s.gap != null).sort((a, b) => a.gap - b.gap).slice(0, 3);
    const rowW = (s, c) => `<div class="rr">${dot(c)}<b>${escH(s.name)}</b><span>${s.v.toFixed(2)} m</span><em>${s.gap != null ? `${RV_N[Math.min(4, s.stage + 1)]}까지 ${s.gap} m` : RV_N[s.stage]}</em></div>`;
    const wlHtml = hi.length ? hi.slice(0, 6).map(s => rowW(s, RV_C[s.stage])).join("")
      : `<div class="nt">관심 수위 이상 없음 — 가장 가까운 곳</div>` + near.map(s => rowW(s, RV_C[0])).join("");
    const rel = RIV.rows.filter(s => s.kind !== "wl" && s.out != null).sort((a, b) => b.out - a.out).slice(0, 6);
    const relHtml = rel.map(s => `<div class="rr">${dot(s.rise ? "var(--rv-2)" : "var(--rv-dam)")}<b>${escH(s.name)}</b><span>${s.out} ㎥/s</span><em>${s.rise ? "▲ 늘어남 · " : ""}유입 ${s.inf ?? "—"}${s.up ? " · 위쪽" : ""}</em></div>`).join("");
    const act = wl.filter(s => s.fc).sort((a, b) => b.fc.lv - a.fc.lv);
    const oth = (RIV.fld || []).filter(f => !act.some(s => s.name === f.obs));   // 경남 밖 낙동강 · 지나간 해제
    const fl = act.length + oth.length ? act.map(s => `<div class="rr">${dot(RV_C[s.fc.lv])}<b>${escH(s.name)}</b><span>${escH(s.fc.kind)}</span><em>발표 ${rvDt(s.fc.at)}</em></div>`)
      .concat(oth.map(f => `<div class="rr">${dot("var(--ink-3)")}<b>${escH(f.obs || "")}</b><span>${escH(f.kind || "")}</span><em>${escH(f.river || "")} ${rvDt(f.at)}</em></div>`)).slice(0, 6).join("")
      : `<div class="nt">발령 없음(최근 24시간${RIV.nfld ? ` · 전국 ${RIV.nfld}건 중 경남 영향 없음` : ""})</div>`;
    body = `<div class="keys2">${chips}</div><div class="nt">막대 색 = 지금 수위 · <i class="rvk"></i>네모 = 홍수예보 발령</div>${nthr ? `<div class="nt">기준 수위 없는 지점 ${nthr}곳은 값만(흐린 막대)</div>` : ""}`
      + `<div class="sec">수위 높은 곳</div>${wlHtml}<div class="sec">댐 · 보 방류</div>${relHtml || `<div class="nt">값 없음</div>`}<div class="sec">홍수예보 발령</div>${fl}`;
  }
  TIPS.set("river-now", `한강홍수통제소(HRFCO) 자료 — 전국 4대강 홍수통제소 원시값(보정 전)이라 확정치와 다를 수 있다. 공식 판단은 홍수통제소 발표로.<br>
    <b>수위</b> 관측소 막대는 꼭대기가 제원의 가장 높은 기준 수위, 차오른 만큼이 지금 수위. 색은 단계(정상 · 관심 · 주의보 · 경보 · 심각), 주의보부터는 번쩍인다.
    기준 수위가 제원에 없는 지점은 흐리게 값만.<br>
    <b>네모 테두리</b>는 홍수통제소가 그 지점에 낸 홍수예보(색은 주의보 · 경보) — 막대는 지금 수위, 네모는 앞으로의 예보다. 발령이 있는 지점에만, 해제될 때까지 나온다(해제를 못 받아도 발표 뒤 4일이면 지운다).<br>
    <b>댐 · 보</b>는 방류량(총방류)이 1시간 전보다 10 ㎥/s 이상 · 20% 이상 늘면 주황으로 번쩍인다. 방류가 얼마면 위험인지는 위키에 숫자가 없어 단계를 만들지 않았다 — 하류 시군은 댐 방류 협의 · 사전예고(위키 위험예보)를 따른다.<br>
    점선 둘레 = 경남으로 흘러드는 낙동강 위쪽(경북 · 대구) 댐 · 보. 낙동강권역 자료는 11분 넘게 늦게 들어온다(지점마다 마지막 시각이 다르다). 10분마다 갱신.`);
  const t = RIV?.at ? RIV.at.slice(11, 16) : "";
  box.innerHTML = `<div class="hd2" title="눌러서 닫기"><b>하천 · 댐</b><span class="k">${RIV?.rows?.length ? `${RIV.rows.length}곳` : ""}</span><i class="inf" data-tip="river-now">i</i><span>${t}</span></div>` + body;
  box.querySelector(".hd2").onclick = ev => { if (!ev.target.closest(".inf")) setLyOpen(null); };
}


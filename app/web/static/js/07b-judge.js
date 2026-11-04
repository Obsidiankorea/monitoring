"use strict";
/* ── 상황판단 모드(X) — 시군 하나의 판단 자료만 한 화면에: 기준이 얼마나 찼나 · 몇 시에 닿나 · 지금 무엇을 결정할까 ──────────
   전략 시뮬레이션의 지휘판처럼 — 읍면동 카드(통제 · 사전대피 · 긴급대피, 결정 단추) + 오른쪽 ① 단계 조정 ② 만약에(예보 배수) ③ 판단 기록 ④ 물어보기.
   도달 시각은 초단기 6시간 + 단기예보(내일 24시까지)로 본다(/api/ai/situation). 결정 단추는 기록만 남긴다(문자 · 보고를 보내지 않는다). */
const SJ = { open: false, sg: null, k: 1, s: null, alt: null, log: [], st: null, seq: 0, more: false, q: [], llm: null };
const SJ_ACT = { 통제: "통제 지시", 사전대피: "사전대피 권고", 긴급대피: "대피명령 요청" };
const SJ_FAM = ["산사태", "하천", "지하공간"];
const sjEta = l => (l ? `${l}시` : "");
function sjBest(cs, stg) {
  const o = { met: 3, near: 2, no: 1, unknown: 0 };
  return (cs || []).filter(c => c.stage === stg).reduce((a, c) => (!a || o[c.st] > o[a.st] || (o[c.st] === o[a.st] && (c.gap?.pct ?? -1) > (a.gap?.pct ?? -1)) ? c : a), null);
}
function sjToggle(on = !SJ.open) {
  SJ.open = on;
  $("sj").hidden = !on;
  $("b-sj").classList.toggle("on", on);
  if (!on) return;
  if (!$("sj-sg").options.length) $("sj-sg").innerHTML = ORDER_GN().map(s => `<option>${s}</option>`).join("");
  SJ.sg = SELS[0] || SJ.sg || "창원";
  $("sj-sg").value = SJ.sg;
  sjLoad();
}
async function sjLoad(onlyAlt) {
  const my = ++SJ.seq, sg = SJ.sg, q = k => getJson(`/api/ai/situation?sigun=${encodeURIComponent(sg)}&k=${k}`);
  if (!onlyAlt) {
    $("sj-bd").innerHTML = `<div class="sj-ld">${escH(sg)} 판단 자료를 모으는 중… (읍면동 · 우려지역 · 기준 대조 · 단기예보)</div>`;
    try {
      const [s, st, lg, rp] = await Promise.all([q(1), getJson("/api/ai/sigunstage"), getJson(`/api/ai/decisions?sigun=${encodeURIComponent(sg)}`),
        getJson(`/api/ai/report?sigun=${encodeURIComponent(sg)}`).catch(() => null)]);
      if (my !== SJ.seq) return;
      Object.assign(SJ, { s, st, log: lg.rows, q: rp?.questions || [], llm: rp?.llm ?? null });
    } catch (e) { if (my === SJ.seq) $("sj-bd").innerHTML = `<div class="sj-ld">못 모았다 — ${escH(e.message)}</div>`; return; }
  }
  SJ.alt = null;
  if (SJ.k !== 1) { try { const a = await q(SJ.k); if (my !== SJ.seq) return; SJ.alt = a; } catch { SJ.alt = null; } }
  sjRender();
}
function sjLast(emd, fam, stg) {
  return SJ.log.find(d => d.emd === emd && d.fam === fam && d.stage === stg);
}
function sjCell(r, fam, stg, alt) {
  const c = sjBest(r.ladders[fam], stg);
  if (!c) return `<div class="sj-c empty">—</div>`;
  const g = c.gap || {}, met = c.st === "met", pct = met ? (g.pct || 100) : g.pct;
  const c2 = alt ? sjBest(alt.ladders?.[fam], stg) : null, e1 = g.eta?.at, e2 = c2?.gap?.eta?.at;
  const eta = met ? `<div class="eta ok">기준 닿음</div>`
    : c.st === "unknown" ? `<div class="eta dim">자료 없음 — 모름</div>`
    : e1 ? `<div class="eta">▶ ${sjEta(e1)} 도달${alt && e2 !== e1 ? ` · 만약에 <b>${e2 ? sjEta(e2) : "안 닿음"}</b>` : ""}</div>`
    : alt && e2 ? `<div class="eta new">만약에 <b>${sjEta(e2)}</b> 도달</div>` : `<div class="eta dim">내일 24시까지 안 닿음</div>`;
  const last = sjLast(r.emd, fam, stg);
  const parts = (g.parts || []).map(p => `${p.label} ${p.now ?? "—"}/${p.need}${p.unit}`).join(" + ");
  return `<div class="sj-c ${met ? "met" : c.st === "near" ? "near" : c.st === "unknown" ? "unk" : ""}" title="${escH(c.rule)}${parts ? " — " + escH(parts) : ""}">
    <div class="top"><b>${stg}</b><span class="pct">${c.st === "unknown" ? "모름" : `${pct ?? 0}%`}</span></div>
    <div class="bar"><i style="width:${Math.min(100, pct || 0)}%"></i></div>${eta}
    <div class="acts"><button data-a="${SJ_ACT[stg]}" data-e="${escH(r.emd)}" data-f="${fam}" data-s="${stg}" data-p="${pct ?? ""}" data-t="${e1 || ""}" class="${met ? "hot" : ""}">${SJ_ACT[stg]}</button>
    <button class="g" data-a="보류" data-e="${escH(r.emd)}" data-f="${fam}" data-s="${stg}" data-p="${pct ?? ""}" data-t="${e1 || ""}">보류</button></div>
    ${last ? `<div class="dec">✔ ${escH(last.act)} ${last.at.slice(11, 16)}</div>` : ""}</div>`;
}
function sjRender() {
  const s = SJ.s;
  if (!s) return;
  const altBy = Object.fromEntries((SJ.alt?.emd || []).map(r => [r.emd, r]));
  const rows = s.emd.filter(r => Object.keys(r.ladders).length);
  const show = SJ.more ? rows : rows.slice(0, 8);
  const cards = show.map(r => {
    const rn = r.rain, alt = altBy[r.emd];
    const fams = SJ_FAM.filter(f => r.ladders[f]).map(f => `<div class="fam"><div class="fn">${f}<em>우려 ${r.risk[f] || 0}곳</em></div>${["통제", "사전대피", "긴급대피"].map(stg => sjCell(r, f, stg, alt)).join("")}</div>`).join("");
    const later = r.later ? ` · 그 뒤 오늘 ${r.later.today}㎜ · 내일 ${r.later.tomorrow}㎜` : "";
    const tag = r.hot === 3 ? `<span class="tag t3">기준 닿음</span>` : r.hot === 2 ? `<span class="tag t2">근접</span>` : "";
    return `<section class="sj-e" id="sje-${escH(r.emd)}"><header><b>${escH(r.emd)}</b>${tag}
      <span>1시간 ${rn["1h"] ?? "—"} · 3시간 ${rn["3h"] ?? "—"} · 24시간 ${rn["24h"] ?? "—"}㎜${r.m15 != null ? ` · 15분 ${r.m15}㎜` : ""}</span>
      <span class="fc">${r.fc6h != null ? `앞으로 6시간 ${r.fc6h}㎜ (최대 ${r.fc_peak}㎜/h)` : "예보 칸 없음"}${later}</span></header>${fams}</section>`;
  }).join("") + (rows.length > 8 ? `<button class="sj-more" id="sj-more">${SJ.more ? "접기" : `나머지 ${rows.length - 8}곳 더 보기`}</button>` : "");
  const met = s.emd.filter(r => r.hot === 3).length, near = s.emd.filter(r => r.hot === 2).length;
  const do_ = SJ.st?.do, order = SJ.st?.do_order || [];
  const rv = (s.flood || []).slice().sort((a, b) => b.stage - a.stage)[0];
  const RVN = ["정상", "관심", "주의보", "경보", "심각"];
  const fc6 = Math.max(0, ...s.emd.map(r => r.fc6h || 0)), lt = s.emd.map(r => r.later).filter(Boolean);
  $("sj-hud").innerHTML = [["특보", s.alerts.join(" · ") || "없음", s.alerts.length ? "r" : ""], ["도 비상단계", do_?.stage || "상시대비", "o"],
    ["기준 닿은 읍면동", `${met} / ${s.emd.length}`, met ? "r" : ""], ["근접(70%↑)", near, near ? "o" : ""],
    ...(rv ? [[rv.name.replace(/^[가-힣]+[시군]\(|\)$/g, ""), `${rv.v?.toFixed(2)}m ${RVN[rv.stage] || ""}`, rv.stage >= 3 ? "r" : rv.stage >= 2 ? "o" : ""]] : []),
    ["앞으로 6시간 최대", `${fc6}㎜`, "c"], ...(lt.length ? [["오늘 · 내일 더(단기)", `${Math.max(...lt.map(x => x.today))} · ${Math.max(...lt.map(x => x.tomorrow))}㎜`, "c"]] : [])]
    .map(([k, v, c]) => `<div class="res ${c}"><em>${escH(k)}</em><b>${escH(String(v))}</b></div>`).join("")
    + `<div class="clk"><b>${s.tm ? `${s.tm.slice(8, 10)}:${s.tm.slice(10, 12)}` : ""}</b><span>${s.tm ? `${+s.tm.slice(4, 6)}.${+s.tm.slice(6, 8)}. 실황` : ""}${window.GN_SNAP?.fake ? " · 가상" : ""}</span></div>`;
  $("sj-bd").innerHTML = `<div class="sj-main"><div class="sj-hint">읍면동마다 — 기준이 얼마나 찼나 · 몇 시에 닿나(초단기 6시간 + 단기예보, 내일 24시까지) · <b>지금 무엇을 결정할까</b>. 단추는 판단 기록에만 남긴다.</div>${cards || `<div class="sj-ld">우려지역이 있는 읍면동이 없다</div>`}</div>
  <aside class="sj-side">
    <div class="box"><h4>① 단계 조정 — 도 비상단계</h4><div class="seg" id="sj-stg">${order.map(x => `<button data-st="${x}" class="${x === do_?.stage ? "on" : ""}">${x}</button>`).join("")}</div>
      <div class="hint">특보 기준이면 '${escH(do_?.auto || "")}'${do_?.set ? ` · 사람이 바꿈 ${escH((do_.set_at || "").slice(11, 16))} — <a href="#" id="sj-stg0">특보 기준으로</a>` : ""}. 24시간 뒤 특보 기준으로 돌아간다.</div></div>
    <div class="box"><h4>② 만약에 — 예보보다 비가 더(덜) 오면</h4>
      <div class="knob"><span>예보 시우량</span><input type="range" id="sj-k" min="50" max="200" step="10" value="${Math.round(SJ.k * 100)}"><b id="sj-kv">×${SJ.k.toFixed(1)}</b></div>
      <div class="hint">초단기 · 단기예보 시우량에 곱해 도달 시각을 다시 계산한다(대시보드 판정 코드). 카드의 '만약에' 글자가 바뀐 시각이다.</div>${sjMoved()}</div>
    <div class="box log"><h4>③ 판단 기록 — 누른 결정 · 그때 수치</h4>${SJ.log.length ? SJ.log.slice(0, 14).map(d => `<div><time>${d.at.slice(5, 16).replace("T", " ")}</time>
      <span class="${d.act === "보류" ? "h" : "d"}">${escH(d.act)}</span> ${escH(d.emd || "")} ${escH(d.fam || "")} ${escH(d.stage || "")}${d.pct != null ? ` · ${d.pct}%` : ""}${d.eta ? ` · ${escH(sjEta(d.eta))} 예상` : ""}${d.note ? ` — ${escH(d.note)}` : ""}<i data-del="${d.id}" title="지우기">✕</i></div>`).join("")
      : `<div class="hint">아직 없다 — 카드의 단추를 누르면 시각 · 도달률 · 예상 시각과 함께 남는다(서버에 — 다른 PC 에서도 보인다).</div>`}
      <form id="sj-note"><input maxlength="300" placeholder="메모 남기기 — 예: 진동면 이장 통화, 대피소 개방 확인"><button>남기기</button></form></div>
    <div class="box chat"><h4>④ 물어보기 — 지금 수치 · 위키 · 판단 기록을 보고</h4>
      <div class="chips">${SJ.q.map(q => `<button data-q="${q.id}">${escH(q.label)}</button>`).join("")}</div>
      <div class="hint">단추는 규칙이라 바로 답한다 · 아래 칸은 AI(${SJ.llm ? `설정 › AI 답변: ${escH({ "claude-cli": "Claude", local: "로컬", openai: "기타" }[SJ.llm] || SJ.llm)}` : "꺼짐 — 설정 › AI 답변에서 켠다"})</div>
      <div id="sj-msgs"></div><form id="sj-ask"><input maxlength="300" placeholder="더 물어보기 — 예: 보류한 진동면 긴급대피, 비가 30% 더 오면 언제 닿나?"><button>묻기</button></form></div>
  </aside>`;
}
/* 만약에로 앞당겨지거나 늦춰진 도달 — 가까운 것부터 */
function sjMoved() {
  if (!SJ.alt) return "";
  const by = Object.fromEntries(SJ.alt.emd.map(r => [r.emd, r])), out = [];
  for (const r of SJ.s.emd) for (const f of SJ_FAM) for (const stg of ["통제", "사전대피", "긴급대피"]) {
    const a = sjBest(r.ladders[f], stg), b = sjBest(by[r.emd]?.ladders?.[f], stg);
    if (!a || !b || a.st === "met") continue;
    const e1 = a.gap?.eta?.at || null, e2 = b.st === "met" ? "지금" : b.gap?.eta?.at || null;
    if (e1 !== e2 && (e1 || e2)) out.push({ r: r.emd, f, stg, e1, e2, i: b.st === "met" ? -1 : b.gap?.eta?.i ?? 99 });
  }
  out.sort((x, y) => x.i - y.i);
  return out.length ? out.slice(0, 10).map(x => `<div class="mv"><b>${escH(x.r)}</b>&nbsp;${x.f} ${x.stg}<span>${x.e1 ? sjEta(x.e1) : "안 닿음"} → <b>${x.e2 === "지금" ? "지금 닿음" : x.e2 ? sjEta(x.e2) : "안 닿음"}</b></span></div>`).join("")
    : `<div class="hint">바뀌는 도달 시각 없음</div>`;
}
async function sjDecide(body) {
  try {
    const r = await fetch("/api/ai/decisions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sigun: SJ.sg, ...body }) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.status);
    SJ.log = j.rows;
    sjRender();
    toast(`기록함 — ${body.act}${body.emd ? ` · ${body.emd}` : ""}`);
  } catch (e) { toast(`기록하지 못했다 — ${e.message}`); }
}
async function sjAsk(body, label) {
  const box = $("sj-msgs");
  const b = document.createElement("div");
  b.innerHTML = `<div class="msg me">${escH(label)}</div><div class="msg ai"><div class="hint">답을 찾는 중…${body.text ? " (AI — 로컬이면 1분쯤)" : ""}</div></div>`;
  box.appendChild(b);
  b.scrollIntoView({ block: "end", behavior: "smooth" });
  let a;
  try {
    const res = await fetch("/api/ai/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sigun: SJ.sg, ...body }) });
    a = await res.json();
    if (!res.ok) throw new Error(a.detail || res.status);
  } catch (e) { a = { sections: [{ h: "답", items: ["못 받았다 — " + e.message] }] }; }
  b.querySelector(".msg.ai").innerHTML = (a.text ? `<div class="mdt">${aiMd(a.text)}</div>` : aiSections(a.sections || [])) + `<div class="src">${escH(a.source || "")}</div>`;
}
$("sj").addEventListener("click", async ev => {
  const t = ev.target, d = t.closest("[data-a]");
  if (t.closest("#sj-x")) return sjToggle(false);
  if (d) return sjDecide({ act: d.dataset.a, emd: d.dataset.e, fam: d.dataset.f, stage: d.dataset.s, pct: d.dataset.p === "" ? null : +d.dataset.p, eta: d.dataset.t || null });
  if (t.closest("#sj-more")) { SJ.more = !SJ.more; return sjRender(); }
  const del = t.closest("[data-del]");
  if (del) {
    await fetch(`/api/ai/decisions/${del.dataset.del}`, { method: "DELETE" });
    SJ.log = SJ.log.filter(x => String(x.id) !== del.dataset.del);
    return sjRender();
  }
  const st = t.closest("[data-st]"), st0 = t.closest("#sj-stg0");
  if (st || st0) {
    ev.preventDefault();
    try {
      const r = await fetch("/api/ai/sigunstage", { method: "PUT", headers: { "content-type": "application/json" }, body: JSON.stringify({ sigun: "도", stage: st0 ? null : st.dataset.st }) });
      if (!r.ok) throw new Error((await r.json()).detail || r.status);
      SJ.st = await r.json();
      if (st) sjDecide({ act: "메모", note: `도 비상단계를 '${st.dataset.st}'(으)로 바꿈` }); else sjRender();
    } catch (e) { toast(`바꾸지 못했다 — ${e.message}`); }
    return;
  }
  const q = t.closest("[data-q]");
  if (q) sjAsk({ q: q.dataset.q }, q.textContent);
});
$("sj").addEventListener("submit", ev => {
  ev.preventDefault();
  const inp = ev.target.querySelector("input"), v = inp.value.trim();
  if (!v) return;
  inp.value = "";
  if (ev.target.id === "sj-note") sjDecide({ act: "메모", note: v });
  else sjAsk({ text: v }, v);
});
let SJ_KT = 0;
$("sj").addEventListener("input", ev => {
  if (ev.target.id !== "sj-k") return;
  SJ.k = +ev.target.value / 100;
  $("sj-kv").textContent = `×${SJ.k.toFixed(1)}`;
  clearTimeout(SJ_KT);
  SJ_KT = setTimeout(() => sjLoad(true), 450);
});
$("sj-sg").onchange = ev => { SJ.sg = ev.target.value; SJ.k = 1; SJ.more = false; sjLoad(); };
$("b-sj").onclick = () => sjToggle();

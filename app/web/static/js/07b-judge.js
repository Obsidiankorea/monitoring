"use strict";
/* ── 상황판단 모드(X) — 지도는 왼쪽 위로 작게, 오른쪽에 지구 카드 판, 왼쪽 아래에 만약에 · 단계 · 판단 기록 · 물어보기 ──────────
   지구 한 줄 = 위키 우려지역 지구 × 두 강수 기준(기상청 격자 · AWS 면)의 통제 · 사전대피 · 긴급대피 %(/api/judge).
   지구 좌표가 아직 없어(지오코딩 전) 값은 그 읍면동의 최대 칸 — 같은 읍면동 · 유형 지구는 % 가 같다. 지구 대피기준만 지구마다.
   연락처는 /api/contacts(잠금 뒤) — AI 물어보기에는 넘기지 않는다. 결정 단추는 판단 기록에만 남긴다. */
const SJ = { open: false, sg: "all", k: 1, addH: 0, add24: 0, basis: "grid", cut: { on: true, pct: 70 }, d: null, log: [], st: null,
  ct: null, q: [], llm: null, seq: 0, more: false, rows: [] };
try { Object.assign(SJ.cut, JSON.parse(localStorage.getItem("gn-sj-cut") || "{}")); SJ.basis = localStorage.getItem("gn-sj-basis") || "grid"; } catch {}
const SJ_STG = ["통제", "사전대피", "긴급대피"];
const SJ_ACT = { 통제: "통제 지시", 사전대피: "사전대피 권고", 긴급대피: "대피명령 요청" };
const SJ_BN = { grid: "기상청 격자", aws: "AWS" };
const sjLv = p => (p >= 100 ? 100 : p >= 90 ? 90 : p >= 80 ? 80 : p >= 70 ? 70 : p >= 50 ? 50 : 0);
const sjPin = () => { try { return localStorage.getItem("gn-ct-pin") || ""; } catch { return ""; } };
const sjName = d => (d.name && !/^[–-]?$/.test(d.name.trim()) && !/[구군시]$/.test(d.name) ? d.name : d.ri || d.emd || "이름 없음");   // 창원은 지구명 칸이 구 이름 · 빈 칸(–)이면 리로
const sjAddr = d => [d.emd, sjName(d) === d.ri ? "" : d.ri, d.jibun].filter(Boolean).join(" ");
const sjB = r => r.b[SJ.basis] || r.b.grid;
function sjToggle(on = !SJ.open) {
  SJ.open = on;
  $("sj").hidden = !on;
  document.body.classList.toggle("sj-on", on);
  $("b-sj")?.classList.toggle("on", on);
  if (!on) return;
  SJ.sg = SELS[0] || "all";
  sjLoad();
}
async function sjLoad(onlyData) {
  const my = ++SJ.seq, sg = SJ.sg, qs = new URLSearchParams({ sigun: sg, k: SJ.k, add_h: SJ.addH, add_24: SJ.add24 });
  if (!onlyData) $("sj-r").innerHTML = `<div class="sj-ld">${sg === "all" ? "경남 전체 18개 시군" : escH(sg)} 지구 판정을 모으는 중…</div>`;
  else $("sj-r").classList.add("busy");
  try {
    const one = sg === "all" ? "" : `?sigun=${encodeURIComponent(sg)}`;
    const [d, st, lg, ct, rp] = await Promise.all([getJson(`/api/judge?${qs}`), onlyData ? SJ.st : getJson("/api/ai/sigunstage"),
      getJson(`/api/ai/decisions${one}`), onlyData ? null : fetch(`/api/contacts?sigun=${encodeURIComponent(sg)}`, { headers: { "x-pin": sjPin() }, cache: "no-store" }),
      onlyData ? null : getJson(`/api/ai/report${one}`).catch(() => null)]);
    if (my !== SJ.seq) return;
    Object.assign(SJ, { d, st, log: lg.rows });
    if (ct) SJ.ct = ct.status === 401 ? { pin: true } : ct.status === 429 ? { err: "잠금 번호를 여러 번 틀렸다 — 5분 뒤" } : await ct.json();
    if (rp) Object.assign(SJ, { q: rp.questions || [], llm: rp.llm ?? null, rep: rp });
  } catch (e) { if (my === SJ.seq) $("sj-r").innerHTML = `<div class="sj-ld">못 모았다 — ${escH(e.message)}</div>`; return; }
  $("sj-r").classList.remove("busy");
  sjRender();
}
/* 지구 한 줄 — 색 띠(가장 많이 찬 칸) · 지구 · 두 기준 강수(누르면 그 기준으로) · 단계 셋(누르면 기록, 다시 누르면 지움) · 담당 */
const sjRec = (r, s) => SJ.log.find(x => x.sigun === r.sigun && x.emd === r.emd && x.fam === r.fam && x.stage === s && x.note === `지구 ${sjName(r)}`);
function sjCard(r, i) {
  const b = sjB(r), lv = sjLv(b.top), all = SJ.sg === "all";
  const rain = k => { const x = r.b[k]; return `<button class="bs${SJ.basis === k ? " on" : ""}" data-bs="${k}" title="${SJ_BN[k]} 기준으로 판정 보기"><em>${k === "grid" ? "격자" : "AWS"}</em>${x ? `${x.rain["24h"] ?? "—"}<small>㎜</small> · ${x.rain["1h"] ?? "—"}<small>㎜/h</small>` : "—"}</button>`; };
  const ms = SJ_STG.map(s => {
    const c = b.st[s];
    if (!c) return `<div class="m none">—</div>`;
    const rec = sjRec(r, s);
    return `<button class="m l${sjLv(c.pct)}${c.met ? " met" : ""}${rec ? " rec" : ""}" data-rec="${i}" data-s="${s}"
      title="${s} ${c.met ? "기준 넘음" : c.eta ? `${c.eta}시 도달 예상` : "내일 24시까지 안 닿음"} · ${rec ? `${escH(rec.act)} ${rec.at.slice(11, 16)} 기록됨 — 다시 누르면 지움` : `눌러서 기록 — ${SJ_ACT[s]}`}\n${escH(c.rule)}">
      <b>${c.unk ? "모름" : `${c.pct}%`}</b>${rec ? `<i>✔</i>` : ""}</button>`;
  }).join("");
  const sl = r.slide && (r.slide.fcst || r.slide.pred);
  const slTxt = sl ? `<span class="sl">산사태${(r.slide.fcst || r.slide.pred).kind} ${r.slide.fcst ? "예보" : "예측"} 발령 중</span>` : "";
  const ppl = SJ.ct?.people?.[r.id];
  const who = !SJ.ct || SJ.ct.pin || SJ.ct.err || !SJ.ct.on ? `<span class="mute">${SJ.ct?.pin ? "담당자 잠김" : SJ.ct?.on === false ? "연락처 없음" : ""}</span>`
    : (ppl || []).map((p, n) => `<div class="pp"><span>${escH((p.who || "").replace(/담당부서\s*/g, "") || `담당${n + 1}`)}</span>${p.tel ? `<a href="tel:${escH(p.tel.replace(/[^0-9-]/g, ""))}" data-ct="${i}|담당${n + 1}|전화">${escH(p.tel)}</a>` : ""}`
      + (/^01/.test(p.tel || "") ? `<a class="sms" href="sms:${escH(p.tel.replace(/[^0-9]/g, ""))}?body=${encodeURIComponent(`${r.sigun} ${r.emd} ${sjName(r)} ${r.fam} 강우 기준 근접 — 통제 · 사전대피 여부 판단 바랍니다. (경남 재난안전상황실)`)}" data-ct="${i}|담당${n + 1}|문자" title="문자 앱 열기">✉</a>` : "") + `</div>`).join("");
  const site = b.site != null ? `<b class="t${sjLv(b.site)}">${b.site_slide ? (b.site >= 100 ? "발령 중" : "발령 없음") : `${b.site}%`}</b> ` : "";
  return `<div class="cd l${lv}">
    <div class="id"><b>${all ? `<span class="sg">${escH(r.sigun)}</span>` : ""}${escH(sjName(r))}</b><span class="ad">${escH(sjAddr(r))} · ${escH(r.kind || r.fam)}${r.shelter && r.shelter !== "–" ? ` · 대피 ${escH(r.shelter)}` : ""}</span>
      ${r.rule ? `<span class="rl" title="${escH(r.rule)}">지구 기준 ${site}${escH(r.rule.split("※")[0].trim().replace(/,$/, ""))}</span>` : ""}${slTxt}</div>
    <div class="bss">${rain("grid")}${rain("aws")}</div>${ms}<div class="who">${who}</div></div>`;
}
function sjRows() {
  const rs = (SJ.d?.rows || []).filter(r => r.b[SJ.basis]).slice().sort((a, b) => sjB(b).top - sjB(a).top);
  return SJ.cut.on ? rs.filter(r => sjB(r).top >= SJ.cut.pct) : rs;
}
/* 경남 전체 — 시군 × 유형 칸판. 칸 = 'N% 이상' 지구 수 / 지구 수, 색 = 그 칸에서 가장 많이 찬 % 단계. 누르면 그 시군으로 */
function sjChart() {
  const cut = SJ.cut.on ? SJ.cut.pct : 50, F = ["산사태", "하천", "지하공간"];
  const ch = (SJ.d?.chart || []).map(c => {
    const f = c.fam?.[SJ.basis] || {}, k = x => (f[x]?.v || []).filter(v => v >= cut).length;
    return { c, f, k, tot: F.reduce((s, x) => s + k(x), 0), top: Math.max(0, ...F.map(x => f[x]?.top ?? 0)) };
  }).sort((a, b) => b.tot - a.tot || b.top - a.top);
  const cell = (sg, f, x) => {
    const d = f[x];
    if (!d?.n) return `<span class="hc none"></span>`;
    const n = (d.v || []).filter(v => v >= cut).length, l = sjLv(d.top ?? 0);
    return `<button class="hc l${l}${n ? "" : " zero"}" data-sg="${sg}" title="${sg} ${x} — ${cut}% 이상 ${n}곳 / ${d.n}곳 · 가장 많이 찬 곳 ${d.top}%"><b>${n || ""}</b><small>${n ? `/${d.n}` : d.n}</small></button>`;
  };
  const hh = `<div class="hh"><span></span>${F.map(x => `<span>${x}</span>`).join("")}<span>합</span><span>가장 높음</span></div>`;
  const rows = ch.map(({ c, f, tot, top }) => `<div class="hr"><button class="hn" data-sg="${c.sigun}">${c.sigun}</button>${F.map(x => cell(c.sigun, f, x)).join("")}
      <b class="ht${tot ? "" : " zero"}">${tot || "—"}</b><b class="hp t${sjLv(top)}">${top ? `${top}%` : "—"}</b></div>`);
  return `<div class="heat">${hh}${rows.slice(0, 9).join("")}${hh}${rows.slice(9).join("")}</div>
    <div class="lgd">${[100, 90, 80, 70, 50].map(l => `<span><i class="l${l}"></i>${l}%</span>`).join("")}<span class="mute">칸 = ${cut}% 이상 지구 / 지구 수 · 색 = 가장 많이 찬 % · 시군을 누르면 그 시군으로</span></div>`;
}
function sjRender() {
  const d = SJ.d;
  if (!d) return;
  const rows = sjRows(), all = SJ.sg === "all", h = d.head, n100 = (d.rows || []).filter(r => r.b[SJ.basis] && sjB(r).top >= 100).length;
  const do_ = SJ.st?.do, RVN = ["정상", "관심", "주의보", "경보", "심각"];
  const hud = [["특보", all ? "" : (h?.alerts || []).join(" · ") || "없음"], ["도 비상단계", do_?.stage || "상시대비"], ["기준 닿은 지구", `${n100} / ${(d.rows || []).length}`],
    ...(h?.river ? [[h.river.name.replace(/^[가-힣]+[시군]\(|\)$/g, ""), `${(+h.river.v).toFixed(2)}m ${RVN[h.river.stage] || ""}`]] : []),
    ...(h ? [["앞으로 6시간", `${h.fc6h}㎜`], ["오늘 · 내일 더", `${h.later.today} · ${h.later.tomorrow}㎜`]] : [])].filter(x => x[1])
    .map(([k, v]) => `<div><em>${escH(k)}</em><b>${escH(String(v))}</b></div>`).join("");
  const show = SJ.more ? rows : rows.slice(0, 40);
  $("sj-r").innerHTML = `<div class="hd"><h2><select id="sj-sg" aria-label="시군">${["all", ...ORDER_GN()].map(s => `<option value="${s}"${s === SJ.sg ? " selected" : ""}>${s === "all" ? "경남 전체" : s}</option>`).join("")}</select></h2>
      <div class="ttl">상황판단 모드<br><span>${d.tm ? `${+d.tm.slice(4, 6)}.${+d.tm.slice(6, 8)}. ${d.tm.slice(8, 10)}:${d.tm.slice(10, 12)} 실황` : ""}${window.GN_SNAP?.fake ? " · 가상 시연" : ""}</span></div>
      <div class="hud">${hud}</div><button class="x" id="sj-x" aria-label="닫기 (Esc · X)">✕</button></div>
    <div class="bar2"><span class="seg">${["grid", "aws"].map(k => `<button data-bs="${k}" class="${SJ.basis === k ? "on" : ""}">${SJ_BN[k]} 기준</button>`).join("")}</span>
      <label><input type="checkbox" id="sj-cut"${SJ.cut.on ? " checked" : ""}> <input type="number" id="sj-cutp" min="10" max="100" step="5" value="${SJ.cut.pct}">% 이상만</label>
      <span class="mute">지구 ${rows.length}곳${SJ.k !== 1 || SJ.addH || SJ.add24 ? " · 만약에 적용 중" : ""} · 지구 위치 미확정 — 읍면동 최대 칸으로 판정</span></div>
    ${all ? sjChart() : ""}
    <div class="list"><div class="lh"><span>지구</span><span>누적 · 시간당 강우</span><span>통제</span><span>사전대피</span><span>긴급대피</span><span>담당</span></div>${show.map((r, i) => sjCard(r, i)).join("") || `<div class="sj-ld">${SJ.cut.on ? `${SJ.cut.pct}% 이상인 지구가 없다` : "지구가 없다"}</div>`}
      ${rows.length > 40 ? `<button class="more" id="sj-more">${SJ.more ? "접기" : `나머지 ${rows.length - 40}곳 더 보기`}</button>` : ""}</div>`;
  SJ.rows = show;
  $("sj-l").innerHTML = `<div class="box man" id="sj-man"><div class="mtab">${sjMan().map(n => `<button data-man="${escH(n)}">${escH(n === "시군 상황관리반 행동매뉴얼" ? "상황관리반 매뉴얼" : n)}</button>`).join("")}</div><div class="mbd"></div></div>
    <div class="box wif"><div class="kn"><h4>만약에</h4><span class="wt">${[SJ.addH && `매시간 +${SJ.addH}㎜`, SJ.add24 && `24시간 +${SJ.add24}㎜`].filter(Boolean).join(" · ")}</span>
      <input type="range" id="sj-k" min="50" max="300" step="10" value="${Math.round(SJ.k * 100)}" title="초단기 · 단기예보 시우량 배수"><b>×${SJ.k.toFixed(1)}</b>
      <button class="cog" id="sj-cog" title="만약에 설정 — 매시간 · 24시간 더 오는 비" aria-label="만약에 설정">⚙</button></div>
      <div class="pop" id="sj-wpop"${SJ.wopen ? "" : " hidden"}><div class="kn"><span>매시간 더</span><input type="number" id="sj-addh" min="0" max="100" step="5" value="${SJ.addH}"><span>㎜ · 앞으로 24시간</span></div>
        <div class="kn"><span>24시간 안에 더</span><input type="number" id="sj-add24" min="0" max="500" step="10" value="${SJ.add24}"><span>㎜ · 고루 나눠</span></div>
        <div class="kn"><span></span><button id="sj-k0" class="g">처음대로</button><button id="sj-wok" class="g">닫기</button></div></div></div>
    <div class="box"><h4>산사태 예보 · 예측</h4><div class="mute">${SJ.d.slide?.keys ? (SJ.d.slide.why ? `받는 중 — ${escH(SJ.d.slide.why)}` : "안 받는 중 — 호우 · 태풍 특보 때만(지도 레이어 '산사태'에서 늘 받기)") : "키가 없다 — 설정 › API 키 › 재난안전데이터 · 산사태"}${SJ.d.slide?.at ? ` · 마지막 ${SJ.d.slide.at.slice(5, 16).replace("T", " ")}` : ""}<br>
      예측(산림청)은 토양함수지수 80% 주의보 · 약 90% 예비경보 · 100% 경보, 예보(시장 · 군수)는 예측 · 기상을 보고 상황판단회의 뒤 발령. '산사태 경보 발령 시'가 기준인 지구는 발령으로 판정한다.</div></div>
    <div class="box log"><h4>판단 기록</h4>${SJ.log.slice(0, 8).map(x => `<div><time>${x.at.slice(5, 16).replace("T", " ")}</time><b>${escH(x.act)}</b> ${escH(x.sigun)} ${escH(x.emd || "")} ${escH(x.fam || "")} ${escH(x.stage || "")}${x.pct != null ? ` ${x.pct}%` : ""}${x.note ? ` — ${escH(x.note)}` : ""}<i data-del="${x.id}">✕</i></div>`).join("")
      || `<div class="mute">아직 없다 — 카드의 단추를 누르면 시각 · 도달률과 함께 남는다</div>`}
      <form id="sj-note"><input maxlength="300" placeholder="메모 남기기"><button>남기기</button></form></div>
    <div class="box chat"><h4>물어보기</h4><div class="chips">${SJ.q.map(q => `<button data-q="${q.id}">${escH(q.label)}</button>`).join("")}</div>
      <div id="sj-msgs"></div><form id="sj-ask"><input maxlength="300" placeholder="${SJ.llm ? "AI 에게 묻기 — 지금 수치 · 위키 · 판단 기록을 보고 답한다" : "AI 꺼짐 — 설정 › AI 답변"}"><button>묻기</button></form></div>
    ${SJ.ct?.pin ? `<div class="box"><h4>담당자 연락처</h4><form class="sj-pin"><input type="password" inputmode="numeric" autocomplete="off" placeholder="연락처 잠금 번호"><button>열기</button></form></div>` : ""}`;
  sjManShow(sjMan().includes(SJ.man) ? SJ.man : "지금 할 일");
}
/* 매뉴얼 칸(왼쪽 위) — 첫 탭은 지금 할 일(규칙 보고), 나머지는 위키 문서를 문서 서식 그대로(/api/wiki/page) */
const SJ_PG = {};
const sjMan = () => ["지금 할 일", "위기경보와 비상단계", "통제·대피 기준", "시군 상황관리반 행동매뉴얼",
  ...(SJ.sg === "거제" ? ["거제시 단계별 업무"] : SJ.sg === "통영" ? ["통영시 단계별 업무"] : [])];
const sjIn = s => escH(s).replace(/\[\[([^\]|]+)\|([^\]]+)\]\]/g, '<span class="wk">$2</span>').replace(/\[\[([^\]]+)\]\]/g, '<span class="wk">$1</span>')
  .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>").replace(/&lt;br\s*\/?(&gt;|>)/g, "<br>");
function sjMd(md) {
  const L = String(md || "").split(/\r?\n/), out = [];
  for (let i = 0; i < L.length; i++) {
    const l = L[i];
    if (/^\s*\|/.test(l)) {                                 // 표 — 둘째 줄(---)은 건너뛴다
      const rows = [];
      while (i < L.length && /^\s*\|/.test(L[i])) rows.push(L[i++].trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim()));
      i--;
      const body = rows.filter((r, n) => !(n === 1 && r.every(c => /^:?-{2,}:?$/.test(c))));
      out.push(`<table><thead><tr>${body[0].map(c => `<th>${sjIn(c)}</th>`).join("")}</tr></thead><tbody>${body.slice(1).map(r => `<tr>${r.map(c => `<td>${sjIn(c)}</td>`).join("")}</tr>`).join("")}</tbody></table>`);
      continue;
    }
    const co = /^>\s*\[!(\w+)\]\s*(.*)$/.exec(l);
    if (co || /^>\s?/.test(l)) {                             // 콜아웃 · 인용 — 이어진 '>' 줄을 한 덩어리로
      const box = [];
      if (co) i++;
      while (i < L.length && /^>\s?/.test(L[i])) box.push(L[i++].replace(/^>\s?/, ""));
      i--;
      out.push(`<div class="co ${co ? escH(co[1].toLowerCase()) : "q"}">${co && co[2] ? `<b class="ct">${sjIn(co[2])}</b>` : ""}${sjMd(box.join("\n"))}</div>`);
      continue;
    }
    const h = /^(#{1,4})\s+(.*)$/.exec(l), li = /^(\s*)([-*]|\d+[.)])\s+(.*)$/.exec(l);
    if (h) out.push(`<h${Math.min(6, h[1].length + 2)}>${sjIn(h[2])}</h${Math.min(6, h[1].length + 2)}>`);
    else if (li) out.push(`<div class="li${li[1].length ? " sub" : ""}"><i>${/\d/.test(li[2]) ? escH(li[2]) : "·"}</i><span>${sjIn(li[3])}</span></div>`);
    else if (l.trim() && !/^\s*(-{3,}|\*{3,})\s*$/.test(l)) out.push(`<p>${sjIn(l)}</p>`);
  }
  return out.join("");
}
async function sjManShow(name) {
  SJ.man = name;
  const box = $("sj-man");
  if (!box) return;
  box.querySelectorAll("[data-man]").forEach(b => b.classList.toggle("on", b.dataset.man === name));
  const bd = box.querySelector(".mbd");
  if (name === "지금 할 일") {
    const r = SJ.rep;
    bd.innerHTML = r ? `${r.flash ? `<div class="co warning"><b class="ct">속보</b><p>${sjIn(r.flash.text)}</p></div>` : ""}` + (r.sections || []).map(s => `<h4>${sjIn(s.h)}</h4>`
      + s.items.map(x => `<div class="li"><i>·</i><span>${sjIn(x)}</span></div>`).join("")).join("") : `<p class="mute">보고를 만드는 중…</p>`;
    return;
  }
  bd.innerHTML = `<p class="mute">읽는 중…</p>`;
  try { SJ_PG[name] ||= await getJson(`/api/wiki/page?name=${encodeURIComponent(name)}`); }
  catch (e) { bd.innerHTML = `<p class="mute">못 읽었다 — ${escH(e.message)}</p>`; return; }
  const pg = SJ_PG[name];
  if (SJ.man !== name) return;
  bd.innerHTML = `<div class="src">${escH(pg.src || "")}${pg.date ? ` · 기준일 ${escH(pg.date)}` : ""}</div>${sjMd(pg.text)}`;
}
async function sjDecide(body) {
  try {
    const r = await fetch("/api/ai/decisions", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
    const j = await r.json();
    if (!r.ok) throw new Error(j.detail || r.status);
    SJ.log = SJ.sg === "all" ? (await getJson("/api/ai/decisions")).rows : j.rows;
    sjRender();
    toast(`기록함 — ${body.act}${body.emd ? ` · ${body.emd}` : ""}`);
  } catch (e) { toast(`기록하지 못했다 — ${e.message}`); }
}
async function sjAsk(body, label) {
  const box = $("sj-msgs"), b = document.createElement("div");
  b.innerHTML = `<div class="msg me">${escH(label)}</div><div class="msg ai"><span class="mute">답을 찾는 중…${body.text ? " (AI — 로컬이면 1분쯤)" : ""}</span></div>`;
  box.appendChild(b);
  b.scrollIntoView({ block: "end", behavior: "smooth" });
  let a;
  try {
    const res = await fetch("/api/ai/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ sigun: SJ.sg === "all" ? null : SJ.sg, ...body }) });
    a = await res.json();
    if (!res.ok) throw new Error(a.detail || res.status);
  } catch (e) { a = { sections: [{ h: "답", items: ["못 받았다 — " + e.message] }] }; }
  b.querySelector(".msg.ai").innerHTML = (a.text ? `<div class="mdt">${aiMd(a.text)}</div>` : aiSections(a.sections || [])) + `<div class="mute">${escH(a.source || "")}</div>`;
}
function sjPick(sg) {
  SJ.sg = sg; SJ.more = false;
  if (sg === "all") selectSig(null); else setSel([sg]);
  sjLoad();
}
$("sj").addEventListener("click", async ev => {
  const t = ev.target;
  if (t.closest("#sj-x")) return sjToggle(false);
  const bs = t.closest("[data-bs]");
  if (bs) { SJ.basis = bs.dataset.bs; try { localStorage.setItem("gn-sj-basis", SJ.basis); } catch {} return sjRender(); }
  const cr = t.closest("[data-sg]");
  if (cr) return sjPick(cr.dataset.sg);
  const rc = t.closest("[data-rec]");
  if (rc) {
    const r = SJ.rows[+rc.dataset.rec], s = rc.dataset.s, c = sjB(r).st[s], old = sjRec(r, s);
    if (old) { await fetch(`/api/ai/decisions/${old.id}`, { method: "DELETE" }); SJ.log = SJ.log.filter(x => x.id !== old.id); toast(`지움 — ${old.act} · ${sjName(r)}`); return sjRender(); }
    return sjDecide({ sigun: r.sigun, emd: r.emd, fam: r.fam, stage: s, act: SJ_ACT[s], pct: c?.pct ?? null, eta: c?.eta || null, note: `지구 ${sjName(r)}` });
  }
  const ct = t.closest("[data-ct]");
  if (ct) { const [i, who, how] = ct.dataset.ct.split("|"), r = SJ.rows[+i]; sjDecide({ sigun: r.sigun, emd: r.emd, fam: r.fam, act: "메모", note: `연락(${how}) — 지구 ${sjName(r)} ${who}` }); return; }
  if (t.closest("#sj-more")) { SJ.more = !SJ.more; return sjRender(); }
  if (t.closest("#sj-k0")) { Object.assign(SJ, { k: 1, addH: 0, add24: 0 }); return sjLoad(true); }
  const del = t.closest("[data-del]");
  if (del) { await fetch(`/api/ai/decisions/${del.dataset.del}`, { method: "DELETE" }); SJ.log = SJ.log.filter(x => String(x.id) !== del.dataset.del); return sjRender(); }
  if (t.closest("#sj-cog") || t.closest("#sj-wok")) { SJ.wopen = t.closest("#sj-cog") ? !SJ.wopen : false; $("sj-wpop").hidden = !SJ.wopen; return; }
  const mn = t.closest("[data-man]");
  if (mn) return sjManShow(mn.dataset.man);
  const q = t.closest("[data-q]");
  if (q) sjAsk({ q: q.dataset.q }, q.textContent);
});
$("sj").addEventListener("submit", ev => {
  ev.preventDefault();
  const inp = ev.target.querySelector("input"), v = inp.value.trim();
  if (!v) return;
  inp.value = "";
  if (ev.target.classList.contains("sj-pin")) { try { localStorage.setItem("gn-ct-pin", v); } catch {} sjLoad(); return; }
  if (ev.target.id === "sj-note") sjDecide({ sigun: SJ.sg === "all" ? "경남" : SJ.sg, act: "메모", note: v });
  else sjAsk({ text: v }, v);
});
let SJ_KT = 0;
$("sj").addEventListener("change", ev => {
  const id = ev.target.id;
  if (id === "sj-sg") return sjPick(ev.target.value);
  if (id === "sj-cut" || id === "sj-cutp") {
    SJ.cut = { on: $("sj-cut").checked, pct: Math.max(10, Math.min(100, +$("sj-cutp").value || 70)) };
    try { localStorage.setItem("gn-sj-cut", JSON.stringify(SJ.cut)); } catch {}
    return sjRender();
  }
  if (id === "sj-addh" || id === "sj-add24") {
    SJ.addH = Math.max(0, +$("sj-addh").value || 0); SJ.add24 = Math.max(0, +$("sj-add24").value || 0);
    sjLoad(true);
  }
});
$("sj").addEventListener("input", ev => {
  if (ev.target.id !== "sj-k") return;
  SJ.k = +ev.target.value / 100;
  ev.target.nextElementSibling.textContent = `×${SJ.k.toFixed(1)}`;
  clearTimeout(SJ_KT);
  SJ_KT = setTimeout(() => sjLoad(true), 450);
});
$("b-sj").onclick = () => sjToggle();
if (new URLSearchParams(location.search).has("sj")) setTimeout(() => sjToggle(true), 1500);   // ?sj — 상황판단 모드로 열기(벽면 화면 · 바로 가기)

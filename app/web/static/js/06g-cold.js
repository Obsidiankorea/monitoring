"use strict";
/* ── 겨울 화면(❄️) ─────────────────────────────────────────────────────────
   제목 앞 아이콘을 눌러 호우 → 폭염 → 겨울. 폭염 화면과 같은 틀(body.heat)에 body.cold 를 더해 카드만 바꾼다(06c).
   지도 층 넷 — 기온 · 체감 · 바람 · 건조(실효습도). 시군 값은 가장 나쁜 지점(app/cold.py).
   카드 — 시군마다 한파 · 강풍 · 건조 특보 기준에 얼마나 가까운가. 기준을 넘었다고 특보가 아니다(발표는 기상청). */
let CD = null, CD_L = "ta";
try { CD_L = localStorage.getItem("gn-map-cold-l") || "ta"; } catch {}
const CD_LV = { warn: ["경보 기준", 3], watch: ["주의보 기준", 2], near: ["가까움", 1] };
const CD_TEMP = ["#6A3FA0", "#4A4FB8", "#3070C4", "#4A95CF", "#76B2D8", "#A4CBE0", "#5E6B7A", "#6B6A4E"];
const CD_LY = {
  ta:   { t: "기온", u: "℃", k: r => r.ta, st: [-12, -9, -6, -3, 0, 3, 6], c: CD_TEMP, lo: true, f: v => `${v.toFixed(1)}°`, al: /한파/, mark: { [-12]: "한파 주의 아침 최저" } },
  feel: { t: "체감", u: "℃", k: r => r.feel, st: [-12, -9, -6, -3, 0, 3, 6], c: CD_TEMP, lo: true, f: v => `${v.toFixed(1)}°`, al: /한파/ },
  wind: { t: "바람", u: "m/s", k: r => r.wss ?? r.ws, st: [4, 7, 10, 14, 17, 20], c: ["#3A4A5E", "#4D6A6E", "#6E8F6A", "#B5A33A", "#E08A2C", "#E2401F", "#B0124A"],
          f: v => v.toFixed(1), al: /강풍/, mark: { 14: "강풍 주의 풍속", 20: "순간 20" } },
  dry:  { t: "건조", u: "%", k: r => r.he, st: [25, 35, 45, 55, 65], c: ["#B5462A", "#D9822B", "#D9B44A", "#8F9A5A", "#4F7A6E", "#3A4A5E"], lo: true,
          f: v => `${Math.round(v)}%`, al: /건조/, mark: { 35: "건조 주의", 25: "경보" } },
};
const cdCol = (L, v) => L.c[L.st.filter(s => v >= s).length];
const cdAlerts = () => (HT_AL?.land || []).filter(g => /한파|강풍|건조|대설/.test(g.name));

function drawCold() {
  const t = $("tempg"), L = CD_LY[CD_L];
  const by = Object.fromEntries((CD?.rows || []).filter(r => L.k(r) != null).map(r => [r.sigun, r]));
  const gn = FEAT.filter(ft => ft.properties.kind !== "nb" && by[ft.properties.sigun]);
  const lvOf = {};
  for (const g of cdAlerts().filter(g => L.al.test(g.name)).sort((a, b) => HT_LV.indexOf(a.lv) - HT_LV.indexOf(b.lv)))
    for (const s of g.regs?.map(r => r[0]) ?? g.where) lvOf[s] = g.lv;
  const fill = gn.map(ft => [ft, cdCol(L, L.k(by[ft.properties.sigun])), lvOf[ft.properties.sigun] || ""]);
  glData("heat", CD_L + fill.map(([ft, c, lv]) => ft.properties.sigun + c + lv).join(), () => fill.map(([ft, col, lv]) => glF(ft.geometry, { col, lv })));
  t.innerHTML = gn.map(ft => {
    const p = ft.properties, fs = FSN * .74, y = V.toY(p.ly) + FSN * .62 + fs * .62;
    return `<text class="b" x="${V.toX(p.lx).toFixed(1)}" y="${y.toFixed(1)}" style="font-size:${fs.toFixed(1)}px;stroke-width:${(fs * .2).toFixed(1)}px">${L.f(L.k(by[p.sigun]))}</text>`;
  }).join("");
}

/* 한 칸 — 값과 그 값이 특보 기준에 걸리면 색 */
const cdV = (v, f, lv) => `<span class="${lv || ""}">${v == null ? "—" : f(v)}</span>`;
function renderCold() {
  const D = CD, L = CD_LY[CD_L], k = V?.k || 1, rows = [...(D?.rows || [])];
  $("ht-mark").hidden = true;
  const tm = D?.tm ? D.tm.slice(11, 16) : "—";
  $("ht-time").textContent = D?.tm ? `${tm} 관측 · AWS ${D.n}곳 · 시군마다 가장 나쁜 지점` : "관측 자료 없음";
  $("cd-bt").textContent = D?.tm ? `${tm} 관측` : "—";
  $("cd-ly").innerHTML = Object.entries(CD_LY).map(([key, l]) =>
    `<button type="button" data-cl="${key}" aria-pressed="${key === CD_L}" class="${key === CD_L ? "on" : ""}">${l.t}</button>`).join("");
  const body = $("cd-b");
  if (!rows.length) body.innerHTML = `<div class="ht-none"><b>관측 자료가 아직 없다</b><span>${D?.err ? escH(D.err) : "AWS 정시 수집이 돌면 시군별 기온 · 바람 · 습도가 여기 나온다."}</span></div>`;
  else {
    const score = r => Object.values(r.lv).reduce((a, lv) => a + (CD_LV[lv]?.[1] || 0), 0);
    const val = r => L.k(r) ?? (L.lo ? Infinity : -Infinity);
    rows.sort((a, b) => score(b) - score(a) || (L.lo ? val(a) - val(b) : val(b) - val(a)));
    const pick = (key, lo) => rows.filter(r => r[key] != null).sort((a, b) => (lo ? a[key] - b[key] : b[key] - a[key]))[0];
    const tmin = pick("ta", true), fl = pick("feel", true), gs = pick("wss") || pick("ws"), dr = pick("he", true);
    const kpi = [[tmin && `${tmin.ta.toFixed(1)}°`, `최저 기온${tmin ? ` · ${tmin.sigun}` : ""}`, tmin && cdCol(CD_LY.ta, tmin.ta)],
                 [fl && `${fl.feel.toFixed(1)}°`, `최저 체감${fl ? ` · ${fl.sigun}` : ""}`, fl && cdCol(CD_LY.feel, fl.feel)],
                 [gs && (gs.wss ?? gs.ws).toFixed(1), `${gs?.wss != null ? "최대 순간풍속" : "최대 풍속"}${gs ? ` · ${gs.sigun}` : ""}`, gs && cdCol(CD_LY.wind, gs.wss ?? gs.ws)],
                 [dr && `${Math.round(dr.he)}%`, dr ? `최저 실효습도 · ${dr.sigun}` : "실효습도 — 습도 모으는 중", dr && cdCol(CD_LY.dry, dr.he)]]
      .map(([v, l, c]) => `<div><b${c ? ` style="color:${c}"` : ""}>${v ?? "—"}</b><span>${l}</span></div>`).join("");
    const one = v => v.toFixed(1);
    body.innerHTML = `<div class="ht-kpi cd-kpi">${kpi}</div>`
      + `<div class="cdr h"><span>시군 · 지점</span><span>기온</span><span>체감</span><span>아침 최저</span><span>바람 · 순간</span><span>실효습도</span><span>특보 기준</span></div>`
      + rows.map(r => {
        const badge = Object.entries({ cold: "한파", wind: "강풍", dry: "건조" }).filter(([key]) => r.lv[key])
          .map(([key, n]) => `<i class="${r.lv[key]}" title="${n} ${CD_LV[r.lv[key]][0]}">${n}${r.lv[key] === "near" ? "↗" : ""}</i>`).join("");
        const tip = `${r.sigun} — 가장 추운 곳 ${r.stn}${r.ws_stn ? ` · 바람 센 곳 ${r.ws_stn}` : ""}${r.he_stn ? ` · 가장 마른 곳 ${r.he_stn}` : ""}`
          + (r.drop != null ? ` · 아침 최저가 전날보다 ${r.drop > 0 ? `${r.drop}℃ 내려감` : `${-r.drop}℃ 오름`}` : "");
        return `<div class="cdr det" data-s="${r.sigun}" title="${escH(tip)}">`
          + `<div class="nm2"><small>${r.sigun}</small>${escH(r.stn)}</div>`
          + cdV(r.ta, one) + cdV(r.feel, one) + cdV(r.tmin, one, r.lv.cold)
          + `<span class="${r.lv.wind}">${r.ws == null ? "—" : one(r.ws)}<em>${r.wss == null ? "" : ` · ${one(r.wss)}`}</em></span>`
          + cdV(r.he, v => `${Math.round(v)}%`, r.lv.dry)
          + `<div class="cdb">${badge}</div></div>`;
      }).join("")
      + (D.he_ready ? "" : `<div class="case-note">실효습도는 앞 4일 평균습도가 있어야 나온다 — 정시 습도를 모으는 중(지난 5일치를 차례로 메운다).</div>`);
    rowEvents(body);
  }
  const al = cdAlerts();
  $("cd-ab").innerHTML = (al.length ? al.map(g => `<div class="ht-al ${g.lv}"><b>${escH(g.name)}</b><span>${g.where.map(escH).join(" · ")}</span></div>`).join("")
      : `<div class="ht-none s"><b>발효 중인 한파 · 강풍 · 건조 · 대설특보 없음</b></div>`)
    + `<div class="ht-crit">한파주의보 아침 최저 −12℃ 이하 또는 전날보다 10℃ 넘게 내려 3℃ 이하 · 강풍주의보 풍속 14m/s 또는 순간 20m/s · 건조주의보 실효습도 35% 이하 2일 지속 예상</div>`;
  $("ht-lg").innerHTML = `<b>${L.t} ${L.u}</b>` + [...L.st].reverse().map(s => `<div><i style="background:${cdCol(L, s)}"></i>${s}${L.mark?.[s] ? `<em>${L.mark[s]}</em>` : ""}</div>`).join("")
    + `<div><i style="background:${L.c[0]}"></i>${L.st[0]} 미만</div>`;
}
$("cd-ly").onclick = ev => {
  const b = ev.target.closest("[data-cl]");
  if (!b) return;
  CD_L = b.dataset.cl;
  try { localStorage.setItem("gn-map-cold-l", CD_L); } catch {}
  drawCold(); renderCold();
};

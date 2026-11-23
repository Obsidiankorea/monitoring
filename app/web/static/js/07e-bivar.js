"use strict";
/* ── 두 변수 판단(층 메뉴 '판단', 9 키) — 지도 색 = 이번 비 누적 × 최근 1시간, 빗금 = 앞으로 6시간 가장 센 시우량.
   자료는 서버가 시각마다 굽는다(/api/bivar — app/bivar.py). 오른쪽 패널(#rail 자리)에 시군 × 시각 판단 시간표 · 색 범례 · 판단표.
   지도에 마우스를 올리면 그 칸의 누적 · 12 · 24 · 3시간 · 앞으로 값을 위키 판정값(통제 · 대피 기준)과 견준 설명(11-misc mousemove → bvTip).
   상태는 01-core 의 BV { on, D, i } — 다른 층을 고르면(pickLayer) 꺼진다.
   ⚠️ 칸 판단(tier)은 대략이다(색 셋 × 빗금 넷 조합). 정확한 판단은 마우스 설명(근거 기준을 값으로 직접 본다). */
const BV_TIERS = [["평온", "#5b636e"], ["해제 검토", "#3fc1ae"], ["관찰", "#9aa3b0"], ["대비", "#e8c547"], ["경계", "#f2903f"], ["비상", "#ff4d5a"]];
const BV_GROUPS = [["서부해안", ["남해", "하동", "사천"]], ["중부해안", ["고성", "통영", "거제"]], ["동부도시", ["창원", "김해", "양산"]],
                   ["동부내륙", ["함안", "의령", "창녕", "밀양"]], ["서부내륙", ["진주", "산청", "합천", "함양", "거창"]]];
const BV_S = 4;                                    // 빗금 그림 — 500m 칸 하나에 4 픽셀(결측 빗금과 같은 비율)
function bvTier(a, n, f) {
  if (!n && !f) return a ? 1 : 0;
  if (n === 2 || (a === 2 && n >= 1) || (a >= 1 && f === 3)) return 5;
  if (f === 3 || (a === 2 && f >= 2) || (a >= 1 && n === 1 && f >= 2)) return 4;
  if (f >= 1 || n >= 1) return 3;
  return 2;
}
const bvWhy = (a, n, f) => a === 2 && n === 0 && f >= 1 ? "소강·다시 옴" : a === 2 && n === 0 && f === 0 ? "그침" : n === 0 && f >= 2 ? "큰비 올 예정" : "";
const bvFmt = t => `${+t.slice(4, 6)}. ${+t.slice(6, 8)}. ${t.slice(8, 10)}:${t.slice(10, 12)}`;
const bvH = t => `${+t.slice(6, 8)}일 ${t.slice(8, 10)}시`;
const bvImg = src => new Promise((ok, no) => { const i = new Image(); i.onload = () => ok(i); i.onerror = no; i.src = "data:image/png;base64," + src; });
const bvLum = h => { const n = parseInt(h.slice(1), 16); return (n >> 16) * .3 + ((n >> 8) & 255) * .59 + (n & 255) * .11; };
const bvTot = f => f.c3.flat(2).reduce((a, b) => a + b, 0) || 1;
const bvFutL = () => { const u = BV.D.fut; return ["~" + u[0], u[0] + "~" + u[1], u[1] + "~" + u[2], u[2] + "~"]; };

/* 빗금 — 1 성긴 사선 · 2 촘촘한 사선 · 3 지그재그(흰 선 — 칠할 때 그 칸 색을 밝게 해서 덮는다) */
function bvPattern(lv, u = 1) {
  const g = document.createElement("canvas"), c = g.getContext("2d");
  c.strokeStyle = "#fff";
  if (lv === 3) {
    const p = Math.round(14 * u), r = Math.round(10 * u); g.width = p; g.height = r;
    c.lineWidth = 2.4 * u; c.lineJoin = "miter"; c.beginPath();
    const y = r / 2, a = 3.6 * u;
    c.moveTo(-p / 2, y + a); c.lineTo(0, y - a); c.lineTo(p / 2, y + a); c.lineTo(p, y - a); c.lineTo(p * 1.5, y + a); c.stroke();
    return g;
  }
  const n = Math.round((lv === 1 ? 16 : 8) * u); g.width = g.height = n;
  c.lineWidth = (lv === 1 ? 1.8 : 2.1) * u; c.beginPath();
  for (const o of [-n, 0, n]) { c.moveTo(o, n); c.lineTo(o + n, 0); }
  c.stroke();
  return g;
}
const BV_PAT = [1, 2, 3].map(lv => bvPattern(lv));

async function bvLoad() {
  const my = (BV.seq = (BV.seq || 0) + 1);
  try {
    const D = await getJson("/api/bivar" + (CASE ? `?case=${encodeURIComponent(CASE)}` : ""));
    if (my !== BV.seq || !BV.on) return;
    const keep = BV.D && BV.i !== BV.D.now_i && D.frames.some(f => f.tm === BV.D.frames[BV.i]?.tm);
    const tm = keep ? BV.D.frames[BV.i].tm : null;
    BV.D = D; BV.HV = null; BV.EMD = null;
    bvPanel();
    await bvFrame(tm ? D.frames.findIndex(f => f.tm === tm) : D.now_i);
    bvHover();
  } catch (e) {
    if (my !== BV.seq) return;
    $("bv-b").innerHTML = `<div class="bv-none">두 변수 판단 자료를 못 만들었다<small>${escH(e.message || String(e))}</small></div>`;
  }
}
/* 켜고 끄기 — 켜면 오른쪽 카드가 아래로 내려가 사라지고, 지도가 왼쪽으로 비켜 작아지고, 판단 패널 둘이 들어온다
   (위 오른쪽 = 색 범례 · 판단표, 아래 오른쪽 = 시간표 — 경남 남동쪽 바다(거제 동쪽 · 김해 남쪽)로 파고든다).
   끄면 거꾸로. 움직임은 CSS 전환(map.css '두 변수 판단') — 지도는 camGo 가 tlFit(BV 틀)로 옮긴다 */
function bvSet(on) {
  if (on === BV.on) return;
  BV.on = on;
  clearInterval(BV.tmr); BV.tmr = null; bvStop();
  if (on) {
    stopPlay();
    if (!$("bv")) {
      $("rail").insertAdjacentHTML("afterend", `<div id="bv" aria-label="두 변수 판단"><section class="card" id="bv-a" aria-label="색 범례 · 판단표"></section><section class="card" id="bv-b" aria-label="시군 판단 시간표"></section></div>`);
      void $("bv").offsetWidth;                  // 처음 붙인 카드도 밖에서 들어오게
    }
    $("bv-a").innerHTML = "";
    $("bv-b").innerHTML = `<div class="bv-none">두 변수 판단 자료를 만드는 중…</div>`;
    BV.intro = true;
    document.body.classList.add("bv");
    bvLayout();
    bvLoad();
    if (!CASE) BV.tmr = setInterval(bvLoad, 5 * 60 * 1000);        // 새 정시 · 새 초단기 발표 — 서버는 같은 입력이면 다시 굽지 않는다
  } else {
    document.body.classList.remove("bv");
    BV.D = null; BV.HV = null; BV.base = null;
    if (GL_OK) glCanvas("hatch");
    HATCH_OF = null;
    camGo(true); placeSw();
  }
  paintHead(); buildMenu();
  draw();
}
/* 자리 — 위 패널 폭(지도가 비켜설 몫, tlFit 이 읽는다)과 아래 패널의 왼쪽 위 모서리(지도가 갈 틀에서 거제 동쪽 끝 · 김해 남쪽 끝) */
const bvTopW = () => Math.round(Math.min(Math.max(360 * V.k, V.W * 0.25), V.W * 0.32));
let BV_NOTCH = null;
function bvNotch() {
  if (BV_NOTCH || !MSIG || !META || !GEO) return BV_NOTCH;
  const hb = META.grids.hr, id = n => GEO.sigun.find(s => s.name === n && s.kind === "gn")?.id;
  const gj = id("거제"), gh = id("김해");
  let ex = -1, sy = 1e9;
  for (let r = 0; r < hb.h; r++) for (let c = 0; c < hb.w; c++) {
    const v = MSIG[r * hb.w + c];
    if (v === gj && c > ex) ex = c;
    if (v === gh && r < sy) sy = r;                // 행은 남→북 — 작은 행이 남쪽
  }
  return (BV_NOTCH = ex < 0 || sy > 1e8 ? null : { gx: ex + hb.i0, gy: sy + hb.j0 });
}
function bvLayout() {
  if (!BV.on || !V) return;
  const k = V.k, w = bvTopW(), de = document.documentElement;
  de.style.setProperty("--bvw", w + "px");
  camGo(true); placeSw();
  const T = camTarget(), c = T.cam, n = bvNotch();
  const sx = gx => c.ox + (gx - V.X0) * c.s, sy = gy => c.oy + (V.Y1 - gy) * c.s;
  const minW = Math.max(w + 120 * k, 520 * k);
  const left = Math.round(Math.min(V.W - 16 - minW, Math.max(V.W * 0.38, n ? sx(n.gx) + 16 * k : V.W * 0.5)));
  // 시간표 열여덟 줄이 숨 쉬게 아래 카드는 380px 이상(낮은 화면이면 남동쪽 바다보다 위로 올라온다)
  const top = Math.round(Math.min(V.H * 0.6, V.H - 16 - 380 * k, Math.max(V.H * 0.36, n ? sy(n.gy) + 10 * k : V.H * 0.5)));
  de.style.setProperty("--bv-l", left + "px");
  de.style.setProperty("--bv-t", top + "px");
}
addEventListener("resize", () => { if (BV.on) requestAnimationFrame(bvLayout); });

/* 지도 — 9색 그림을 rain 소스에, 빗금을 hatch 소스에(결측 빗금 자리를 빌린다) */
async function bvFrame(i) {
  const D = BV.D; if (!D) return;
  BV.i = i = Math.max(0, Math.min(D.frames.length - 1, i));
  const f = D.frames[i];
  const [b, mk] = await Promise.all([bvImg(f.now), bvImg(f.mask)]);
  if (BV.D !== D || BV.i !== i) return;
  BV.base = b; BV.mask = mk;
  draw();
  bvSide(f); bvCursor(i); paintHead();
  requestAnimationFrame(bvFit);
}
function bvDraw() {
  if (!GL_OK || !BV.base) return;
  const D = BV.D, gr = { grid: "hr", w: D.w, h: D.h }, co = gridCorners(gr);
  glCanvas("rain", D.w, D.h, c => { c.imageSmoothingEnabled = false; c.drawImage(BV.base, 0, 0); }, co);
  HATCH_OF = null;
  const W = D.w * BV_S, H = D.h * BV_S;
  // 빗금 단계마다 마스크(붉은 칸 값 = 단계 × 80)를 한 번 뽑아 둔다
  const mc = document.createElement("canvas"); mc.width = D.w; mc.height = D.h;
  const mx = mc.getContext("2d"); mx.drawImage(BV.mask, 0, 0);
  const px = mx.getImageData(0, 0, D.w, D.h).data;
  const lvm = [1, 2, 3].map(lv => {
    const m = document.createElement("canvas"); m.width = D.w; m.height = D.h;
    const x = m.getContext("2d"), id = x.createImageData(D.w, D.h);
    let any = false;
    for (let p = 0; p < px.length; p += 4) if (Math.round(px[p] / 80) === lv) { id.data[p + 3] = 255; any = true; }
    x.putImageData(id, 0, 0);
    return any ? m : null;
  });
  if (!lvm.some(Boolean)) { glCanvas("hatch"); return; }
  const fx = document.createElement("canvas"); fx.width = W; fx.height = H;
  const fc = fx.getContext("2d");
  glCanvas("hatch", W, H, c => {
    lvm.forEach((m, l) => {
      if (!m) return;
      fc.globalCompositeOperation = "source-over"; fc.filter = "none"; fc.clearRect(0, 0, W, H);
      fc.fillStyle = fc.createPattern(BV_PAT[l], "repeat"); fc.fillRect(0, 0, W, H);
      fc.globalCompositeOperation = "source-in"; fc.imageSmoothingEnabled = false;
      fc.filter = `brightness(${[1.45, 1.6, 1.8][l]}) saturate(1.25)`; fc.drawImage(BV.base, 0, 0, W, H); fc.filter = "none";
      fc.globalCompositeOperation = "destination-in"; fc.drawImage(m, 0, 0, W, H);
      c.drawImage(fx, 0, 0);
    });
  }, co);
}

/* 오른쪽 패널 — 머리(시각 · 재생 · 다 보기) · 시간표 · 아래 범례와 판단표 */
function bvPanel() {
  const D = BV.D;
  $("bv-a").innerHTML = `<div class="hd"><b>지금 상태</b><span class="sub" id="bv-at"></span></div>
    <div class="lgw"><div class="leg" id="bv-leg"></div><div class="key" id="bv-key"></div></div><table class="mx" id="bv-mx"></table>
    <p class="nt">색 = <b style="color:#36b3e6">이번 비 누적</b>(${D.acc.join(" · ")}㎜) × <b style="color:#ff4f8b">최근 1시간</b>(${D.h1.join(" · ")}㎜), 빗금 = 앞으로 6시간 가장 센 시우량(${D.fut.join(" · ")}㎜/h). 끊는 값은 위키 판정값.
      ${D.live ? "지난 시각의 '앞으로'는 실제로 온 비, 지금부터는 초단기예보." : "사례 — '앞으로'는 실제로 온 비."}${D.missing ? ` 빠진 정시 ${D.missing}개.` : ""} 지도에 마우스를 올리면 근거와 함께 설명.</p>`;
  $("bv-b").innerHTML = `<div class="hd"><b>두 변수 판단</b><span class="sub">${escH(D.title || "")}${D.live ? ` · 초단기 ${D.tmfc ? hm(D.tmfc) : "없음"} 발표` : ""}</span><span class="sp"></span>
      <button type="button" data-a="play" title="재생 — 시각을 하나씩">▶</button>
      <label title="끄면 지금 뒤 6시간만 빗금(예보), 그 뒤는 흐리게"><input type="checkbox" data-a="all"> 다 보기</label>
      <button type="button" data-a="x" title="끄기 — 보던 층으로(9)">✕</button></div>
    <div class="tlg" id="bv-tlg"></div>
    <div id="bv-tl"${BV.intro ? ' class="intro"' : ""} role="slider" tabindex="0" aria-label="시각 — 시군별 판단 시간표"></div>`;
  const q = a => $("bv").querySelector(`[data-a="${a}"]`);
  BV.intro = false;                         // 시간표가 왼쪽부터 쓸려 나오는 것은 켤 때 한 번만(5분마다 새로 받을 때는 아니다)
  q("x").onclick = () => bvSet(false);
  q("play").onclick = () => BV.play ? bvStop() : bvPlay();
  q("all").onchange = () => bvCursor(BV.i);
  $("bv-key").innerHTML = bvFutL().map((s, i) => `<div><canvas data-l="${i}"></canvas><span>${["없음", "성긴 빗금", "촘촘한 빗금", "지그재그"][i]} ${s}</span></div>`).join("");
  bvTimeline();
}
function bvPlay() {
  BV.play = setInterval(() => bvFrame((BV.i + 1) % BV.D.frames.length), 900);
  const b = $("bv").querySelector('[data-a="play"]'); b.textContent = "❚❚";
}
function bvStop() {
  clearInterval(BV.play); BV.play = null;
  const b = $("bv")?.querySelector('[data-a="play"]'); if (b) b.textContent = "▶";
}
function bvSwatch(cnv, lv, bg) {
  const r = cnv.getBoundingClientRect(), u = Math.min(2, devicePixelRatio || 1);
  cnv.width = Math.max(1, (r.width || 60) * u); cnv.height = Math.max(1, (r.height || 12) * u);
  const c = cnv.getContext("2d"); c.fillStyle = bg; c.fillRect(0, 0, cnv.width, cnv.height);
  if (!lv) return;
  const t = document.createElement("canvas"); t.width = cnv.width; t.height = cnv.height;
  const x = t.getContext("2d"); x.fillStyle = x.createPattern(bvPattern(lv, u * 0.6), "repeat"); x.fillRect(0, 0, t.width, t.height);
  x.globalCompositeOperation = "source-in"; x.fillStyle = bg; x.filter = `brightness(${[1.45, 1.6, 1.8][lv - 1]}) saturate(1.25)`;
  x.fillRect(0, 0, t.width, t.height); c.drawImage(t, 0, 0);
}
function bvSide(f) {
  const D = BV.D, tt = bvTot(f), FL = bvFutL();
  let h = "";
  for (let r = 2; r >= 0; r--) {
    h += `<div class="ax">${["~" + D.acc[0], D.acc[0] + "~" + D.acc[1], D.acc[1] + "~"][r]}</div>`;
    for (let c = 0; c < 3; c++) {
      const col = D.pal[r][c], v = f.c3[r][c].reduce((a, b) => a + b, 0) / tt * 100;
      h += `<div class="c${bvLum(col) < 120 ? " dk" : ""}" style="background:${col}" title="${D.names[r][c]} — 경남 땅 ${v.toFixed(1)}%"><b>${v && v < 1 ? v.toFixed(1) : v.toFixed(0)}%</b></div>`;
    }
  }
  h += `<div class="ax">누적</div>` + ["~" + D.h1[0], D.h1[0] + "~" + D.h1[1], D.h1[1] + "~"].map(s => `<div class="ax">${s}</div>`).join("");
  $("bv-leg").innerHTML = h + `<div class="cap">← 이번 비 누적(㎜) · 최근 1시간(㎜) →</div>`;
  let m = `<colgroup><col class="s"><col><col><col><col></colgroup><tr><th></th>${FL.map((s, i) => `<th>${["없음", "성김", "촘촘", "지그재그"][i]}<canvas data-l="${i}"></canvas></th>`).join("")}</tr>`;
  for (let a = 2; a >= 0; a--) for (let n = 2; n >= 0; n--) {
    m += `<tr><td class="st"><span class="chip" style="background:${D.pal[a][n]}"></span>${D.names[a][n]}</td>`;
    for (let fl = 0; fl < 4; fl++) {
      const t = bvTier(a, n, fl), k = f.c3[a][n][fl], w = bvWhy(a, n, fl);
      m += `<td class="t${k ? " on" : ""}" style="background:${BV_TIERS[t][1]}" title="${D.names[a][n]} · 앞으로 ${FL[fl]}㎜/h → ${BV_TIERS[t][0]}${w ? " (" + w + ")" : ""} · 경남 땅 ${(k / tt * 100).toFixed(1)}%">${BV_TIERS[t][0]}</td>`;
    }
    m += "</tr>";
  }
  $("bv-mx").innerHTML = m;
  $("bv-at").textContent = `${bvFmt(f.tm)}${f.fc ? " 예보" : ""} · 경남 땅 칸 비율`;
  $("bv").querySelectorAll("#bv-mx th canvas, #bv-key canvas").forEach(c => bvSwatch(c, +c.dataset.l, D.pal[1][1]));
}

/* 시간표 — 맨 위 경남 전체(경계 · 비상 땅 비율 막대), 아래 시군마다 시각별 판단 색(지역으로 묶어 왼쪽에 세로 글씨). 누르거나 끌면 그 시각 */
function bvTimeline() {
  const D = BV.D, NF = D.frames.length;
  const T = D.frames.map(f => Object.fromEntries(f.rows.map(r => [r[0], bvTier(r[4], r[5], r[6])])));
  const names = D.frames[0].rows.map(r => r[0]);
  const worst = n => Math.max(...T.map(x => x[n] ?? 0));
  const tl = $("bv-tl"); tl.style.setProperty("--n", NF);
  const d0 = f => f.tm.slice(8, 10) === "00" ? " d0" : "";
  const areaOf = f => { const a = [0, 0, 0, 0, 0, 0]; for (let x = 0; x < 3; x++) for (let n = 0; n < 3; n++) for (let fl = 0; fl < 4; fl++) a[bvTier(x, n, fl)] += f.c3[x][n][fl]; return a; };
  const SC = Math.max(.01, ...D.frames.map(f => { const a = areaOf(f); return (a[4] + a[5]) / bvTot(f); }));
  const top = Math.max(...D.frames.map(f => areaOf(f)[5] / bvTot(f)));
  let h = `<div></div><div class="lb bh">경남</div>`;
  D.frames.forEach((f, i) => {
    const tt = bvTot(f), a = areaOf(f);
    h += `<div class="bar${d0(f)}" data-i="${i}" title="${bvH(f.tm)}${f.fc ? "(예보)" : ""} — 비상 ${(a[5] / tt * 100).toFixed(0)}% · 경계 ${(a[4] / tt * 100).toFixed(0)}% · 대비 ${(a[3] / tt * 100).toFixed(0)}%">${[4, 5].map(t => `<i style="height:${a[t] / tt / SC * 100}%;background:${BV_TIERS[t][1]}"></i>`).join("")}</div>`;
  });
  h += `<div class="rs">경계 · 비상 땅(막대 위 ${(SC * 100).toFixed(0)}%)<br>비상 가장 넓을 때 <b style="color:${BV_TIERS[5][1]}">${(top * 100).toFixed(0)}%</b></div>`;
  h += `<div></div><div></div>` + D.frames.map((f, i) => { const hh = +f.tm.slice(8, 10); return `<div class="ax${d0(f)}" data-i="${i}">${hh % 6 === 0 ? `<span>${hh === 0 ? +f.tm.slice(6, 8) + "일" : hh + "시"}</span>` : ""}</div>`; }).join("") + `<div></div>`;
  const groups = BV_GROUPS.map(g => [g[0], g[1]]), left = names.filter(n => !groups.some(g => g[1].includes(n)));
  if (left.length) groups.push(["그 밖", left]);
  for (const [gname, gs] of groups) {
    const ns = names.filter(n => gs.includes(n)); if (!ns.length) continue;
    h += `<div class="gn" style="grid-row:span ${ns.length}" title="${gname}">${gname}</div>`;
    ns.forEach((n, ri) => {
      const g0 = ri === 0 ? " g0" : "", w = worst(n);
      const spans = []; let st = -1;
      T.forEach((x, i) => { if (x[n] === w && st < 0) st = i; if ((x[n] !== w || i === NF - 1) && st >= 0) { spans.push([st, x[n] === w ? i : i - 1]); st = -1; } });
      const sp = spans[0];
      const txt = w >= 3 && sp ? `<b style="color:${BV_TIERS[w][1]}">${BV_TIERS[w][0]}</b> ${bvH(D.frames[sp[0]].tm)}${sp[1] > sp[0] ? "~" + bvH(D.frames[sp[1]].tm) : ""}${spans.length > 1 ? ` 외 ${spans.length - 1}번` : ""}` : `<span>가장 높게 ${BV_TIERS[w][0]}</span>`;
      h += `<div class="lb${g0}">${n}</div>` + T.map((x, i) => `<div class="k${d0(D.frames[i])}${g0}" data-i="${i}" style="background:${BV_TIERS[x[n] ?? 0][1]}" title="${n} ${bvH(D.frames[i].tm)}${D.frames[i].fc ? "(예보)" : ""} — ${BV_TIERS[x[n] ?? 0][0]}"></div>`).join("")
        + `<div class="rs${g0}" title="${txt.replace(/<[^>]+>/g, "")}">${txt}</div>`;
    });
  }
  tl.innerHTML = h;
  $("bv-tlg").innerHTML = `<span><i></i>관측</span><span><i class="fut"></i>앞으로 6시간</span><span><i style="opacity:.25"></i>그 뒤</span><span class="sp"></span>`
    + BV_TIERS.map(t => `<span><i style="background:${t[1]}"></i>${t[0]}</span>`).join("");
  let drag = false;
  const pick = e => { const el = document.elementFromPoint(e.clientX, e.clientY)?.closest("#bv-tl [data-i]"); if (el && +el.dataset.i !== BV.i) { bvStop(); bvFrame(+el.dataset.i); } };
  tl.onpointerdown = e => { drag = true; tl.setPointerCapture(e.pointerId); pick(e); };
  tl.onpointermove = e => { if (drag) pick(e); };
  tl.onpointerup = () => { drag = false; };
  tl.onkeydown = e => {
    if (e.key === "ArrowRight" || e.key === "ArrowLeft") { bvStop(); bvFrame(BV.i + (e.key === "ArrowRight" ? 1 : -1)); e.preventDefault(); e.stopPropagation(); }
  };
  if (!BV.ro) { BV.ro = new ResizeObserver(() => bvFit()); }
  BV.ro.disconnect(); BV.ro.observe(tl);
}
function bvFit() {
  const tl = $("bv-tl"); if (!tl) return;
  const n = tl.querySelectorAll(".lb").length - 1, fixed = 34 + 16 + (n + 2) + 8;
  tl.style.setProperty("--rh", Math.max(9, Math.min(30, Math.floor((tl.clientHeight - fixed) / n))) + "px");
}
function bvCursor(i) {
  const all = $("bv")?.querySelector('[data-a="all"]')?.checked;
  $("bv").querySelectorAll("#bv-tl [data-i]").forEach(e => {
    const j = +e.dataset.i, ax = e.classList.contains("ax");
    e.classList.toggle("cur", j === i && !ax);
    e.classList.toggle("fut", !all && j > i && j <= i + 6 && !ax);
    e.classList.toggle("far", !all && j > i + 6 && !ax);
    if (ax) {
      e.classList.toggle("now", j === i);
      e.querySelector(".nw")?.remove();
      if (j === i) e.insertAdjacentHTML("beforeend", `<span class="nw">${j === BV.D.now_i && BV.D.live ? "지금" : bvH(BV.D.frames[j].tm).split(" ")[1]}</span>`);
    }
  });
  $("bv-tl").setAttribute("aria-valuetext", bvFmt(BV.D.frames[i].tm));
}
const bvLabel = () => {
  const D = BV.D, f = D?.frames[BV.i];
  return !f ? "두 변수 판단" : `두 변수 판단 · ${bvH(f.tm)}${f.fc ? " 예보" : BV.i === D.now_i && D.live ? " 지금" : ""}`;
};

/* 마우스 설명 — 그 칸의 1시간 강수(시각마다)로 이번 비 · 12 · 24 · 3시간 · 앞으로를 더해, 위키 판정값의 기준과 견준다 */
async function bvHover() {
  const D = BV.D;
  const rd = async src => { const im = await bvImg(src), c = document.createElement("canvas"); c.width = D.w; c.height = D.h; const x = c.getContext("2d"); x.drawImage(im, 0, 0); return x.getImageData(0, 0, D.w, D.h).data; };
  const e = await rd(D.emdpng), EMD = new Uint16Array(D.w * D.h);
  for (let p = 0; p < EMD.length; p++) EMD[p] = e[p * 4] << 8 | e[p * 4 + 1];
  const HV = [];
  for (const f of D.frames) { const g = await rd(f.h1), a = new Uint8Array(D.w * D.h); for (let p = 0; p < a.length; p++) a[p] = g[p * 4]; HV.push(a); }
  if (BV.D === D) { BV.EMD = EMD; BV.HV = HV; }
}
function bvExplain(p, i) {
  const D = BV.D, HV = BV.HV, VV = k => D.v[k]?.v ?? 0;
  const at = j => HV[j] ? HV[j][p] / 2 : 0, sum = (a, b) => { let s = 0; for (let j = Math.max(0, a); j <= b; j++) s += at(j); return s; };
  const ev = sum(0, i), a12 = sum(i - 11, i), a24 = sum(i - 23, i), h = at(i), h3 = sum(i - 2, i);
  const fut = []; for (let j = i + 1; j <= Math.min(D.frames.length - 1, i + 6); j++) fut.push([at(j), +D.frames[j].tm.slice(8, 10)]);
  const fm = Math.max(0, ...fut.map(x => x[0])), fh = fut.filter(x => x[0] >= VV("하천_통제_시우량")).length;
  const night = fut.some(([v, hr]) => v >= VV("산사태_사전대피_야간예보시우량") && (hr >= 22 || hr <= 6));   // 정시 값은 앞 한 시간 — 22~06시 정시 = 21~06시 비
  const n0 = v => Math.round(v), n1 = v => +v.toFixed(1);
  const L = [], add = (lv, t, k) => L.push({ lv, t, k });
  if (a12 >= VV("산사태_긴급대피_12시간") || a24 >= VV("산사태_긴급대피_24시간")) add(5, `지난 12시간 ${n0(a12)}㎜ · 24시간 ${n0(a24)}㎜ — 산사태 <b>긴급대피</b> 기준(12시간 ${VV("산사태_긴급대피_12시간")} · 24시간 ${VV("산사태_긴급대피_24시간")}㎜) 이상`, "산사태_긴급대피_12시간");
  else if (a12 >= VV("산사태_사전대피_12시간") || a24 >= VV("산사태_사전대피_24시간")) add(4, `지난 12시간 ${n0(a12)}㎜ · 24시간 ${n0(a24)}㎜ — 산사태 <b>사전대피</b> 기준(${VV("산사태_사전대피_12시간")} · ${VV("산사태_사전대피_24시간")}㎜) 이상`, "산사태_사전대피_12시간");
  else if (a12 >= VV("산사태_통제_12시간") || a24 >= VV("산사태_통제_24시간")) add(3, `지난 12시간 ${n0(a12)}㎜ · 24시간 ${n0(a24)}㎜ — 산사태 <b>통제</b> 기준(${VV("산사태_통제_12시간")} · ${VV("산사태_통제_24시간")}㎜) 이상`, "산사태_통제_12시간");
  if (fm >= VV("산사태_사전대피_예보시우량")) add(4, `앞으로 6시간 안에 시간당 ${n0(fm)}㎜ — 산사태 <b>사전대피</b> 기준(${VV("산사태_사전대피_예보시우량")}㎜/h 예보)`, "산사태_사전대피_예보시우량");
  else if (night) add(4, `밤(21~06시)에 시간당 ${VV("산사태_사전대피_야간예보시우량")}㎜ 이상 — 산사태 <b>사전대피</b>(취약시간대) 기준`, "산사태_사전대피_야간예보시우량");
  if (ev >= VV("하천_긴급대피_누적") && h >= VV("하천_긴급대피_시우량")) add(5, `이번 비 ${n0(ev)}㎜에 지금 시간당 ${n1(h)}㎜ — 하천 <b>긴급대피</b> 기준(누적 ${VV("하천_긴급대피_누적")}㎜ + 실제 ${VV("하천_긴급대피_시우량")}㎜/h)`, "하천_긴급대피_누적");
  else if (ev >= VV("하천_사전대피_누적") && fm >= VV("하천_사전대피_예보시우량")) add(4, `이번 비 ${n0(ev)}㎜인데 앞으로 시간당 ${n0(fm)}㎜ — 하천 <b>사전대피</b> 기준(누적 ${VV("하천_사전대피_누적")}㎜ + ${VV("하천_사전대피_예보시우량")}㎜/h 예보)`, "하천_사전대피_누적");
  if (fh >= VV("하천_통제_지속시간")) add(3, `앞으로 시간당 ${VV("하천_통제_시우량")}㎜ 이상이 ${fh}시간 — 하천 <b>통제</b> 기준(${VV("하천_통제_시우량")}㎜/h · ${VV("하천_통제_지속시간")}시간 이상 예보)`, "하천_통제_시우량");
  if (h >= VV("지하공간_긴급대피_시우량")) add(5, `지금 시간당 ${n1(h)}㎜ — 지하공간 <b>긴급대피</b> 시우량(${VV("지하공간_긴급대피_시우량")}㎜/h) 이상. 15분 ${VV("지하공간_긴급대피_15분")}㎜ 조건은 따로 확인`, "지하공간_긴급대피_시우량");
  else if (fm >= VV("지하공간_사전대피_예보시우량")) add(4, `앞으로 시간당 ${n0(fm)}㎜ — 지하공간 <b>사전대피</b> 시우량(${VV("지하공간_사전대피_예보시우량")}㎜/h 예보) 이상(15분 조건 따로 확인)`, "지하공간_사전대피_예보시우량");
  if (h >= VV("긴급재난문자_1시간_단독") || (h >= VV("긴급재난문자_1시간") && h3 >= VV("긴급재난문자_3시간"))) add(5, `1시간 ${n1(h)}㎜ · 3시간 ${n0(h3)}㎜ — 기상청 호우 <b>긴급재난문자</b> 기준(1시간 ${VV("긴급재난문자_1시간")} + 3시간 ${VV("긴급재난문자_3시간")}, 또는 1시간 ${VV("긴급재난문자_1시간_단독")}㎜)`, "긴급재난문자_1시간");
  else if (h >= VV("상황전파_1시간")) add(2, `시간당 ${n1(h)}㎜ — 시군 재난상황실 <b>유선 전파</b> 기준(${VV("상황전파_1시간")}㎜/h)`, "상황전파_1시간");
  L.sort((a, b) => b.lv - a.lv);
  const past = ev >= VV("하천_사전대피_누적") ? `이미 ${n0(ev)}㎜가 와 땅과 하천이 가득 찬 상태` : ev >= VV("상황전파_일") ? `이미 ${n0(ev)}㎜가 왔고` : `아직 많이 오지 않았고(${n0(ev)}㎜)`;
  const now = h >= VV("긴급재난문자_1시간") ? `지금 매우 강한 비(시간당 ${n1(h)}㎜)` : h >= VV("상황전파_1시간") ? `지금도 강한 비(시간당 ${n1(h)}㎜)` : h >= 5 ? `지금은 약한 비(${n1(h)}㎜)` : "지금은 비가 멎어 있음";
  const fu = fm >= VV("산사태_사전대피_예보시우량") ? `앞으로 6시간 안에 시간당 ${n0(fm)}㎜ 큰비` : fm >= VV("하천_사전대피_예보시우량") ? `앞으로 시간당 ${n0(fm)}㎜가 더 옴` : fm >= VV("상황전파_1시간") ? `앞으로 시간당 ${n0(fm)}㎜ 정도 더 옴` : "앞으로 6시간 큰비 없음";
  let txt = `${past}, ${now}. ${fu}.`;
  if (ev >= VV("상황전파_일") && h < 5 && fm >= VV("하천_사전대피_예보시우량")) txt += ` <span style="color:#f2903f">잠시 그쳤지만 다시 온다 — 해제하지 말고 유지.</span>`;
  else if (ev >= VV("상황전파_일") && h < 5 && fm < VV("상황전파_1시간") && !L.some(x => x.lv >= 4)) txt += ` <span style="color:#3fc1ae">고비를 넘긴 것으로 보인다 — 현장 확인 뒤 해제 검토.</span>`;
  const lv = L.length ? L[0].lv : bvTier(...[ev, h, fm].map((v, k) => [D.acc, D.h1, D.fut][k].filter(c => v >= c).length));
  return { ev, a12, a24, h, h3, fm, L, sum: txt, lv };
}
/* 칸(행 남→북 r, 열 c) → 설명 HTML. 경남 땅이 아니면 "" */
function bvTip(r, c) {
  const D = BV.D;
  if (!D || r < 0 || c < 0 || r >= D.h || c >= D.w) return "";
  if (!BV.HV) return `<div class="bvt">설명 자료를 읽는 중…</div>`;
  const p = (D.h - 1 - r) * D.w + c, em = BV.EMD[p];       // 그림은 위가 북 — 행을 뒤집는다
  if (!em || !D.emd[em]) return "";
  const X = bvExplain(p, BV.i), t = BV_TIERS[X.lv], f = D.frames[BV.i];
  const src = k => (D.v[k]?.src || "").replace(/ · 계획.*$/, "").replace(/\s*\(전문.*\)$/, "");
  return `<div class="bvt"><div class="hd"><span class="tier" style="background:${t[1]}">${t[0]}</span><b>${escH(D.emd[em])}</b><small>${bvFmt(f.tm)}${f.fc ? " 예보" : ""}</small></div>
    <div class="sum">${X.sum}</div>
    <div class="vals"><span>이번 비 <b>${Math.round(X.ev)}㎜</b></span><span>12시간 <b>${Math.round(X.a12)}㎜</b></span><span>24시간 <b>${Math.round(X.a24)}㎜</b></span>
      <span>1시간 <b>${X.h.toFixed(1)}㎜</b></span><span>3시간 <b>${Math.round(X.h3)}㎜</b></span><span>앞 6시간 최대 <b>${Math.round(X.fm)}㎜/h</b></span></div>
    ${X.L.length ? `<ul>${X.L.map(l => `<li style="--c:${BV_TIERS[l.lv][1]}">${l.t}<small>근거 — ${escH(src(l.k))}${D.v[l.k]?.doc ? ` · 위키 [[${escH(D.v[l.k].doc)}]]` : ""}</small></li>`).join("")}</ul>` : `<div class="ft">넘은 통제 · 대피 기준 없음</div>`}
    <div class="ft">500m 칸 하나의 값. ${D.live ? "'앞으로'는 지난 시각이면 실제로 온 비, 지금부터는 초단기예보(5km)." : "사례 — '앞으로'는 실제로 온 비."}</div></div>`;
}

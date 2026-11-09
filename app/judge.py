"""상황판단 모드의 지구 한 줄 — 위키 우려지역 지구 × 두 강수 기준(기상청 격자 · AWS 면)의 통제 · 사전대피 · 긴급대피 %.

지구 좌표(app/geocode.py)가 있으면 그 자리 강수(둘레 1.5km 최대 칸, 기준마다)로 사다리를 다시 대조한다 — where="지구".
좌표가 없으면 그 읍면동의 최대 칸 — where="읍면동"(같은 읍면동 · 같은 유형 지구는 % 가 같다).
예보 시우량 · 선행 5일은 읍면동 값 그대로(5km 예보라 지구까지 나눠지지 않는다). 연락처는 넣지 않는다 — 화면이 /api/contacts 로 따로(잠금 뒤).
기준 판정은 ai.ladders 그대로 — 여기는 지구 값으로 다시 부르고 묶고 줄 세우기만.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import re
from datetime import datetime

from . import ai, contacts, safety, terrain

STAGES = ("통제", "사전대피", "긴급대피")
FAMS = ("산사태", "하천", "지하공간")
BUCKETS = (50, 70, 80, 90, 100)
_C: dict = {}
TTL = 60


def _best(cs: list[dict], stage: str) -> dict | None:
    o = {"met": 3, "near": 2, "no": 1, "unknown": 0}
    c = [x for x in cs if x["stage"] == stage]
    return max(c, key=lambda x: (o[x["st"]], (x.get("gap") or {}).get("pct") or -1)) if c else None


def pack(e: dict, fam: str, rule: str) -> dict:
    """읍면동 한 줄(situation emd) → 그 유형의 단계별 % · 도달 시각 · 그 지구 대피기준 % · 강수."""
    st = {}
    for s in STAGES:
        c = _best(e["ladders"].get(fam, []), s)
        if not c:
            continue
        g = c.get("gap") or {}
        met = c["st"] == "met"
        ei = (g.get("eta") or {}).get("i")
        st[s] = {"pct": max(100, g.get("pct") or 0) if met else (g.get("pct") or 0), "met": met,
                 "unk": c["st"] == "unknown", "eta": (g.get("eta") or {}).get("at"), "eta_h": None if ei is None else ei + 1,
                 "rule": c["rule"], "partial": bool(g.get("partial")),
                 # 조건 하나하나(그리고로 묶임) — 지금 · 필요 · % · 단위. 상세 칸이 '무엇이 모자라나'를 보인다
                 "parts": [{k: p.get(k) for k in ("label", "now", "need", "unit", "pct")} for p in g.get("parts") or []]}
    sx = next((x for x in e.get("sites", []) if (x["rule"] or "").strip() == rule), None)
    site = sx["max_pct"] if sx else None
    return {"rain": {k: e["rain"].get(k) for k in ("1h", "3h", "24h")}, "st": st, "site": site,
            "site_parts": [{"label": c.get("label"), "now": c.get("now"), "need": c.get("mm"), "unit": "㎜", "pct": c.get("pct")}
                           for c in (sx or {}).get("conds", [])],
            "top": max([v["pct"] for v in st.values()] + [site or 0])}


def slide_of(sg: str) -> dict:
    """그 시군에 지금 걸린 산사태 예보(시장 · 군수) · 예측(산림청) — app/safety.py 가 받아 둔 것."""
    on = lambda xs: next((x for x in sorted(xs, key=lambda x: -x["lv"]) if x["sigun"] == sg and x["on"]), None)  # noqa: E731
    f, p = on(safety._LIVE["fcst"]), on(safety._LIVE["pred"])
    return {"fcst": {"kind": f["kind"], "lv": f["lv"], "at": f["at"]} if f else None,
            "pred": {"kind": p["kind"], "lv": p["lv"], "at": p["at"]} if p else None}


_SLIDE_RULE = re.compile(r"산사태\s*(예보|주의보|경보)\s*발령")


def slide_site(rule: str, sl: dict) -> int | None:
    """지구 대피기준이 '산사태 경보 발령 시' · '산사태예보 발령 시' 꼴이면 — 발령 중이면 100, 아니면 0. 그런 기준이 아니면 None."""
    m = _SLIDE_RULE.search(rule or "")
    if not m:
        return None
    need = 2 if m.group(1) == "경보" else 1
    lv = max((sl[k]["lv"] for k in ("fcst", "pred") if sl.get(k)), default=0)
    return 100 if lv >= need else 0


_SOIL = re.compile(r"토양\s*함수[^%]{0,30}?(\d+)\s*%")


def soil_site(rule: str, pred_lv: int | None) -> dict | None:
    """지구 기준의 '토양함수율 90%' — 산림청 예측정보(시군 단위)로 명백한 것만. 주의보 = 지수 80% · 경보 = 100%(위키 [[산사태 예측정보와 토양함수지수]]).
    pred_lv: 2 경보 · 1 주의보 · 0 없음(받았는데 발령 없음 = 80% 미만) · None 받지 못함. 기준이 아니면 None.
    st: met(충족) · check(80~100 사이라 산사태정보시스템에서 확인) · no(80% 미만) · unknown"""
    m = _SOIL.search(rule or "")
    if not m:
        return None
    need = int(m.group(1))
    lo, hi = {2: (100, None), 1: (80, 100), 0: (None, 80)}.get(pred_lv, (None, None))
    st = ("unknown" if pred_lv is None else "met" if lo is not None and lo >= need
          else "no" if hi is not None and hi <= need and pred_lv == 0 else "check")
    return {"need": need, "st": st, "lv": pred_lv,
            "now": {2: "100%↑(경보)", 1: "80~100%(주의보)", 0: "80% 미만(발령 없음)"}.get(pred_lv)}


def _pred_lv(sl: dict) -> int | None:
    """산림청 예측정보 — 2시간 안에 받았으면 그 시군 단계(없으면 0), 못 받았으면 None(산사태는 호우 · 태풍 특보 때만 받는다)."""
    at = safety._LIVE["at"].get("pred")
    if not at or time.time() - datetime.fromisoformat(at).timestamp() > 2 * 3600:
        return None
    return (sl.get("pred") or {}).get("lv") or 0


def _sit(sg: str, base: str, k: float, basis: str, add: tuple = (0.0, 0.0)) -> dict:
    key = (sg, base, k, basis, add)
    hit = _C.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    v = ai.situation(sg, base, k, basis, *add)
    _C[key] = (time.time(), v)
    return v


def _pts(base: str, basis: str) -> dict:
    """지구 자리 강수 {지구ID: {1h, 3h, …, 15m}} — 좌표가 없거나 못 받으면 빈 것(읍면동 기준으로 떨어진다)."""
    try:
        return ai._get(base, "/api/ai/emdwin", basis=basis, pts=1).get("pts") or {}
    except Exception:                                          # noqa: BLE001
        return {}


def at_point(e: dict, p: dict | None, s: dict, fam: str, rule: str) -> dict:
    """읍면동 줄 e 를 지구 자리 강수 p 로 바꿔 그 유형 사다리 · 지구 대피기준을 다시 대조한다. p 가 없으면 e 그대로."""
    if not p:
        return e
    rain = {h: p.get(h, e["rain"].get(h)) for h in e["rain"]}
    row = {**e, "rain": rain, "m15": p.get("15m", e.get("m15"))}
    row["ladders"] = {fam: ai.ladders(row, s["night"], s["alerts"], s.get("river"), s.get("flood")).get(fam, [])}
    prog = [{**c, "now": rain.get(f"{c['win']}h"),
             "pct": None if rain.get(f"{c['win']}h") is None else round(rain[f"{c['win']}h"] / c["mm"] * 100)}
            for c in ai.conditions(rule)] if fam == "산사태" else []
    row["sites"] = [{"rule": rule, "conds": prog, "max_pct": max((c["pct"] or 0 for c in prog), default=None)}] if prog else []
    return row


_ACC = re.compile(r"누적|일|12시간|24시간|48시간|선행")


def plane(lad: list[dict], stage: str, rule: str | None) -> tuple[list, list] | None:
    """조건 평면 한 점 — 그 단계 기준(rule)의 조건들을 쌓이는 것(가로) · 시간당 · 예보 · 수위(세로)로 나눠 각 % 중 큰 것.
    한쪽 조건이 없는 기준은 대각선(그 조건 하나로 오른쪽 위 칸이 갈린다). 모르는 조건만 있으면 None."""
    c = next((x for x in lad if x["stage"] == stage and x["rule"] == rule), None)
    parts = [q for q in ((c or {}).get("gap") or {}).get("parts") or [] if q.get("pct") is not None]
    if not parts:
        return None
    a = [q for q in parts if _ACC.search(q.get("label") or "")]
    h = [q for q in parts if q not in a]
    x = max((q["pct"] for q in a), default=None)
    y = max((q["pct"] for q in h), default=None)
    lab = [" · ".join(q["label"] for q in a), " · ".join(q["label"] for q in h)]
    return [x if x is not None else y, y if y is not None else x], lab


def series_of(e: dict, s: dict, fam: str, rule: str) -> dict | None:
    """앞으로 시간마다 그 지구의 가장 높은 단계 % — 차트 줄 · 재생. e 는 지구 자리로 바꾼 줄(at_point 뒤).
    t 시각의 비 = 지금 누적 + 그때까지 예보 합(창에서 빠지는 옛 비는 빼지 않는다 — 도달 시각과 같은 가정),
    1시간 = 그 시각 예보 시우량, 15분 = 모름. 예보 시우량 조건은 그 뒤 6시간 예보로. 야간(21~06시)은 그 시각으로.
    ⚠️ 예보 끝 시각은 넣지 않는다 — 뒤 예보가 없어 예보 조건이 '모름'으로 빠지면 누적만 남아 % 가 튀었다."""
    fh, fl = e.get("eta_hours") or e.get("fc_hours") or [], e.get("eta_labels") or e.get("fc_labels") or []
    if not fh:
        return None
    r0, cut30 = e["rain"], ai.R("하천_통제_시우량")
    out, cum = [], 0.0
    # 단계 영역 평면 — 시각마다 (누적 = 24 · 48시간 중 큰 것, 시우량, 15분). 앞으로의 15분은 예보가 없어 None
    acc = lambda rn: max((rn.get(h) for h in ("24h", "48h") if rn.get(h) is not None), default=None)  # noqa: E731
    pl = [[acc(r0), r0.get("1h"), e.get("m15")]]
    # 조건 평면 — 단계마다 '지금 가장 많이 찬 기준'을 끝까지 같은 축으로(시각마다 기준이 바뀌면 점이 다른 축으로 튄다)
    now = pack(e, fam, rule)["st"]
    rule0 = {st: v["rule"] for st, v in now.items()}
    xy = {st: [] for st in rule0}
    ax = {}
    for st in rule0:
        pt = plane(e["ladders"].get(fam, []), st, rule0[st])
        xy[st].append(pt[0] if pt else None)
        if pt:
            ax[st] = pt[1]
    for i, v in enumerate(fh[:-1]):
        v = v or 0
        cum += v
        rain = {h: None if r0.get(h) is None else round(r0[h] + cum, 1) for h in r0}
        rain["1h"] = v
        rain["3h"] = round(sum(fh[max(0, i - 2):i + 1]) + (r0.get("3h") or 0) * max(0, 2 - i) / 3, 1)
        nxt = fh[i + 1:i + 7]
        run = best = 0
        for x in nxt:
            run = run + 1 if (x or 0) >= cut30 else 0
            best = max(best, run)
        hh = re.search(r"(\d{1,2})$", str(fl[i]) if i < len(fl) else "")
        night = s["night"] if not hh else int(hh.group(1)) >= 21 or int(hh.group(1)) < 6
        row = {**e, "fc_hours": nxt, "fc_labels": fl[i + 1:i + 7], "eta_hours": fh[i + 1:], "eta_labels": fl[i + 1:],
               "fc_peak": max(nxt) if nxt else None, "fc_run30": best}
        pl.append([acc(rain), v, None])
        p = at_point(row, {**rain, "15m": None}, {**s, "night": night}, fam, rule)
        out.append(pack(p, fam, rule)["top"])
        for st in rule0:
            pt = plane(p["ladders"].get(fam, []), st, rule0[st])
            xy[st].append(pt[0] if pt else None)
    return {"t": list(fl[:len(out)]), "v": out, "xy": xy, "ax": ax, "rule": rule0, "pl": pl, "site": ai.site_area(rule)}


def past_of(sr: dict | None, hrs: list | None, n: int = 48) -> dict | None:
    """평면의 지난 자취 pp — 지금에서 거꾸로 n 시간: 누적 = 지금 누적 − 그 뒤 온 비, 시우량 = 그 시각 매시 값. 오래된 것부터, 끝은 지금 바로 앞.
    hrs 는 지구 자리 매시(gridview._pt_hours, 오래된 것부터). 빈 시각은 0 으로 뺀다(누적이 덜 줄어 — 자취가 지금 쪽으로 붙는다)."""
    if not sr or not hrs or not sr.get("pl") or sr["pl"][0][0] is None:
        return sr
    a0, out, cum = sr["pl"][0][0], [], 0.0
    hs = hrs[-n:]
    for k in range(len(hs) - 1, 0, -1):                       # hs[k] = 그 시각까지 1시간 — 그 앞 시각의 점은 그만큼 뺀다
        cum += hs[k] or 0
        out.append([round(max(a0 - cum, 0), 1), hs[k - 1], None])
    sr["pp"] = out[::-1]
    return sr


def rows_of(sg: str, base: str, k: float, add: tuple = (0.0, 0.0), series: bool = False, sb: str | None = None) -> tuple[list[dict], dict]:
    g, a = _sit(sg, base, k, "grid", add), _sit(sg, base, k, "aws", add)
    ga = {e["emd"]: e for e in a["emd"]}
    pg, pa = _pts(base, "grid"), _pts(base, "aws")
    dist = contacts.districts(sg)["emd"]
    sl = slide_of(sg)
    plv = _pred_lv(sl)
    out = []
    for e in g["emd"]:
        for d in dist.get(e["emd"], []):
            if d["fam"] not in e["ladders"]:
                continue
            ea = ga.get(e["emd"])
            eg, ea2 = at_point(e, pg.get(d["id"]), g, d["fam"], d["rule"]), ea and at_point(ea, pa.get(d["id"]), a, d["fam"], d["rule"])
            b = {"grid": pack(eg, d["fam"], d["rule"]), "aws": pack(ea2, d["fam"], d["rule"]) if ea else None}
            if series and sb != "aws":
                b["grid"]["series"] = past_of(series_of(eg, g, d["fam"], d["rule"]), (pg.get(d["id"]) or {}).get("hrs"))
            if series and sb != "grid" and ea:
                b["aws"]["series"] = past_of(series_of(ea2, a, d["fam"], d["rule"]), (pa.get(d["id"]) or pg.get(d["id"]) or {}).get("hrs"))
            ss = slide_site(d["rule"], sl) if d["fam"] == "산사태" else None
            for v in b.values():                             # 산사태 예보 발령이 기준인 지구 — 강수가 아니라 발령으로
                if v and ss is not None:
                    v.update(site=ss, site_slide=True, top=max(v["top"], ss))
            out.append({"sigun": sg, "emd": e["emd"], **d, "b": b, "slide": sl if d["fam"] == "산사태" else None,
                        "soil": soil_site(d["rule"], plv), "terrain": terrain.of(d),   # 지역 여건(지형 · 침수흔적) — 판정 % 는 그대로
                        "where": "지구" if d["id"] in pg else "읍면동",
                        "fc6h": e.get("fc6h"), "later": e.get("later")})
    return out, g


def build(sigun: str, base: str, k: float = 1.0, add_h: float = 0.0, add_24: float = 0.0, series: bool = False, sb: str | None = None) -> dict:
    sgs = list(ai.SIGUN_FULL) if sigun == "all" else [sigun]
    with ThreadPoolExecutor(max_workers=4) as ex:
        got = list(ex.map(lambda s: (s, *rows_of(s, base, k, (add_h, add_24), series, sb)), sgs))
    rows, chart, head = [], [], None
    for sg, rs, g in got:
        rows += rs
        tops = {b: [(r["fam"], r["b"][b]["top"]) for r in rs if r["b"][b]] for b in ("grid", "aws")}
        chart.append({"sigun": sg, "n": len(rs),
                      "b": {b: {str(t): sum(1 for _, v in tops[b] if v >= t) for t in BUCKETS} for b in tops},
                      # 시군 × 유형 — 지구 수 · 가장 많이 찬 % · 문턱별 지구 수(화면의 'N% 이상' 문턱으로 센다)
                      "fam": {b: {f: {"n": sum(1 for x, _ in tops[b] if x == f), "top": max((v for x, v in tops[b] if x == f), default=None),
                                      "v": sorted((v for x, v in tops[b] if x == f), reverse=True)} for f in FAMS} for b in tops}})
        if sigun != "all":
            rv = max(g.get("flood") or [], key=lambda x: x.get("stage") or 0, default=None)
            head = {"alerts": g["alerts"], "stage": g["stage"], "tm": g["tm"],
                    "river": {"name": rv["name"], "v": rv["v"], "stage": rv["stage"]} if rv else None,
                    "fc6h": max((r["fc6h"] or 0 for r in g["emd"]), default=0),
                    "later": {"today": max((r["later"]["today"] for r in g["emd"] if r.get("later")), default=0),
                              "tomorrow": max((r["later"]["tomorrow"] for r in g["emd"] if r.get("later")), default=0)}}
        tm = g["tm"]
    rows.sort(key=lambda r: -r["b"]["grid"]["top"])
    st = safety.status()
    slide = {"keys": st["keys"]["fcst"] or st["keys"]["pred"], "why": st["slide"]["why"], "at": st["at"].get("fcst")}
    return {"slide": slide, "terrain_built": terrain.table().get("built"), "sigun": sigun, "k": k, "add_h": add_h, "add_24": add_24, "tm": tm, "rows": rows, "chart": chart, "head": head,
            "regions": ai.regions() if series else None}

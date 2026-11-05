"""상황판단 모드의 지구 한 줄 — 위키 우려지역 지구 × 두 강수 기준(기상청 격자 · AWS 면)의 통제 · 사전대피 · 긴급대피 %.

⚠️ 지구 좌표가 아직 없다(지오코딩 전) → 지구 값은 그 읍면동의 최대 칸(기준마다). 같은 읍면동 · 같은 유형 지구는 % 가 같다.
   지구 대피기준(원문)만 지구마다 다르다. 연락처는 넣지 않는다 — 화면이 /api/contacts 로 따로(잠금 뒤).
기준 판정은 ai.situation(ladders) 그대로 — 여기는 묶고 줄 세우기만.
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

import re

from . import ai, contacts, safety

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


def _sit(sg: str, base: str, k: float, basis: str, add: tuple = (0.0, 0.0)) -> dict:
    key = (sg, base, k, basis, add)
    hit = _C.get(key)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    v = ai.situation(sg, base, k, basis, *add)
    _C[key] = (time.time(), v)
    return v


def rows_of(sg: str, base: str, k: float, add: tuple = (0.0, 0.0)) -> tuple[list[dict], dict]:
    g, a = _sit(sg, base, k, "grid", add), _sit(sg, base, k, "aws", add)
    ga = {e["emd"]: e for e in a["emd"]}
    dist = contacts.districts(sg)["emd"]
    sl = slide_of(sg)
    out = []
    for e in g["emd"]:
        for d in dist.get(e["emd"], []):
            if d["fam"] not in e["ladders"]:
                continue
            ea = ga.get(e["emd"])
            b = {"grid": pack(e, d["fam"], d["rule"]), "aws": pack(ea, d["fam"], d["rule"]) if ea else None}
            ss = slide_site(d["rule"], sl) if d["fam"] == "산사태" else None
            for v in b.values():                             # 산사태 예보 발령이 기준인 지구 — 강수가 아니라 발령으로
                if v and ss is not None:
                    v.update(site=ss, site_slide=True, top=max(v["top"], ss))
            out.append({"sigun": sg, "emd": e["emd"], **d, "b": b, "slide": sl if d["fam"] == "산사태" else None,
                        "fc6h": e.get("fc6h"), "later": e.get("later")})
    return out, g


def build(sigun: str, base: str, k: float = 1.0, add_h: float = 0.0, add_24: float = 0.0) -> dict:
    sgs = list(ai.SIGUN_FULL) if sigun == "all" else [sigun]
    with ThreadPoolExecutor(max_workers=4) as ex:
        got = list(ex.map(lambda s: (s, *rows_of(s, base, k, (add_h, add_24))), sgs))
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
    return {"slide": slide, "sigun": sigun, "k": k, "add_h": add_h, "add_24": add_24, "tm": tm, "rows": rows, "chart": chart, "head": head}

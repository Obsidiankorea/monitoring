"""데모(시연) 화면 — 실제로 비가 왔던 때를 그대로 되돌려 보여 준다.

평소 화면은 비가 안 오면 온통 0.0 이라 무엇을 보여 주는 화면인지 알 수 없다.
호우주의보·경보가 걸렸던 실제 사례를 담아 두고 그걸 띄운다.

**자료는 실측이다.** 스방 265개소의 시간강우량을 그 날짜로 그대로 받아 담는다.
지어낸 숫자가 아니다.

초단기예측도 실측이다 — 격자 API(`nph-dfs_vsrt_grd`)는 지난 발표분도 내준다.
다만 **예측 분포 이미지**(`nph-qpf_ana_img`)는 과거분이 404 라 데모에 넣을 수 없다.

⚠️ **특보만은 실측이 아니다.** 기상청 특보 이력 API(`wrn_met_data.php`)는 이 키로
   403 이라 과거 발표 내역을 받을 수 없다. 그래서 담긴 강수량에 기상청 **호우 특보
   기준**을 그대로 적용해 산출한다. 화면에 `산출` 이라고 적어 발표 내역과 구분한다.

        호우주의보  3시간 60mm 이상  또는 12시간 110mm 이상
        호우경보    3시간 90mm 이상  또는 12시간 180mm 이상
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

from .bangjae import Client
from .config import DATA
from .domain.regions import ORDER

log = logging.getLogger("demo")

DEMO_DIR = DATA / "demo"

#: 담아 둘 사례. 스방은 최근 며칠치만 남기므로 **미리 받아 파일로 굳혀** 둔다.
CASES = {
    "20260828": {
        "title": "2026.8.28. 경남 호우",
        "note": "김해 율하 123.5㎜/일, 창원 111.0㎜/일. 8.27. 11시 진영 47.5㎜/시.",
        "fr": "20260827", "to": "20260829",
    },
    # ⚠️ 위 사례는 기준선에 딱 걸쳐 있어(최대 3시간 60.0㎜, 12시간 109.5㎜)
    #    주의보 한 곳밖에 안 나온다. 경보까지 걸린 화면을 시연하려면 배율이 필요하다.
    #    **지어낸 화면이므로** 화면 어디서나 '가상'이라고 밝힌다.
    # 사흘을 통째로 보면 비가 언제 셌는지 뭉개진다. 봉우리(8.28. 11시)에서 끊어
    # '지금 한창 오는 중'인 화면을 만든다 — 그때의 초단기예측도 함께 담긴다.
    "20260828peak": {
        "title": "2026.8.28. 11시 — 한창 올 때",
        "note": "봉우리에서 끊은 화면. 그 시각 발표된 초단기예측이 함께 담겼다.",
        "from": "20260828", "cut": "2026-08-28 11:00",
    },
    "20260828x2": {
        "title": "2026.8.28. 호우 ×2 (가상)",
        "note": "같은 사례의 실측값을 두 배로 키운 시연용. 실제 발생한 값이 아니다.",
        "fr": "20260827", "to": "20260829", "scale": 2.0, "fake": True,
    },
}

# 호우 특보 기준 (3시간, 12시간) mm
WATCH = (60, 110)
WARN = (90, 180)


def _window(fr: str, to: str) -> list[str]:
    a = datetime.strptime(fr, "%Y%m%d")
    b = datetime.strptime(to, "%Y%m%d")
    out, d = [], a
    while d <= b:
        out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def _max_run(vals: list[float | None], win: int) -> float:
    """연속 `win` 칸 합의 최대. 결측은 0으로 세지 않고 건너뛴다."""
    best = 0.0
    for i in range(len(vals)):
        s = sum(v for v in vals[i:i + win] if v is not None)
        best = max(best, s)
    return round(best, 1)


def _alerts(rows: list[dict], labels: list[str], base: str) -> dict:
    """담긴 강수량에 호우 기준을 적용해 특보를 산출한다.

    시군 안에서 가장 센 지점이 그 시군의 등급을 정한다 — 특보는 구역 단위라
    한 지점만 넘어도 그 구역에 걸린다.
    """
    lv_of: dict[str, str] = {}
    hit: dict[str, tuple[float, float, str]] = {}
    for r in rows:
        sig = r["sigun"]
        h3, h12 = _max_run(r["d"], 3), _max_run(r["d"], 12)
        lv = None
        if h3 >= WARN[0] or h12 >= WARN[1]:
            lv = "warn"
        elif h3 >= WATCH[0] or h12 >= WATCH[1]:
            lv = "watch"
        if not lv:
            continue
        if lv_of.get(sig) != "warn":
            lv_of[sig] = lv
        old = hit.get(sig)
        if not old or h3 > old[0]:
            hit[sig] = (h3, h12, r["name"])

    groups = []
    for lv, name in (("warn", "호우경보"), ("watch", "호우주의보")):
        sigs = sorted([s for s, v in lv_of.items() if v == lv],
                      key=lambda s: ORDER.index(s) if s in ORDER else 99)
        if not sigs:
            continue
        groups.append({
            "lv": lv, "name": name, "sea": False, "tmfc": base[11:16],
            "count": len(sigs), "unit": "개시군",
            "regions": sigs, "siguns": sigs,
            # 왜 이 등급인지 화면이 그대로 보여 줄 수 있게 근거를 남긴다
            "why": {s: {"h3": hit[s][0], "h12": hit[s][1], "stn": hit[s][2]} for s in sigs},
        })
    return {"groups": groups, "pending": []}


async def build(slug: str) -> dict:
    """스방에서 그 날짜를 받아 파일로 굳힌다. 한 번만 하면 된다."""
    case = CASES.get(slug)
    if not case:
        raise KeyError(f"모르는 사례: {slug}")
    if case.get("from"):
        return await build_cut(slug)
    days = _window(case["fr"], case["to"])
    scale = float(case.get("scale", 1) or 1)

    per: dict[str, dict] = {}
    async with Client() as c:
        for day in days:
            iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
            for st in await c.station_hourly(day):
                row = per.setdefault(st["stn"], {"stn": st["stn"], "name": st["name"],
                                                 "sigun": st["sigun"], "v": {}})
                row["name"], row["sigun"] = st["name"], st["sigun"]
                for h, mm in enumerate(st["mm"]):
                    row["v"][f"{iso} {h:02d}:00"] = (
                        None if mm is None else round(mm * scale, 1))

    # 스방 시각 → 기상청 표기 칸(한 칸 뒤로). 화면이 쓰는 축과 같아야 한다.
    slots = []
    for day in days:
        iso = f"{day[:4]}-{day[4:6]}-{day[6:]}"
        for h in range(24):
            slots.append(f"{iso} {h:02d}:00")
    slots = slots[1:]                       # 첫 칸은 앞날 23시가 있어야 채워진다
    back = {s: (datetime.strptime(s, "%Y-%m-%d %H:00")
                - timedelta(hours=1)).strftime("%Y-%m-%d %H:00") for s in slots}

    from .domain.regions import REP_STN
    rows = []
    for st in per.values():
        vals = [st["v"].get(back[s]) for s in slots]
        ok = [v for v in vals if v is not None]
        rows.append({"stn": st["stn"], "name": st["name"], "sigun": st["sigun"],
                     "rep": REP_STN.get(st["sigun"]) == st["stn"],
                     "d": vals, "m60": None,
                     "sum": round(sum(ok), 1), "bad": len(vals) - len(ok)})
    rows.sort(key=lambda r: (ORDER.index(r["sigun"]) if r["sigun"] in ORDER else 99, r["name"]))

    labels = [s[11:13] for s in slots]
    base = slots[-1]
    bundle = {
        "slug": slug, "title": case["title"], "note": case["note"],
        "fake": bool(case.get("fake")), "scale": scale,
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "span": [slots[0][:16], slots[-1][:16]],
        "rain": {"labels": labels, "hours": len(labels), "src": "bangjae",
                 "src_label": f"스방 {len(rows)}개소", "count": len(rows),
                 "base_hour": base[11:16], "minute_tm": None, "missing": 0,
                 "rows": rows},
        "alerts": {"base_time": base, "fetched_at": base,
                   "derived": True, "data": _alerts(rows, labels, base)},
    }
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    (DEMO_DIR / f"{slug}.json").write_text(
        json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    log.info("데모 %s 저장: %d지점 %d칸", slug, len(rows), len(labels))
    return bundle


async def forecast_at(tmfc: str, hours: int = 6) -> dict:
    """지난 발표분의 초단기예측. `queries.forecast()` 와 같은 모양으로 돌려준다.

    격자 API 는 지난 발표시각도 내준다 — 그래서 데모에 **실제 예측**을 담을 수 있다.
    (예측 분포 이미지는 과거분이 404 라 못 담는다)
    """
    from .collectors.forecast import _grid, _pick
    from .domain.regions import grids as _grids

    base = datetime.strptime(tmfc, "%Y%m%d%H%M")
    width = _grids().get("grid_width", 149)
    labels, per = [], {}
    for h in range(1, hours + 1):
        tmef = (base + timedelta(hours=h)).replace(minute=0).strftime("%Y%m%d%H%M")
        vals = await _grid(tmfc, tmef)
        rows = _pick(vals, width)
        if not rows:
            continue
        labels.append(tmef[8:10])
        for sig, emds in rows.items():
            for emd, v in emds.items():
                per.setdefault((sig, emd), []).append(v)

    n = len(labels)
    emd_list = [{"sigun": sg, "emd": e, "d": (d + [0.0] * n)[:n],
                 "sum": round(sum(d), 1), "peak": max(d) if d else 0}
                for (sg, e), d in per.items()]
    emd_list.sort(key=lambda x: (-x["sum"], -x["peak"]))

    sig = []
    for sg in ORDER:
        mine = [e for e in emd_list if e["sigun"] == sg]
        if mine:
            t = mine[0]
            sig.append({"sigun": sg, "emd": t["emd"], "d": t["d"],
                        "sum": t["sum"], "peak": t["peak"]})
    sig.sort(key=lambda x: (-x["sum"], -x["peak"]))
    return {"tmfc": tmfc, "labels": labels, "emd": emd_list[:24], "sigun": sig}


async def build_cut(slug: str) -> dict:
    """이미 굳혀 둔 사례를 어느 시각에서 끊어 새 사례를 만든다.

    ⚠️ 스방은 며칠치만 남기므로 원본을 다시 받을 수 없다. 굳혀 둔 파일에서
       잘라 쓴다 — 그래서 처음부터 파일로 굳혀 두었다.
    """
    case = CASES[slug]
    src = load(case["from"])
    if src is None:
        raise KeyError(f"원본 사례가 없다: {case['from']}")
    cut = case["cut"]                                   # 'YYYY-MM-DD HH:00'
    day0 = datetime.strptime(src["span"][0], "%Y-%m-%d %H:%M")
    끝 = datetime.strptime(cut, "%Y-%m-%d %H:%M")
    keep = int((끝 - day0).total_seconds() // 3600) + 1
    if keep < 2 or keep > src["rain"]["hours"]:
        raise ValueError(f"끊을 자리가 범위 밖이다: {cut}")

    rain = dict(src["rain"])
    rain["labels"] = src["rain"]["labels"][:keep]
    rain["hours"] = keep
    rows = []
    for r in src["rain"]["rows"]:
        d = r["d"][:keep]
        ok = [v for v in d if v is not None]
        rows.append({**r, "d": d, "sum": round(sum(ok), 1), "bad": len(d) - len(ok)})
    rows.sort(key=lambda r: (ORDER.index(r["sigun"]) if r["sigun"] in ORDER else 99, r["name"]))
    rain["rows"] = rows

    bundle = {
        "slug": slug, "title": case["title"], "note": case["note"],
        "fake": bool(case.get("fake")), "scale": src.get("scale", 1),
        "built_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "span": [src["span"][0], cut],
        "rain": rain,
        "alerts": {"base_time": cut, "fetched_at": cut,
                   "derived": True, "data": _alerts(rows, rain["labels"], cut)},
        "forecast": await forecast_at(끝.strftime("%Y%m%d%H%M")),
    }
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    (DEMO_DIR / f"{slug}.json").write_text(
        json.dumps(bundle, ensure_ascii=False), encoding="utf-8")
    log.info("데모 %s 저장: %d칸, 예측 %d칸", slug, keep, len(bundle["forecast"]["labels"]))
    return bundle


def listing() -> list[dict]:
    out = []
    for slug, c in CASES.items():
        f = DEMO_DIR / f"{slug}.json"
        out.append({"slug": slug, "title": c["title"], "note": c["note"],
                    "fake": bool(c.get("fake")), "scale": float(c.get("scale", 1) or 1),
                    "ready": f.exists(),
                    "bytes": f.stat().st_size if f.exists() else 0})
    return out


def load(slug: str) -> dict | None:
    f = DEMO_DIR / f"{slug}.json"
    if not f.exists():
        return None
    return json.loads(f.read_text(encoding="utf-8"))

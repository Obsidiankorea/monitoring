"""경남 지도 판 — 층 이름을 풀어 격자를 찾고, 지연을 판정한다. DB·파일만 읽는다.

층(화면 이름)             저장 층   격자   기준시각
  obs15 · obs60 · obsday   같은 이름  500m   tm
  odam                     odam      5km    tm(10분 발표)
  vsrt+N (N=1~6)           vsrt      5km    가장 최근 발표분의 N번째 대상시각
  shrt_today · _tomorrow   shrt      5km    가장 최근 발표분의 그날 PCP 합

⚠️ 단기예보 '오늘'은 **발표 뒤 남은 시간만** 더한다(권역 예보 판과 같은 규칙).
   대상시각 H 는 (H-1)~H 시 몫이라 00시 값은 전날 몫이다.
⚠️ PCP 는 30 에서 막힌다(실측). 30 이 한 번이라도 든 칸은 합계가 **하한**이다 — 칸 수를 같이 준다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from . import db, gridstore
from .collectors.shortfc import base_of
from .domain import gridproj

LAYERS = [
    {"id": "obs15", "label": "15분 강수량", "short": "15분", "group": "실측", "grid": "hr",
     "src": "기상청 고해상도 격자(500m)", "stale_min": 25, "x4": True},
    {"id": "obs60", "label": "60분 강수량", "short": "60분", "group": "실측", "grid": "hr",
     "src": "기상청 고해상도 격자(500m)", "stale_min": 25},
    {"id": "obsday", "label": "오늘 누적", "short": "오늘", "group": "실측", "grid": "hr",
     "src": "기상청 고해상도 격자(500m)", "stale_min": 25},
    {"id": "odam", "label": "실황 1시간(5km)", "short": "실황 5km", "group": "실측", "grid": "dfs",
     "src": "기상청 동네예보 실황 RN1(5km)", "stale_min": 30},
    {"id": "vsrt", "label": "초단기 예측", "short": "초단기", "group": "예측", "grid": "dfs",
     "src": "기상청 초단기예보 RN1(5km)", "stale_min": 30},
    {"id": "shrt_today", "label": "단기 오늘 누적", "short": "단기 오늘", "group": "예측",
     "grid": "dfs", "src": "기상청 단기예보 PCP(5km)"},
    {"id": "shrt_tomorrow", "label": "단기 내일 누적", "short": "단기 내일", "group": "예측",
     "grid": "dfs", "src": "기상청 단기예보 PCP(5km)"},
]
BY_ID = {x["id"]: x for x in LAYERS}
PCP_CAP = 30.0

# 지연 판정 근거(평소 가장 늙은 때 + 여유):
#   500m  6분 물러선 5분 칸을 10분마다 → 평소 6~21분 → 25분
#   실황  발표 +3~13분, 10분마다 → 평소 ~25분 → 30분
#   초단기 발표 슬롯에서 10분 물러서고 10분마다 → 평소 10~30분 → 30분 넘으면
#   단기  발표 +20분부터 받는다 → 지금 받을 수 있는 발표분보다 30분 넘게 묵으면


def split(layer: str) -> tuple[str, int]:
    """'vsrt+3' · 'vsrt3' → ('vsrt', 3). 나머지는 (layer, 0)."""
    if layer.startswith("vsrt"):
        n = layer[4:].lstrip("+ ") or "1"
        if not n.isdigit() or not 1 <= int(n) <= 6:
            raise LookupError(f"초단기는 +1~+6 이다: {layer}")
        return "vsrt", int(n)
    if layer not in BY_ID:
        raise LookupError(f"모르는 층: {layer}")
    return layer, 0


def _dt(key: str) -> datetime:
    return datetime.strptime(key[:12].ljust(12, "0"), "%Y%m%d%H%M")


def vsrt_run(tmfc: str | None = None) -> tuple[str | None, list[str]]:
    runs: dict[str, list[str]] = {}
    for k in gridstore.keys("vsrt"):
        a, b = k.split("_")
        runs.setdefault(a, []).append(b)
    if not runs:
        return None, []
    t = tmfc if tmfc in runs else max(runs)
    return t, sorted(runs[t])


def shrt_run(tmfc: str | None = None) -> tuple[str | None, list[str]]:
    """다 받은 가장 최근 발표분(권역 예보 판과 같은 것). 지도 파일이 있어야 한다."""
    runs: dict[str, list[str]] = {}
    for k in gridstore.keys("shrt"):
        a, b = k.split("_")
        runs.setdefault(a, []).append(b)
    if not runs:
        return None, []
    if tmfc in runs:
        return tmfc, sorted(runs[tmfc])
    with db.tx() as con:
        done = [r["tmfc"] for r in con.execute(
            "SELECT tmfc FROM fcst_short_run WHERE complete=1 ORDER BY tmfc DESC")]
    t = next((x for x in done if x in runs), max(runs))
    return t, sorted(runs[t])


def _day_of(tmef: str) -> str:
    return (datetime.strptime(tmef[:10], "%Y%m%d%H") - timedelta(hours=1)).strftime("%Y%m%d")


def shrt_sum(tmfc: str, tmefs: list[str], day: str) -> dict:
    """그날 PCP 합. 한 시간이라도 결측이면 그 칸은 결측 — 0 으로 치고 더하지 않는다."""
    hours = [t for t in tmefs if _day_of(t) == day]
    if not hours:
        return {"arr": None, "hours": [], "capped": 0}
    tot = None
    capped = None
    for t in hours:
        a = gridstore.load("shrt", f"{tmfc}_{t}")
        if a is None:
            continue
        tot = a.copy() if tot is None else tot + a          # NaN 은 NaN 으로 남는다
        c = a >= PCP_CAP - 1e-9
        capped = c if capped is None else capped | c
    return {"arr": tot, "hours": hours,
            "capped": int(np.count_nonzero(capped)) if capped is not None else 0}


# ── 한 층의 한 장 ────────────────────────────────────────────────────────
def frame(layer: str, tm: str | None = None, now: datetime | None = None,
          test: bool = False) -> dict:
    """{'grid', 'tm', 'tmfc'?, 'store'+'key'(파일 그대로) 또는 'arr'(계산한 것)}. 없으면 LookupError."""
    kind, n = split(layer)
    info = BY_ID[kind]
    now = now or datetime.now()
    if test:
        return {"grid": info["grid"], "tm": now.strftime("%Y%m%d%H%M"), "test": True,
                "arr": synth(kind, info["grid"], n)}
    if kind == "vsrt":
        tmfc, tmefs = vsrt_run(tm)
        if not tmfc or n > len(tmefs):
            raise LookupError("초단기 격자가 아직 없다")
        tmef = tmefs[n - 1]
        return {"grid": "dfs", "tm": tmef, "tmfc": tmfc, "n": n, "store": "vsrt",
                "key": f"{tmfc}_{tmef}"}
    if kind.startswith("shrt_"):
        tmfc, tmefs = shrt_run(tm)
        if not tmfc:
            raise LookupError("단기예보 격자가 아직 없다")
        day = (now + timedelta(days=0 if kind == "shrt_today" else 1)).strftime("%Y%m%d")
        s = shrt_sum(tmfc, tmefs, day)
        if s["arr"] is None:
            raise LookupError(f"{tmfc} 발표분에 {day} 몫이 없다")
        return {"grid": "dfs", "tm": day, "tmfc": tmfc, "arr": s["arr"],
                "hours": [s["hours"][0], s["hours"][-1]], "capped": s["capped"]}
    ks = gridstore.keys(kind)
    key = tm if tm else (ks[-1] if ks else None)
    if not key or not gridstore.has(kind, key):
        raise LookupError(f"{kind} 격자가 아직 없다" if not tm else f"{kind} {tm} 없음")
    return {"grid": info["grid"], "tm": key, "store": kind, "key": key}


def array(fr: dict) -> np.ndarray:
    if "arr" in fr:
        return fr["arr"]
    return gridstore.load(fr["store"], fr["key"])


def sigun(layer: str, tm: str | None = None, test: bool = False) -> dict:
    fr = frame(layer, tm, test=test)
    a = array(fr)
    hr = a if fr["grid"] == "hr" else gridstore.to_hr(a)
    out = {k: v for k, v in fr.items() if k not in ("arr", "store", "key")}
    out["layer"] = layer
    out["rows"] = gridstore.sigun_stats(hr)
    return out


# ── 목록 · 지연 ─────────────────────────────────────────────────────────
def meta(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    g = gridstore.geo()
    out = []
    for info in LAYERS:
        row = {k: v for k, v in info.items()}
        kind = info["id"]
        try:
            if kind == "vsrt":
                tmfc, tmefs = vsrt_run()
                row.update(tmfc=tmfc, tmefs=tmefs, tm=tmfc)
                age = (now - _dt(tmfc)).total_seconds() / 60 if tmfc else None
            elif kind.startswith("shrt_"):
                fr = frame(kind, now=now)
                row.update(tmfc=fr["tmfc"], tm=fr["tmfc"], day=fr["tm"], hours=fr["hours"],
                           capped=fr["capped"])
                expect = base_of(now - timedelta(minutes=30))
                age = None
                row["behind"] = _dt(fr["tmfc"]) < expect
            else:
                ks = gridstore.keys(kind)
                row.update(tm=ks[-1] if ks else None, frames=len(ks))
                age = (now - _dt(ks[-1])).total_seconds() / 60 if ks else None
        except LookupError as e:
            row.update(tm=None, error=str(e))
            age = None
        row["age_min"] = None if age is None else round(age, 1)
        if kind.startswith("shrt_"):
            row["stale"] = bool(row.get("behind")) if row.get("tm") else None
        else:
            row["stale"] = None if age is None else age > info["stale_min"]
        out.append(row)
    status = {}
    with db.tx() as con:
        for r in con.execute("SELECT kind, ok_at, tried_at, ok, detail FROM collect_log "
                             "WHERE kind IN ('grid','odam','forecast','short')"):
            status[r["kind"]] = {"ok_at": r["ok_at"], "tried_at": r["tried_at"],
                                 "ok": bool(r["ok"]), "detail": r["detail"]}
    return {"now": now.strftime("%Y%m%d%H%M"),
            "grids": {"hr": g["hr"]["bbox"], "dfs": g["dfs"]["bbox"], "dfs_to_hr": g["dfs_to_hr"],
                      "proj": {k: g["hr"][k] for k in ("xo", "yo", "grid_m", "slat1", "slat2",
                                                        "olon", "olat", "ellps")}},
            "layers": out, "collect": status, "setting": setting()}


SETTING_DEFAULT = {"layer": "obs60", "x4": False, "vsrt_n": 1}


def setting() -> dict:
    return db.get_setting("map", SETTING_DEFAULT)


def put_setting(body: dict) -> dict:
    cur = setting()
    if "layer" in body:
        split(str(body["layer"]))            # 모르는 층이면 LookupError
        cur["layer"] = str(body["layer"])
    if "x4" in body:
        cur["x4"] = bool(body["x4"])
    if "vsrt_n" in body:
        n = int(body["vsrt_n"])
        if not 1 <= n <= 6:
            raise ValueError("vsrt_n 은 1~6")
        cur["vsrt_n"] = n
    db.put_setting("map", cur)
    return cur


# ── 테스트 모드 — 비 없는 날 화면 점검용 합성 격자 ─────────────────────────────
# (경도, 위도, 봉우리 ㎜, 반경 km). 창원·진주·산청·거제에 덩어리를 둔다.
_BLOBS = [(128.60, 35.23, 1.0, 9), (128.10, 35.18, 0.55, 14), (127.85, 35.40, 0.8, 7),
          (128.62, 34.88, 0.35, 18), (128.95, 35.30, 0.25, 25)]
_PEAK = {"obs15": 14.0, "obs60": 42.0, "obsday": 180.0, "odam": 38.0, "vsrt": 30.0,
         "shrt_today": 120.0, "shrt_tomorrow": 60.0}


def synth(kind: str, grid: str, n: int = 0) -> np.ndarray:
    """늘 같은 모양 — 점검하는 사람이 '어제 본 그 그림'과 견줄 수 있게. 육지 칸 몇 개는 결측."""
    b = gridstore.geo()[grid]["bbox"]
    rr, cc = np.mgrid[0:b["h"], 0:b["w"]]
    col, row = cc + b["i0"], rr + b["j0"]
    step = 0.5 if grid == "hr" else 5.0
    out = np.zeros(rr.shape)
    shift = 0.03 * max(0, n - 1)                 # 초단기 +N 은 동쪽으로 조금씩 흘린다
    for lon, lat, amp, rad in _BLOBS:
        x, y = (gridproj.hr_xy if grid == "hr" else gridproj.dfs_xy)(lon + shift, lat)
        d2 = ((col - x) ** 2 + (row - y) ** 2) * step * step
        out += amp * np.exp(-d2 / (2 * rad * rad))
    out *= _PEAK.get(kind, 30.0)
    out[out < 0.1] = 0.0
    out = np.round(out, 1 if grid == "hr" else 0)
    if grid == "hr":
        x, y = gridproj.hr_xy(128.35, 35.55)      # 의령·합천 사이 한 조각을 결측으로
        out[(abs(col - x) < 6) & (abs(row - y) < 4)] = np.nan
    return out

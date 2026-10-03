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

import json
from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np

from . import db, gridstore
from .collectors.shortfc import base_of
from .domain import gridproj

LAYERS = [
    {"id": "obs15", "label": "15분 강수량", "short": "15분", "group": "실측", "grid": "hr",
     "src": "기상청 고해상도 격자(500m)", "stale_min": 30, "x4": True},
    {"id": "obs60", "label": "60분 강수량", "short": "60분", "group": "실측", "grid": "hr",
     "src": "기상청 고해상도 격자(500m)", "stale_min": 30},
    {"id": "obsday", "label": "오늘 누적", "short": "오늘", "group": "실측", "grid": "hr",
     "src": "기상청 고해상도 격자(500m)", "stale_min": 30},
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
#   500m  6분 물러선 10분 칸을 10분마다 → 평소 6~26분 → 30분
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


def _floor10(t: datetime) -> datetime:
    t = t.replace(second=0, microsecond=0)
    return t - timedelta(minutes=t.minute % 10)


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
        # tm 을 주면 그 시각만큼 흘린 모양 — 재생해 보면 덩어리가 움직인다.
        # tm 이 없으면 실제 수집과 같은 '최신' 칸(6분 물러선 10분 칸) — 재생 막대의 마지막 실측과 맞게
        if not tm and not kind.startswith("shrt") and kind != "vsrt":
            tm = _floor10(now - timedelta(minutes=6)).strftime("%Y%m%d%H%M")
        off = 0 if not tm or kind.startswith("shrt") else (_dt(tm) - now).total_seconds() / 60
        if kind == "vsrt":
            off = n * 60
        fr = {"grid": info["grid"], "tm": tm or now.strftime("%Y%m%d%H%M"), "test": True,
              "arr": synth(kind, info["grid"], off)}
        if kind == "vsrt":
            fr.update(tmfc=_floor10(now).strftime("%Y%m%d%H%M"), n=n,
                      tm=(now + timedelta(hours=n)).strftime("%Y%m%d%H00"))
        elif kind.startswith("shrt_"):
            d = now + timedelta(days=0 if kind == "shrt_today" else 1)
            fr.update(tmfc=now.strftime("%Y%m%d%H"), tm=d.strftime("%Y%m%d"), capped=0,
                      hours=[d.strftime("%Y%m%d01"), (d + timedelta(days=1)).strftime("%Y%m%d00")])
        return fr
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


def sigun(layer: str, tm: str | None = None, test: bool = False, case: str | None = None) -> dict:
    from . import gridcase
    fr = gridcase.frame(case, layer, tm) if case else frame(layer, tm, test=test)
    a = array(fr)
    hr = a if fr["grid"] == "hr" else gridstore.to_hr(a)
    out = {k: v for k, v in fr.items() if k not in ("arr", "store", "key")}
    out["layer"] = layer
    out["rows"] = gridstore.sigun_stats(hr)
    return out


# ── 관측소 — 격자 옆에 놓는 실측(경남 AWS 56곳 중 위치를 아는 55곳) ─────────────────
# 격자는 관측소 사이를 메운 분석값이다. 관측소 값이 **정답**이고 격자는 그림이다 — 둘을 같은
# 시각으로 나란히 놓아야 비교가 된다. 그래서 그 시각의 값만 준다(가까운 시각으로 메우지 않는다).
#   층       매분자료(obs_minute, 격자 수집기가 격자 시각에 맞춰 받는다)   정시(obs_hourly) — :00 일 때만
#   obs15    rn_15m                                                         —
#   obs60    rn_60m                                                         rn_hr1
#   obsday   rn_day                                                         rn_day(00:00 은 전날 총량이라 뺀다)
#   odam     rn_60m(실황 RN1 도 그 앞 한 시간)                              rn_hr1
# 예측 층은 자리만 준다(status 'forecast'). 행마다 q = ok | missing(기상청 결측) | none(그 시각 값을 못 받음).
STN_VALUE = {"obs15": ("rn_15m", None), "obs60": ("rn_60m", "rn_hr1"),
             "obsday": ("rn_day", "rn_day"), "odam": ("rn_60m", "rn_hr1")}


@lru_cache(maxsize=1)
def station_sites() -> dict:
    """data/geo/stations.json(tools/build_stations.py) — 지점 위치. x·y 는 500m 칸 좌표."""
    return json.loads((gridstore.GEO / "stations.json").read_text(encoding="utf-8"))


def _minute_key(tm: str) -> str:
    return f"{tm[:4]}-{tm[4:6]}-{tm[6:8]} {tm[8:10]}:{tm[10:12]}"


def _test_station_values(layer: str, tm: str | None, base: list[dict]) -> dict:
    """테스트 — 합성 격자를 지점 칸에서 읽고 지점마다 늘 같은 비율(0.7~1.3)을 곱한다.
    관측소와 격자가 어긋나 보이는 모양까지 점검하려고(실제 자료가 아니다)."""
    fr = frame(layer, tm, test=True)
    a = fr["arr"] if fr["grid"] == "hr" else gridstore.to_hr(fr["arr"])
    hb = gridstore.geo()["hr"]["bbox"]
    rows = []
    for b in base:
        c, r = round(b["x"]) - hb["i0"], round(b["y"]) - hb["j0"]
        v = float(a[r, c]) if 0 <= r < hb["h"] and 0 <= c < hb["w"] else float("nan")
        f = 0.7 + 0.6 * ((int(b["stn"]) * 37) % 100) / 100
        ok = v == v
        rows.append({**b, "v": round(v * f, 1) if ok else None, "q": "ok" if ok else "missing"})
    return {"tm": fr["tm"], "status": "test", "src": "합성 — 실제 자료 아님", "rows": rows}


def stations(layer: str, tm: str | None = None, test: bool = False, case: str | None = None) -> dict:
    sites = station_sites()
    base = [{k: s[k] for k in ("stn", "name", "sigun", "x", "y", "ht")} for s in sites["stations"]]
    head = {"layer": layer, "sites": sites["source"], "unsited": sites.get("missing", [])}
    if case:
        from . import gridcase
        return {**head, **gridcase.stations(case, layer, tm, base)}
    kind, _ = split(layer)
    if kind not in STN_VALUE:
        return {**head, "tm": tm, "status": "forecast", "src": "",
                "rows": [{**b, "v": None, "q": None} for b in base]}
    if test:
        return {**head, **_test_station_values(layer, tm, base)}
    tm = tm or frame(layer)["tm"]
    if len(tm) != 12 or not tm.isdigit():
        raise LookupError(f"시각은 YYYYMMDDHHMI: {tm}")
    col, hcol = STN_VALUE[kind]
    key = _minute_key(tm)
    with db.tx() as con:
        got = {r["stn"]: r[col] for r in con.execute(
            f"SELECT stn, {col} FROM obs_minute WHERE tm=?", (key,))}
        src = f"기상청 매분자료 {tm[8:10]}:{tm[10:12]}"
        if not any(v is not None for v in got.values()) and hcol and tm[10:12] == "00" \
                and not (hcol == "rn_day" and tm[8:12] == "0000"):
            hr = {r["stn"]: r[hcol] for r in con.execute(
                f"SELECT stn, {hcol} FROM obs_hourly WHERE tm=?", (key,))}
            if any(v is not None for v in hr.values()):
                got, src = hr, f"기상청 정시자료 {tm[8:10]}:00"
    rows = []
    for b in base:
        if b["stn"] not in got:
            rows.append({**b, "v": None, "q": "none"})
        else:
            v = got[b["stn"]]
            bad = v is None or v < 0                     # 음수는 기상청 결측 표기다
            rows.append({**b, "v": None if bad else round(v, 1), "q": "missing" if bad else "ok"})
    status = "ok" if got else "none"
    return {**head, "tm": tm, "status": status, "src": src if got else "", "rows": rows}


# ── 격자 누적 표 — 오른쪽 '강수 누적' 카드의 격자 기준(관측소 기준과 바꿔 본다) ─────────
# 매시 정각 60분 격자를 칸마다 더한다(결측 칸은 결측으로 남는다 — 0 으로 치지 않는다).
# 시군 줄 = 그 시군 누적 최대 칸(+읍면동), 시군을 고르면 읍면동 줄 = 그 읍면동 누적 최대 칸.
# 줄마다 그 칸의 매시 값(d)을 같이 준다 — 카드의 작은 선 그래프가 '그 자리'의 비를 그린다.
# ⚠️ 받지 못한 정시가 있으면 합은 **하한**이다(missing 에 몇 시간인지 적는다).
def acc_table(acc: np.ndarray, frames: list, sigun: str | None = None) -> list[dict]:
    """acc(경남 bbox 500m 누적), frames(매시 배열 또는 None) → 줄들. 값이 없는 줄은 sum None."""
    g = gridstore.geo()
    hb = g["hr"]["bbox"]
    msig, memd = gridstore.masks()
    flat = acc.ravel()

    def row(name: str, sig: str, idx: np.ndarray, emd_at=None) -> dict:
        v = flat[idx]
        ok = np.isfinite(v)
        out = {"sig": sig, "name": name, "sum": None, "mean": None, "d": [None] * len(frames),
               "col": None, "row": None, "cells": int(idx.size)}
        if not ok.any():
            return out
        mx = float(v[ok].max())
        out.update(sum=round(mx, 1), mean=round(float(v[ok].mean()), 1))
        if mx < 0.1:
            return out                           # 비가 없으면 '어느 칸'도 없다
        k = idx[ok][int(np.argmax(v[ok]))]
        r, c = divmod(int(k), hb["w"])
        out.update(col=c + hb["i0"], row=r + hb["j0"],
                   d=[None if f is None or not np.isfinite(f[r, c]) else round(float(f[r, c]), 1)
                      for f in frames])
        if emd_at:
            out["name"] = emd_at(r, c, sig) or ""
        return out

    emds = {e["id"]: e for e in g["emd"]}
    if sigun is None:
        def emd_at(r, c, sig):
            e = emds.get(int(memd[r, c]))
            if e and e["sigun"] == sig:
                return e["name"]
            # 경계 칸(읍면동 지도와 시군 지도가 어긋난 자리·섬) — 같은 시군에서 가장 가까운 읍면동
            col, row_ = c + hb["i0"], r + hb["j0"]
            cand = [x for x in g["emd"] if x["sigun"] == sig and x["c"]]
            e = min(cand, key=lambda x: (x["c"][0] - col) ** 2 + (x["c"][1] - row_) ** 2, default=None)
            return e["name"] if e else None
        sf = msig.ravel()
        return [row("", s["name"], np.flatnonzero(sf == s["id"]), emd_at)
                for s in g["sigun"] if s["kind"] == "gn"]
    mine = [e for e in g["emd"] if e["sigun"] == sigun]
    if not mine:
        raise LookupError(f"모르는 시군: {sigun}")
    ef = memd.ravel()
    return [row(e["name"], sigun, np.flatnonzero(ef == e["id"])) for e in mine]


_ACC_CACHE: dict[tuple, dict] = {}


def acc(hours: int = 12, sigun: str | None = None, now: datetime | None = None,
        test: bool = False) -> dict:
    """지난 hours 시간(가장 최근 정시 격자까지) 격자 누적 — 시군 줄, 또는 sigun 의 읍면동 줄."""
    now = now or datetime.now()
    if test:
        last = _floor10(now - timedelta(minutes=6)).replace(minute=0)
    else:
        ks = [k for k in gridstore.keys("obs60") if k.endswith("00")]
        if not ks:
            raise LookupError("정시 60분 격자가 아직 없다")
        last = _dt(ks[-1])
    want = [(last - timedelta(hours=h)).strftime("%Y%m%d%H%M") for h in range(hours - 1, -1, -1)]
    have = want if test else [k for k in want if gridstore.has("obs60", k)]
    ck = (tuple(have), hours, sigun, test, now.strftime("%Y%m%d%H") if test else "")
    if ck in _ACC_CACHE:
        return _ACC_CACHE[ck]
    frames = []
    for k in want:
        if test:
            frames.append(synth("obs60", "hr", (_dt(k) - now).total_seconds() / 60))
        else:
            frames.append(gridstore.load("obs60", k) if k in have else None)
    got = [f for f in frames if f is not None]
    if not got:
        raise LookupError("이 구간에 받은 정시 격자가 없다")
    total = got[0].copy()
    for f in got[1:]:
        total = total + f
    out = {"basis": "grid", "hours": hours, "frames": want, "tm": want[-1], "sigun": sigun,
           "missing": len(want) - len(got), "test": test,
           "src": "합성 — 실제 자료 아님" if test else "기상청 고해상도 격자(500m) · 매시 60분 합",
           "rows": acc_table(total, frames, sigun)}
    if len(_ACC_CACHE) > 24:
        _ACC_CACHE.pop(next(iter(_ACC_CACHE)))
    _ACC_CACHE[ck] = out
    return out


# ── 재생 흐름 — 지난 N시간 실측(60분, 10분마다) → 초단기 +1~6h ────────────────
# 지도와 오른쪽 타임라인이 **같은 프레임 목록**을 쓴다. 그래야 재생 위치 하나로 둘이 함께 움직인다.
# 값은 '1시간 강수량'으로 통일한다 — 실측 60분(지난 한 시간)과 초단기 RN1(앞 한 시간)은 같은 단위다.
# ⚠️ 예측은 1시간 간격뿐이다. 초단기 격자에 10분 대상시각을 주면 가까운 정시 격자가 온다
#    (실측 2026-10-01: 8.28. tmfc 10:30 에 tmef 12:10 → 12:00 과 같은 값, 12:30 → 13:00 과 같은 값).
#    10분 예측은 QPF '그림'뿐이고 숫자 격자를 찾지 못했다.
_STAT: dict[tuple, dict] = {}


def _frame_values(store: str, key: str, arr_fn) -> dict:
    """프레임 하나의 시군 값. 프레임은 한 번 저장되면 안 바뀌므로 기억해 둔다."""
    ck = (store, key)
    if ck not in _STAT:
        a = arr_fn()
        if a is None:
            return {}
        hr = a if GRID_OF_STORE[store] == "hr" else gridstore.to_hr(a)
        if len(_STAT) > 600:
            _STAT.pop(next(iter(_STAT)))
        _STAT[ck] = gridstore.sigun_values(hr)
    return _STAT[ck]


GRID_OF_STORE = gridstore.GRID_OF


def flow(hours: int = 6, step: int = 10, now: datetime | None = None, test: bool = False) -> dict:
    now = now or datetime.now()
    start = now - timedelta(hours=hours)
    frames: list[dict] = []
    # ⚠️ 가장 최근 실측은 간격과 상관없이 늘 넣는다. 30분 간격에 최신이 23:40 이면
    #    23:30 에서 흐름이 끝나 '지금' 화면이 재생 막대 밖으로 빠졌다.
    if test:
        latest = _floor10(now - timedelta(minutes=6))
        t = latest
        while t >= start:
            if (t.hour * 60 + t.minute) % step == 0 or t == latest:
                frames.append({"t": t.strftime("%Y%m%d%H%M"), "kind": "obs"})
            t -= timedelta(minutes=10)
        frames.reverse()
        tmfc = _floor10(now).strftime("%Y%m%d%H%M")
        tmefs = [(now + timedelta(hours=n)).strftime("%Y%m%d%H00") for n in range(1, 7)]
    else:
        ks = gridstore.keys("obs60")
        for k in ks:
            t = _dt(k)
            if start <= t <= now and ((t.hour * 60 + t.minute) % step == 0 or k == ks[-1]):
                frames.append({"t": k, "kind": "obs"})
        tmfc, tmefs = vsrt_run()
    for f in frames:
        f.update(layer="obs60", key=f["t"])
    for n, ef in enumerate(tmefs[:6], 1):
        frames.append({"t": ef, "kind": "fcst", "layer": f"vsrt+{n}", "n": n,
                       "key": f"{tmfc}_{ef}", "tmfc": tmfc})

    names = [s["name"] for s in gridstore.geo()["sigun"] if s["kind"] == "gn"]
    series = {s: {"max": [], "mean": []} for s in names + ["경남"]}
    for f in frames:
        if test:
            if f["kind"] == "obs":
                a = synth("obs60", "hr", (_dt(f["t"]) - now).total_seconds() / 60)
            else:
                a = gridstore.to_hr(synth("vsrt", "dfs", f["n"] * 60))
            vals = gridstore.sigun_values(a)
        else:
            store = "obs60" if f["kind"] == "obs" else "vsrt"
            vals = _frame_values(store, f["key"], lambda s=store, k=f["key"]: gridstore.load(s, k))
        for s in series:
            mx, mean = vals.get(s, (None, None))
            series[s]["max"].append(mx)
            series[s]["mean"].append(mean)
    return {"now": now.strftime("%Y%m%d%H%M"), "start": start.strftime("%Y%m%d%H%M"),
            "hours": hours, "step": step, "tmfc": tmfc, "frames": frames,
            "series": [{"sigun": s, **series[s]} for s in names], "total": series["경남"]}


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


SETTING_DEFAULT = {"layer": "obs60", "x4": False, "vsrt_n": 1,
                   # 재생 — 실측 간격(분)·지난 시간·한 장 머무는 시간(ms)
                   "flow_step": 10, "flow_hours": 6, "play_ms": 1200,
                   # 오른쪽 패널 — 켬/끔, 방식(카드: 종합 화면 판을 작게 / 타임라인: 격자 시군 선),
                   # 타임라인의 시군 '최대'/'평균', 카드의 누적 구간(시간)
                   "tl_on": False, "panel": "cards", "tl_stat": "max", "acc_hours": 12,
                   # 누적 카드 기준 — aws: 관측소 다우지점(스방 265 → 기상청 56) / grid: 격자 누적 최대 칸
                   "acc_basis": "aws",
                   # 지도 위에 겹칠 레이어(왼쪽 위 '레이어'에서 켠다). 차츰 늘린다.
                   "overlays": []}
OVERLAYS = ("alerts", "stations", "stnval")   # stnval = 관측소 옆 값 글자(관측소에 딸림)
_CHOICES = {"flow_step": (10, 20, 30, 60), "flow_hours": (1, 3, 6, 12),
            "play_ms": (600, 1200, 2000), "tl_stat": ("max", "mean"),
            "panel": ("cards", "timeline"), "acc_hours": (6, 12, 24, 48),
            "acc_basis": ("aws", "grid")}
_TEXT = {"tl_stat", "panel", "acc_basis"}


def setting() -> dict:
    return db.get_setting("map", SETTING_DEFAULT)


def put_setting(body: dict) -> dict:
    cur = setting()
    if "layer" in body:
        split(str(body["layer"]))            # 모르는 층이면 LookupError
        cur["layer"] = str(body["layer"])
    for k in ("x4", "tl_on"):
        if k in body:
            cur[k] = bool(body[k])
    if "vsrt_n" in body:
        n = int(body["vsrt_n"])
        if not 1 <= n <= 6:
            raise ValueError("vsrt_n 은 1~6")
        cur["vsrt_n"] = n
    for k, ok in _CHOICES.items():
        if k in body:
            v = body[k] if k in _TEXT else int(body[k])
            if v not in ok:
                raise ValueError(f"{k} 는 {ok} 중 하나")
            cur[k] = v
    if "overlays" in body:
        ov = body["overlays"]
        if not isinstance(ov, list) or any(x not in OVERLAYS for x in ov):
            raise ValueError(f"overlays 는 {OVERLAYS} 의 부분 목록")
        cur["overlays"] = list(dict.fromkeys(ov))
    db.put_setting("map", cur)
    return cur


# ── 테스트 모드 — 비 없는 날 화면 점검용 합성 격자 ─────────────────────────────
# (경도, 위도, 봉우리 비율, 반경 km). 창원·진주·산청·거제·양산에 덩어리를 둔다 —
# 봉우리 하나는 시군 경계에 걸치게 해서 라벨 자리 옮기기도 같이 본다.
_BLOBS = [(128.60, 35.23, 1.0, 5), (128.10, 35.18, 0.55, 8), (127.85, 35.40, 0.8, 4),
          (128.62, 34.88, 0.4, 9), (129.03, 35.37, 0.3, 6), (128.37, 35.33, 0.45, 3)]
_PEAK = {"obs15": 14.0, "obs60": 42.0, "obsday": 180.0, "odam": 38.0, "vsrt": 30.0,
         "shrt_today": 120.0, "shrt_tomorrow": 60.0}


def synth(kind: str, grid: str, off_min: float = 0.0) -> np.ndarray:
    """합성 격자. 재생하면 같은 프레임을 여러 번 그리므로 분 단위로 기억해 둔다(읽기 전용으로 쓴다)."""
    return _synth(kind, grid, int(round(off_min)))


@lru_cache(maxsize=256)
def _synth(kind: str, grid: str, off_min: int) -> np.ndarray:
    """늘 같은 모양 — 점검하는 사람이 '어제 본 그 그림'과 견줄 수 있게. 육지 칸 몇 개는 결측.

    off_min(지금부터 몇 분 뒤/앞)만큼 덩어리가 북동쪽으로 흐르고 세기가 오르내린다 —
    재생해 보면 비구름이 지나가는 것처럼 보인다. 같은 off_min 이면 늘 같은 그림.
    """
    b = gridstore.geo()[grid]["bbox"]
    rr, cc = np.mgrid[0:b["h"], 0:b["w"]]
    col, row = cc + b["i0"], rr + b["j0"]
    step = 0.5 if grid == "hr" else 5.0
    out = np.zeros(rr.shape)
    h = off_min / 60.0
    for k, (lon, lat, amp, rad) in enumerate(_BLOBS):
        dlon, dlat = 0.10 * h, 0.035 * h                # 시간당 약 9km 동쪽·4km 북쪽
        a = amp * (0.55 + 0.45 * np.cos(h * 0.9 + k * 1.3))
        x, y = (gridproj.hr_xy if grid == "hr" else gridproj.dfs_xy)(lon + dlon, lat + dlat)
        d2 = ((col - x) ** 2 + (row - y) ** 2) * step * step
        out += a * np.exp(-d2 / (2 * rad * rad))
    peak = _PEAK.get(kind, 30.0)
    out *= peak
    out[out < max(0.1, peak * 0.01)] = 0.0       # 꼬리를 끊는다 — 도 전체가 옅게 물들지 않게
    out = np.round(out, 1 if grid == "hr" else 0)
    if grid == "hr":
        x, y = gridproj.hr_xy(128.35, 35.55)      # 의령·합천 사이 한 조각을 결측으로
        out[(abs(col - x) < 6) & (abs(row - y) < 4)] = np.nan
    out.setflags(write=False)                     # 기억해 두고 나눠 쓰므로 고치지 못하게
    return out

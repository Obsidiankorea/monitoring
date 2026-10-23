"""경남 지도 판 — 층 이름을 풀어 격자를 찾고, 지연을 판정한다. DB·파일만 읽는다.

층(화면 이름)             저장 층   격자   기준시각
  obs15 · obs60 · obsday   같은 이름  500m   tm
  acc                      obs60     500m   누적 구간(강수 누적 카드와 같은 것 — 지난 N시간 · 오늘/어제 0시부터)의
                                            정시 60분 격자를 칸마다 더한 것. 마지막 정시까지 + '지금' 칸(아래)
  ⏱ 격자 누적의 '지금' 칸 — 마지막 정시 뒤 ~ 가장 최근 일강수 격자(10분 칸): 일강수(obsday) 증분(_grid_tail).
  aws                      (관측소)   500m   같은 구간의 **관측소 값만으로** 메운 면 — 기상청 AWS(obs_hourly) +
                                            경남 AWS(스방 bangjae_hourly, 목록 위치) 정시 강수량 합을 IDW 로
  aws60                    (관측소)   500m   정시 한 시간 몫을 같은 관측소 · 같은 IDW 로(재생 흐름의 AWS 실측).
                                            시각은 누적 층과 같은 정시들 — 관측소 값이 아직 없는 정시는 건너뛴다
  ⏱ AWS 두 층의 '지금' 칸 — **실시간 감시(설정 aws_live)를 켰을 때만**, 마지막 정시 뒤 매분자료(1분 수집기 minute)까지 잇는다:
     누적 = 정시 합 + 정시부터 지금까지(기상청 RN_DAY 증분 · 경남 AWS 스방 진행 칸), 종합 화면 강수량 판 마지막 칸과 같은 셈.
     1시간 = 그 분의 직전 60분(기상청 RN-60m — 경남 AWS 는 정시 자료라 정시 칸에만).
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

from . import clock, db, gridstore, queries, sites
from .collectors.shortfc import base_of
from .domain import gridproj

LAYERS = [
    {"id": "obs15", "label": "15분 강수량", "short": "15분", "group": "실측", "grid": "hr",
     "src": "기상청 고해상도 격자(500m)", "stale_min": 30, "x4": True},
    {"id": "obs60", "label": "60분 강수량", "short": "60분", "group": "실측", "grid": "hr",
     "src": "기상청 고해상도 격자(500m)", "stale_min": 30},
    {"id": "obsday", "label": "오늘 누적", "short": "오늘", "group": "실측", "grid": "hr",
     "src": "기상청 고해상도 격자(500m)", "stale_min": 30},
    {"id": "acc", "label": "강수 누적", "short": "누적", "group": "실측", "grid": "hr",
     "src": "기상청 고해상도 격자(500m) · 매시 60분 합", "stale_min": 90},
    {"id": "aws", "label": "AWS 누적", "short": "AWS", "group": "실측", "grid": "hr",
     "src": "AWS 관측소 값만으로 메운 면(IDW, 가까운 8곳) · 정시 강수량 합", "stale_min": 90},
    {"id": "aws60", "label": "AWS 1시간 강수량", "short": "AWS 1시간", "group": "실측", "grid": "hr",
     "src": "AWS 관측소 값만으로 메운 면(IDW, 가까운 8곳) · 정시 1시간 강수량", "stale_min": 90},
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
          test: bool = False, hours: int | None = None, since: str | None = None) -> dict:
    """{'grid', 'tm', 'tmfc'?, 'store'+'key'(파일 그대로) 또는 'arr'(계산한 것)}. 없으면 LookupError.
    acc(누적) 층은 hours · since(today|yesterday) — 없으면 지도 설정(강수 누적 카드의 구간)."""
    kind, n = split(layer)
    info = BY_ID[kind]
    now = now or clock.now()
    if kind == "aws":
        return aws_frame(*acc_window(hours, since), now=now, test=test)
    if kind == "aws60":
        return aws_hour_frame(tm, now=now, test=test)
    if kind == "acc":
        s = acc_sum(*acc_window(hours, since), now=now, test=test)
        return {"grid": "hr", "tm": s["tail"] or s["want"][-1], "from": s["want"][0], "arr": s["total"],
                "n": len(s["want"]), "missing": len(s["want"]) - len(s["have"]),
                **({"live": s["tail"]} if s["tail"] else {}), **({"test": True} if test else {})}
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


SEL_MAX = 3                     # 지도에서 한꺼번에 고르는 시군(Ctrl+클릭으로 비교)


def siguns_of(sigun: str | list | None) -> list[str]:
    """'함양,거창' → ['함양', '거창']. 경남 시군만, 겹치면 하나로, SEL_MAX 곳까지. 모르면 LookupError.
    'all' 이면 경남 열여덟 시군 전부 — 위 카드 줄 세우기(시군당 2·3곳 · 시군 무관)가 경남 읍면동을 다 받는다."""
    if not sigun:
        return []
    gn = [s["name"] for s in gridstore.geo()["sigun"] if s["kind"] == "gn"]
    if sigun == "all":
        return gn
    names = [x.strip() for x in (sigun.split(",") if isinstance(sigun, str) else sigun) if x.strip()]
    bad = [x for x in names if x not in gn]
    if bad:
        raise LookupError(f"모르는 시군: {', '.join(bad)}")
    out = list(dict.fromkeys(names))
    if len(out) > SEL_MAX:
        raise LookupError(f"시군은 {SEL_MAX}곳까지")
    return out


def emd(sigun: str, layer: str = "obs60", tm: str | None = None, test: bool = False,
        case: str | None = None, hours: int = 1) -> dict:
    """고른 시군들 **읍면동마다** 그 층 최대 — 오른쪽 '지금 오는 비'·'예측 상위'(테스트)를 읍면동으로.

    사례(case)면 1시간 격자를 tm 까지 hours 장 더한다(3시간 등). 결측 칸은 결측으로 남긴다."""
    sg = siguns_of(sigun)
    if not sg:
        raise LookupError("시군을 하나 이상 주어야 한다")
    if case:
        from . import gridcase
        m = gridcase.meta(case)
        tm = tm or m["end"]
        if tm not in m["frames"]:
            raise LookupError(f"{case} {tm} 없음")
        i = m["frames"].index(tm)
        keys = m["frames"][max(0, i - hours + 1):i + 1]
        hr = gridcase.obs(case, keys[0])
        for k in keys[1:]:
            hr = hr + gridcase.obs(case, k)
        out = {"grid": "hr", "tm": tm, "case": case, "hours": len(keys)}
    else:
        fr = frame(layer, tm, test=test)
        a = array(fr)
        hr = a if fr["grid"] == "hr" else gridstore.to_hr(a)
        out = {k: v for k, v in fr.items() if k not in ("arr", "store", "key")}
    out.update(layer=layer, siguns=sg, rows=gridstore.emd_stats(hr, sg))
    return out


DAY_WIN = ("06", "12", "18", "24")       # 단기 하루를 6시간씩 — 끝 시각(KMA 'H시' = (H-1)~H시 한 시간)
_DAYC: dict[tuple, dict] = {}


def _win_of(tmef: str) -> int:
    """'YYYYMMDDHH' 한 시간 → 0~3 구간. 00시는 그 전날 24시다."""
    h = int(tmef[8:10]) or 24
    return (h - 1) // 6


def emd_day(layer: str, sigun: str | None = None, test: bool = False, now: datetime | None = None) -> dict:
    """단기 오늘·내일 — **읍면동마다** 그날 합, 6시간 구간 합(00~06·06~12·12~18·18~24시), 매시 값의 최대.

    지도 '단기 오늘/내일'을 볼 때 오른쪽 카드가 이것으로 바뀐다 — 위 카드(그날 합 · 매시 선 그래프)와
    '단기 상위'(6시간 칸). sigun 이 없으면 경남 읍면동 전부.
    ⚠️ 5km 격자라 이웃 읍면동이 같은 값이 많다(한 칸이 여러 읍면동에 걸친다).
    ⚠️ 오늘은 발표 뒤 남은 시간만 — 지난 구간은 hours 0(값 None), 매시 값도 남은 시간만(times)."""
    kind, _ = split(layer)
    if not kind.startswith("shrt_"):
        raise LookupError(f"단기 오늘·내일만: {layer}")
    sg = siguns_of(sigun) or [s["name"] for s in gridstore.geo()["sigun"] if s["kind"] == "gn"]
    now = now or clock.now()
    day = (now + timedelta(days=0 if kind == "shrt_today" else 1)).strftime("%Y%m%d")
    if test:
        tot = synth(kind, "dfs", 0)
        d0 = datetime.strptime(day, "%Y%m%d")
        times = [(d0 + timedelta(hours=h)).strftime("%Y%m%d%H") for h in range(1, 25)]
        wt = np.exp(-((np.arange(1, 25) - 17) / 5.0) ** 2)               # 합성 — 오후에 몰리는 모양
        hourly = [tot * (w / wt.sum()) for w in wt]
        tmfc = now.strftime("%Y%m%d%H")
    else:
        tmfc, tmefs = shrt_run()
        if not tmfc:
            raise LookupError("단기예보 격자가 아직 없다")
        hours = [t for t in tmefs if _day_of(t) == day]
        if not hours:
            raise LookupError(f"{tmfc} 발표분에 {day} 몫이 없다")
        ck = (tmfc, day, tuple(sg))
        if ck in _DAYC:
            return _DAYC[ck]
        times, hourly = [], []
        for t in hours:
            a = gridstore.load("shrt", f"{tmfc}_{t}")
            if a is not None:
                times.append(t)
                hourly.append(a)
        if not hourly:
            raise LookupError(f"{tmfc} 발표분 {day} 격자를 읽지 못했다")
    wins, counts = [None] * 4, [0] * 4
    for t, a in zip(times, hourly):
        w = _win_of(t)
        wins[w] = a.copy() if wins[w] is None else wins[w] + a          # NaN 은 NaN 으로 남는다
        counts[w] += 1
    got = [w for w in wins if w is not None]
    tot = got[0].copy()
    for w in got[1:]:
        tot = tot + w
    total = gridstore.emd_stats(gridstore.to_hr(tot), sg)
    per = [gridstore.emd_stats(gridstore.to_hr(w), sg) if w is not None else None for w in wins]
    hr = [gridstore.emd_stats(gridstore.to_hr(a), sg) for a in hourly]
    rows = []
    for i, r in enumerate(total):
        rows.append({**r, "sum": r["max"], "w": [p[i]["max"] if p else None for p in per],
                     "h": [x[i]["max"] for x in hr]})
    rows.sort(key=lambda r: -(r["sum"] or 0))
    out = {"layer": layer, "tmfc": tmfc, "day": day, "labels": list(DAY_WIN), "hours": counts,
           "times": times, "siguns": sg if sigun else [], "test": test, "rows": rows}
    if not test:
        if len(_DAYC) > 32:
            _DAYC.pop(next(iter(_DAYC)))
        _DAYC[ck] = out
    return out


def sigun(layer: str, tm: str | None = None, test: bool = False, case: str | None = None,
          hours: int | None = None, since: str | None = None) -> dict:
    from . import gridcase
    fr = gridcase.frame(case, layer, tm) if case else frame(layer, tm, test=test, hours=hours, since=since)
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


def _tfac(stn: str) -> float:
    """테스트 지점마다 늘 같은 비율(0.7~1.3) — 관측과 격자가 어긋나 보이는 모양까지 점검하려고."""
    k = int(stn) if stn.isdigit() else sum(ord(ch) * (i + 7) for i, ch in enumerate(stn))
    return 0.7 + 0.6 * ((k * 37) % 100) / 100


def test_rain(hours: int = 12, now: datetime | None = None) -> dict:
    """테스트 — /api/rain 과 같은 모양. 기상청 지점(위치 있음) + 시군마다 '스방 흉내' 합성 지점 셋.

    값은 합성 60분 격자를 그 칸에서 읽어 지점 비율을 곱한다 — 지도·관측소 층(테스트)과 같은 비다.
    스방 흉내 지점은 실제 스방처럼 위치를 이름으로 짐작한다(sites.position — 읍면동 가운데, est).
    비 없는 날 내부망 목록 모양(한 시군 여러 지점, 위치 모르는 지점)을 미리 보려는 것 — 실제 자료가 아니다.
    """
    now = now or clock.now()
    top = now.replace(minute=0, second=0, microsecond=0)
    slots = [top - timedelta(hours=h) for h in range(hours - 1, -1, -1)]
    frames = [synth("obs60", "hr", (t - now).total_seconds() / 60) for t in slots]
    g = gridstore.geo()
    hb = g["hr"]["bbox"]
    pts = [(s["stn"], s["name"], s["sigun"], s["x"], s["y"]) for s in station_sites()["stations"]]
    for sg in (x for x in g["sigun"] if x["kind"] == "gn"):
        emds = [e for e in g["emd"] if e["sigun"] == sg["name"] and e.get("c")]
        for e in emds[::max(1, len(emds) // 3)][:3]:
            pts.append((f"T{e['id']}", f"{e['name']}(가상)", sg["name"], e["c"][0], e["c"][1]))
    rows = []
    for stn, name, sig, x, y in pts:
        c, r = round(x) - hb["i0"], round(y) - hb["j0"]
        f = _tfac(stn)
        d = []
        for a in frames:
            v = a[r, c] if 0 <= r < hb["h"] and 0 <= c < hb["w"] else np.nan
            d.append(round(float(v) * f, 1) if np.isfinite(v) else None)
        ok = [v for v in d if v is not None]
        row = {"stn": stn, "name": name, "sigun": sig, "rep": False, "d": d, "m60": None,
               "sum": round(sum(ok), 1), "bad": len(d) - len(ok)}
        if stn.startswith("T"):
            row["pos"] = sites.position(stn, name, sig)
        rows.append(row)
    return {"labels": [t.strftime("%H") for t in slots], "hours": hours, "src": "test",
            "src_label": "테스트", "count": len(rows), "base_hour": top.strftime("%H:%M"),
            "minute_tm": None, "missing": 0, "rows": rows}


def _gn_hourly(want: list[str]) -> dict[str, list]:
    """경남 AWS 정시 강수량 — 스방 bangjae_hourly 를 기상청 칸(H시 = (H-1)~H)으로 밀어 읽고, 경남 AWS 목록 지점(G…)에
    짝짓는다(시군 + 장치명). 기상청 지점번호로 오는 것 · 목록에 없는 것은 뺀다(기상청은 obs_hourly 가 낫다)."""
    gk = {(s["sigun"], s["name"]): s["stn"] for s in sites.gn_sites()}
    kma = {s["stn"] for s in station_sites()["stations"]}
    back = [(datetime.strptime(k, "%Y%m%d%H%M") - timedelta(hours=1)).strftime("%Y-%m-%d %H:00") for k in want]
    out: dict[str, list] = {}
    with db.tx() as con:
        for r in con.execute(f"SELECT stn, name, sigun, tm, mm FROM bangjae_hourly WHERE tm IN ({','.join('?' * len(back))})",
                             back):
            if r["stn"] in kma:
                continue
            a = sites.aws_site(r["name"], sites.sigun_of(r["stn"], r["sigun"]))
            g = gk.get((a["sigun"], a["name"])) if a and a["org"] == "gn" else None
            if g:
                v = r["mm"]
                out.setdefault(g, []).append(None if v is None or v < 0 else v)
    return out


LIVE_MAX_MIN = 90       # 매분자료가 이보다 묵었으면 '지금' 칸을 잇지 않는다(수집이 멈췄다 — 지난 값을 지금이라 하지 않게)


def live_on() -> bool:
    """AWS 실시간 감시(지도 설정 aws_live) — 끄면 AWS 층은 정시까지만."""
    return bool(setting().get("aws_live"))


def live_minute(after: str | None, now: datetime | None = None) -> str | None:
    """'지금' 칸 시각 'YYYYMMDDHHMI' — 실시간 감시를 켰고, 가장 최근 매분자료가 정시 after 보다 늦고 LIVE_MAX_MIN 안이면.
    아니면 None(정시까지만)."""
    if not live_on():
        return None
    now = now or clock.now()
    with db.tx() as con:
        r = con.execute("SELECT MAX(tm) AS tm FROM obs_minute WHERE quality='ok'").fetchone()
    if not r or not r["tm"]:
        return None
    k = r["tm"].replace("-", "").replace(" ", "").replace(":", "")
    if after and k <= after:
        return None
    return k if (now - _dt(k)).total_seconds() <= LIVE_MAX_MIN * 60 else None


def _acc_tail(after: str, base: list[dict], now: datetime, at: str | None = None) -> tuple[str | None, dict]:
    """정시 after(키) 뒤 ~ 지금(또는 at 키) — 지점마다 온 비. → ('지금' 키, {stn: 값|None}). 이을 매분자료가 없으면 (None, {}).
    기상청 = RN_DAY 증분(queries.minute_tail, 종합 화면 강수량 판 마지막 칸과 같다). 경남 AWS = 스방 시간 칸 중
    after 부터 지금 시각 칸까지(진행 칸 포함 — 스방 수집 10분 · 5분 물러선 값). 스방 칸이 하나도 없으면(내부망 밖) 경남은 뺀다."""
    live = at or live_minute(after, now)
    if not live or live <= after:
        return None, {}
    mt, tail, _ = queries.minute_tail(_minute_key(after), _minute_key(live))
    if not mt:
        return None, {}
    out = {k: v for k, v in tail.items()}
    t0, t1 = _dt(after), _dt(live).replace(minute=0)
    keys, t = [], t0
    while t <= t1:                                   # 스방 H시 칸 = 기상청 (H+1)시 키(_gn_hourly 가 한 칸 민다)
        keys.append((t + timedelta(hours=1)).strftime("%Y%m%d%H%M"))
        t += timedelta(hours=1)
    gn = _gn_hourly(keys)
    if gn:
        for b in base:
            if b.get("org") == "gn" or b["stn"].startswith("G"):
                got = [v for v in gn.get(b["stn"], []) if v is not None]
                out[b["stn"]] = round(sum(got), 1) if got else None
    return live, out


def _acc_station_values(hours: int, since: str | None, base: list[dict], upto: str = "minute") -> dict:
    """누적 층의 관측소 값 — 같은 구간(격자와 같은 정시들)의 정시 강수량 합 + '지금' 칸.
    upto = minute(AWS 누적 — 가장 최근 매분까지) | grid(격자 누적 — 격자 '지금' 칸과 같은 10분 칸까지, 그 시각
    매분자료는 격자 수집기가 받아 둔다) | 매분 키(그 분까지 — 화면이 그린 AWS 누적 면과 같은 시각)."""
    now = clock.now()
    want, _ = _acc_keys(hours, since, now, False)
    at = _grid_tail_key(want[-1]) if upto == "grid" else upto if upto not in ("minute", "grid") else None
    lv, tail = _acc_tail(want[-1], base, now, at) if upto == "minute" or (at and at > want[-1]) else (None, {})
    return _station_sums(want, base, tail if lv else None, lv)


def _station_sums(want: list[str], base: list[dict], tail: dict | None = None, live: str | None = None) -> dict:
    """정시들(want)의 관측소 정시 강수량 합. 기상청 AWS 는 obs_hourly(rn_hr1), 경남 AWS 는 스방(내부망에서만 —
    밖에서는 자리만). 한 시간이라도 빠지면 q='part'(하한), 다 빠지면 missing/none. AWS 1시간 층은 want 가 한 칸.
    tail = '지금' 칸(_acc_tail) — 든 지점은 한 칸 더 센다(그 칸이 비면 part), tm 은 live."""
    tms = [_minute_key(k) for k in want]
    vals: dict[str, list] = {}
    with db.tx() as con:
        for r in con.execute(f"SELECT stn, tm, rn_hr1, quality FROM obs_hourly WHERE tm IN ({','.join('?' * len(tms))})",
                             tms):
            v = r["rn_hr1"]
            vals.setdefault(r["stn"], []).append(None if v is None or v < 0 or r["quality"] != "ok" else v)
    gn = _gn_hourly(want)
    vals.update(gn)
    tail = tail or {}
    rows = []
    for b in base:
        got = list(vals.get(b["stn"]) or [])
        n = len(want)
        if b["stn"] in tail:
            got.append(tail[b["stn"]])
            n += 1
        if not got:
            rows.append({**b, "v": None, "q": "none"})
            continue
        ok = [v for v in got if v is not None]
        if not ok:
            rows.append({**b, "v": None, "q": "missing"})
        else:
            rows.append({**b, "v": round(sum(ok), 1), "q": "ok" if len(ok) == n else "part",
                         "miss": n - len(ok)})                         # 빠진 시각 수 — 화면은 숫자만, 툴팁에 이것
    src = (f"기상청 정시자료{' + 경남 AWS(스방)' if gn else ''} {len(want)}시간 합") if vals else ""
    if live and tail:
        src += f" + {want[-1][8:10]}:00~{live[8:10]}:{live[10:12]}(매분)"
    return {"tm": live if live and tail else want[-1], "from": want[0], "status": "ok" if vals or tail else "none",
            "src": src, "rows": rows, **({"live": live} if live and tail else {})}


# ── AWS 누적 면 — 관측소 값만으로(격자 분석값을 쓰지 않는다) ─────────────────────
# 가까운 관측소 8곳의 역거리 제곱 가중 평균(IDW). 1km(2칸)마다 계산해 500m 로 늘린다 — 관측소 사이가 수 km 라 충분하다.
# 경남 땅 밖(바다 · 다른 시도)은 0 — 칠하지 않는다(관측소가 없는 곳을 지어내지 않게).
# ⚠️ 관측소 값이 정답이고 면은 그 사이를 메운 그림이다. 기상청 56곳만 있으면(내부망 밖) 면이 거칠다 — 경남 AWS 가 들어와야 촘촘하다.
IDW_K, IDW_POW, IDW_STEP = 8, 2.0, 2
_AWS_CACHE: dict[tuple, dict] = {}


def _aws_cached(ck: tuple) -> dict | None:
    """IDW 면 기억 — 맞으면 맨 뒤로 옮긴다(가장 오래 안 쓴 것부터 버린다). 실시간 감시를 켜면 '지금' 칸이 1분마다 하나씩
    생긴다 — 넣은 차례로 버리면 재생 흐름 정시 장들이 40분 뒤 밀려나 다시 계산했다."""
    hit = _AWS_CACHE.pop(ck, None)
    if hit is not None:
        _AWS_CACHE[ck] = hit
    return hit


def idw_surface(pts: list[tuple[float, float, float]]) -> np.ndarray:
    """[(열, 행, 값)] (500m 칸 좌표) → 경남 bbox 500m 면. 경남 땅 밖은 0."""
    hb = gridstore.geo()["hr"]["bbox"]
    h, w = hb["h"], hb["w"]
    if not pts:
        raise LookupError("값이 있는 관측소가 없다")
    P = np.array([(x - hb["i0"], y - hb["j0"]) for x, y, _ in pts], dtype="f8")
    V = np.array([v for _, _, v in pts], dtype="f8")
    ys, xs = np.arange(0, h, IDW_STEP) + (IDW_STEP - 1) / 2, np.arange(0, w, IDW_STEP) + (IDW_STEP - 1) / 2
    gx, gy = np.meshgrid(xs, ys)
    Q = np.stack([gx.ravel(), gy.ravel()], 1)
    k = min(IDW_K, len(P))
    out = np.empty(len(Q))
    for i in range(0, len(Q), 8192):
        q = Q[i:i + 8192]
        d2 = ((q[:, None, :] - P[None, :, :]) ** 2).sum(-1)
        idx = np.argpartition(d2, k - 1, axis=1)[:, :k] if k < len(P) else np.broadcast_to(np.arange(len(P)), d2.shape)
        dk = np.take_along_axis(d2, idx, 1)
        wt = 1.0 / np.maximum(dk, 0.25) ** (IDW_POW / 2)        # 반 칸 안이면 그 관측소 값 그대로에 가깝게
        out[i:i + 8192] = (wt * V[idx]).sum(1) / wt.sum(1)
    coarse = out.reshape(len(ys), len(xs))
    full = np.repeat(np.repeat(coarse, IDW_STEP, 0), IDW_STEP, 1)[:h, :w]
    msig, _ = gridstore.masks()
    gn = np.isin(msig, [s["id"] for s in gridstore.geo()["sigun"] if s["kind"] == "gn"])
    full = np.where(gn, np.round(full, 1), 0.0)
    full.setflags(write=False)
    return full


def aws_frame(hours: int, since: str | None, now: datetime | None = None, test: bool = False) -> dict:
    """AWS 누적 면 — 강수 누적 카드 구간의 관측소 합(기상청 + 경남 AWS)을 IDW 로. 'n' = 쓴 관측소 수."""
    now = now or clock.now()
    want, _ = _acc_keys(hours, since, now, test)
    st = {}
    if test:                                   # 합성 누적 격자를 관측소 자리에서 읽어 — 모양 점검용
        tot = acc_sum(hours, since, now=now, test=True)["total"]
        hb = gridstore.geo()["hr"]["bbox"]
        base = [{**s, "org": "kma"} for s in station_sites()["stations"]] + sites.gn_sites()
        pts = []
        for s in base:
            c, r = round(s["x"]) - hb["i0"], round(s["y"]) - hb["j0"]
            if 0 <= r < hb["h"] and 0 <= c < hb["w"] and np.isfinite(tot[r, c]):
                pts.append((s["x"], s["y"], float(tot[r, c])))
    else:
        st = _acc_station_values(hours, since, _kma_gn_base())
        pts = [(s["x"], s["y"], s["v"]) for s in st["rows"] if s["q"] in ("ok", "part") and s["v"] is not None]
    live = None if test else st.get("live")
    ck = (tuple(want), live, test, tuple(sorted(pts)))
    hit = _aws_cached(ck)
    if hit is None:
        hit = {"arr": idw_surface(pts)}
        if len(_AWS_CACHE) > 40:
            _AWS_CACHE.pop(next(iter(_AWS_CACHE)))
        _AWS_CACHE[ck] = hit
    n_gn = sum(1 for x, y, _ in pts if any(abs(x - g["x"]) < 1e-6 and abs(y - g["y"]) < 1e-6 for g in sites.gn_sites()))
    return {"grid": "hr", "tm": live or want[-1], "from": want[0], "arr": hit["arr"], "n": len(pts), "n_gn": n_gn,
            **({"live": live} if live else {}), **({"test": True} if test else {})}


def _hour_keys(now: datetime, test: bool) -> list[str]:
    """정시 키들(오래된 것부터) — 누적 층과 같은 정시 60분 격자 키. 테스트는 지난 하루를 지어낸다."""
    if test:
        last = _floor10(now - timedelta(minutes=6)).replace(minute=0)
        return [(last - timedelta(hours=h)).strftime("%Y%m%d%H%M") for h in range(23, -1, -1)]
    return [k for k in gridstore.keys("obs60") if k.endswith("00")]


def _kma_gn_base() -> list[dict]:
    return [{k: s[k] for k in ("stn", "name", "sigun", "x", "y", "ht")} for s in station_sites()["stations"]] \
        + sites.gn_sites()


def _sampled_pts(arr: np.ndarray) -> list[tuple[float, float, float]]:
    """테스트 — 합성 격자를 관측소 자리에서 읽은 값(모양 점검용, 실제 자료가 아니다)."""
    hb = gridstore.geo()["hr"]["bbox"]
    pts = []
    for s in [{**s, "org": "kma"} for s in station_sites()["stations"]] + sites.gn_sites():
        c, r = round(s["x"]) - hb["i0"], round(s["y"]) - hb["j0"]
        if 0 <= r < hb["h"] and 0 <= c < hb["w"] and np.isfinite(arr[r, c]):
            pts.append((s["x"], s["y"], float(arr[r, c])))
    return pts


def _hour_pts(tm: str, now: datetime, test: bool) -> list[tuple[float, float, float]]:
    if test:
        return _sampled_pts(synth("obs60", "hr", (_dt(tm) - now).total_seconds() / 60))
    st = _station_sums([tm], _kma_gn_base())
    return [(s["x"], s["y"], s["v"]) for s in st["rows"] if s["q"] in ("ok", "part") and s["v"] is not None]


def _minute_values(tm: str, base: list[dict]) -> dict:
    """AWS 1시간 '지금' 칸 — 그 분의 직전 60분(기상청 매분자료 RN-60m). 경남 AWS 는 정시 자료라 자리만(q none)."""
    with db.tx() as con:
        got = {r["stn"]: (r["rn_60m"] if r["quality"] == "ok" else None) for r in con.execute(
            "SELECT stn, rn_60m, quality FROM obs_minute WHERE tm=?", (_minute_key(tm),))}
    rows = []
    for b in base:
        if b["stn"] not in got:
            rows.append({**b, "v": None, "q": "none"})
            continue
        v = got[b["stn"]]
        bad = v is None or v < 0
        rows.append({**b, "v": None if bad else round(v, 1), "q": "missing" if bad else "ok"})
    return {"tm": tm, "status": "ok" if got else "none", "live": tm,
            "src": f"기상청 매분자료 {tm[8:10]}:{tm[10:12]} · 직전 60분 — 경남 AWS 는 정시 자료라 정시 칸에만" if got else "",
            "rows": rows}


def aws_hour_now(now: datetime | None = None, test: bool = False) -> str | None:
    """AWS 1시간 층의 '지금' — 마지막 정시 뒤 매분자료가 있으면 그 분(직전 60분), 없으면 관측소 값이 든 마지막 정시."""
    now = now or clock.now()
    last = aws_hour_latest(now, test)
    return (None if test else live_minute(last, now)) or last


def aws_hour_latest(now: datetime | None = None, test: bool = False) -> str | None:
    """AWS 1시간 층의 '지금' — 관측소 값이 하나라도 든 가장 최근 정시(최근 넷까지만 거슬러 본다).
    ⚠️ 정시자료(awsh)는 정시 뒤 몇 분~몇십 분 늦게 온다 — 마지막 정시 격자가 있어도 관측소는 아직일 수 있다."""
    now = now or clock.now()
    ks = _hour_keys(now, test)
    for k in reversed(ks[-4:]):
        if test or _hour_pts(k, now, False):
            return k
    return None


def aws_hour_frame(tm: str | None, now: datetime | None = None, test: bool = False) -> dict:
    """AWS 1시간 면 — 정시 tm 한 시간 몫(기상청 + 경남 AWS)을 누적 층과 같은 IDW 로. tm 이 없으면 aws_hour_now.
    정시 값이 없는 시각(정시가 아니거나 정시자료가 아직)은 그 분의 매분자료 직전 60분(기상청만) — '지금' 칸."""
    now = now or clock.now()
    tm = tm or aws_hour_now(now, test)
    if not tm:
        raise LookupError("관측소 정시 강수량이 아직 없다")
    if len(tm) != 12 or not tm.isdigit():
        raise LookupError(f"시각은 YYYYMMDDHHMI: {tm}")
    pts = _hour_pts(tm, now, test) if tm.endswith("00") else []
    live = None
    if not pts and not test:
        st = _minute_values(tm, _kma_gn_base())
        pts = [(s["x"], s["y"], s["v"]) for s in st["rows"] if s["q"] == "ok"]
        live = tm if pts else None
    if not pts:
        raise LookupError(f"AWS 1시간 {tm} — 그 시각 관측소 값이 없다" if test or tm.endswith("00")
                          else f"AWS 1시간 {tm} — 정시도 아니고 그 분 매분자료도 없다")
    ck = ("h", tm, test, tuple(sorted(pts)))
    hit = _aws_cached(ck)
    if hit is None:
        hit = {"arr": idw_surface(pts)}               # 값 있는 관측소가 없으면 LookupError
        if len(_AWS_CACHE) > 40:                      # 재생 한 바퀴(지난 12시간)가 다 들어가게
            _AWS_CACHE.pop(next(iter(_AWS_CACHE)))
        _AWS_CACHE[ck] = hit
    gn = {(g["x"], g["y"]) for g in sites.gn_sites()}
    return {"grid": "hr", "tm": tm, "arr": hit["arr"], "n": len(pts),
            "n_gn": sum(1 for x, y, _ in pts if (x, y) in gn), **({"live": live} if live else {}),
            **({"test": True} if test else {})}


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
        f = _tfac(b["stn"])
        ok = v == v
        rows.append({**b, "v": round(v * f, 1) if ok else None, "q": "ok" if ok else "missing"})
    return {"tm": fr["tm"], "status": "test", "src": "합성 — 실제 자료 아님", "rows": rows}


def stations(layer: str, tm: str | None = None, test: bool = False, case: str | None = None,
             hours: int | None = None, since: str | None = None) -> dict:
    """관측소 — 기상청 AWS(stations.json) + 경남 AWS(경남 AWS 목록, org 'gn'). 사례에는 기상청만(그때 자료가 기상청뿐)."""
    st_ = station_sites()
    kma = [{k: s[k] for k in ("stn", "name", "sigun", "x", "y", "ht")} | {"org": "kma"} for s in st_["stations"]]
    head = {"layer": layer, "sites": st_["source"], "unsited": st_.get("missing", [])}
    if case:
        from . import gridcase
        return {**head, **gridcase.stations(case, layer, tm, kma)}
    base = kma + sites.gn_sites()
    kind, _ = split(layer)
    if kind in ("acc", "aws") and not test:
        upto = "grid" if kind == "acc" else tm if tm and len(tm) == 12 and tm.isdigit() else "minute"
        return {**head, **_acc_station_values(*acc_window(hours, since), base, upto)}
    if kind == "aws60" and not test:
        tm = tm or aws_hour_now()
        if not tm:
            raise LookupError("관측소 정시 강수량이 아직 없다")
        st = _station_sums([tm], base) if tm.endswith("00") else None
        if not st or not any(r["q"] in ("ok", "part") for r in st["rows"]):
            st = _minute_values(tm, base)                 # '지금' 칸 — 그 분의 직전 60분(기상청만)
        return {**head, **st}
    if kind not in STN_VALUE and not (test and kind in ("acc", "aws", "aws60")):
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
def acc_table(acc: np.ndarray, frames: list, sigun: str | None = None, h1: np.ndarray | None = None) -> list[dict]:
    """acc(경남 bbox 500m 누적), frames(매시 배열 또는 None) → 줄들. 값이 없는 줄은 sum None.
    h1(그 시각 60분 격자)을 주면 줄마다 그 칸의 최근 1시간 — 마지막 칸이 '지금' 칸(한 시간이 안 되는 몫)일 때 카드 빗금용."""
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
        if h1 is not None and np.isfinite(h1[r, c]):
            out["h1"] = round(float(h1[r, c]), 1)
        if emd_at:
            out["name"] = emd_at(r, c, sig) or ""
        return out

    emds = {e["id"]: e for e in g["emd"]}
    if not sigun:
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
    sg = siguns_of(sigun)                      # '함양,거창' — 여러 시군 읍면동을 한 표로(비교)
    mine = [e for e in g["emd"] if e["sigun"] in sg]
    ef = memd.ravel()
    return [row(e["name"], e["sigun"], np.flatnonzero(ef == e["id"])) for e in mine]


_ACC_CACHE: dict[tuple, dict] = {}


ACC_DATE_DAYS = 7                 # 날짜 지정 누적 — 오늘부터 며칠 앞까지 고를 수 있나(그날 0시부터)
ACC_SPAN_MAX = 24 * (ACC_DATE_DAYS + 1)      # 그때 최대 시간 수(7일 전 0시 ~ 오늘 23시)


def valid_date(s) -> bool:
    """'YYYYMMDD' 날짜 지정 누적의 시작일인가."""
    if not isinstance(s, str) or len(s) != 8 or not s.isdigit():
        return False
    try:
        datetime.strptime(s, "%Y%m%d")
    except ValueError:
        return False
    return True


def since_day(since: str | None, end: datetime) -> datetime | None:
    """누적 시작 0시 — today · yesterday · 'YYYYMMDD'(날짜 지정). 지난 N시간이면 None."""
    if since in ("today", "yesterday"):
        return end.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1 if since == "yesterday" else 0)
    if valid_date(since):
        return datetime.strptime(since, "%Y%m%d")
    return None


def span_hours(since: str | None, end: datetime, hours: int = 12) -> int:
    """누적 구간 시간 수 — since 가 today/yesterday/날짜(YYYYMMDD)면 그날 0시부터 end(마지막 정시)까지, 아니면 hours.

    ⚠️ 정시 'H시' 한 장은 (H-1)~H시다. 0시부터 15시까지는 01·02 … 15시 열다섯 장이다.
       0시 정각이면 오늘 몫이 아직 없다 — 한 장(어제 23~24시)이라도 보여 준다.
    날짜 지정은 ACC_SPAN_MAX(8일)까지 — 그보다 앞이면 그만큼만(설정이 7일 앞까지만 받는다)."""
    d0 = since_day(since, end)
    if d0 is None:
        return max(1, min(48, int(hours)))
    cap = 48 if since in ("today", "yesterday") else ACC_SPAN_MAX
    return max(1, min(cap, int((end - d0).total_seconds() // 3600)))


_SUM_CACHE: dict[tuple, dict] = {}


def acc_window(hours: int | None = None, since: str | None = None) -> tuple[int, str | None]:
    """누적 구간 — 주지 않으면 지도 설정(강수 누적 카드가 고른 것).
    since 는 today | yesterday | 'YYYYMMDD'(날짜 지정 — 설정 acc_from=date · acc_date) | None(지난 hours)."""
    if hours is None or since is None:
        st = setting()
        hours = int(hours or st.get("acc_hours") or 12)
        if since is None:
            since = st.get("acc_from")
            if since == "date":
                since = st.get("acc_date")
    return int(hours), (since if since in ("today", "yesterday") or valid_date(since) else None)


def _acc_keys(hours: int, since: str | None, now: datetime, test: bool) -> tuple[list[str], list[str]]:
    if test:
        last = _floor10(now - timedelta(minutes=6)).replace(minute=0)
    else:
        ks = [k for k in gridstore.keys("obs60") if k.endswith("00")]
        if not ks:
            raise LookupError("정시 60분 격자가 아직 없다")
        last = _dt(ks[-1])
    hours = span_hours(since, last, hours)
    want = [(last - timedelta(hours=h)).strftime("%Y%m%d%H%M") for h in range(hours - 1, -1, -1)]
    have = want if test else [k for k in want if gridstore.has("obs60", k)]
    return want, have


def _acc_frames(want: list[str], have: list[str], now: datetime, test: bool) -> list:
    if test:
        return [synth("obs60", "hr", (_dt(k) - now).total_seconds() / 60) for k in want]
    return [gridstore.load("obs60", k) if k in have else None for k in want]


def _grid_tail_key(after: str) -> str | None:
    """격자 누적 '지금' 칸의 시각 — 정시 after 뒤 같은 날의 가장 최근 일강수 격자. 뺄 기준(after 일강수)이 없으면 None.
    after 가 0시 정각이면 기준은 0(그날 일강수가 곧 0시부터의 합). 일강수 00:00 · 00:05 는 받지 않는다(grid_rain)."""
    ks = [k for k in gridstore.keys("obsday") if k[:8] == after[:8] and k > after]
    if not ks or (after[8:] != "0000" and not gridstore.has("obsday", after)):
        return None
    return ks[-1]


def _grid_tail(after: str, key: str) -> np.ndarray:
    """정시 after 뒤 ~ key — 일강수 증분. 음수 칸은 0(분석 잡음 — 누적이 줄 수는 없다), 결측은 결측."""
    cur = gridstore.load("obsday", key)
    base = 0.0 if after[8:] == "0000" else gridstore.load("obsday", after)
    return np.maximum(cur - base, 0.0)


def acc_sum(hours: int = 12, since: str | None = None, now: datetime | None = None, test: bool = False) -> dict:
    """누적 구간 정시 60분 격자를 칸마다 더한 것 — 강수 누적 카드(acc)와 지도 '누적' 층(frame acc)이 같은 합을 쓴다.
    → {want(정시 키), have(받은 것), total, tail(지금 칸 시각|None), tail_arr}. 결측 칸은 결측으로 남는다(0 으로 치지 않는다).
    tail — 마지막 정시 뒤 ~ 가장 최근 일강수 격자(10분 칸)의 일강수 증분을 더한다. 그래서 정시에만 바뀌던 누적이 10분마다 는다."""
    now = now or clock.now()
    want, have = _acc_keys(hours, since, now, test)
    tk = None if test else _grid_tail_key(want[-1])
    ck = (tuple(want), tuple(have), tk, test, now.strftime("%Y%m%d%H") if test else "")
    if ck in _SUM_CACHE:
        return _SUM_CACHE[ck]
    got = [f for f in _acc_frames(want, have, now, test) if f is not None]
    if not got:
        raise LookupError("이 구간에 받은 정시 격자가 없다")
    total = got[0].copy()
    for f in got[1:]:
        total = total + f
    tail = _grid_tail(want[-1], tk) if tk else None
    if tail is not None:
        total = np.where(np.isfinite(tail), total + tail, total)
    total.setflags(write=False)
    out = {"want": want, "have": have, "total": total, "tail": tk, "tail_arr": tail}
    if len(_SUM_CACHE) > 4:                       # 한 장이 1~2MB — 몇 개만
        _SUM_CACHE.pop(next(iter(_SUM_CACHE)))
    _SUM_CACHE[ck] = out
    return out


def acc(hours: int = 12, sigun: str | None = None, now: datetime | None = None,
        test: bool = False, since: str | None = None) -> dict:
    """지난 hours 시간(가장 최근 정시 격자까지) 격자 누적 — 시군 줄, 또는 sigun 의 읍면동 줄.
    since=today|yesterday 면 그날 0시부터(시간 수는 마지막 정시 격자에서 센다)."""
    now = now or clock.now()
    want, have = _acc_keys(hours, since, now, test)
    hours = len(want)
    tk = None if test else _grid_tail_key(want[-1])
    ck = (tuple(have), hours, sigun, tk, test, now.strftime("%Y%m%d%H") if test else "")
    if ck in _ACC_CACHE:
        return _ACC_CACHE[ck]
    s = acc_sum(hours, None, now=now, test=test)
    frames = _acc_frames(want, have, now, test)
    total = s["total"]
    keys, h1 = list(want), None
    if s["tail"]:                                # '지금' 칸 — 줄의 마지막 칸(한 시간이 안 되는 몫), 빗금은 그 시각 60분 격자
        frames = frames + [s["tail_arr"]]
        keys.append(s["tail"])
        h1 = gridstore.load("obs60", s["tail"]) if gridstore.has("obs60", s["tail"]) else None
    out = {"basis": "grid", "hours": hours, "frames": keys, "tm": s["tail"] or want[-1], "sigun": sigun,
           "missing": len(want) - len(have), "test": test, **({"tail": s["tail"]} if s["tail"] else {}),
           "src": "합성 — 실제 자료 아님" if test else "기상청 고해상도 격자(500m) · 매시 60분 합"
                  + (f" + {want[-1][8:10]}:00~{s['tail'][8:10]}:{s['tail'][10:12]}(일강수 차)" if s["tail"] else ""),
           "rows": acc_table(total, frames, sigun, h1)}
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


def flow(hours: int = 6, step: int = 10, now: datetime | None = None, test: bool = False,
         src: str = "grid") -> dict:
    """src = grid(500m 60분, step 분마다) | aws(AWS 1시간 면, 정시마다 — 경남 AWS 가 정시 자료라 간격은 1시간)."""
    now = now or clock.now()
    start = now - timedelta(hours=hours)
    frames: list[dict] = []
    # ⚠️ 가장 최근 실측은 간격과 상관없이 늘 넣는다. 30분 간격에 최신이 23:40 이면
    #    23:30 에서 흐름이 끝나 '지금' 화면이 재생 막대 밖으로 빠졌다.
    if src == "aws":
        last = aws_hour_latest(now, test)
        # 관측소 값이 하나도 없는 정시(수집이 비었던 시간)는 건너뛴다 — 한 장 때문에 흐름 전체가 404 가 되지 않게
        frames = [{"t": k, "kind": "obs", "layer": "aws60", "key": k} for k in _hour_keys(now, test)
                  if last and start <= _dt(k) <= _dt(last) and (test or _hour_pts(k, now, False))]
        live = None if test else live_minute(last, now)
        if live:                                  # '지금' 칸 — 매분 직전 60분(마지막 정시 뒤, 1분마다 바뀐다)
            frames.append({"t": live, "kind": "obs", "layer": "aws60", "key": live, "live": True})
        if test:
            tmfc = _floor10(now).strftime("%Y%m%d%H%M")
            tmefs = [(now + timedelta(hours=n)).strftime("%Y%m%d%H00") for n in range(1, 7)]
        else:
            tmfc, tmefs = vsrt_run()
    elif test:
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
        f.setdefault("layer", "obs60")
        f.setdefault("key", f["t"])
    for n, ef in enumerate(tmefs[:6], 1):
        frames.append({"t": ef, "kind": "fcst", "layer": f"vsrt+{n}", "n": n,
                       "key": f"{tmfc}_{ef}", "tmfc": tmfc})

    names = [s["name"] for s in gridstore.geo()["sigun"] if s["kind"] == "gn"]
    series = {s: {"max": [], "mean": []} for s in names + ["경남"]}
    for f in frames:
        if f.get("layer") == "aws60":
            vals = gridstore.sigun_values(aws_hour_frame(f["t"], now=now, test=test)["arr"])
        elif test:
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
            "hours": hours, "step": 60 if src == "aws" else step, "src": src, "tmfc": tmfc, "frames": frames,
            "series": [{"sigun": s, **series[s]} for s in names], "total": series["경남"]}


# ── 목록 · 지연 ─────────────────────────────────────────────────────────
def meta(now: datetime | None = None) -> dict:
    now = now or clock.now()
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
            elif kind == "aws60":
                last = aws_hour_latest(now)
                k = live_minute(last, now) or last
                row.update(tm=k, live=k is not None and k != last)
                age = (now - _dt(k)).total_seconds() / 60 if k else None
            elif kind in ("acc", "aws"):
                ks = [k for k in gridstore.keys("obs60") if k.endswith("00")]
                live = (live_minute(ks[-1], now) if kind == "aws" else _grid_tail_key(ks[-1])) if ks else None
                row.update(tm=live or (ks[-1] if ks else None), frames=len(ks), live=bool(live))
                age = (now - _dt(ks[-1])).total_seconds() / 60 if ks else None
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
                   # 누적 구간을 어디서부터 — hours(지난 acc_hours 시간) · today(오늘 0시부터) · yesterday(어제 0시부터)
                   # · date(acc_date 'YYYYMMDD' 0시부터 — 오늘부터 ACC_DATE_DAYS 일 앞까지)
                   "acc_from": "hours", "acc_date": "",
                   # 누적 카드 기준 — aws: 관측소 다우지점(스방 265 → 기상청 56) / grid: 격자 누적 최대 칸
                   "acc_basis": "aws",
                   # 시군을 누르면 그 시군으로 확대(읍면동 경계·이름이 나온다). 끄면 테두리만
                   "sel_zoom": True,
                   # 누적 카드에 예상(앞으로 6시간)을 붙이나 — 카드 머리 AWS|격자 옆 단추(F)
                   "acc_fc": True,
                   # 누적 막대의 실측 중 최근 1시간을 빗금으로 강조하나(H)
                   "acc_h1": True,
                   # 지도 색 — blue: 청색 램프 / kma: 기상청 레이더 색(예측 분포 범례에서 뽑은 색)
                   "pal": "blue",
                   # 위 카드 줄 세우기(우클릭) — 시군당 1·2·3곳, 0 = 시군 무관(전 지점 순위)
                   "acc_per": 1,
                   # 위 카드를 패널 가득(지금 오는 비 · 예측 상위를 감춘다) — 카드 머리 단추
                   "acc_full": False,
                   # AWS 실시간 감시 — 끄면 AWS 누적 · 1시간이 정시마다, 켜면 마지막 정시 뒤 매분까지 1분마다(R).
                   # 1분 수집기(minute)도 켠 동안만 기상청을 부른다
                   "aws_live": False,
                   # 오른쪽 패널 아래를 '예측 분포 재생'(초단기 QPF B 융합 그림)으로 — 강수 누적과 같이 본다(Q).
                   # 지도를 재생하는 동안은 그림이 지도와 같은 시각으로 따라간다
                   "acc_qpf": False,
                   # 초단기예측 이미지 한 장 머무는 시간(ms) — 따로 재생할 때(지도와 같이 갈 때는 지도 빠르기)
                   "qpf_ms": 600,
                   # 강수 누적 카드 머리(제목 · 설명 · 단추) 고정 — 끄면 마우스를 올렸을 때만, 평소에는 시군 줄만
                   "acc_hdr_pin": True,
                   # 지도 위에 겹칠 레이어(왼쪽 위 '레이어'에서 켠다). 차츰 늘린다.
                   "overlays": []}
OVERLAYS = ("alerts", "stations", "stnval")   # stnval = 관측소 옆 값 글자(관측소에 딸림)
_CHOICES = {"flow_step": (10, 20, 30, 60), "flow_hours": (1, 3, 6, 12),
            "play_ms": (400, 600, 1200, 2000, 3000), "tl_stat": ("max", "mean"),
            "qpf_ms": (250, 400, 600, 1000, 1500),
            "panel": ("cards", "timeline"), "acc_hours": (6, 12, 24, 48),
            "acc_from": ("hours", "today", "yesterday", "date"),
            "acc_basis": ("aws", "grid"),
            # 지도 색 — 청색 램프 / 기상청 레이더 색(범례 색 띠를 누르면 바뀐다)
            "pal": ("blue", "kma"),
            # 위 카드 줄 세우기 — 시군당 n곳, 0 = 시군 무관
            "acc_per": (0, 1, 2, 3)}
_TEXT = {"tl_stat", "panel", "acc_basis", "acc_from", "pal"}


def setting() -> dict:
    return db.get_setting("map", SETTING_DEFAULT)


def put_setting(body: dict) -> dict:
    cur = setting()
    if "layer" in body:
        split(str(body["layer"]))            # 모르는 층이면 LookupError
        cur["layer"] = str(body["layer"])
    for k in ("x4", "tl_on", "sel_zoom", "acc_fc", "acc_h1", "acc_full", "aws_live", "acc_qpf", "acc_hdr_pin"):
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
    if "acc_date" in body:
        d = str(body["acc_date"] or "")
        if not valid_date(d):
            raise ValueError("acc_date 는 YYYYMMDD")
        today = clock.now().replace(hour=0, minute=0, second=0, microsecond=0)
        if not today - timedelta(days=ACC_DATE_DAYS) <= datetime.strptime(d, "%Y%m%d") <= today:
            raise ValueError(f"acc_date 는 오늘부터 {ACC_DATE_DAYS}일 앞까지")
        cur["acc_date"] = d
    if cur.get("acc_from") == "date" and not valid_date(cur.get("acc_date")):
        raise ValueError("날짜 지정 누적에는 acc_date 가 있어야 한다")
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

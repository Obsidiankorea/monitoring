"""우려지역 지구의 '지역 여건' — 지형(미리 계산한 data/geo/dz_terrain.json) + 과거 침수흔적(safety 가 받아 둔 다각형).

판정 %(강우 기준)는 바꾸지 않는다. 위키 [[대피판단 기준 (주민대피 길라잡이 2026.5판)]]의 '지역 여건'(배수 불량 저지대 · 급경사지 인접 ·
상습 침수 · 저수지 제방)을 숫자로 보여 주고, 눈여겨볼 것만 꼬리표(flags)로 단다. 꼬리표 문턱 — 위키 수치가 있는 것:
  급경사 30°↑ — [[산사태 유형과 발생 원인]] '30~35°에서 가장 많이, 20° 이하는 적다'
  붕괴위험지역 안 — 급경사지법으로 지정 · 고시된 구역(국토교통부 연속주제도) 그 자체가 근거
그 밖(저지대 10m↓ — 지도 '저지대' 레이어와 같은 문턱, 위키엔 수치 없음 · 국가 · 지방하천 200m 안 · 5m 안 높이, 저수지 300m 안 · 10m 낮음, 해안 500m · 5m)은 위키 수치가 없어 이 앱이 정한 눈여겨볼 범위다 — 화면에도 그렇게 적는다.
"""
from __future__ import annotations

import gzip
import json
import math
import time
from functools import lru_cache

from . import config
from .domain.gridproj import hr_xy

DZT = config.DATA / "geo" / "dz_terrain.json"
TER = config.ROOT / "app" / "web" / "static" / "terrain"     # 지도 지형 그림과 같은 125m 표고(elev.i16.gz) — 저수지 자리 높이


@lru_cache(maxsize=2)
def _dzt(mtime: float) -> dict:
    return json.loads(DZT.read_text("utf-8"))


def table() -> dict:
    try:
        return _dzt(DZT.stat().st_mtime)
    except OSError:
        return {"rows": {}}


DZH = config.DATA / "geo" / "dz_history.json"            # 최근 10년 호우 피해 이력(tools/build_dz_history.py — 경남도 복구계획)


@lru_cache(maxsize=2)
def _dzh(mtime: float) -> dict:
    return json.loads(DZH.read_text("utf-8"))


def history(sigun: str | None, emd: str | None) -> dict | None:
    """그 읍면동 · 시군의 지난 호우 이력 — {e: 읍면동(확인된 것만), s: 시군, span}. 자료가 없으면 None."""
    try:
        h = _dzh(DZH.stat().st_mtime)
    except OSError:
        return None
    e, s = h["emd"].get(f"{sigun}|{emd}"), h["sigun"].get(sigun or "")
    return {"e": e, "s": s, "span": h["span"]} if e or s else None


@lru_cache(maxsize=2)
def _floods(mtime: float) -> list[tuple]:
    from . import safety
    out = []
    for f in json.loads(safety.FLOOD_FILE.read_text("utf-8")):
        pts = [p for r in f["r"] for p in r]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        out.append(((min(xs), min(ys), max(xs), max(ys)), f["r"], f.get("yr"), f.get("nm") or ""))
    return out


def floods() -> list[tuple]:
    from . import safety
    try:
        return _floods(safety.FLOOD_FILE.stat().st_mtime)
    except (OSError, ValueError):
        return []


def _inside(lon: float, lat: float, rings: list) -> bool:
    c = False
    for r in rings:                                         # 짝홀 규칙 — 구멍 고리도 같이
        for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
            if (y1 > lat) != (y2 > lat) and lon < (x2 - x1) * (lat - y1) / (y2 - y1) + x1:
                c = not c
    return c


def flood_at(lat: float, lon: float) -> dict | None:
    """지구 자리가 과거 침수흔적 안이면 그 흔적, 100m 안이면 near."""
    dx, dy = 0.0011, 0.0009                                 # ≈ 100m
    near = None
    for (x0, y0, x1, y1), rings, yr, nm in floods():
        if not (x0 - dx <= lon <= x1 + dx and y0 - dy <= lat <= y1 + dy):
            continue
        if _inside(lon, lat, rings):
            return {"in": True, "yr": yr, "nm": nm}
        if near is None and any(math.hypot((p[0] - lon) / dx, (p[1] - lat) / dy) <= 1 for r in rings for p in r):
            near = {"in": False, "yr": yr, "nm": nm}
    return near


@lru_cache(maxsize=1)
def _elev():
    m = json.loads((TER / "terrain.json").read_text("utf-8"))
    import array
    a = array.array("h"); a.frombytes(gzip.decompress((TER / "elev.i16.gz").read_bytes()))
    return m, a


def elev_at(lon: float, lat: float) -> float | None:
    """125m 표고(m) — 경남 bbox 밖이면 None."""
    try:
        m, a = _elev()
    except OSError:
        return None
    b, S = m["bbox"], m["S"]
    gx, gy = hr_xy(lon, lat)
    c, r = int((gx - (b["i0"] - 0.5)) * S), int((b["j1"] + 0.5 - gy) * S)
    return float(a[r * m["w"] + c]) if 0 <= c < m["w"] and 0 <= r < m["h"] else None


@lru_cache(maxsize=1)
def _rivers() -> dict:
    """하천중심선(water.json, 이름 있는 선)을 50m 간격 점으로 — {(칸 x, 칸 y): [(x, y, 이름)]}."""
    fs = json.loads((TER.parent / "water" / "water.json").read_text("utf-8"))["features"]
    b: dict = {}
    for f in fs:
        p = f["properties"]
        if p["k"] != "river" or not p.get("n"):
            continue
        for line in f["geometry"]["coordinates"]:
            for (x1, y1), (x2, y2) in zip(line[:-1], line[1:]):
                n = max(1, int(math.hypot(x2 - x1, y2 - y1) / 0.1))
                for k in range(n + 1):
                    x, y = x1 + (x2 - x1) * k / n, y1 + (y2 - y1) * k / n
                    b.setdefault((int(x), int(y)), []).append((x, y, p["n"]))
    return b


@lru_cache(maxsize=4096)
def river_of(x: float, y: float, rm: int = 300) -> str:
    """칸 좌표 자리에서 rm 안 가장 가까운 이름 있는 하천 — 수위관측소(300m) · 지구(2km)가 어느 하천인지(관측소 자료엔 하천명이 없다)."""
    try:
        b = _rivers()
    except OSError:
        return ""
    r = int(rm / 500) + 1
    pts = [p for i in range(-r, r + 1) for j in range(-r, r + 1) for p in b.get((int(x) + i, int(y) + j), [])]
    best = min(((math.hypot(px - x, py - y), n) for px, py, n in pts), default=None)
    return best[1] if best and best[0] * 500 <= rm else ""


@lru_cache(maxsize=2)
def _live(tick: int) -> tuple[list, list]:
    """지금 수위관측소(기준 수위가 있는 것) · 위험저수지 계측기 경보 — 30초마다 다시 읽는다."""
    from . import river, safety
    wl = [s for s in river.status()["rows"] if s["kind"] == "wl" and not s.get("up") and any(s.get("thr") or []) and "저수지" not in s["name"]]
    return wl, list(safety._LIVE.get("res") or [])


def live(d: dict) -> dict:
    """지구 자리 둘레의 지금 값 — 가장 가까운 수위관측소(5km 안) 단계, 위쪽(5m↑ 높은) 위험저수지 계측기 경보(3km 안)."""
    pos = d.get("pos")
    if not pos:
        return {}
    from .river import STAGES
    wl, res = _live(int(time.time() // 30))
    gx, gy = hr_xy(pos[1], pos[0])
    out = {}
    # 같은 하천(지구 2km 안 이름 있는 하천 = 관측소 자리 300m 안 하천) 20km 안이 먼저, 없으면 아무 하천 5km 안
    near = sorted(((math.hypot(s["x"] - gx, s["y"] - gy) * 500, s) for s in wl), key=lambda x: x[0])
    rn = river_of(round(gx, 2), round(gy, 2), 2000)          # 지구에서 2km 안 가장 가까운 이름 있는 하천
    same = next(((dm, s) for dm, s in near if dm <= 20000 and rn and river_of(round(s["x"], 2), round(s["y"], 2)) == rn), None)
    best = same or next(((dm, s) for dm, s in near if dm <= 5000), None)
    if best:
        dm, s = best
        st = s.get("stage", -1)
        out["wl"] = {"n": s["name"], "d": round(dm), "st": st, "stn": STAGES[st] if 0 <= st < len(STAGES) else "값 없음",
                     "v": s.get("v"), "gap": s.get("gap"), "nx": STAGES[min(st + 1, len(STAGES) - 1)] if st >= 0 else None, "stale": bool(s.get("stale")),
                     "rn": river_of(round(s["x"], 2), round(s["y"], 2)), "same": bool(same)}
    el = d.get("_el")
    for r in res:
        dm = math.hypot((r["lon"] - pos[1]) * 91000, (r["lat"] - pos[0]) * 111000)
        if dm > 3000:
            continue
        er = elev_at(r["lon"], r["lat"])
        if er is None or el is None or er - el < 5:
            continue
        out["rs"] = {"n": r["name"], "d": round(dm), "on": r["on"], "lvn": r["lvn"], "at": r["at"], "dh": round(er - el)}
        break                                                    # res 는 발령 중 · 높은 단계부터 — 첫 것이 가장 급하다
    return out


def of(d: dict) -> dict | None:
    """지구 하나(id · pos · fam)의 지형 사실 + 꼬리표. 지형 표에 없으면(좌표 없음 · 표 만든 뒤 생김) 침수흔적만."""
    t = dict(table()["rows"].get(d.get("id"), {}))
    pos = d.get("pos")
    fl = flood_at(pos[0], pos[1]) if pos else None
    if fl:
        t["fl"] = fl
    t |= live({**d, "_el": t.get("el")})
    hx = history(d.get("sigun"), d.get("emd"))
    if hx:
        t["hx"] = hx
    if not t:
        return None
    fam, F = d.get("fam"), []
    w = lambda s: F.append({"t": s, "lv": "w"})
    i = lambda s: F.append({"t": s, "lv": "i"})
    el = t.get("el")
    if fl:
        yr = "".join(ch for ch in str(fl.get("yr") or "") if ch.isdigit())[:4]   # 연도 칸에 '외' 같은 글이 섞여 온다
        (w if fl["in"] else i)(f"침수흔적{' ' + yr if yr else ''}{'' if fl['in'] else ' 100m 안'}")
    cz = t.get("cz")
    if cz and cz["d"] <= 300:                                      # 급경사지법으로 지정 · 고시된 붕괴위험지역 — 안이면 눈여겨볼 것
        nm = f" {cz['n']}" if cz.get("n") else ""
        (w if cz["d"] == 0 else i)(f"붕괴위험지역{nm}" if cz["d"] == 0 else f"붕괴위험지역{nm} {cz['d']}m")
    sv = t.get("sv")
    if sv and sv["d"] <= 300:                                      # 산림청 · 시군이 지정한 산사태취약지역(산사태 · 토석류)이 가까우면
        (w if sv["d"] <= 100 else i)(f"산사태취약지역({sv['ty']}) {sv['d']}m" + (f" · 300m 안 {sv['n']}곳" if sv["n"] > 1 else ""))
    if el is not None and el <= 10:
        w(f"저지대 {el:.0f}m")
    rv = t.get("rv")
    if rv and rv["d"] <= 200 and rv["dh"] <= 5:                  # 하천 유형(교량 · 둔치 · 세월교)은 하천 자체라 당연 — 참고로만
        (i if fam == "하천" else w)(f"{rv['n'] or '하천'} {rv['d']}m · {max(rv['dh'], 0):.0f}m 위")
    lk = t.get("lk")
    if lk and lk["d"] <= 1000 and lk["dh"] >= 5:                  # 가깝고 꽤 낮을 때만 눈여겨볼 것(산골이면 대개 저수지가 위에 있다)
        (w if lk["d"] <= 300 and lk["dh"] >= 10 else i)(f"{lk['n'] or '저수지'} 아래 {lk['d']}m · {lk['dh']:.0f}m 낮음")
    if t.get("cs") is not None and t["cs"] <= 500 and el is not None and el <= 5:
        w("해안 저지대")
    sl = t.get("sl50", t.get("sl"))                                # 등고선(1:5,000) 경사가 있으면 그것 — 30m 표고는 비탈을 낮게 잡는다
    if fam == "산사태" and sl is not None:
        (w if sl >= 30 else i)(f"경사 {sl}°" + (" 급경사" if sl >= 30 else " 완만" if sl < 20 else ""))
    wl = t.get("wl")
    if wl and wl["st"] >= 0:                                       # 수위 — 관심 이상이면 눈여겨볼 것
        (w if wl["st"] >= 1 else i)(f"수위 {wl['n']} {wl['stn']}" + (f" · {wl['nx']}까지 {wl['gap']}m" if wl.get("gap") is not None and wl["st"] < 4 else ""))
    rs = t.get("rs")
    if rs:                                                         # 위쪽 위험저수지 — 발령 중이면 하류 대피 확인(위키 [[저수지 재난 시군 사전대피와 주민대피 준비 (진주시 매뉴얼)]])
        (w if rs["on"] else i)(f"위험저수지 {rs['n']} {rs['lvn']}{' 발령' if rs['on'] else ' 해제'} · 위쪽 {rs['d']}m")
    if hx and hx["e"]:                                            # 이 읍면동에 지난 10년 복구가 잦았으면 눈여겨볼 것(확인된 건수만 — 실제보다 적다)
        e = hx["e"]
        (w if e["ev"] >= 4 or e["n"] >= 30 else i)(f"최근 10년 호우 {e['ev']}회 · 복구 {e['n']}건({d.get('emd')})")
    if t.get("b300"):
        i(f"건물 {t['b300']}동(300m)" + (f" · 오래된 약한 구조 {t['bo']}동" if t.get("bo") else "") + (f" · 지하층 {t['bb']}동" if t.get("bb") else ""))
    t["flags"] = F
    return t


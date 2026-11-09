"""우려지역 지구의 '지역 여건' — 지형(미리 계산한 data/geo/dz_terrain.json) + 과거 침수흔적(safety 가 받아 둔 다각형).

판정 %(강우 기준)는 바꾸지 않는다. 위키 [[대피판단 기준 (주민대피 길라잡이 2026.5판)]]의 '지역 여건'(배수 불량 저지대 · 급경사지 인접 ·
상습 침수 · 저수지 제방)을 숫자로 보여 주고, 눈여겨볼 것만 꼬리표(flags)로 단다. 꼬리표 문턱은 위키 근거가 있는 것만:
  급경사 30°↑ — [[산사태 유형과 발생 원인]] '30~35°에서 가장 많이, 20° 이하는 적다'
  저지대 10m↓ — 지도 '저지대' 레이어와 같은 문턱(해안 · 강가 저지대 침수, [[고조정보 4단계와 대조기 해안침수]])
그 밖(국가 · 지방하천 200m 안 · 5m 안 높이, 저수지 300m 안 · 10m 낮음, 해안 500m · 5m)은 위키 수치가 없어 이 앱이 정한 눈여겨볼 범위다 — 화면에도 그렇게 적는다.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache

from . import config

DZT = config.DATA / "geo" / "dz_terrain.json"


@lru_cache(maxsize=2)
def _dzt(mtime: float) -> dict:
    return json.loads(DZT.read_text("utf-8"))


def table() -> dict:
    try:
        return _dzt(DZT.stat().st_mtime)
    except OSError:
        return {"rows": {}}


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


def of(d: dict) -> dict | None:
    """지구 하나(id · pos · fam)의 지형 사실 + 꼬리표. 지형 표에 없으면(좌표 없음 · 표 만든 뒤 생김) 침수흔적만."""
    t = dict(table()["rows"].get(d.get("id"), {}))
    pos = d.get("pos")
    fl = flood_at(pos[0], pos[1]) if pos else None
    if fl:
        t["fl"] = fl
    if not t:
        return None
    fam, F = d.get("fam"), []
    w = lambda s: F.append({"t": s, "lv": "w"})
    i = lambda s: F.append({"t": s, "lv": "i"})
    el = t.get("el")
    if fl:
        yr = "".join(ch for ch in str(fl.get("yr") or "") if ch.isdigit())[:4]   # 연도 칸에 '외' 같은 글이 섞여 온다
        (w if fl["in"] else i)(f"침수흔적{' ' + yr if yr else ''}{'' if fl['in'] else ' 100m 안'}")
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
    if fam == "산사태" and t.get("sl") is not None:
        (w if t["sl"] >= 30 else i)(f"경사 {t['sl']}°" + (" 급경사" if t["sl"] >= 30 else " 완만" if t["sl"] < 20 else ""))
    if t.get("b300"):
        i(f"건물 {t['b300']}동(300m)")
    t["flags"] = F
    return t


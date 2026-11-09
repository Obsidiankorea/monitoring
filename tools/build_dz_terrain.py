"""우려지역 지구마다 지형 사실(표고 · 경사 · 하천 · 저수지 · 해안 · 건물)을 미리 계산해 data/geo/dz_terrain.json 에 둔다.

    PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/build_dz_terrain.py [대시보드 주소(기본 NAS :8000)]

판정(%)은 바꾸지 않는다 — 상황판단 창 · AI 에 '지역 여건'으로 보여 준다(위키 [[대피판단 기준 (주민대피 길라잡이 2026.5판)]]:
배수 불량 저지대 · 급경사지 인접 · 저수지 제방 등을 함께 본다).
지구 자리 = 대시보드 /api/districts/all(위키 좌표 + 서버에서 고친 좌표). 자리를 고치면 다시 돌린다.
쓰는 자료(모두 PC 캐시 · 저장소)
  표고 · 경사   tools/.cache/terrain/ (Terrarium z12 ≈ 30m — build_terrain 이 받아 둔 것). 30m 라 축대 · 옹벽 같은 작은 비탈은 안 잡힌다
  하천 · 저수지  app/web/static/water/water.json (국토지리정보원 연속수치지형도 — build_water)
  건물          tools/.cache/vworld/AL_D010_48_*.zip (국토교통부 GIS건물통합정보 — build_bldg)
"""
from __future__ import annotations

import json
import math
import sys
import urllib.request
from collections import defaultdict
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_terrain import Dem  # noqa: E402
from build_bldg import lcc_fwd_np, load as load_bldg  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "geo" / "dz_terrain.json"
M = 500.0                                   # 칸 하나 = 500m
STEP = 0.05                                 # 선 · 테두리를 25m 마다 점으로


def dens(coords):
    """선(칸 좌표 점들)을 STEP 간격 점으로."""
    out = []
    for (x1, y1), (x2, y2) in zip(coords[:-1], coords[1:]):
        n = max(1, int(math.hypot(x2 - x1, y2 - y1) / STEP))
        out += [(x1 + (x2 - x1) * t / n, y1 + (y2 - y1) * t / n) for t in range(n)]
    out.append(tuple(coords[-1]))
    return out


class Pts:
    """점 묶음 + 꼬리표 — 가까운 점 찾기(칸 단위 바구니)."""

    def __init__(self):
        self.x, self.y, self.t = [], [], []

    def add(self, pts, tag):
        for x, y in pts:
            self.x.append(x); self.y.append(y); self.t.append(tag)

    def done(self):
        self.x, self.y = np.array(self.x), np.array(self.y)
        self.b = defaultdict(list)
        for i, (x, y) in enumerate(zip(self.x, self.y)):
            self.b[(int(x), int(y))].append(i)
        self.b = {k: np.array(v) for k, v in self.b.items()}
        return self

    def near(self, x, y, r=4):
        """반지름 r 칸 안 가장 가까운 점 (거리 m, 점 번호) — 없으면 None."""
        ids = [self.b[k] for k in ((int(x) + i, int(y) + j) for i in range(-r, r + 1) for j in range(-r, r + 1)) if k in self.b]
        if not ids:
            return None
        ids = np.concatenate(ids)
        d = np.hypot(self.x[ids] - x, self.y[ids] - y)
        k = int(d.argmin())
        return float(d[k]) * M, int(ids[k])

    def count(self, x, y, rm):
        r = int(rm / M) + 1
        ids = [self.b[k] for k in ((int(x) + i, int(y) + j) for i in range(-r, r + 1) for j in range(-r, r + 1)) if k in self.b]
        if not ids:
            return 0
        ids = np.concatenate(ids)
        return int((np.hypot(self.x[ids] - x, self.y[ids] - y) * M <= rm).sum())


def slope_deg(dem, x, y):
    """지구 둘레 ±90m(30m 간격 7×7)에서 가장 가파른 곳의 경사(°)와 지구 자리 경사."""
    h = 30 / M
    k = (np.arange(7) - 3) * h
    GX, GY = np.meshgrid(x + k, y + k)
    z = dem.sample(GX, GY)
    gy, gx = np.gradient(z, 30.0)
    s = np.degrees(np.arctan(np.hypot(gx, gy)))
    return float(s.max()), float(s[3, 3])


def coast_m(dem, x, y):
    """표고 0m 이하(바다) 땅까지 — 3km 안에서 100m 간격으로 찾는다. 없으면 None."""
    for rm in range(0, 3001, 100):
        if rm == 0:
            if dem.sample(np.array([x]), np.array([y]))[0] <= 0:
                return 0
            continue
        n = max(8, int(2 * math.pi * rm / 100))
        a = np.linspace(0, 2 * math.pi, n, endpoint=False)
        z = dem.sample(x + np.cos(a) * rm / M, y + np.sin(a) * rm / M)
        if (z <= 0).any():
            return rm
    return None


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://100.106.116.92:8000"
    p = json.loads((ROOT / "data" / "geo" / "grids.json").read_text(encoding="utf-8"))["hr"]
    rows = json.loads(urllib.request.urlopen(f"{base}/api/districts/all", timeout=120).read())["rows"]
    rows = [r for r in rows if r.get("pos")]
    print(f"지구 {len(rows)}곳(좌표 있음) — {base}", file=sys.stderr)
    dem = Dem(p)

    wj = json.loads((ROOT / "app" / "web" / "static" / "water" / "water.json").read_text(encoding="utf-8"))["features"]
    riv, st, lake, names = Pts(), Pts(), Pts(), []          # riv = 국가 · 지방하천 선 + 넓은 강(실폭) 테두리, st = 소하천 · 개울 선
    for f in wj:
        pr, g = f["properties"], f["geometry"]
        names.append((pr.get("n") or "", pr.get("g") or 0, pr["k"], bool(pr.get("r"))))
        tag = len(names) - 1
        if pr["k"] == "river":
            for line in g["coordinates"]:
                (riv if pr.get("g") in (1, 2) else st).add(dens(line), tag)
        elif pr.get("r"):                                  # 실폭하천 면 테두리 = 강가
            riv.add(dens(g["coordinates"][0]), tag)
        else:                                              # 호수 · 저수지 테두리
            lake.add(dens(g["coordinates"][0]), tag)
    riv.done(); st.done(); lake.done()
    print(f"하천 점 {len(riv.x):,} · 호수 · 저수지 점 {len(lake.x):,}", file=sys.stderr)

    rings, _ = load_bldg(p)
    bl = Pts()
    bl.add([(float(r[:, 0].mean()), float(r[:, 1].mean())) for r in rings], 0)
    bl.done()
    print(f"건물 {len(bl.x):,}동", file=sys.stderr)

    out = {}
    lat = np.array([r["pos"][0] for r in rows]); lon = np.array([r["pos"][1] for r in rows])
    GX, GY = lcc_fwd_np(lon, lat, p)
    Z = dem.sample(GX, GY)
    for r, x, y, z in zip(rows, GX, GY, Z):
        x, y, z = float(x), float(y), float(z)
        smax, s0 = slope_deg(dem, x, y)
        o = {"el": round(z, 1), "sl": round(smax), "sl0": round(s0)}
        nr = riv.near(x, y)
        if nr:
            d, i = nr
            n, g, k, wide = names[riv.t[i]]
            zr = float(dem.sample(np.array([riv.x[i]]), np.array([riv.y[i]]))[0])
            o["rv"] = {"d": round(d), "n": n, "g": g or (2 if wide else 0), "dh": round(z - zr, 1)}
        ns = st.near(x, y, r=2)
        if ns and ns[0] <= 500:
            o["st"] = round(ns[0])                                # 가장 가까운 소하천 · 개울(m)
        nl = lake.near(x, y, r=6)
        if nl and nl[0] <= 2000:
            d, i = nl
            zl = float(dem.sample(np.array([lake.x[i]]), np.array([lake.y[i]]))[0])
            o["lk"] = {"d": round(d), "n": names[lake.t[i]][0], "dh": round(zl - z, 1)}   # dh > 0 = 저수지 물가가 지구보다 높다
        c = coast_m(dem, x, y)
        if c is not None:
            o["cs"] = c
        o["b100"], o["b300"] = bl.count(x, y, 100), bl.count(x, y, 300)
        out[r["id"]] = o
    OUT.write_text(json.dumps({"built": date.today().isoformat(), "n": len(out),
                               "src": "표고·경사 Terrarium z12(≈30m) · 하천·저수지 국토지리정보원 연속수치지형도 · 건물 국토교통부 GIS건물통합정보",
                               "rows": out}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    v = list(out.values())
    print(f"→ {OUT} {OUT.stat().st_size // 1024}KB · 저지대(10m↓) {sum(x['el'] <= 10 for x in v)} · 경사 30°↑ {sum(x['sl'] >= 30 for x in v)}"
          f" · 하천 100m 안 {sum(x.get('rv', {}).get('d', 9e9) <= 100 for x in v)} · 저수지 아래 {sum(x.get('lk', {}).get('dh', -1) > 0 for x in v)}", file=sys.stderr)


if __name__ == "__main__":
    main()

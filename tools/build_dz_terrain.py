"""우려지역 지구마다 지형 사실(표고 · 경사 · 하천 · 저수지 · 해안 · 건물)을 미리 계산해 data/geo/dz_terrain.json 에 둔다.

    PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/build_dz_terrain.py [대시보드 주소(기본 NAS :8000)]

판정(%)은 바꾸지 않는다 — 상황판단 창 · AI 에 '지역 여건'으로 보여 준다(위키 [[대피판단 기준 (주민대피 길라잡이 2026.5판)]]:
배수 불량 저지대 · 급경사지 인접 · 저수지 제방 등을 함께 본다).
지구 자리 = 대시보드 /api/districts/all(위키 좌표 + 서버에서 고친 좌표). 자리를 고치면 다시 돌린다.
쓰는 자료(모두 PC 캐시 · 저장소)
  표고 · 경사   tools/.cache/terrain/ (Terrarium z12 ≈ 30m — build_terrain 이 받아 둔 것). 30m 라 축대 · 옹벽 같은 작은 비탈은 안 잡힌다
  하천 · 저수지  app/web/static/water/water.json (국토지리정보원 연속수치지형도 — build_water)
  건물          tools/.cache/vworld/AL_D010_48_*.zip (국토교통부 GIS건물통합정보 — build_bldg)
  붕괴위험지역   tools/.cache/vworld/LSMD_CONT_UP401_경남.zip (국토교통부 연속주제도 급경사재해예방/붕괴위험지역, 급경사지법 지정 · 고시)
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
import shapefile

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

    def within(self, x, y, rm):
        """반지름 rm(m) 안 점 번호들."""
        r = int(rm / M) + 1
        ids = [self.b[k] for k in ((int(x) + i, int(y) + j) for i in range(-r, r + 1) for j in range(-r, r + 1)) if k in self.b]
        if not ids:
            return np.array([], int)
        ids = np.concatenate(ids)
        return ids[np.hypot(self.x[ids] - x, self.y[ids] - y) * M <= rm]


WEAK = ("목구조", "벽돌", "블록", "조적", "석구조", "흙")       # 비 · 토사에 약한 구조(건축물대장 구조명에 이 글자가 들면)
OLD_Y = 30                                                # 사용승인 뒤 이 햇수가 지나면 '오래된'


def bldg_attrs(p):
    """건물마다(도형 하나 = 한 동) 자리와 건축물대장 속성 — (Pts, known, weak, base).
    known = 대장이 붙은 건물(용도 · 구조 · 사용승인일이 있다. 경남은 열에 넷쯤만 — 농촌 옛집은 대장이 없는 것이 많다),
    weak = 사용승인 OLD_Y 년 넘은 목 · 벽돌 · 블록 · 조적 · 석 구조, base = 지하층이 있는 건물."""
    import struct
    import zipfile
    from build_bldg import SRC
    z = zipfile.ZipFile(sorted(SRC.glob("AL_D010_48_*.zip"))[-1])
    tr = __import__("pyproj").Transformer.from_crs(5186, 4326, always_xy=True)
    cut = date.today().year - OLD_Y
    X, Y, K, W, B = [], [], [], [], []
    for shp in [n for n in z.namelist() if n.endswith(".shp")]:
        s, d = z.open(shp), z.open(shp[:-4] + ".dbf")
        h = d.read(32)
        cnt, hl, rl = struct.unpack("<IHH", h[4:12])
        hd, fs, o = d.read(hl - 32), {}, 1                 # 머리말 나머지 — 칸 정의 32바이트씩, 0x0D 에서 끝
        for k in range(0, len(hd) - 1, 32):
            f = hd[k:k + 32]
            if f[0] == 0x0D:
                break
            fs[f[:11].split(b"\0")[0].decode()] = (o, f[16]); o += f[16]
        s.read(100)
        g = lambda r, k: r[fs[k][0]:fs[k][0] + fs[k][1]].replace(b"\0", b"").decode("euc-kr", "replace").strip()  # noqa: E731
        for _ in range(cnt):
            r, rh = d.read(rl), s.read(8)
            if len(rh) < 8:
                break
            rec = s.read(struct.unpack(">i", rh[4:8])[0] * 2)
            if struct.unpack("<i", rec[:4])[0] == 0:
                continue
            x0, y0, x1, y1 = struct.unpack("<4d", rec[4:36])
            st, yr, dn = g(r, "A11"), g(r, "A13")[:4], g(r, "A27")
            X.append((x0 + x1) / 2); Y.append((y0 + y1) / 2)
            K.append(bool(st or yr)); B.append(dn not in ("", "0"))
            W.append(yr.isdigit() and 1000 <= int(yr) <= cut and any(k in st for k in WEAK))
    lon, lat = tr.transform(np.array(X), np.array(Y))
    gx, gy = lcc_fwd_np(np.asarray(lon), np.asarray(lat), p)
    pt = Pts()
    pt.x, pt.y, pt.t = list(gx), list(gy), [0] * len(gx)
    return pt.done(), np.array(K), np.array(W), np.array(B)


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


def collapse_zones():
    """급경사 붕괴위험지역 다각형(EPSG:5186 m) — [(고리들, 지구명, 고시일)]. 파일이 없으면 빈 목록."""
    import glob
    import io
    import zipfile
    zp = sorted(glob.glob(str(ROOT / "tools" / ".cache" / "vworld" / "LSMD_CONT_UP401*.zip")))
    if not zp:
        return []
    z = zipfile.ZipFile(zp[-1])
    base = next(n for n in z.namelist() if n.endswith(".shp"))[:-4]
    r = shapefile.Reader(shp=io.BytesIO(z.read(base + ".shp")), shx=io.BytesIO(z.read(base + ".shx")), dbf=io.BytesIO(z.read(base + ".dbf")), encoding="cp949")
    out = []
    for sr in r.iterShapeRecords():
        pts, parts = sr.shape.points, list(sr.shape.parts) + [len(sr.shape.points)]
        rec = sr.record.as_dict()
        out.append(([pts[a:b] for a, b in zip(parts[:-1], parts[1:])], rec.get("REMARK") or rec.get("ALIAS") or "", rec.get("NTFDATE") or ""))
    return out


def zone_at(x, y, zones):
    """점(5186 m)이 붕괴위험지역 안이면 (0, 이름, 고시일), 아니면 가장 가까운 테두리까지 (m, 이름, 고시일)."""
    best = None
    for rings, nm, dt in zones:
        inside, dmin = False, 1e18
        for r in rings:
            for (x1, y1), (x2, y2) in zip(r, r[1:] + r[:1]):
                if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                    inside = not inside
                dx, dy = x2 - x1, y2 - y1
                t = max(0.0, min(1.0, ((x - x1) * dx + (y - y1) * dy) / (dx * dx + dy * dy or 1e-9)))
                dmin = min(dmin, math.hypot(x - x1 - t * dx, y - y1 - t * dy))
        d = 0.0 if inside else dmin
        if best is None or d < best[0]:
            best = (d, nm, dt)
    return best


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
    ba, BK, BW, BB = bldg_attrs(p)
    print(f"건축물대장 붙은 건물 {int(BK.sum()):,} / {len(BK):,} · 오래된 약한 구조 {int(BW.sum()):,} · 지하층 {int(BB.sum()):,}", file=sys.stderr)

    zones = collapse_zones()
    to5186 = __import__("pyproj").Transformer.from_crs(4326, 5186, always_xy=True)
    print(f"붕괴위험지역 {len(zones)}곳", file=sys.stderr)
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
        ii = ba.within(x, y, 300)                                 # 300m 안 — 대장 붙은 동 · 오래된 약한 구조 · 지하층 있는 동
        if len(ii):
            o["bk"], o["bo"], o["bb"] = int(BK[ii].sum()), int(BW[ii].sum()), int(BB[ii].sum())
        if zones:
            zx, zy = to5186.transform(r["pos"][1], r["pos"][0])
            zd, zn, zt = zone_at(zx, zy, zones)
            if zd <= 1000:
                o["cz"] = {"d": round(zd), "n": zn, "dt": zt}           # 붕괴위험지역 — d 0 = 안
        out[r["id"]] = o
    OUT.write_text(json.dumps({"built": date.today().isoformat(), "n": len(out),
                               "src": "표고·경사 Terrarium z12(≈30m) · 하천·저수지 국토지리정보원 연속수치지형도 · 건물 국토교통부 GIS건물통합정보(구조 · 사용승인일 · 지하층은 건축물대장이 붙은 건물만)",
                               "rows": out}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    v = list(out.values())
    print(f"→ {OUT} {OUT.stat().st_size // 1024}KB · 저지대(10m↓) {sum(x['el'] <= 10 for x in v)} · 경사 30°↑ {sum(x['sl'] >= 30 for x in v)}"
          f" · 붕괴위험지역 안 {sum(x.get('cz', {}).get('d', 1) == 0 for x in v)} · 300m 안 {sum(x.get('cz', {}).get('d', 9e9) <= 300 for x in v)}"
          f" · 하천 100m 안 {sum(x.get('rv', {}).get('d', 9e9) <= 100 for x in v)} · 저수지 아래 {sum(x.get('lk', {}).get('dh', -1) > 0 for x in v)}", file=sys.stderr)


if __name__ == "__main__":
    main()

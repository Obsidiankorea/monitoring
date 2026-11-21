"""경남 지형 그림(음영기복 · 저지대 · 등고선)을 500m 격자 칸 좌표에 맞춰 만든다.

    PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/build_terrain.py            # 한 장 그림 + 마우스 높이(저장소에 넣는다)
    PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/build_terrain.py --tiles    # 확대용 조각(data/terrain/, 저장소 밖) · --only=low 면 저지대만

표고 = AWS 공개 지형 타일(Terrarium, z12 ≈ 경남에서 30m급, 키 없음). 원본 타일은 tools/.cache/terrain/ 에(커밋하지 않는다).
만드는 것
  app/web/static/terrain/  — 경남 전체 화면용(확대 전), 저장소에 넣는다
    relief.png · low.png   bbox 칸 하나에 S 픽셀(125m) 한 장씩
    elev.i16.gz            같은 칸의 표고(m, int16, 행 북→남) — 마우스 높이 읽기
    terrain.json           S · bbox · 만든 날
  data/terrain/{relief,low}/{z}/{x}/{y}.png  — 확대용 조각(z 11~13), 바다만인 조각은 만들지 않는다.
    NAS 는 /mnt/user/appdata/gn-monitor/terrain 에 올려 두면 컨테이너가 /terrain 으로 읽는다(GN_TERRAIN, deploy.sh).
    조각 좌표 = 화면(01b-gl.js)의 가짜 메르카토르 세계 좌표 — 칸 (gx, gy) ↔ 세계 (0.5 + (gx-GC0)·GE, 0.5 - (gy-GC1)·GE)
"""
from __future__ import annotations

import gzip
import json
import math
import sys
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "tools" / ".cache" / "terrain"
OUT = ROOT / "app" / "web" / "static" / "terrain"
TILES = ROOT / "data" / "terrain"
Z, S = 12, 4                       # 원본 타일 줌 · 한 장 그림은 칸(500m) 하나에 픽셀 4 → 125m
TZ = (11, 12, 13)                  # 확대용 조각 줌(13 ≈ 19m/픽셀 — 30m 자료로는 이 이상 의미 없다, 화면이 늘려 쓴다)
GE = 500 / 40075016.686            # 01b-gl.js 와 같아야 한다
GC = (1328, 942)
LOW_M, EXAG = 10.0, 1.5
ONLY = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--only=")), None)   # --only=low · relief
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def _lcc(p):
    D = math.pi / 180
    a, f = 6378137.0, 1 / 298.257222101
    e = math.sqrt(f * (2 - f))
    m = lambda q: math.cos(q) / math.sqrt(1 - e * e * math.sin(q) ** 2)
    t = lambda q: math.tan(math.pi / 4 - q / 2) / ((1 - e * math.sin(q)) / (1 + e * math.sin(q))) ** (e / 2)
    p1, p2, p0 = p["slat1"] * D, p["slat2"] * D, p["olat"] * D
    n = (math.log(m(p1)) - math.log(m(p2))) / (math.log(t(p1)) - math.log(t(p2)))
    AF = a * m(p1) / (n * t(p1) ** n)
    return D, e, t, n, AF, AF * t(p0) ** n


def lcc_inv(gx, gy, p):
    """500m 칸 좌표 → 경위도(타원체 LCC 역변환, 05-layers.js LCCF 의 반대)."""
    D, e, _, n, AF, rho0 = _lcc(p)
    g = p["grid_m"]
    x = (gx - p["xo"]) * g
    y = rho0 - (gy - p["yo"]) * g
    rho = np.sign(n) * np.hypot(x, y)
    lon = p["olon"] + np.arctan2(x, y) / n / D
    tt = (rho / AF) ** (1 / n)
    lat = math.pi / 2 - 2 * np.arctan(tt)
    for _ in range(6):
        es = e * np.sin(lat)
        lat = math.pi / 2 - 2 * np.arctan(tt * ((1 - es) / (1 + es)) ** (e / 2))
    return lon, lat / D


def lcc_fwd(lon, lat, p):
    D, _, t, n, AF, rho0 = _lcc(p)
    rho, th = AF * t(lat * D) ** n, n * (lon - p["olon"]) * D
    return rho * math.sin(th) / p["grid_m"] + p["xo"], (rho0 - rho * math.cos(th)) / p["grid_m"] + p["yo"]


def merc_px(lon, lat, z=Z):
    n = 256 * 2 ** z
    lr = np.radians(lat)
    return (lon + 180) / 360 * n, (1 - np.log(np.tan(lr) + 1 / np.cos(lr)) / math.pi) / 2 * n


def src_tile(x, y):
    fp = CACHE / f"{Z}_{x}_{y}.png"
    if not fp.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(URL.format(z=Z, x=x, y=y), headers={"User-Agent": "gn-monitor-terrain"})
        fp.write_bytes(urllib.request.urlopen(req, timeout=30).read())
    a = np.asarray(Image.open(fp).convert("RGB"), dtype=np.float32)
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768


class Dem:
    """bbox 를 덮는 원본 타일 모자이크 — sample(칸 좌표) → 표고(이중선형)."""

    def __init__(self, p):
        self.p = p
        b = p["bbox"]
        lon, lat = lcc_inv(np.array([b["i0"] - 2, b["i1"] + 2, b["i0"] - 2, b["i1"] + 2]),
                           np.array([b["j0"] - 2, b["j0"] - 2, b["j1"] + 2, b["j1"] + 2]), p)
        mx, my = merc_px(lon, lat)
        self.tx0, tx1 = int(mx.min() // 256), int(mx.max() // 256)
        self.ty0, ty1 = int(my.min() // 256), int(my.max() // 256)
        nt = (tx1 - self.tx0 + 1) * (ty1 - self.ty0 + 1)
        print(f"원본 타일 {nt}장 (z{Z})", file=sys.stderr)
        self.mos = np.zeros(((ty1 - self.ty0 + 1) * 256, (tx1 - self.tx0 + 1) * 256), np.float32)
        for ty in range(self.ty0, ty1 + 1):
            for tx in range(self.tx0, tx1 + 1):
                self.mos[(ty - self.ty0) * 256:(ty - self.ty0 + 1) * 256, (tx - self.tx0) * 256:(tx - self.tx0 + 1) * 256] = src_tile(tx, ty)

    def sample(self, GX, GY):
        lon, lat = lcc_inv(GX, GY, self.p)
        mx, my = merc_px(lon, lat)
        u, v = mx - self.tx0 * 256 - 0.5, my - self.ty0 * 256 - 0.5
        u0, v0 = np.floor(u).astype(int), np.floor(v).astype(int)
        fu, fv = u - u0, v - v0
        mos = self.mos
        u0 = u0.clip(0, mos.shape[1] - 2); v0 = v0.clip(0, mos.shape[0] - 2)
        return (mos[v0, u0] * (1 - fu) * (1 - fv) + mos[v0, u0 + 1] * fu * (1 - fv)
                + mos[v0 + 1, u0] * (1 - fu) * fv + mos[v0 + 1, u0 + 1] * fu * fv)


def _land(z, cell):
    """땅 = 약 150m(최소 5×5) 이웃에서 표고 > 0 이 과반인 곳 — 논 · 들의 0m 언저리 잡음이 바다 구멍(검은 점)으로 뚫렸다.
    ⚠️ 닫기(불리고 깎기)로 메우면 섬 사이 좁은 바다까지 땅(저지대)이 됐다 — 과반은 작은 구멍만 메운다."""
    return _box(z > 0, max(2, round(150 / cell))) > 0.5


def _box(a, r):
    """(2r+1)² 평균(누적합) — 가장자리는 덧칸(P)이 받아 준다."""
    if r < 1:
        return a.astype(np.float32)
    c = np.pad(a.astype(np.float64), r + 1, mode="edge").cumsum(0).cumsum(1)
    k = 2 * r + 1
    return ((c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k))[: a.shape[0], : a.shape[1]].astype(np.float32)


def _nb(m, op, r=1):
    """r 픽셀 이웃 and/or(깎기 · 불리기)."""
    sh = [np.roll(np.roll(m, dy, 0), dx, 1) for dy in range(-r, r + 1) for dx in range(-r, r + 1)]
    return np.logical_and.reduce(sh) if op == "and" else np.logical_or.reduce(sh)


def relief_la(z, cell, contour=0, r=1):
    """표고 z(행 북→남), 픽셀 간격 cell(m) → 음영기복 회색+알파. contour>0 이면 그 간격 등고선(5배마다 굵게)."""
    zs = _box(z, r)                                # 고른 면으로 그늘 · 등고선 — 들판의 표고 잡음(±2m)이 얼룩 점으로 보였다
    dzdx = np.gradient(zs, axis=1) / cell
    dzdy = -np.gradient(zs, axis=0) / cell         # 북쪽이 +
    slope = np.arctan(EXAG * np.hypot(dzdx, dzdy))  # 과장 — 경남 산이 낮아 밋밋했다
    aspect = np.arctan2(-dzdx, -dzdy)
    az, alt = math.radians(315), math.radians(45)
    shade = math.sin(alt) * np.cos(slope) + math.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    flat = math.sin(alt)
    land = _land(z, cell)
    d = shade - flat
    dark = d < 0
    alpha = np.where(dark, np.clip(-d / flat, 0, 1) * 200, np.clip(d / (1 - flat), 0, 1) * 110)
    lum = np.where(dark, 0, 255).astype(np.uint8)
    if contour:
        zc = np.maximum(zs, 1.0)                    # 0m 선은 긋지 않는다 — 들판 0m 언저리 잡음이 검은 고리 점으로 찍혔다
        k = np.floor(zc / contour)
        edge = (k != np.roll(k, -1, 1)) | (k != np.roll(k, -1, 0))
        big = np.floor(zc / (contour * 5))
        bold = _nb((big != np.roll(big, -1, 1)) | (big != np.roll(big, -1, 0)), "or")
        line = (edge | bold) & land
        lum = np.where(line, 0, lum)                 # 등고선은 어두운 선
        alpha = np.where(bold & land, 190, np.where(line, np.maximum(alpha, 120), alpha))
    alpha = (np.where(land, alpha, 0).astype(np.uint8) // 4) * 4       # 알파 4단 묶음 — PNG 가 1/3 작아진다
    return np.stack([lum, alpha], -1)


def low_rgba(z, cell, r=1):
    land = _land(z, cell)
    # 표고를 (2r+1)² 평균으로 고른 뒤 가른다 — 10m 언저리 원본 잡음이 확대 조각에서 점점이 흩뿌려졌다
    zs = np.mean([np.roll(np.roll(z, dy, 0), dx, 1) for dy in range(-r, r + 1) for dx in range(-r, r + 1)], axis=0)
    ro = max(1, round(200 / cell))                 # 열기 약 200m — 해안선 · 섬마다 생기던 가는 테두리 지우기(배율이 달라도 같은 폭)
    lw = _nb(_nb(land & (zs <= LOW_M), "and", ro), "or", ro)
    lw = (_box(lw, ro) > 0.5) & land               # 열기의 네모 모서리를 둥글게(네모 덩어리로 보였다)
    out = np.zeros(z.shape + (4,), np.uint8)
    out[lw] = (70, 235, 170, 150)                  # 민트 — 강수 청색 단계와 안 겹치게
    return out, lw


def overview(dem):
    p, b = dem.p, dem.p["bbox"]
    W, H = b["w"] * S, b["h"] * S
    GX, GY = np.meshgrid(b["i0"] - 0.5 + (np.arange(W) + 0.5) / S, b["j1"] + 0.5 - (np.arange(H) + 0.5) / S)
    lon, lat = lcc_inv(GX[H // 2:H // 2 + 1, W // 2:W // 2 + 1], GY[H // 2:H // 2 + 1, W // 2:W // 2 + 1], p)
    cx, cy = lcc_fwd(float(lon[0, 0]), float(lat[0, 0]), p)   # 왕복 검산 — 역변환이 틀리면 그림이 통째로 밀린다
    assert abs(cx - GX[H // 2, W // 2]) < 1e-3 and abs(cy - GY[H // 2, W // 2]) < 1e-3, (cx, cy)
    z = dem.sample(GX, GY)
    cell = p["grid_m"] / S
    OUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(relief_la(z, cell), "LA").save(OUT / "relief.png", optimize=True)
    low, lw = low_rgba(z, cell)
    Image.fromarray(low, "RGBA").save(OUT / "low.png", optimize=True)
    (OUT / "elev.i16.gz").write_bytes(gzip.compress(np.clip(np.round(z), -1, 32767).astype("<i2").tobytes(), 9))
    (OUT / "terrain.json").write_text(json.dumps({
        "S": S, "bbox": b, "w": W, "h": H, "low_m": LOW_M, "zoom": Z, "tiles": list(TZ), "built": date.today().isoformat(),
        "source": "AWS Terrain Tiles (Terrarium) — SRTM 등",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in ("relief.png", "low.png", "elev.i16.gz"):
        print(f, (OUT / f).stat().st_size // 1024, "KB", file=sys.stderr)
    print(f"표고 최고 {z.max():.0f}m · 저지대 {lw.sum() * cell * cell / 1e6:.0f}㎢", file=sys.stderr)


def tiles(dem):
    b, P = dem.p["bbox"], 32                        # P = 조각 둘레 덧칸(기울기 · 열기(z13 은 반지름 10)가 조각 경계에서 끊기지 않게)
    wx = lambda gx: 0.5 + (gx - GC[0]) * GE
    wy = lambda gy: 0.5 - (gy - GC[1]) * GE
    n_out = 0
    for tz in TZ:
        N = 2 ** tz
        x0, x1 = int(wx(b["i0"] - 0.5) * N), int(wx(b["i1"] + 0.5) * N)
        y0, y1 = int(wy(b["j1"] + 0.5) * N), int(wy(b["j0"] - 0.5) * N)
        cell = 1 / (256 * N) / GE * 500             # 조각 한 픽셀 = 칸 평면 m
        contour = 100 if tz >= 12 else 200           # 등고선 간격(5배마다 굵게) — z11 = 시군 확대 화면(지금 앱에서 가장 깊은 배율)은 200m
        rlow = max(1, round(40 / cell))
        cnt = 0
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                k = (np.arange(-P, 256 + P) + 0.5) / 256
                GX, GY = np.meshgrid(GC[0] + ((tx + k) / N - 0.5) / GE, GC[1] - ((ty + k) / N - 0.5) / GE)
                z = dem.sample(GX, GY)
                if not (z > 0).any():
                    continue
                for name, mk, mode in (("relief", lambda: relief_la(z, cell, contour, rlow), "LA"), ("low", lambda: low_rgba(z, cell, rlow)[0], "RGBA")):
                    if ONLY and name != ONLY:
                        continue
                    img = mk()[P:-P, P:-P]
                    fp = TILES / name / str(tz) / str(tx) / f"{ty}.png"
                    if not img[..., -1].any():
                        fp.unlink(missing_ok=True)
                        continue
                    fp = TILES / name / str(tz) / str(tx) / f"{ty}.png"
                    fp.parent.mkdir(parents=True, exist_ok=True)
                    Image.fromarray(img, mode).save(fp, optimize=True)
                    cnt += 1
        print(f"z{tz}: 조각 {cnt}장 (x {x0}~{x1}, y {y0}~{y1}, {cell:.0f}m/픽셀)", file=sys.stderr)
        n_out += cnt
    size = sum(f.stat().st_size for f in TILES.rglob("*.png"))
    print(f"모두 {n_out}장 · {size / 1e6:.0f}MB → {TILES}", file=sys.stderr)


def main():
    p = json.loads((ROOT / "data" / "geo" / "grids.json").read_text(encoding="utf-8"))["hr"]
    dem = Dem(p)
    if "--tiles" in sys.argv:
        tiles(dem)
    else:
        overview(dem)


if __name__ == "__main__":
    main()

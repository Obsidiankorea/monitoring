"""경남 지형 그림(음영기복 · 저지대)을 500m 격자 칸 좌표에 맞춰 만든다. 한 번 돌려 결과를 저장소에 넣는다.

    PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/build_terrain.py

표고 = AWS 공개 지형 타일(Terrarium, z11 ≈ 경남에서 60m, 키 없음). 원본 타일은 tools/.cache/terrain/ 에(커밋하지 않는다).
만드는 것 (app/web/static/terrain/) — 지도 bbox(grids.json hr.bbox) 칸 하나에 S 픽셀
  relief.png  음영기복 — 그늘은 검정, 볕 받는 쪽은 흰색을 알파로(빛 북서 315° · 고도 45°). 바다(표고 ≤ 0)는 투명
  low.png     저지대 — 표고 0 초과 10m 이하 땅을 민트 알파로(배수 · 침수 취약)
  terrain.json  S · bbox · 만든 날
화면(01b-gl.js)은 bbox 네 모서리만 gll 로 넘기면 칸에 꼭 맞는다(gridCorners 와 같은 셈).
"""
from __future__ import annotations

import io
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
Z, S = 11, 4                       # 타일 줌 · 칸(500m) 하나에 픽셀 4 → 125m
LOW_M = 10.0
URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"


def lcc_inv(gx, gy, p):
    """500m 칸 좌표 → 경위도(타원체 LCC 역변환, app/static LCCF 의 반대)."""
    D = math.pi / 180
    a, f = 6378137.0, 1 / 298.257222101
    e = math.sqrt(f * (2 - f))
    m = lambda q: math.cos(q) / math.sqrt(1 - e * e * math.sin(q) ** 2)
    t = lambda q: math.tan(math.pi / 4 - q / 2) / ((1 - e * math.sin(q)) / (1 + e * math.sin(q))) ** (e / 2)
    p1, p2, p0 = p["slat1"] * D, p["slat2"] * D, p["olat"] * D
    n = (math.log(m(p1)) - math.log(m(p2))) / (math.log(t(p1)) - math.log(t(p2)))
    AF = a * m(p1) / (n * t(p1) ** n)
    rho0 = AF * t(p0) ** n
    g = p["grid_m"]
    x = (gx - p["xo"]) * g
    y = rho0 - (gy - p["yo"]) * g
    rho = np.sign(n) * np.hypot(x, y)
    th = np.arctan2(x, y)
    lon = p["olon"] + th / n / D
    tt = (rho / AF) ** (1 / n)
    lat = math.pi / 2 - 2 * np.arctan(tt)
    for _ in range(6):
        es = e * np.sin(lat)
        lat = math.pi / 2 - 2 * np.arctan(tt * ((1 - es) / (1 + es)) ** (e / 2))
    return lon, lat / D


def lcc_fwd(lon, lat, p):
    D = math.pi / 180
    a, f = 6378137.0, 1 / 298.257222101
    e = math.sqrt(f * (2 - f))
    m = lambda q: math.cos(q) / math.sqrt(1 - e * e * math.sin(q) ** 2)
    t = lambda q: math.tan(math.pi / 4 - q / 2) / ((1 - e * math.sin(q)) / (1 + e * math.sin(q))) ** (e / 2)
    p1, p2, p0 = p["slat1"] * D, p["slat2"] * D, p["olat"] * D
    n = (math.log(m(p1)) - math.log(m(p2))) / (math.log(t(p1)) - math.log(t(p2)))
    AF = a * m(p1) / (n * t(p1) ** n)
    rho0 = AF * t(p0) ** n
    rho, th = AF * t(lat * D) ** n, n * (lon - p["olon"]) * D
    return rho * math.sin(th) / p["grid_m"] + p["xo"], (rho0 - rho * math.cos(th)) / p["grid_m"] + p["yo"]


def tile(x, y):
    fp = CACHE / f"{Z}_{x}_{y}.png"
    if not fp.exists():
        CACHE.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(URL.format(z=Z, x=x, y=y), headers={"User-Agent": "gn-monitor-terrain"})
        fp.write_bytes(urllib.request.urlopen(req, timeout=30).read())
    a = np.asarray(Image.open(fp).convert("RGB"), dtype=np.float32)
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768


def merc_px(lon, lat):
    """경위도 → z 줌 전역 픽셀(256 타일)."""
    n = 256 * 2 ** Z
    lr = np.radians(lat)
    return (lon + 180) / 360 * n, (1 - np.log(np.tan(lr) + 1 / np.cos(lr)) / math.pi) / 2 * n


def main():
    p = json.loads((ROOT / "data" / "geo" / "grids.json").read_text(encoding="utf-8"))["hr"]
    b = p["bbox"]
    W, H = b["w"] * S, b["h"] * S
    px = np.arange(W) + 0.5
    py = np.arange(H) + 0.5
    gx = b["i0"] - 0.5 + px / S
    gy = b["j1"] + 0.5 - py / S
    GX, GY = np.meshgrid(gx, gy)
    lon, lat = lcc_inv(GX, GY, p)
    # 왕복 검산 — 역변환이 틀리면 그림이 통째로 밀린다
    cx, cy = lcc_fwd(float(lon[H // 2, W // 2]), float(lat[H // 2, W // 2]), p)
    assert abs(cx - GX[H // 2, W // 2]) < 1e-3 and abs(cy - GY[H // 2, W // 2]) < 1e-3, (cx, cy)

    mx, my = merc_px(lon, lat)
    tx0, tx1 = int(mx.min() // 256), int(mx.max() // 256)
    ty0, ty1 = int(my.min() // 256), int(my.max() // 256)
    print(f"타일 {(tx1 - tx0 + 1) * (ty1 - ty0 + 1)}장 (z{Z})", file=sys.stderr)
    mos = np.zeros(((ty1 - ty0 + 1) * 256, (tx1 - tx0 + 1) * 256), np.float32)
    for ty in range(ty0, ty1 + 1):
        for tx in range(tx0, tx1 + 1):
            mos[(ty - ty0) * 256:(ty - ty0 + 1) * 256, (tx - tx0) * 256:(tx - tx0 + 1) * 256] = tile(tx, ty)
    # 이중선형
    u, v = mx - tx0 * 256 - 0.5, my - ty0 * 256 - 0.5
    u0, v0 = np.floor(u).astype(int), np.floor(v).astype(int)
    fu, fv = u - u0, v - v0
    u0 = u0.clip(0, mos.shape[1] - 2); v0 = v0.clip(0, mos.shape[0] - 2)
    z = (mos[v0, u0] * (1 - fu) * (1 - fv) + mos[v0, u0 + 1] * fu * (1 - fv)
         + mos[v0 + 1, u0] * (1 - fu) * fv + mos[v0 + 1, u0 + 1] * fu * fv)

    # 음영기복 — 픽셀 간격 = 500/S m. 행(py)은 북→남
    cell = p["grid_m"] / S
    dzdx = np.gradient(z, axis=1) / cell
    dzdy = -np.gradient(z, axis=0) / cell          # 북쪽이 +
    slope = np.arctan(1.5 * np.hypot(dzdx, dzdy))   # 1.5 = 과장(경남 산이 낮아 밋밋했다)
    aspect = np.arctan2(-dzdx, -dzdy)               # 내리막 방향(북 0, 시계)
    az, alt = math.radians(315), math.radians(45)
    shade = math.sin(alt) * np.cos(slope) + math.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    flat = math.sin(alt)
    land = z > 0
    d = shade - flat                                 # 음수 = 그늘, 양수 = 볕
    dark = d < 0
    alpha = np.where(dark, np.clip(-d / flat, 0, 1) * 200, np.clip(d / (1 - flat), 0, 1) * 110)
    alpha = (np.where(land, alpha, 0).astype(np.uint8) // 4) * 4       # 회색+알파 · 알파 4단 묶음 → 2.1MB 가 1.4MB 로
    la = np.stack([np.where(dark, 0, 255).astype(np.uint8), alpha], -1)
    OUT.mkdir(parents=True, exist_ok=True)
    Image.fromarray(la, "LA").save(OUT / "relief.png", optimize=True)

    low = np.zeros((H, W, 4), np.uint8)
    lw = land & (z <= LOW_M)
    # 열기(깎고 다시 불리기) 1픽셀(2픽셀은 들까지 깎였다) — 섬 · 해안선마다 생기던 가는 테두리(표고 보간 언저리)를 지우고 넓은 들은 남긴다
    sh = lambda m, f: np.logical_and.reduce([np.roll(np.roll(m, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)]) if f == "and" \
        else np.logical_or.reduce([np.roll(np.roll(m, dy, 0), dx, 1) for dy in (-1, 0, 1) for dx in (-1, 0, 1)])
    lw = sh(sh(lw, "and"), "or") & land
    low[lw] = (70, 235, 170, 150)        # 민트 — 강수 청색 단계와 안 겹치게
    Image.fromarray(low, "RGBA").save(OUT / "low.png", optimize=True)

    (OUT / "terrain.json").write_text(json.dumps({
        "S": S, "bbox": b, "low_m": LOW_M, "zoom": Z, "built": date.today().isoformat(),
        "source": "AWS Terrain Tiles (Terrarium) — Mapzen/SRTM 등",
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    for f in ("relief.png", "low.png"):
        print(f, (OUT / f).stat().st_size // 1024, "KB", file=sys.stderr)
    print(f"표고 최고 {z.max():.0f}m · 저지대 {lw.sum() * cell * cell / 1e6:.0f}㎢", file=sys.stderr)


if __name__ == "__main__":
    main()

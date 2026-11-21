"""경남 건물 밀도 그림(국토교통부 GIS건물통합정보)을 지형 그림과 같은 격자 · 조각 체계로 만든다.

    PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/build_bldg.py            # 한 장 그림(저장소) + 확대용 조각(data/terrain/bldg)

원본 = 브이월드 › 공간정보 다운로드 › GIS건물통합정보 › 경상남도 · 전체데이터 · SHP(AL_D010_48_YYYYMMDD.zip, 약 250MB, CC BY).
  tools/.cache/vworld/ 에 둔다(커밋하지 않는다). 가장 최근 zip 을 쓴다. 속성(dbf, 3GB)은 읽지 않는다 — 모양만.
만드는 것
  app/web/static/terrain/bldg.png       경남 전체 화면용 — 지형 그림과 같은 bbox · 칸당 S 픽셀(125m), 픽셀 = 건물이 덮은 넓이 비율
  data/terrain/bldg/{z}/{x}/{y}.png     확대용 조각(z 11~13) — NAS /mnt/user/appdata/gn-monitor/terrain 에 올린다(지형과 같다)
색 = 따뜻한 모래색(비 파랑 · 저지대 민트 · 산사태 갈색과 섞이지 않게), 진할수록 건물이 빽빽하다.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import shapefile
from PIL import Image, ImageDraw
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_terrain import GC, GE, OUT, TILES, TZ, S, _lcc  # noqa: E402  같은 투영 · 조각 체계

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tools" / ".cache" / "vworld"
COL = (242, 196, 120)                  # 모래색
GAIN = 2.2                             # 덮은 비율 → 불투명도(시가지 40% 덮으면 거의 꽉)


def lcc_fwd_np(lon, lat, p):
    """build_terrain.lcc_fwd 의 배열판."""
    D, e, _, n, AF, rho0 = _lcc(p)
    q = lat * D
    t = np.tan(np.pi / 4 - q / 2) / ((1 - e * np.sin(q)) / (1 + e * np.sin(q))) ** (e / 2)
    rho, th = AF * t ** n, n * (lon - p["olon"]) * D
    return rho * np.sin(th) / p["grid_m"] + p["xo"], (rho0 - rho * np.cos(th)) / p["grid_m"] + p["yo"]


def load(p):
    """건물 고리들 → 칸 좌표 배열 목록. zip 안 SHP 가 여러 덩어리((2) 등)면 다 읽는다."""
    zp = sorted(SRC.glob("AL_D010_48_*.zip"))
    if not zp:
        raise SystemExit(f"{SRC} 에 AL_D010_48_*.zip 이 없다 — 브이월드에서 경남 GIS건물통합정보(전체데이터 · SHP)를 받아 둔다")
    z = zipfile.ZipFile(zp[-1])
    tr = Transformer.from_crs(5186, 4326, always_xy=True)
    rings = []
    for shp in [n for n in z.namelist() if n.endswith(".shp")]:
        base = shp[:-4]
        out = SRC / "x"
        out.mkdir(exist_ok=True)
        for ext in (".shp", ".shx"):
            fp = out / Path(base + ext).name
            if not fp.exists():
                fp.write_bytes(z.read(base + ext))
        r = shapefile.Reader(shp=open(out / Path(shp).name, "rb"), shx=open(out / Path(base + ".shx").name, "rb"))
        n0 = len(rings)
        for sh in r.iterShapes():
            if not sh.points:
                continue
            pts, parts = np.asarray(sh.points, float), list(sh.parts) + [len(sh.points)]
            rings += [pts[a:b] for a, b in zip(parts[:-1], parts[1:]) if b - a >= 3]
        print(f"{Path(shp).name}: 고리 {len(rings) - n0:,}", file=sys.stderr)
    # 한 번에 투영(고리를 이어 붙여 변환한 뒤 다시 자른다)
    cut = np.cumsum([len(x) for x in rings])[:-1]
    allp = np.concatenate(rings)
    lon, lat = tr.transform(allp[:, 0], allp[:, 1])
    gx, gy = lcc_fwd_np(np.asarray(lon), np.asarray(lat), p)
    return np.split(np.stack([gx, gy], 1), cut), zp[-1].name


def overview(rings, p):
    """칸당 S 픽셀 한 장 — 8배로 그려 상자 평균 = 덮은 비율."""
    b, K = p["bbox"], 8
    W, H = b["w"] * S, b["h"] * S
    img = Image.new("L", (W * K, H * K))
    d = ImageDraw.Draw(img)
    x0, y1 = b["i0"] - 0.5, b["j1"] + 0.5
    for r in rings:
        d.polygon([((x - x0) * S * K, (y1 - y) * S * K) for x, y in r], fill=255)
    cov = np.asarray(img.resize((W, H), Image.BOX), float) / 255
    a = np.clip(cov * GAIN, 0, 1)
    rgba = np.zeros((H, W, 4), np.uint8)
    rgba[..., :3] = COL
    rgba[..., 3] = (np.sqrt(a) * 230).astype(np.uint8) * (cov > 0)   # 제곱근 — 시골 집 몇 채도 보이게
    Image.fromarray(rgba, "RGBA").save(OUT / "bldg.png", optimize=True)
    print(f"bldg.png {(OUT / 'bldg.png').stat().st_size // 1024}KB · 덮은 넓이 {cov.sum() * (p['grid_m'] / S) ** 2 / 1e6:.0f}㎢", file=sys.stderr)


def tiles(rings):
    """확대용 조각 — 세계 좌표(가짜 메르카토르)로 옮겨 조각마다 4배로 그리고 줄인다."""
    W = [np.stack([0.5 + (r[:, 0] - GC[0]) * GE, 0.5 - (r[:, 1] - GC[1]) * GE], 1) for r in rings]
    lo = np.array([w.min(0) for w in W]); hi = np.array([w.max(0) for w in W])
    for f in (TILES / "bldg").rglob("*.png"):
        f.unlink()
    total = 0
    for tz in TZ:
        N, K = 2 ** tz, 4
        t0, t1 = np.floor(lo * N).astype(int), np.floor(hi * N).astype(int)
        by = {}
        for i in range(len(W)):
            for tx in range(t0[i, 0], t1[i, 0] + 1):
                for ty in range(t0[i, 1], t1[i, 1] + 1):
                    by.setdefault((tx, ty), []).append(i)
        for (tx, ty), ids in by.items():
            img = Image.new("L", (256 * K, 256 * K))
            d = ImageDraw.Draw(img)
            for i in ids:
                q = (W[i] * N - (tx, ty)) * 256 * K
                d.polygon([tuple(v) for v in q], fill=255)
            cov = np.asarray(img.resize((256, 256), Image.BOX), float) / 255
            if not cov.any():
                continue
            rgba = np.zeros((256, 256, 4), np.uint8)
            rgba[..., :3] = COL
            rgba[..., 3] = (np.sqrt(np.clip(cov * GAIN, 0, 1)) * 235).astype(np.uint8)
            fp = TILES / "bldg" / str(tz) / str(tx) / f"{ty}.png"
            fp.parent.mkdir(parents=True, exist_ok=True)
            Image.fromarray(rgba, "RGBA").save(fp, optimize=True)
        total += len(by)
        print(f"z{tz}: 조각 {len(by)}장", file=sys.stderr)
    size = sum(f.stat().st_size for f in (TILES / "bldg").rglob("*.png"))
    print(f"모두 {total}장 · {size / 1e6:.0f}MB → {TILES / 'bldg'}", file=sys.stderr)


def main():
    p = json.loads((ROOT / "data" / "geo" / "grids.json").read_text(encoding="utf-8"))["hr"]
    rings, name = load(p)
    c = np.concatenate(rings[:2000])                  # 검산 — 경남 bbox 안에 떨어져야 한다(좌표계를 잘못 읽으면 바다로 간다)
    b = p["bbox"]
    assert b["i0"] - 20 < np.median(c[:, 0]) < b["i1"] + 20 and b["j0"] - 20 < np.median(c[:, 1]) < b["j1"] + 20, np.median(c, 0)
    overview(rings, p)
    meta = json.loads((OUT / "terrain.json").read_text(encoding="utf-8"))
    meta["bldg"] = {"src": name, "n": len(rings), "source": "국토교통부 GIS건물통합정보(브이월드, CC BY)"}
    (OUT / "terrain.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    if "--no-tiles" not in sys.argv:
        tiles(rings)


if __name__ == "__main__":
    main()

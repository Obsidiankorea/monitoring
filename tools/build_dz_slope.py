"""우려지역 지구 둘레 경사를 1:5,000 등고선(국토지리정보원 연속수치지형도, 5m 간격)으로 다시 잰다 → data/geo/dz_terrain.json 의 sl5 · sl50.

    PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/build_dz_slope.py [등고선 zip 폴더(기본 ~/Downloads)]

30m 표고(build_dz_terrain)는 비탈을 낮게 잡는다(예: 사천 망산공원 — 붕괴위험지역인데 19°). 등고선은 5m 마다라 산비탈은 훨씬 정확하다
(축대 · 옹벽 같은 인공 비탈은 여전히 등고선에 없다).
원본 = 브이월드 › 등고선(연속수치지형도) — 경남은 파일 번호 4·5·6·8·9·12·13·14·15·19(시도별_등고선_파일_목록.xlsx). zip 그대로 두면 된다.
계산 — 지구마다 반지름 R 안 등고선 점(5m 간격으로 촘촘히)에 평면 z = ax + by + c 를 맞춰 기울기 atan(√(a²+b²)).
  sl5  = 지구 자리(R 50m)
  sl50 = 둘레 최대 — 지구 둘레 40m 떨어진 8곳 + 자리, 각 R 30m 평면 중 가장 가파른 것
  등고선이 R 안에 두 높이 미만이면(평지) 0 으로 둔다. build_dz_terrain 을 다시 돌리면 sl5 · sl50 이 지워지니 그 뒤에 이 도구를 다시 돌린다.
"""
from __future__ import annotations

import glob
import json
import math
import shutil
import sys
import urllib.request
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import shapefile
from pyproj import Transformer

ROOT = Path(__file__).resolve().parents[1]
DZT = ROOT / "data" / "geo" / "dz_terrain.json"
TMP = ROOT / "tools" / ".cache" / "vworld" / "x"
GN = ("004", "005", "006", "008", "009", "012", "013", "014", "015", "019")
CELL, NEAR = 200.0, 130.0                   # 바구니 크기 · 지구에서 이만큼 안의 등고선만 모은다(40m 떨어진 곳 + R 30m + 여유)
STEP = 5.0


def plane_slope(p: np.ndarray) -> float | None:
    if len(p) < 6 or np.ptp(p[:, 2]) < 0.5:              # 한 높이뿐 — 평지(또는 등고선 하나)
        return None
    A = np.c_[p[:, 0] - p[:, 0].mean(), p[:, 1] - p[:, 1].mean(), np.ones(len(p))]
    (a, b, _), *_ = np.linalg.lstsq(A, p[:, 2], rcond=None)
    return math.degrees(math.atan(math.hypot(a, b)))


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Downloads"
    zips = {n: next(iter(glob.glob(str(src / f"*등고선_{n}.zip"))), None) for n in GN}
    miss = [n for n, z in zips.items() if not z]
    if miss:
        raise SystemExit(f"{src} 에 등고선 파일이 없다: {', '.join(miss)}")
    rows = json.loads(urllib.request.urlopen("http://100.106.116.92:8000/api/districts/all", timeout=120).read())["rows"]
    rows = [r for r in rows if r.get("pos")]
    tm = Transformer.from_crs(4326, 5179, always_xy=True)
    xy = {r["id"]: tm.transform(r["pos"][1], r["pos"][0]) for r in rows}
    bucket = defaultdict(list)
    for i, (x, y) in xy.items():
        bucket[(int(x // CELL), int(y // CELL))].append(i)
    pts = defaultdict(list)                              # 지구 → [(x, y, z)]
    TMP.mkdir(parents=True, exist_ok=True)
    for n, zp in zips.items():
        z = zipfile.ZipFile(zp)
        base = next(m for m in z.namelist() if m.endswith(".shp"))[:-4]
        for e in ("shp", "shx", "dbf"):
            fp = TMP / f"{base}.{e}"
            if not fp.exists():
                with z.open(f"{base}.{e}") as s, open(fp, "wb") as d:
                    shutil.copyfileobj(s, d, 1 << 24)
        r = shapefile.Reader(str(TMP / base), encoding="cp949")
        hit = 0
        for k, sh in enumerate(r.iterShapes()):
            x0, y0, x1, y1 = sh.bbox
            near = {i for cx in range(int((x0 - NEAR) // CELL), int((x1 + NEAR) // CELL) + 1)
                    for cy in range(int((y0 - NEAR) // CELL), int((y1 + NEAR) // CELL) + 1) for i in bucket.get((cx, cy), ())}
            if not near:
                continue
            zc = r.record(k)["CONT"]
            p = np.asarray(sh.points)
            seg = np.diff(p, axis=0)
            nn = np.maximum(1, (np.hypot(seg[:, 0], seg[:, 1]) // STEP).astype(int))
            d = np.concatenate([p[j] + seg[j] * (np.arange(nn[j])[:, None] / nn[j]) for j in range(len(seg))] + [p[-1:]])
            for i in near:
                cx, cy = xy[i]
                m = np.hypot(d[:, 0] - cx, d[:, 1] - cy) <= NEAR
                if m.any():
                    pts[i].append(np.c_[d[m], np.full(m.sum(), zc)])
                    hit += 1
        print(f"등고선_{n}: {len(r):,}줄 중 지구 둘레 {hit:,}", file=sys.stderr)
    t = json.loads(DZT.read_text("utf-8"))
    n_ok = 0
    for i, (cx, cy) in xy.items():
        o = t["rows"].get(i)
        if o is None:
            continue
        p = np.concatenate(pts[i]) if pts[i] else np.zeros((0, 3))
        if not len(p):
            o["sl5"] = o["sl50"] = 0                      # 둘레 130m 에 등고선이 없다 — 평지
            continue
        sub = lambda ox, oy, R: plane_slope(p[np.hypot(p[:, 0] - cx - ox, p[:, 1] - cy - oy) <= R])
        s0 = sub(0, 0, 50)
        ring = [sub(40 * math.cos(a), 40 * math.sin(a), 30) for a in np.linspace(0, 2 * math.pi, 8, endpoint=False)] + [sub(0, 0, 30)]
        o["sl5"] = round(s0 or 0)
        o["sl50"] = round(max([v for v in ring if v is not None] + [s0 or 0]))
        n_ok += 1
    t["slope_src"] = "국토지리정보원 연속수치지형도 등고선(1:5,000, 브이월드 2026-10-01 갱신)"
    DZT.write_text(json.dumps(t, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    v = [o for o in t["rows"].values() if "sl50" in o]
    print(f"→ {DZT} · 등고선 경사 {n_ok}곳 · 30°↑ {sum(o['sl50'] >= 30 for o in v)}(30m 자료는 {sum(o['sl'] >= 30 for o in v)})", file=sys.stderr)


if __name__ == "__main__":
    main()

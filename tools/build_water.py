"""경남 강 · 호수 · 저수지(국토지리정보원 연속수치지형도)를 500m 격자 칸 좌표 GeoJSON 으로 만든다. 한 번 돌려 결과를 저장소에 넣는다.

    PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/build_water.py

원본 = 브이월드 › 공간정보 다운로드(국토지리정보원, 전국 SHP · EPSG:5179) — tools/.cache/vworld/ 에 zip 그대로(커밋하지 않는다)
  N3L_E0020000.zip  하천중심선(선) — SCLS E0022115 만(E0022112 세류 278만 줄은 뺀다). DIVI RCD001 국가하천 · RCD002 지방하천 · RCD000 그 밖(소하천 등)
  N3A_E0052114.zip  호수/저수지(면) — 넓이(MARA) MIN_M2 이상
  N3A_E0032111.zip  실폭하천(면, 넓은 강의 물) — 있으면 넣는다
만드는 것 app/web/static/water/water.json — FeatureCollection(칸 좌표)
  properties.k = river(선) | water(면), g = 1 국가 · 2 지방 · 3 그 밖(선만), n = 이름, o = 1 경남 밖(흐리게)
  선은 같은 (등급, 이름)끼리 MultiLineString 하나로 묶는다(토막 수만 개 → 객체 수를 줄인다). 좌표는 칸 0.01(5m), 더글러스-푸커 TOL.
"""
from __future__ import annotations

import json
import shutil
import sys
import zipfile
from collections import defaultdict
from pathlib import Path

import numpy as np
import shapefile
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_terrain import lcc_inv  # noqa: E402
from build_bldg import lcc_fwd_np  # noqa: E402  배열판 투영

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tools" / ".cache" / "vworld"
OUT = ROOT / "app" / "web" / "static" / "water" / "water.json"
MIN_M2 = 10_000                        # 호수 · 저수지 1ha 이상(작은 농업용 저수지까지 — 위험저수지가 대개 이 크기)
TOL = 0.02                             # 칸(500m) 단위 → 10m(5m 면 9MB — 화면 확대 한계(시군 ≈ 76m/픽셀)에서 차이가 안 보인다)
GRADE = {"RCD001": 1, "RCD002": 2}     # 그 밖은 3


def dp(pts, tol):
    """더글러스-푸커(되풀이 없이 스택)."""
    if len(pts) < 3:
        return pts
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    st = [(0, len(pts) - 1)]
    while st:
        a, b = st.pop()
        (x1, y1), (x2, y2) = pts[a], pts[b]
        dx, dy = x2 - x1, y2 - y1
        L = (dx * dx + dy * dy) ** 0.5 or 1e-12
        best, bi = -1.0, -1
        for i in range(a + 1, b):
            d = abs(dy * (pts[i][0] - x1) - dx * (pts[i][1] - y1)) / L
            if d > best:
                best, bi = d, i
        if best > tol:
            keep[bi] = True
            st += [(a, bi), (bi, b)]
    return [q for q, k in zip(pts, keep) if k]


def area(r):
    return abs(sum(r[i][0] * r[(i + 1) % len(r)][1] - r[(i + 1) % len(r)][0] * r[i][1] for i in range(len(r)))) / 2


def join(ways):
    """선 조각들을 끝점끼리 이어 닫힌 고리로(오픈스트리트맵 멀티폴리곤용 — build_town 등이 쓴다)."""
    ways = [w[:] for w in ways if len(w) >= 2]
    rings = []
    while ways:
        cur = ways.pop()
        changed = True
        while cur[0] != cur[-1] and changed:
            changed = False
            for i, w in enumerate(ways):
                if w[0] == cur[-1]: cur += w[1:]
                elif w[-1] == cur[-1]: cur += w[::-1][1:]
                elif w[-1] == cur[0]: cur = w + cur[1:]
                elif w[0] == cur[0]: cur = w[::-1] + cur[1:]
                else: continue
                ways.pop(i); changed = True
                break
        if cur[0] == cur[-1] and len(cur) >= 4:
            rings.append(cur)
    return rings


def gn_mask(b):
    """경남 시군 칸 True — 한 칸(500m) 넓혀 경계를 따라 흐르는 강(낙동강)은 안으로 친다. 행 남→북, b 의 i0 · j0 기준."""
    import gzip
    g = json.loads((ROOT / "data" / "geo" / "grids.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in g["sigun"] if s["kind"] == "gn"]
    m = np.isin(np.frombuffer(gzip.decompress((ROOT / "data" / "geo" / "mask_sigun.u8.gz").read_bytes()), np.uint8).reshape(b["h"], b["w"]), ids)
    d = m.copy()
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            d |= np.roll(np.roll(m, dy, 0), dx, 1)
    return lambda x, y: 0 <= (c := round(x) - b["i0"]) < b["w"] and 0 <= (r := round(y) - b["j0"]) < b["h"] and bool(d[r, c])


def runs(pts, inside):
    """선을 경남 안 · 밖 토막으로 나눈다 — [(안?, 점들)], 토막끼리 끝점을 나눠 가져 끊김이 없다."""
    out, cur, st = [], [pts[0]], inside(*pts[0])
    for q in pts[1:]:
        f = inside(*q)
        cur.append(q)
        if f != st:
            out.append((st, cur)); cur, st = [q], f
    if len(cur) >= 2:
        out.append((st, cur))
    return out


def reader(code):
    """zip 의 SHP 를 캐시에 풀어(한 번만) 연다. 없으면 None."""
    zp = SRC / f"{code}.zip"
    if not zp.exists():
        return None
    x = SRC / "x"
    x.mkdir(exist_ok=True)
    z = zipfile.ZipFile(zp)
    for e in ("shp", "shx", "dbf"):
        fp = x / f"{code}.{e}"
        if not fp.exists():
            with z.open(f"{code}.{e}") as s, open(fp, "wb") as d:
                shutil.copyfileobj(s, d, 1 << 24)
    return shapefile.Reader(str(x / code), encoding="cp949")


def main():
    p = json.loads((ROOT / "data" / "geo" / "grids.json").read_text(encoding="utf-8"))["hr"]
    b = p["bbox"]
    inside = gn_mask(b)
    to_ll = Transformer.from_crs(5179, 4326, always_xy=True)
    to_tm = Transformer.from_crs(4326, 5179, always_xy=True)
    # 경남 bbox(칸 ±5) → 5179 bbox — 읽을 때 걸러 전국 330만 줄을 다 풀지 않는다
    gx = np.array([b["i0"] - 5, b["i1"] + 5, b["i0"] - 5, b["i1"] + 5], float)
    gy = np.array([b["j0"] - 5, b["j0"] - 5, b["j1"] + 5, b["j1"] + 5], float)
    lon, lat = lcc_inv(gx, gy, p)
    ex, ey = to_tm.transform(lon, lat)
    bb = [min(ex), min(ey), max(ex), max(ey)]

    def grid(pts):
        a = np.asarray(pts, float)
        lo, la = to_ll.transform(a[:, 0], a[:, 1])
        x, y = lcc_fwd_np(np.asarray(lo), np.asarray(la), p)
        return [(round(u / TOL) * TOL, round(v / TOL) * TOL) for u, v in zip(x, y)]

    inb = lambda r: any(b["i0"] - 5 <= x <= b["i1"] + 5 and b["j0"] - 5 <= y <= b["j1"] + 5 for x, y in r)
    feats = []

    # ① 하천중심선 — (등급, 이름, 경남 안?)끼리 묶는다
    r = reader("N3L_E0020000")
    if r is None:
        raise SystemExit(f"{SRC}/N3L_E0020000.zip(하천중심선)이 없다 — 브이월드에서 받아 둔다")
    lines = defaultdict(list)
    n_seg = 0
    for sr in r.iterShapeRecords(fields=["NAME", "DIVI", "SCLS"], bbox=bb):
        rec = sr.record.as_dict()
        if rec["SCLS"] != "E0022115" or len(sr.shape.points) < 2:
            continue
        g = GRADE.get(rec["DIVI"], 3)
        pts = dp(grid(sr.shape.points), TOL)
        if len(pts) < 2 or not inb(pts):
            continue
        n_seg += 1
        for ins, seg in runs(pts, inside):
            if not ins and g > 1:              # 경남 밖은 국가하천만 — 흐리게 깔 맥락이라 잔 물줄기는 무게만 늘린다
                continue
            lines[(g, rec["NAME"] or "", ins)].append([[round(x, 2), round(y, 2)] for x, y in seg])
    for (g, n, ins), segs in lines.items():
        feats.append({"type": "Feature", "properties": {"k": "river", "g": g, "n": n, **({} if ins else {"o": 1})},
                      "geometry": {"type": "MultiLineString", "coordinates": segs}})
    print(f"하천중심선 토막 {n_seg:,} → 묶음 {len(lines):,}", file=sys.stderr)

    # ② 호수/저수지 · 실폭하천 — 면
    for code, label, min_m2 in (("N3A_E0052114", "호수/저수지", MIN_M2), ("N3A_E0032111", "실폭하천", 0)):
        r = reader(code)
        if r is None:
            print(f"{label}({code}.zip) 없음 — 건너뜀", file=sys.stderr)
            continue
        cnt = small = 0
        for sr in r.iterShapeRecords(bbox=bb):
            rec = sr.record.as_dict()
            if min_m2 and (rec.get("MARA") or 0) < min_m2:
                small += 1
                continue
            pts, parts = sr.shape.points, list(sr.shape.parts) + [len(sr.shape.points)]
            rings = [grid(pts[a:c]) for a, c in zip(parts[:-1], parts[1:]) if c - a >= 4]
            rings = [dp(q[:len(q) // 2 + 1], TOL) + dp(q[len(q) // 2:], TOL)[1:] for q in rings]   # 닫힌 고리는 반씩 — 시작=끝이면 dp 가 두 점으로 접는다
            rings = [q for q in rings if len(q) >= 4 and area(q) > 0]
            if not rings or not inb(rings[0]):
                continue
            ins = sum(inside(x, y) for x, y in rings[0]) * 2 >= len(rings[0])
            if not ins and min_m2 and (rec.get("MARA") or 0) < 10 * min_m2:   # 경남 밖 호수는 10ha 이상만
                continue
            feats.append({"type": "Feature", "properties": {"k": "water", "n": rec.get("NAME") or "", **({} if ins else {"o": 1})},
                          "geometry": {"type": "Polygon", "coordinates": [[[round(x, 2), round(y, 2)] for x, y in q] for q in rings]}})
            cnt += 1
        print(f"{label} 면 {cnt:,}" + (f"(1ha 안 돼 뺀 것 {small:,})" if min_m2 else ""), file=sys.stderr)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats,
                               "attribution": "국토지리정보원 연속수치지형도(브이월드)"}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"→ {OUT} {OUT.stat().st_size // 1024}KB", file=sys.stderr)


if __name__ == "__main__":
    main()

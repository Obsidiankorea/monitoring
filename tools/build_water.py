"""경남 강 · 호수 · 저수지(오픈스트리트맵)를 500m 격자 칸 좌표 GeoJSON 으로 만든다. 한 번 돌려 결과를 저장소에 넣는다.

    PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/build_water.py

받는 것(Overpass) — waterway=river(선) · natural=water / landuse=reservoir(면, 강 넓은 물 · 호수 · 저수지 · 댐 호수)
만드는 것 app/web/static/water/water.json — FeatureCollection(칸 좌표), properties.k = river(선) | water(면), n = 이름, o = 1 경남 밖(흐리게)
  면은 넓이 MIN_KM2 이상만(논 둠벙까지 넣으면 수만 개), 좌표는 칸 0.01(5m) 단위로 줄이고 더글러스-푸커 5m 로 솎는다.
⚠️ 자료 © OpenStreetMap 기여자(ODbL) — 화면에서 이 레이어를 켜면 출처를 띄운다(05-layers.js).
원본 응답은 tools/.cache/water.json 에(커밋하지 않는다).
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_terrain import lcc_fwd, lcc_inv  # noqa: E402  같은 투영식

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT / "tools" / ".cache" / "water.json"
OUT = ROOT / "app" / "web" / "static" / "water" / "water.json"
MIN_KM2 = 0.03
TOL = 0.01                                 # 칸(500m) 단위 → 5m


def fetch(p):
    if CACHE.exists():
        return json.loads(CACHE.read_text(encoding="utf-8"))
    b = p["bbox"]
    import numpy as np
    lon, lat = lcc_inv(np.array([b["i0"], b["i1"], b["i0"], b["i1"]], float), np.array([b["j0"], b["j0"], b["j1"], b["j1"]], float), p)
    bb = f"{lat.min():.4f},{lon.min():.4f},{lat.max():.4f},{lon.max():.4f}"
    q = f"""[out:json][timeout:300];
(way["waterway"="river"]({bb});
 way["natural"="water"]({bb}); relation["natural"="water"]({bb});
 way["landuse"="reservoir"]({bb}); relation["landuse"="reservoir"]({bb}););
out geom;"""
    req = urllib.request.Request("https://overpass-api.de/api/interpreter", data=urllib.parse.urlencode({"data": q}).encode(),
                                 headers={"User-Agent": "gn-monitor-water/1.0"})
    raw = urllib.request.urlopen(req, timeout=400).read()
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_bytes(raw)
    return json.loads(raw)


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
    """선 조각들을 끝점끼리 이어 닫힌 고리로(멀티폴리곤 outer/inner)."""
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
    import numpy as np
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


def main():
    p = json.loads((ROOT / "data" / "geo" / "grids.json").read_text(encoding="utf-8"))["hr"]
    b = p["bbox"]
    inside = gn_mask(b)
    els = fetch(p)["elements"]
    to = lambda g: [(round(x / TOL) * TOL, round(y / TOL) * TOL) for x, y in (lcc_fwd(q["lon"], q["lat"], p) for q in g)]
    inb = lambda r: any(b["i0"] - 5 <= x <= b["i1"] + 5 and b["j0"] - 5 <= y <= b["j1"] + 5 for x, y in r)
    feats, n_small = [], 0
    min_a = MIN_KM2 / 0.25                      # 칸² (칸 하나 = 0.25㎢)
    for e in els:
        t = e.get("tags", {})
        name = t.get("name:ko") or t.get("name") or ""
        if e["type"] == "way" and t.get("waterway") == "river":
            r = dp(to(e["geometry"]), TOL)
            if len(r) >= 2 and inb(r):
                for ins, seg in runs(r, inside):     # o=1 경남 밖 — 화면에서 흐리게
                    feats.append({"type": "Feature", "properties": {"k": "river", "n": name, **({} if ins else {"o": 1})},
                                  "geometry": {"type": "LineString", "coordinates": [[round(x, 2), round(y, 2)] for x, y in seg]}})
            continue
        if e["type"] == "way":
            outer, inner = [to(e["geometry"])], []
        elif e["type"] == "relation":
            mem = [m for m in e.get("members", []) if m.get("type") == "way" and m.get("geometry")]
            outer = join([to(m["geometry"]) for m in mem if m.get("role") != "inner"])
            inner = join([to(m["geometry"]) for m in mem if m.get("role") == "inner"])
        else:
            continue
        for o in outer:
            if len(o) < 4 or o[0] != o[-1] or not inb(o):
                continue
            if area(o) < min_a:
                n_small += 1
                continue
            rings = [o] + [i for i in inner if area(i) >= min_a / 4]   # shortcut: 구멍은 어느 바깥 고리 것인지 따지지 않고 다 붙인다 — 큰 호수 하나짜리가 대부분
            rings = [dp(r[:len(r) // 2 + 1], TOL) + dp(r[len(r) // 2:], TOL)[1:] for r in rings]   # 닫힌 고리는 반씩 — 시작=끝이면 dp 가 두 점으로 접었다
            rings = [r for r in rings if len(r) >= 4]
            if rings:
                ins = sum(inside(x, y) for x, y in rings[0]) * 2 >= len(rings[0])   # 테두리 점 절반 이상이 경남 안이면 안
                feats.append({"type": "Feature", "properties": {"k": "water", "n": name, **({} if ins else {"o": 1})},
                              "geometry": {"type": "Polygon", "coordinates": [[[round(x, 2), round(y, 2)] for x, y in r] for r in rings]}})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"type": "FeatureCollection", "features": feats,
                               "attribution": "© OpenStreetMap 기여자 (ODbL)"}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    nr = sum(f["properties"]["k"] == "river" for f in feats)
    print(f"강 선 {nr} · 물 면 {len(feats) - nr} (작아서 뺀 면 {n_small}) → {OUT} {OUT.stat().st_size // 1024}KB", file=sys.stderr)


if __name__ == "__main__":
    main()

"""도로망 층 자료(tools/build_roads.py 가 만든 app/web/static/roads/roads.json) — 모양 · 크기 · 등급 · 자리."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
F = ROOT / "app" / "web" / "static" / "roads" / "roads.json"


def _fc():
    return json.loads(F.read_text(encoding="utf-8"))


def test_size_budget_and_shape():
    import gzip
    assert len(gzip.compress(F.read_bytes(), 6)) < 1_000_000   # 1MB 예산, 압축 뒤(build_roads.BUDGET)
    fc = _fc()
    assert fc["type"] == "FeatureCollection" and fc["features"]
    for f in fc["features"]:
        p, g = f["properties"], f["geometry"]
        assert p["g"] in (1, 2, 3) and isinstance(p["n"], str) and isinstance(p["r"], str)
        assert p.get("o", 1) == 1 and (p["g"] == 1 or "o" not in p)   # 경남 밖은 고속도로만
        assert g["type"] == "MultiLineString" and all(len(l) >= 2 for l in g["coordinates"])


def test_grades_present_and_in_grid():
    grid = json.loads((ROOT / "data" / "geo" / "grids.json").read_text(encoding="utf-8"))["hr"]["bbox"]
    fc = _fc()
    lines = {g: 0 for g in (1, 2, 3)}
    for f in fc["features"]:
        lines[f["properties"]["g"]] += len(f["geometry"]["coordinates"])
        for l in f["geometry"]["coordinates"]:
            for x, y in l if "o" not in f["properties"] else ():     # 경남 밖 고속도로는 줄기째 둔다
                assert grid["i0"] - 6 <= x <= grid["i1"] + 6 and grid["j0"] - 6 <= y <= grid["j1"] + 6
    assert all(lines.values()), lines
    names = {f["properties"]["n"] for f in fc["features"] if f["properties"]["g"] == 1}
    assert {"남해고속도로", "통영대전고속도로", "중부내륙고속도로"} <= names
    ns = {(f["properties"]["g"], f["properties"]["r"]) for f in fc["features"]}
    assert (2, "14") in ns and (2, "2") in ns                 # 국도 14 · 2호선(경남을 지난다)


def test_few_gaps_between_lines():
    """끊김 — 선 끝이 다른 선에 닿지 않고 50~250m 떨어진 곳(눈에 보이는 틈)이 등급마다 60곳 이하.
    2026-11-11 판은 고속 52 · 국도 47 · 지방도 38 — 대개 빼 둔 연결로(CONNECT 1)로 이어지는 나들목 · 교차로.
    (2026-11-23 '60m 곁 선 빼기'로 줄였을 때는 수백 곳 — 리 확대에서 점선처럼 보였다)"""
    import math
    from collections import Counter, defaultdict
    L = [(f["properties"]["g"], l) for f in _fc()["features"] for l in f["geometry"]["coordinates"]]
    idx = defaultdict(set)
    for i, (_, l) in enumerate(L):
        for a, b in zip(l, l[1:]):
            for x in range(int(min(a[0], b[0])) - 1, int(max(a[0], b[0])) + 2):
                for y in range(int(min(a[1], b[1])) - 1, int(max(a[1], b[1])) + 2):
                    idx[(x, y)].add(i)

    def seg(p, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        t = max(0, min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy or 1)))
        return math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy)
    ends = Counter(tuple(p) for _, l in L for p in (l[0], l[-1]))
    gaps = Counter()
    for i, (g, l) in enumerate(L):
        for p in (l[0], l[-1]):
            if ends[tuple(p)] > 1:
                continue
            d = min((seg(p, a, b) for j in idx[(int(p[0]), int(p[1]))] if j != i for a, b in zip(L[j][1], L[j][1][1:])), default=9)
            gaps[g] += 0.1 <= d < 0.5
    assert all(v <= 60 for v in gaps.values()), gaps


SG = ROOT / "app" / "web" / "static" / "roads"


def test_sigun_road_files():
    """시군도 — 경남 18 시군 파일, 하나 압축 300KB 아래(build_roads.SG_BUDGET), g = 4."""
    import gzip
    idx = json.loads((SG / "sg-index.json").read_text(encoding="utf-8"))
    assert len(idx) == 18 and {"창원", "남해", "합천"} <= set(idx)
    for nm, v in idx.items():
        f = SG / v["f"]
        assert f.stat().st_size == v["b"] and len(gzip.compress(f.read_bytes(), 6)) < 300_000 and v["n"] > 500, (nm, v)
        fc = json.loads(f.read_text(encoding="utf-8"))
        assert fc["features"] and all(x["properties"]["g"] == 4 for x in fc["features"])
        assert all(len(l) >= 2 for x in fc["features"] for l in x["geometry"]["coordinates"])

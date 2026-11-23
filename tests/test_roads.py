"""도로망 층 자료(tools/build_roads.py 가 만든 app/web/static/roads/roads.json) — 모양 · 크기 · 등급 · 자리."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
F = ROOT / "app" / "web" / "static" / "roads" / "roads.json"


def _fc():
    return json.loads(F.read_text(encoding="utf-8"))


def test_size_budget_and_shape():
    assert F.stat().st_size < 1_000_000                      # 1MB 예산(build_roads.BUDGET)
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


def test_no_both_direction_duplicates():
    """방향마다 따로인 링크 · 분리 차로를 한 줄로 — 같은 등급에서 끝점 짝이 같은 선이 또 있으면 안 된다."""
    seen = set()
    for f in _fc()["features"]:
        for l in f["geometry"]["coordinates"]:
            k = (f["properties"]["g"], *sorted(map(tuple, (l[0], l[-1]))))
            assert k not in seen, k
            seen.add(k)


def test_cover_drops_parallel_carriageway():
    """맞은편 차로(30m 옆 나란한 선)는 덮인 것으로, 1km 떨어진 다른 길은 아닌 것으로 — build_roads.covered."""
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    from build_roads import cells, covered
    a = [(0.0, 0.0), (10.0, 0.0)]
    occ = set(cells(a))
    assert covered(cells([(0.0, 0.06), (10.0, 0.06)]), occ)          # 30m 옆
    assert not covered(cells([(0.0, 2.0), (10.0, 2.0)]), occ)        # 1km 옆
    assert not covered(cells([(5.0, 0.0), (5.0, 8.0)]), occ)         # 갈라져 나가는 길

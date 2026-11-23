"""경남 도로망(고속도로 · 일반국도 · 지방도) — 국가교통정보센터 전국 표준노드링크를 500m 격자 칸 좌표 GeoJSON 으로. 한 번 돌려 결과를 저장소에 넣는다.

    PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/build_roads.py

원본 = https://www.its.go.kr/nodelink/nodelinkRef › [기준일]NODELINKDATA.zip(약 250MB) — tools/.cache/nodelink/ 에 zip 그대로(커밋하지 않는다)
  MOCT_LINK.shp — 좌표계 .prj 'ITRF2000_Central_Belt_60'(TM 중부원점 38N 127E, 가산 200000/600000, GRS80) = EPSG:5186
  ROAD_RANK(파일에서 확인, 2026-11-11판): 101 고속국도 · 102 도시고속 · 103 일반국도 · 104 특별 · 광역시도 · 105 국가지원지방도 · 106 지방도 · 107 시군도
  → 여기서는 101 · 102 = 1(고속), 103 = 2(국도), 105 · 106 = 3(지방도), 107 = 4(시군도, 시군 파일로 따로).
  링크는 방향마다 따로(같은 길이 두 줄) — 칸 좌표 끝점 짝이 같으면 하나만. 연결로(CONNECT 1)는 뺀다.
  ⚠️ 분리 차로(상 · 하행이 따로 그려진 길)는 두 줄 그대로 둔다. '같은 등급 선 60m 곁이면 뺀다'로 줄였더니(2026-11-23)
     교차로 · 나란한 길의 짧은 토막까지 빠져 리 단위 확대에서 도로가 점선처럼 끊겼다.
만드는 것 data/geo/gn_links.json.gz — 경남 땅 위(링크 가운데 점이 경남 시군 칸) 링크 번호(모든 등급) → 칸 좌표 선(60m 로 줄임).
  꼴 {id: [첫 번호, 차이, 차이 …](번호 차례), xy: [[x0, y0, dx, dy, …] …](칸 × 50 정수)} — 읽는 쪽은 app/its.py link_lines. 재난상황정보 침수 경보의 linkId 와 같은 번호(2026-11-23 세종 건 15개 중 14개 일치로 확인)
만드는 것 app/web/static/roads/roads.json — FeatureCollection(칸 좌표)
  properties.g = 1 고속 · 2 국도 · 3 지방도, n = 도로 이름, r = 노선 번호(없으면 빈칸), o = 1 경남 밖(흐리게)
  같은 (등급, 번호, 그 자리 이름, 안팎)끼리 MultiLineString 하나 — 끝점이 이어지는 토막은 긴 줄기로.
만드는 것 app/web/static/roads/sg-<시군 번호>.json · sg-index.json — 시군도(107)를 시군마다(링크 가운데 점의 시군). g = 4, 화면은 시군을 골라 확대했을 때만 받는다.
  2026-11-11 판 경남 시군도 79,922 링크 · 18 파일 합 2.2MB(창원 420KB 가 가장 크다, SG_BUDGET 600KB). 원본 등급은 101~107 뿐 — 골목길(더 작은 등급)은 없다. 104(광역시도)는 경남에 없다.
"""
from __future__ import annotations

import json
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import shapefile
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_bldg import lcc_fwd_np  # noqa: E402  배열판 투영
from build_terrain import lcc_inv  # noqa: E402
from build_water import dp, gn_mask, merge, runs  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "tools" / ".cache" / "nodelink"
OUT = ROOT / "app" / "web" / "static" / "roads" / "roads.json"
LINKS = ROOT / "data" / "geo" / "gn_links.json.gz"   # 경남 땅 위 링크 번호 → 칸 좌표 선 — 서버만 읽는다(재난상황정보 침수 링크를 지도에, app/its.py)
TOL = 0.06                     # 칸(500m) 단위 → 30m. 시군 확대에서도 한 픽셀이 약 76m 라 모양이 같다(1MB 예산)
GRADE = {"101": 1, "102": 1, "103": 2, "105": 3, "106": 3}
BUDGET = 1_000_000             # 바이트 — 넘으면 실패(TOL 을 키운다)
SG_BUDGET = 600_000            # 시군도 시군 파일 하나(roads/sg-<번호>.json) — 넘으면 실패(2026-11-11 판 창원 420KB 가 가장 크다)


def sigun_at(b):
    """칸 → 경남 시군 (번호, 이름) 또는 None(넓히지 않는다)."""
    import gzip
    g = json.loads((ROOT / "data" / "geo" / "grids.json").read_text(encoding="utf-8"))
    nm = {s["id"]: s["name"] for s in g["sigun"] if s["kind"] == "gn"}
    m = np.frombuffer(gzip.decompress((ROOT / "data" / "geo" / "mask_sigun.u8.gz").read_bytes()), np.uint8).reshape(b["h"], b["w"])

    def at(x, y):
        c, r = round(x) - b["i0"], round(y) - b["j0"]
        k = int(m[r, c]) if 0 <= c < b["w"] and 0 <= r < b["h"] else 0
        return (k, nm[k]) if k in nm else None
    return at


def gn_strict(b):
    """경남 시군 칸이면 True(넓히지 않는다) — 링크 번호표(gn_links)는 땅 위 자리로 고른다.
    ⚠️ 번호 앞자리로는 못 고른다: 381~389 · 390~398 에 창원은 414 · 416 · 418(2026-11-11 판, 시군 칸으로 확인)."""
    import gzip
    g = json.loads((ROOT / "data" / "geo" / "grids.json").read_text(encoding="utf-8"))
    ids = [s["id"] for s in g["sigun"] if s["kind"] == "gn"]
    m = np.isin(np.frombuffer(gzip.decompress((ROOT / "data" / "geo" / "mask_sigun.u8.gz").read_bytes()), np.uint8).reshape(b["h"], b["w"]), ids)
    return lambda x, y: 0 <= (c := round(x) - b["i0"]) < b["w"] and 0 <= (r := round(y) - b["j0"]) < b["h"] and bool(m[r, c])


def reader():
    x = SRC / "x"
    if not (x / "MOCT_LINK.shp").exists():
        zp = sorted(SRC.glob("*NODELINKDATA*.zip")) or sorted(SRC.glob("*.zip"))
        if not zp:
            raise SystemExit(f"{SRC} 에 NODELINKDATA.zip 이 없다 — its.go.kr/nodelink/nodelinkRef 에서 받아 둔다")
        x.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zp[-1]) as z:
            for e in ("shp", "shx", "dbf", "prj"):
                z.extract(f"MOCT_LINK.{e}", x)
    prj = (x / "MOCT_LINK.prj").read_text()
    assert "Central_Belt" in prj and "200000" in prj and "600000" in prj, f"좌표계가 바뀌었다 — 확인: {prj[:120]}"
    return shapefile.Reader(str(x / "MOCT_LINK"), encoding="cp949")


def main():
    p = json.loads((ROOT / "data" / "geo" / "grids.json").read_text(encoding="utf-8"))["hr"]
    b = p["bbox"]
    inside = gn_mask(b)
    in_gn = gn_strict(b)
    to_ll = Transformer.from_crs(5186, 4326, always_xy=True)
    to_tm = Transformer.from_crs(4326, 5186, always_xy=True)
    gx = np.array([b["i0"] - 5, b["i1"] + 5, b["i0"] - 5, b["i1"] + 5], float)
    gy = np.array([b["j0"] - 5, b["j0"] - 5, b["j1"] + 5, b["j1"] + 5], float)
    ex, ey = to_tm.transform(*lcc_inv(gx, gy, p))
    bb = [min(ex), min(ey), max(ex), max(ey)]
    inb = lambda r: any(b["i0"] - 5 <= x <= b["i1"] + 5 and b["j0"] - 5 <= y <= b["j1"] + 5 for x, y in r)

    def grid(pts):
        a = np.asarray(pts, float)
        lo, la = to_ll.transform(a[:, 0], a[:, 1])
        x, y = lcc_fwd_np(np.asarray(lo), np.asarray(la), p)
        return [(round(u / TOL) * TOL, round(v / TOL) * TOL) for u, v in zip(x, y)]

    r = reader()
    sg_at = sigun_at(b)
    sg_seen, sg_lines, sg_n = set(), defaultdict(lambda: defaultdict(list)), Counter()   # 시군도(107) — 시군마다
    seen, lines, n_link = set(), defaultdict(list), defaultdict(int)
    gn_links = {}
    for sr in r.iterShapeRecords(fields=["LINK_ID", "ROAD_RANK", "ROAD_NAME", "ROAD_NO", "CONNECT"], bbox=bb):
        rec = sr.record.as_dict()
        if len(sr.shape.points) >= 2:          # 등급 · 연결로 가리지 않고 경남 땅 위 링크 전부(지하차도는 시군도에도 있다)
            ln = dp(grid(sr.shape.points), TOL * 2)
            if in_gn(*ln[len(ln) // 2]):     # 칸 × 50 정수(10m) 를 x, y, x, y … 한 줄로 — 칠하기용이라 60m 로 줄여도 된다
                gn_links[rec["LINK_ID"]] = [round(v * 50) for q in ln for v in q]
        if rec["ROAD_RANK"] == "107" and rec["CONNECT"] != "1" and len(sr.shape.points) >= 2:
            pts = [(round(x, 2), round(y, 2)) for x, y in dp(grid(sr.shape.points), TOL)]
            key = tuple(sorted((pts[0], pts[-1])))
            sg = sg_at(*pts[len(pts) // 2])
            if sg and pts[0] != pts[-1] and key not in sg_seen:
                sg_seen.add(key)
                sg_n[sg] += 1
                sg_lines[sg][(rec["ROAD_NAME"] or "").strip().strip("-")].append([list(q) for q in pts])
            continue
        g = GRADE.get(rec["ROAD_RANK"])
        if not g or rec["CONNECT"] == "1" or len(sr.shape.points) < 2:      # CONNECT 1 = 연결로(나들목 · 분기점 고리)
            continue
        pts = dp(grid(sr.shape.points), TOL)
        pts = [(round(x, 2), round(y, 2)) for x, y in pts]      # 칸 좌표 부동소수 끝자리 — 맞은편 방향 끝점이 같은 값이 되게
        key = (g, *sorted((pts[0], pts[-1])))       # 맞은편 방향 링크 — 상 · 하행 노드가 따로인 길(분리 차로)도 칸 좌표 끝점이 같다
        if pts[0] == pts[-1] or key in seen or not inb(pts):
            continue
        seen.add(key)
        n_link[g] += 1
        name = (rec["ROAD_NAME"] or "").strip().strip("-")      # 노선 이름은 시군마다 바뀐다(○○대로) — 구간마다 그 자리 이름
        no = (rec["ROAD_NO"] or "").strip().strip("-")
        for ins, seg in runs(pts, inside):
            if not ins and g > 1:              # 경남 밖은 고속도로만(맥락) — 나머지는 무게만 는다
                continue
            lines[(g, no, name, ins)].append([[round(x, 2), round(y, 2)] for x, y in seg])
    feats = []
    for (g, no, n, ins), segs in sorted(lines.items(), key=lambda kv: -kv[0][0]):   # 지방도 → 고속(위에 그릴수록 뒤)
        feats.append({"type": "Feature", "properties": {"g": g, "n": n, "r": no, **({} if ins else {"o": 1})},
                      "geometry": {"type": "MultiLineString", "coordinates": [dp(l, TOL) for l in merge(segs)]}})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    txt = json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(txt, encoding="utf-8")
    print(f"링크(방향 하나) 고속 {n_link[1]:,} · 국도 {n_link[2]:,} · 지방도 {n_link[3]:,}"
          f" → 묶음 {len(feats):,} · 선 {sum(len(f['geometry']['coordinates']) for f in feats):,} · {len(txt.encode()):,} 바이트", file=sys.stderr)
    over, index = [], {}
    for (k, nm), byname in sorted(sg_lines.items()):
        fs = [{"type": "Feature", "properties": {"g": 4, "n": n, "r": ""},
               "geometry": {"type": "MultiLineString", "coordinates": [dp(l, TOL) for l in merge(segs)]}} for n, segs in byname.items()]
        t = json.dumps({"type": "FeatureCollection", "features": fs}, ensure_ascii=False, separators=(",", ":"))
        (OUT.parent / f"sg-{k}.json").write_text(t, encoding="utf-8")
        index[nm] = {"f": f"sg-{k}.json", "n": sg_n[(k, nm)], "b": len(t.encode())}
        print(f"  시군도 {nm} 링크 {sg_n[(k, nm)]:,} → sg-{k}.json {len(t.encode()):,} 바이트", file=sys.stderr)
        if len(t.encode()) > SG_BUDGET:
            over.append(nm)
    (OUT.parent / "sg-index.json").write_text(json.dumps(index, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"시군도 모두 링크 {sum(sg_n.values()):,} · {sum(v['b'] for v in index.values()):,} 바이트", file=sys.stderr)
    import gzip
    ks = sorted(gn_links, key=int)               # 번호는 차례대로 앞 번호와의 차이, 선은 첫 점 + 점끼리 차이 — 2.2MB → 0.8MB(압축)
    ids = [int(k) for k in ks]
    pack = {"id": ids[:1] + [b2 - a2 for a2, b2 in zip(ids, ids[1:])],
            "xy": [v[:2] + [v[i] - v[i - 2] for i in range(2, len(v))] for v in (gn_links[k] for k in ks)]}
    LINKS.write_bytes(gzip.compress(json.dumps(pack, separators=(",", ":")).encode(), 9, mtime=0))
    print(f"경남 링크 {len(gn_links):,} → {LINKS.name} {LINKS.stat().st_size:,} 바이트", file=sys.stderr)
    if len(txt.encode()) > BUDGET:
        raise SystemExit(f"{OUT} 가 {BUDGET:,} 바이트를 넘는다 — TOL 을 키운다")
    if over:
        raise SystemExit(f"시군도 파일이 {SG_BUDGET:,} 바이트를 넘는다: {', '.join(over)}")


if __name__ == "__main__":
    main()

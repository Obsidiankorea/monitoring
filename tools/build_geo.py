"""경남 지도 경계·칸 지도를 만든다. 한 번 돌려 결과를 저장소에 넣는다.

    .venv\\Scripts\\python.exe tools\\build_geo.py        (윈도)
    .venv/bin/python tools/build_geo.py                  (맥)

node 가 있어야 한다 — 단순화·TopoJSON 은 mapshaper 를 npx 로 부른다.
원본은 tools/.cache/ 에 받아 두고 커밋하지 않는다(합쳐 45MB).

만드는 것 (data/geo/)
  gyeongnam.topo.json  시군 경계(경남 18 + 부산·울산). **500m 격자 칸 좌표**로 미리 바꿔 둔다
  grids.json           투영 매개변수, bbox, 5km→500m 아핀, 시군·읍면동 번호
  mask_sigun.u8.gz     bbox 칸마다 시군 번호(0 = 밖)
  mask_emd.u16.gz      bbox 칸마다 경남 읍면동 번호(0 = 밖) — 최대값 위치 이름에 쓴다
  칸 지도의 행은 남→북, 한 행은 서→동 — 기상청 격자 자료와 같은 순서다.

⚠️ 경계를 d3.geoConicConformal 로 그리지 않는다. 그건 구면이라 500m 격자(타원체)와
   경남 안에서 최대 800m 어긋난다. 여기서 타원체 식으로 칸 좌표까지 바꿔 두면
   화면은 축척만 곱하면 되고, 격자와 한 치도 어긋날 수 없다.
⚠️ statgarten 경계 파일은 경위도가 아니라 UTM-K(EPSG:5179)다. 파일에 표기가 없다.
"""
from __future__ import annotations

import gzip
import json
import math
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.domain import gridproj as gp  # noqa: E402
from app.domain.regions import ORDER, ZONES  # noqa: E402

CACHE = Path(__file__).resolve().parent / ".cache"
OUT = ROOT / "data" / "geo"

# 원본은 커밋에 고정한다 — 같은 명령이 언제 돌아도 같은 결과가 나오게.
SGIS = ("https://raw.githubusercontent.com/statgarten/maps/"
        "8d53dca28fed87f98a75886ea86ed75774f052eb/json/{}_시군구_경계.json")
SGIS_FILES = {"경상남도": "gn", "부산광역시": "nb", "울산광역시": "nb"}
EMD = ("https://raw.githubusercontent.com/vuski/admdongkor/"
       "7360288277dfd12d74e54b959c59bdd66f852e3a/ver20260701/HangJeongDong_ver20260701.geojson")

MARGIN_KM = 20
MAPSHAPER = "mapshaper@0.7.71"
SIMPLIFY = "0.15"          # 칸 단위 간격(0.15칸 = 75m). 1080p 에서 한 칸이 약 2.5px
MIN_ISLAND = "0.3"         # 칸² — 이보다 작은 섬은 뺀다(0.3칸² ≈ 0.075㎢)


def fetch(url: str, name: str) -> Path:
    p = CACHE / name
    if not p.exists():
        CACHE.mkdir(exist_ok=True)
        print("받는 중", name)
        with urllib.request.urlopen(urllib.parse.quote(url, safe=":/")) as r:
            p.write_bytes(r.read())
    return p


def short_sigun(title: str) -> str:
    """'창원시 마산합포구' → '창원', '고성군' → '고성'.

    ⚠️ 행정동 파일은 '창원시마산합포구' 처럼 붙여 쓴다. 띄어쓰기로 자르지 않고
       관제순 목록의 앞머리로 맞춘다.
    """
    for s in ORDER:
        if title.startswith(s):
            return s
    head = title.split()[0]
    return head[:-1] if head[-1] in "시군" else head


def zone_of(sig: str) -> tuple[str | None, str | None]:
    """(상위 권역, 하위 권역). ZONES 한 곳에서만 읽는다."""
    top = sub = None
    for name, siguns, _grp, parent in ZONES:
        if sig in siguns:
            if parent is None:
                top = name
            else:
                sub = name
    return top, sub


def rings_to_grid(geom: dict, conv) -> list[list[list[tuple[float, float]]]]:
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    return [[[conv(x, y) for x, y in ring] for ring in poly] for poly in polys]


def rasterize(mask: np.ndarray, polys, value: int, i0: int, j0: int) -> None:
    """칸 가운데가 다각형 안이면 value 를 칠한다. 홀짝 규칙(구멍은 저절로 빠진다).

    변마다 걸치는 행에서만 교차점을 구한다 — 모든 행 × 모든 변을 돌면 느리다.
    """
    h, w = mask.shape
    for poly in polys:
        xs_by_row: dict[int, list[float]] = {}
        for ring in poly:
            for k in range(len(ring) - 1):
                x1, y1 = ring[k][0] - i0, ring[k][1] - j0
                x2, y2 = ring[k + 1][0] - i0, ring[k + 1][1] - j0
                if y1 == y2:
                    continue
                lo, hi = (y1, y2) if y1 < y2 else (y2, y1)
                # 반열린 구간 [lo, hi) — 꼭짓점을 두 번 세지 않는다
                for r in range(max(0, math.ceil(lo)), min(h - 1, math.ceil(hi) - 1) + 1):
                    if lo <= r < hi:
                        xs_by_row.setdefault(r, []).append(x1 + (r - y1) * (x2 - x1) / (y2 - y1))
        for r, xs in xs_by_row.items():
            xs.sort()
            for a, b in zip(xs[0::2], xs[1::2]):
                c0, c1 = max(0, math.ceil(a)), min(w, math.ceil(b))
                if c0 < c1:
                    mask[r, c0:c1] = value


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    def utmk_to_hr(e, n):
        return gp.hr_xy(*gp.utmk_lonlat(e, n))

    # ── 시군 경계: UTM-K → 경위도 → 500m 칸 ───────────────────────────────
    feats = []
    for sido, kind in SGIS_FILES.items():
        d = json.loads(fetch(SGIS.format(sido), f"{sido}.json").read_text("utf-8"))
        for ft in d["features"]:
            sig = short_sigun(ft["properties"]["title"]) if kind == "gn" else sido[:2]
            feats.append((sig, kind, rings_to_grid(ft["geometry"], utmk_to_hr)))
    names = [s for s in ORDER] + ["부산", "울산"]
    got = {s for s, _, _ in feats}
    if got != set(names):
        raise SystemExit(f"시군 이름이 맞지 않는다: 빠짐 {set(names) - got}, 남음 {got - set(names)}")

    xs = [p[0] for _, _, polys in feats for poly in polys for ring in poly for p in ring]
    ys = [p[1] for _, _, polys in feats for poly in polys for ring in poly for p in ring]
    m = MARGIN_KM * 1000 / gp.HR["grid_m"]
    i0, i1 = math.floor(min(xs) - m), math.ceil(max(xs) + m)
    j0, j1 = math.floor(min(ys) - m), math.ceil(max(ys) + m)
    w, h = i1 - i0 + 1, j1 - j0 + 1
    print(f"500m bbox 열 {i0}~{i1} 행 {j0}~{j1} = {w}×{h} = {w * h:,}칸")

    # 5km bbox — 같은 경계 외곽 + 20km
    lonlat = [gp.hr_lonlat(x, y) for x, y in zip(xs, ys)]
    d5 = [gp.dfs_xy(lo, la) for lo, la in lonlat]
    m5 = MARGIN_KM / gp.DFS["grid_km"]
    a0 = math.floor(min(p[0] for p in d5) - m5)
    a1 = math.ceil(max(p[0] for p in d5) + m5)
    b0 = math.floor(min(p[1] for p in d5) - m5)
    b1 = math.ceil(max(p[1] for p in d5) + m5)
    print(f"5km bbox 열 {a0}~{a1} 행 {b0}~{b1} (0부터) = {(a1 - a0 + 1) * (b1 - b0 + 1):,}칸")

    # 5km 칸 → 500m 칸 아핀 — 두 격자는 지구 모양이 달라 정확히 겹치지 않는다.
    # bbox 안에서 최소제곱으로 맞추고 잔차를 적어 둔다(실측 0.015칸).
    src, dst = [], []
    for ii in np.linspace(a0 - 1, a1 + 1, 40):
        for jj in np.linspace(b0 - 1, b1 + 1, 40):
            src.append((ii, jj, 1.0))
            dst.append(gp.hr_xy(*gp.dfs_lonlat(ii, jj)))
    A, B = np.array(src), np.array(dst)
    cx, *_ = np.linalg.lstsq(A, B[:, 0], rcond=None)
    cy, *_ = np.linalg.lstsq(A, B[:, 1], rcond=None)
    resid = float(max(np.abs(A @ cx - B[:, 0]).max(), np.abs(A @ cy - B[:, 1]).max()))
    print(f"5km→500m 아핀 잔차 최대 {resid:.4f}칸")
    if resid > 0.05:
        raise SystemExit("아핀 잔차가 너무 크다 — 5km 층이 경계와 어긋난다")

    # ── 시군 칸 지도 ────────────────────────────────────────────────────
    sig_id = {s: k + 1 for k, s in enumerate(names)}
    msig = np.zeros((h, w), np.uint8)
    for sig, _, polys in feats:
        rasterize(msig, polys, sig_id[sig], i0, j0)
    (OUT / "mask_sigun.u8.gz").write_bytes(gzip.compress(msig.tobytes(), 9, mtime=0))
    print("시군 칸 수", {s: int((msig == sig_id[s]).sum()) for s in names})

    # ── 읍면동 칸 지도(경남만) ───────────────────────────────────────────
    e = json.loads(fetch(EMD, "HangJeongDong_ver20260701.geojson").read_text("utf-8"))
    emds = []
    memd = np.zeros((h, w), np.uint16)
    for ft in e["features"]:
        p = ft["properties"]
        if p.get("sidonm") != "경상남도":
            continue
        sig = short_sigun(p["sggnm"])
        emds.append({"id": len(emds) + 1, "sigun": sig, "name": p["adm_nm"].split()[-1],
                     "code": p["adm_cd2"]})
        rasterize(memd, rings_to_grid(ft["geometry"], gp.hr_xy), len(emds), i0, j0)
    for it in emds:
        rr, cc = np.nonzero(memd == it["id"])
        # 칸 가운데(열, 행) — 읍면동이 칸 하나보다 작아 칸이 없을 때를 대비한 가까운 곳 찾기용
        it["c"] = [round(float(cc.mean()) + i0, 1), round(float(rr.mean()) + j0, 1)] if len(rr) else None
        it["n"] = int(len(rr))
    (OUT / "mask_emd.u16.gz").write_bytes(gzip.compress(memd.astype("<u2").tobytes(), 9, mtime=0))
    bad = {it["sigun"] for it in emds} - set(ORDER)
    if bad:
        raise SystemExit(f"읍면동 시군 이름이 맞지 않는다: {bad}")
    print(f"읍면동 {len(emds)}곳, 칸이 없는 곳 {sum(1 for it in emds if not it['n'])}")

    # ── TopoJSON: 시군 경계를 칸 좌표 그대로 mapshaper 에 넘긴다 ───────────────
    gj = {"type": "FeatureCollection", "features": []}
    for sig, kind, polys in feats:
        top, sub = zone_of(sig)
        gj["features"].append({
            "type": "Feature",
            "properties": {"sigun": sig, "id": sig_id[sig], "kind": kind,
                           "zone": top or sig, "sub": sub or top or sig},
            "geometry": {"type": "MultiPolygon",
                         "coordinates": [[[[round(x, 4), round(y, 4)] for x, y in ring]
                                          for ring in poly] for poly in polys]}})
    tmp = CACHE / "sigun_grid.json"
    tmp.write_text(json.dumps(gj, ensure_ascii=False), "utf-8")
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    if not npx:
        raise SystemExit("npx 가 없다 — node 를 깔아야 mapshaper 를 부를 수 있다")
    topo = OUT / "gyeongnam.topo.json"
    cmd = [npx, "-y", MAPSHAPER, "-i", str(tmp), "name=sigun",
           "-dissolve", "sigun", "copy-fields=id,kind,zone,sub",
           "-filter-islands", f"min-area={MIN_ISLAND}",
           "-simplify", f"interval={SIMPLIFY}", "keep-shapes",
           # 시군명 자리 — 다각형 안쪽 가장 깊은 점(볼록하지 않은 시군도 안에 떨어진다)
           "-each", "lx=+this.innerX.toFixed(2), ly=+this.innerY.toFixed(2)",
           "-o", str(topo), "format=topojson", "quantization=100000", "force"]
    subprocess.run(cmd, check=True)
    print(f"{topo.name} {topo.stat().st_size / 1024:.1f}KB")

    meta = {
        "_comment": "경남 지도 격자 틀. tools/build_geo.py 가 만든다 — 손으로 고치지 않는다. "
                    "칸 번호는 0부터, 칸 가운데가 정수. 행은 남→북.",
        "hr": {**{k: gp.HR[k] for k in ("nx", "ny", "xo", "yo", "grid_m", "slat1", "slat2",
                                         "olon", "olat", "ellps")},
               "bbox": {"i0": i0, "i1": i1, "j0": j0, "j1": j1, "w": w, "h": h}},
        "dfs": {**{k: gp.DFS[k] for k in ("nx", "ny", "xo", "yo", "grid_km", "slat1", "slat2",
                                          "olon", "olat", "re_km")},
                "bbox": {"i0": a0, "i1": a1, "j0": b0, "j1": b1,
                         "w": a1 - a0 + 1, "h": b1 - b0 + 1},
                "_x": "기상청 X = 열 + 1, Y = 행 + 1"},
        # 500m 칸 = [a, b, c] · (5km 열, 5km 행, 1) — 행도 같은 꼴 [d, e, f]
        "dfs_to_hr": {"col": [round(float(v), 6) for v in cx],
                      "row": [round(float(v), 6) for v in cy], "resid": round(resid, 4)},
        "sigun": [{"id": sig_id[s], "name": s, "kind": "gn" if s in ORDER else "nb",
                   "zone": (zone_of(s)[0] or s), "sub": (zone_of(s)[1] or zone_of(s)[0] or s),
                   "cells": int((msig == sig_id[s]).sum())} for s in names],
        "emd": emds,
        "masks": {"sigun": "mask_sigun.u8.gz", "emd": "mask_emd.u16.gz",
                  "shape": [h, w], "order": "행은 남→북(j0부터), 한 행은 서→동(i0부터)"},
        "sources": {
            "sigun": "statgarten/maps@8d53dca json/*_시군구_경계.json — SGIS 2020년 경계, UTM-K",
            "emd": "vuski/admdongkor@7360288 ver20260701 — 행정동 2026-07-01, WGS84",
            "simplify": f"{MAPSHAPER} interval={SIMPLIFY}칸, 섬 {MIN_ISLAND}칸² 미만 뺌",
        },
    }
    (OUT / "grids.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    print("grids.json 씀")


if __name__ == "__main__":
    import urllib.parse  # noqa: F401 — fetch() 가 쓴다
    main()

"""경남 리 경계 → data/geo/ri.topo.json (읍면동과 같은 칸 좌표 · 같은 단순화). 시군을 확대했을 때 리 선 · 이름.

    PYTHONUTF8=1 ./.venv/Scripts/python.exe tools/build_ri.py [LSMD_ADM_SECT_RI_경남.zip(기본 ~/Desktop)]

원본 = 브이월드 › 공간정보 다운로드 › 행정구역_리(법정동) (국토교통부, SHP, EPSG:5186) — LSMD_ADM_SECT_RI_경남.zip.
속성 RI_CD(10자리 법정리 코드 — 앞 5자리 시군구) · RI_NM. 시군 이름은 grids.json 읍면동 코드 앞 5자리로 붙인다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import numpy as np
import shapefile
from pyproj import Transformer

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_bldg import lcc_fwd_np  # noqa: E402
from build_geo import MAPSHAPER, MIN_ISLAND, SIMPLIFY  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "geo" / "ri.topo.json"


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "Desktop" / "LSMD_ADM_SECT_RI_경남.zip"
    g = json.loads((ROOT / "data" / "geo" / "grids.json").read_text("utf-8"))
    p = g["hr"]
    sig = {e["code"][:5]: e["sigun"] for e in g["emd"]}
    to_ll = Transformer.from_crs(5186, 4326, always_xy=True)
    tmp = Path(tempfile.mkdtemp())
    with zipfile.ZipFile(src) as z:
        z.extractall(tmp)
    shp = next(tmp.rglob("*.shp"))
    r = shapefile.Reader(str(shp), encoding="cp949")
    feats, miss = [], set()
    for sr in r.iterShapeRecords():
        code, name = str(sr.record["RI_CD"]), sr.record["RI_NM"]
        sg = sig.get(code[:5])
        if not sg:
            miss.add(code[:5])
            continue
        pts, parts = np.asarray(sr.shape.points, float), list(sr.shape.parts) + [len(sr.shape.points)]
        lo, la = to_ll.transform(pts[:, 0], pts[:, 1])
        x, y = lcc_fwd_np(np.asarray(lo), np.asarray(la), p)
        rings = [[[round(float(x[k]), 4), round(float(y[k]), 4)] for k in range(a, b)] for a, b in zip(parts, parts[1:])]
        # shortcut: 고리마다 따로 다각형(구멍 구분 안 함) — 선(mesh)과 이름 자리만 쓰니 충분, 면을 칠하게 되면 바로잡는다
        feats.append({"type": "Feature", "properties": {"code": code, "name": name, "sigun": sg},
                      "geometry": {"type": "MultiPolygon", "coordinates": [[rg] for rg in rings if len(rg) >= 4]}})
    shutil.rmtree(tmp, ignore_errors=True)
    if miss:
        print("시군을 못 찾은 시군구 코드(뺌):", sorted(miss), file=sys.stderr)
    gj = ROOT / "tools" / ".cache" / "ri_grid.json"
    gj.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), "utf-8")
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    subprocess.run([npx, "-y", MAPSHAPER, "-i", str(gj), "name=ri",
                    "-dissolve", "code", "copy-fields=name,sigun",
                    "-filter-islands", f"min-area={MIN_ISLAND}",
                    "-simplify", f"interval={SIMPLIFY}", "keep-shapes",
                    "-each", "lx=+this.innerX.toFixed(2), ly=+this.innerY.toFixed(2)",
                    "-o", str(OUT), "format=topojson", "quantization=100000", "force"], check=True)
    gj.unlink()
    t = json.loads(OUT.read_text("utf-8"))
    n = len(t["objects"]["ri"]["geometries"])
    assert n > 1500, f"리가 {n}곳뿐 — 원본을 확인"
    print(f"→ {OUT} · 리 {n}곳 · {OUT.stat().st_size / 1024:.0f}KB", file=sys.stderr)


if __name__ == "__main__":
    main()

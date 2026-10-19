"""경남 AWS 목록(엑셀) → data/geo/aws_sites.json — 지점마다 관리기관(경남 · 기상청) · 위경도 · 500m 칸.

    .venv\\Scripts\\python.exe tools\\build_aws_sites.py <aws.xlsx>

엑셀 칸: 시군명 · 장치명 · 주소 · 위도 · 경도 · 관리기관(경상남도 | 기상청) · 설치위치 · 해발고도 · 바닥재질.
스방(경남 스마트 통합 방재시스템) 시간강우량은 지점을 장치코드(lnk_id) · 장치명(rtu_name) · 시군으로 준다 —
장치코드가 엑셀에 없어 **시군 + 장치명**으로 짝짓는다(app/sites.py). 같은 시군에 같은 이름이 둘이면
(합천 — 경남 · 기상청) 기상청 지점번호로 오는 것이 기상청, 아닌 것이 경남이다.

기상청 지점은 data/geo/stations.json(기상청 지점 목록)에 이미 위치가 있다 — 엑셀 값과 견줘 얼마나 떨어졌는지
kma_check 에 남긴다(같은 계기면 수십 m 안).
openpyxl 없이 읽는다(xlsx 는 zip 안 XML).
"""
from __future__ import annotations

import json
import math
import re
import sys
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.domain import gridproj  # noqa: E402

OUT = ROOT / "data" / "geo" / "aws_sites.json"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
ORG = {"경상남도": "gn", "기상청": "kma"}


def read_xlsx(path: Path) -> list[list]:
    z = zipfile.ZipFile(path)
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", NS):
            ss.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    rows = []
    for row in ET.fromstring(z.read("xl/worksheets/sheet1.xml")).iter("{%s}row" % NS["m"]):
        cells = {}
        for c in row.findall("m:c", NS):
            col = 0
            for ch in re.match(r"[A-Z]+", c.get("r")).group():
                col = col * 26 + ord(ch) - 64
            v, t = c.find("m:v", NS), c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
            elif v is None:
                val = None
            else:
                val = ss[int(v.text)] if t == "s" else v.text
            cells[col - 1] = val
        if cells:
            rows.append([cells.get(i) for i in range(max(cells) + 1)])
    return rows


def short_sigun(s: str) -> str:
    s = (s or "").strip()
    return s[:-1] if s[-1:] in ("시", "군") and len(s) > 2 else s


def dist_m(a, b) -> float:
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371000 * math.asin(math.sqrt(h))


def main(argv=None) -> None:
    argv = argv or sys.argv[1:]
    src = Path(argv[0])
    rows = read_xlsx(src)
    head = [str(x or "").strip() for x in rows[0]]
    ix = {k: head.index(k) for k in ("시군명", "장치명", "주소", "위도", "경도", "관리기관", "설치위치", "해발고도")}
    kma = json.loads((ROOT / "data" / "geo" / "stations.json").read_text("utf-8"))["stations"]
    sites, check = [], []
    for r in rows[1:]:
        g = lambda k: (r[ix[k]] if ix[k] < len(r) else None)  # noqa: E731
        name = re.sub(r"\s+", "", str(g("장치명") or ""))
        if not name or not g("위도"):
            continue
        lat, lon = float(g("위도")), float(g("경도"))
        x, y = gridproj.hr_xy(lon, lat)
        org = ORG.get(str(g("관리기관") or "").strip(), "gn")
        s = {"sigun": short_sigun(str(g("시군명"))), "name": name, "org": org,
             "lat": round(lat, 6), "lon": round(lon, 6), "x": round(x, 2), "y": round(y, 2),
             "ht": float(g("해발고도")) if g("해발고도") not in (None, "") else None,
             "addr": str(g("주소") or "").strip(), "place": str(g("설치위치") or "").strip()}
        if org == "kma":
            m = [k for k in kma if k["sigun"] == s["sigun"] and k["name"] == name]
            if m:
                s["stn"] = m[0]["stn"]
                check.append({"stn": m[0]["stn"], "name": name, "sigun": s["sigun"],
                              "m": round(dist_m((lat, lon), (m[0]["lat"], m[0]["lon"])))})
            else:
                check.append({"stn": None, "name": name, "sigun": s["sigun"], "m": None})
        sites.append(s)
    out = {"_comment": "경남 AWS 지점 위치 — tools/build_aws_sites.py 가 엑셀(관리기관 · 위경도)로 만든다. "
                       "스방 지점은 시군 + 장치명으로 짝짓는다(app/sites.py).",
           "source": src.name, "built": datetime.now().strftime("%Y-%m-%d"),
           "count": {"gn": sum(s["org"] == "gn" for s in sites), "kma": sum(s["org"] == "kma" for s in sites)},
           "sites": sites, "kma_check": check}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), "utf-8")
    far = [c for c in check if c["m"] is None or c["m"] > 200]
    print(json.dumps({"out": str(OUT), "count": out["count"], "kma_matched": sum(c["stn"] is not None for c in check),
                      "kma_far_or_unmatched": far,
                      "kma_m_max": max((c["m"] for c in check if c["m"] is not None), default=None)},
                     ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()

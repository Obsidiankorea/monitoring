"""경남 AWS 지점 위치 — 지도 '관측소' 층이 점을 찍을 자리를 굳혀 둔다.

    .venv\\Scripts\\python.exe tools\\build_stations.py [YYYYMMDD]

기관키가 있어야 한다(config/api_keys.txt). 한 번 돌려 data/geo/stations.json 을 커밋하면
화면은 기상청을 부르지 않는다. 지점을 옮기거나 새로 놓았을 때만 다시 돌린다.

⚠️ 지점정보 API(stn_inf.php)는 이 키로 **403**(활용신청 필요)이다. 일자료(sfc_aws_day.php)가
   지점마다 경도·위도·노장 해발고도를 같이 주므로(help=1 머리글에 'LON LAT HT') 그것을 쓴다.
   그날 자료가 없는 지점은 빠진다 — 사천공항(161)은 매시·매분 자료도 늘 결측이라 위치도 없다.
⚠️ 목록은 data/aws_stations.json 의 56곳 그대로다(종합 화면과 같은 지점). 경남 땅에 있는데
   목록에 없는 지점은 경고로만 알린다 — 값을 모으는 수집기가 그 지점을 받지 않는다.
"""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import gridstore  # noqa: E402
from app.domain import gridproj  # noqa: E402
from app.domain.regions import stations  # noqa: E402
from app.kma import fetch_text  # noqa: E402

OUT = ROOT / "data" / "geo" / "stations.json"


def parse(text: str) -> dict[str, dict]:
    """'YYMMDD, STN, LON, LAT, HT, VAL, 이름=' → {stn: {lon, lat, ht, name}}."""
    out = {}
    for line in text.splitlines():
        if line.startswith("#") or "," not in line:
            continue
        p = [x.strip() for x in line.split(",")]
        if len(p) < 7:
            continue
        out[p[1]] = {"lon": float(p[2]), "lat": float(p[3]), "ht": float(p[4]),
                     "name": p[6].rstrip("=").strip()}
    return out


async def main(day: str) -> None:
    text = await fetch_text("/api/typ01/url/sfc_aws_day.php",
                            {"obs": "rn_day", "tm1": day, "tm2": day, "stn": "0", "help": "1"})
    if "LON" not in text or "LAT" not in text:
        raise SystemExit("응답 머리글에 LON·LAT 가 없다 — 형식이 바뀌었다. 추측으로 맞추지 않는다")
    co = parse(text)
    if len(co) < 300:
        raise SystemExit(f"지점이 {len(co)}곳뿐이다 — 응답이 이상하다")

    sig, memd = gridstore.masks()
    g = gridstore.geo()
    hb = g["hr"]["bbox"]
    name_of = {s["id"]: s["name"] for s in g["sigun"]}
    kind_of = {s["id"]: s["kind"] for s in g["sigun"]}
    emd_of = {e["id"]: e for e in g["emd"]}

    def emd_name(x, y, sigun):
        """지점 칸의 읍면동 — 그 읍면동 초단기 예측을 지점 줄에 붙이려고. 시군이 다르면(경계 칸) 비운다."""
        c, r = round(x) - hb["i0"], round(y) - hb["j0"]
        if not (0 <= c < hb["w"] and 0 <= r < hb["h"]):
            return None
        e = emd_of.get(int(memd[r, c]))
        return e["name"] if e and e["sigun"] == sigun else None

    def cell(lon, lat):
        x, y = gridproj.hr_xy(lon, lat)
        c, r = round(x) - hb["i0"], round(y) - hb["j0"]
        inside = 0 <= c < hb["w"] and 0 <= r < hb["h"]
        return x, y, (int(sig[r, c]) if inside else 0)

    rows, missing, warn = [], [], []
    for s in stations():
        p = co.get(s["stn"])
        if not p:
            missing.append({"stn": s["stn"], "name": s["name"], "sigun": s["sigun"],
                            "why": f"sfc_aws_day {day} 에 없다"})
            continue
        x, y, sid = cell(p["lon"], p["lat"])
        on = name_of.get(sid)
        if on and on != s["sigun"]:
            warn.append(f"{s['stn']} {s['name']}: 목록은 {s['sigun']}, 자리는 {on}")
        rows.append({"stn": s["stn"], "name": s["name"], "sigun": s["sigun"],
                     "emd": emd_name(x, y, s["sigun"]), "lon": round(p["lon"], 5), "lat": round(p["lat"], 5), "ht": p["ht"],
                     "x": round(x, 2), "y": round(y, 2)})

    listed = {s["stn"] for s in stations()}
    for stn, p in co.items():
        if stn in listed:
            continue
        _, _, sid = cell(p["lon"], p["lat"])
        if sid and kind_of.get(sid) == "gn":
            warn.append(f"{stn} {p['name']}: 경남({name_of[sid]}) 땅에 있는데 목록에 없다 — 값을 모으지 않는다")

    head = {"_comment": "경남 AWS 지점 위치(tools/build_stations.py). x·y 는 500m 격자 칸 좌표(칸 중심이 정수)",
            "source": f"기상청 sfc_aws_day.php {day} (LON·LAT·HT)",
            "built": datetime.now().strftime("%Y-%m-%d %H:%M")}
    j = lambda o: json.dumps(o, ensure_ascii=False)          # noqa: E731 — 한 지점 한 줄(diff 읽기 좋게)
    OUT.write_text("{\n" + "".join(f" {j(k)}: {j(v)},\n" for k, v in head.items())
                   + ' "stations": [\n' + ",\n".join(f"  {j(r)}" for r in rows) + "\n ],\n"
                   + f' "missing": {j(missing)}\n}}\n', "utf-8")
    print(f"{len(rows)}곳 → {OUT.relative_to(ROOT)}")
    for m in missing:
        print("위치 없음:", m["stn"], m["name"], "—", m["why"])
    for w in warn:
        print("확인:", w)


if __name__ == "__main__":
    d = sys.argv[1] if len(sys.argv) > 1 else (datetime.now() - timedelta(days=1)).strftime("%Y%m%d")
    asyncio.run(main(d))

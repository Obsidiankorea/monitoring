"""경남 산사태취약지역(공공데이터포털 15014457 · 2026-05-01판) → 좌표를 붙여 data/geo/slide_vuln.json 에 둔다.
산사태 복구 지점(위키 data/경남 산사태 지점 이력.csv)도 좌표로 바꿔, 취약지역과의 거리를 잰다(검증표를 화면에 찍는다).

    PYTHONUTF8=1 PYTHONPATH=. ./.venv/Scripts/python.exe tools/build_slide_vuln.py

키는 config/api_keys.txt(DATA_GO_KR_KEY · VWORLD_KEY). 주소 → 좌표는 브이월드 지오코더(app/geocode.ask) — 한 번 찾은 것은 tools/.cache/slide_geo.json 에 적어 다시 묻지 않는다.
"""
from __future__ import annotations

import asyncio
import csv
import json
import math
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

import httpx

from app import ai, config, geocode

ROOT = Path(__file__).resolve().parents[1]
WIKI = Path.home() / "obsidian" / "재난"
CACHE = ROOT / "tools" / ".cache" / "slide_geo.json"
OUT = ROOT / "data" / "geo" / "slide_vuln.json"
API = "https://api.odcloud.kr/api/15014457/v1/uddi:df71d834-a300-4c29-8649-ca116ad30ab1"
FULL = {v[:2]: v for v in ai.SIGUN_FULL.values()}


def lot(s: str) -> str:
    m = re.search(r"(산)?\s*(\d+)(?:-(\d+))?", s or "")
    return f"{'산' if m.group(1) else ''}{m.group(2)}{'-' + m.group(3) if m.group(3) else ''}" if m else ""


def vuln_rows(key: str) -> list[dict]:
    rows, page = [], 1
    while True:
        j = httpx.get(API, params={"page": page, "perPage": 1000, "serviceKey": key}, timeout=30).json()
        rows += j["data"]
        if len(rows) >= j["totalCount"] or not j["data"]:
            return rows
        page += 1


def vuln_addr(v: dict) -> str:
    sg = v["시군구"].split()
    return " ".join(x for x in ["경상남도", FULL.get(sg[0][:2], sg[0]), *sg[1:], v["읍면동"] or "", v["리"] or "", lot(v["지번"])] if x)


def inc_addr(r: dict) -> str | None:
    """복구 지점 → '경상남도 시군 (구) 읍면동 (리) 지번'. 읍면동 · 리는 시설 이름 글에서, 없으면 읍면동 칸에서."""
    t, j = r["리_마을_단지"], lot(r["지번"])
    sg = FULL.get(re.sub(r"\(.*", "", r["시군"]).split()[0][:2])
    emd = re.search(r"[가-힣0-9]+(?:읍|면)(?![가-힣])", t)
    ri = re.search(r"[가-힣0-9]+리(?![가-힣])", t)
    dong = re.search(r"[가-힣0-9]+동(?![가-힣])", t)
    gu = re.search(r"(의창구|성산구|마산합포구|마산회원구|진해구)", t)
    place = [emd.group(), ri.group()] if emd and ri else [dong.group()] if dong and not emd else [r["읍면동"], ri.group()] if ri and r["읍면동"] else None
    if not (sg and j and place):
        return None
    return " ".join(["경상남도", sg, *([gu.group()] if gu else []), *place, j])


async def locate(addrs: list[str]) -> dict:
    got = json.loads(CACHE.read_text("utf-8")) if CACHE.exists() else {}
    todo = [a for a in dict.fromkeys(addrs) if a not in got]
    key = config.KEYS.get("VWORLD_KEY")
    async with httpx.AsyncClient(timeout=15) as cli:
        for n, a in enumerate(todo, 1):
            r = await geocode.ask(cli, key, a)
            got[a] = list(r) if isinstance(r, tuple) else None
            if not isinstance(r, tuple) and geocode._key_error(r):
                raise SystemExit(f"브이월드 키 · 한도 문제: {r}")
            if n % 100 == 0 or n == len(todo):
                CACHE.write_text(json.dumps(got, ensure_ascii=False), "utf-8")
                print(f"  좌표 {n}/{len(todo)}", file=sys.stderr, flush=True)
            await asyncio.sleep(0.12)
    return got


def dist(a, b) -> float:
    return math.hypot((a[1] - b[1]) * 91000, (a[0] - b[0]) * 111000)


def main():
    V = vuln_rows(config.KEYS["DATA_GO_KR_KEY"])
    I = [r for r in csv.DictReader(open(WIKI / "data" / "경남 산사태 지점 이력.csv", encoding="utf-8-sig")) if inc_addr(r)]
    got = asyncio.run(locate([vuln_addr(v) for v in V] + [inc_addr(r) for r in I]))
    rows = []
    for v in V:
        p = got.get(vuln_addr(v))
        if p:
            sg = v["시군구"].split()[0][:2]
            rows.append({"sg": sg, "emd": v["읍면동"] or "", "ri": v["리"] or "", "jb": lot(v["지번"]), "ty": v["취약지역유형"],
                         "a": round(float(v["지정면적(제곱미터)"] or 0)), "sh": (v["지정대피소"] or "").strip("- "), "p": [round(p[0], 6), round(p[1], 6)]})
    OUT.write_text(json.dumps({"built": date.today().isoformat(), "src": "경상남도 산사태취약지역 지정현황 2026-05-01(공공데이터포털 15014457) · 좌표는 지번을 브이월드로 찾은 것",
                               "n": len(V), "rows": rows}, ensure_ascii=False, separators=(",", ":")), "utf-8")
    print(f"→ {OUT} · 취약지역 {len(V)}곳 중 좌표 {len(rows)}")
    # 검증 — 복구 지점에서 가장 가까운 취약지역까지
    pts = [r["p"] for r in rows]
    def table(inc, tag):
        ds = [min(dist(got[inc_addr(r)], p) for p in pts) for r in inc if got.get(inc_addr(r))]
        if not ds:
            return
        c = Counter("100m 안" if d <= 100 else "300m 안" if d <= 300 else "1km 안" if d <= 1000 else "1km 밖" for d in ds)
        print(f"{tag}: 좌표를 찾은 복구 지점 {len(ds)} → " + " · ".join(f"{k} {c[k]}({c[k] / len(ds):.0%})" for k in ("100m 안", "300m 안", "1km 안", "1km 밖")))
    table(I, "2016~2026 전체")
    for y in ("2020", "2025", "2026"):
        table([r for r in I if r["event_id"].startswith(y)], y)
    table([r for r in I if r["event_id"].startswith("202608") and "거제" in r["시군"]], "2026-08 거제")


if __name__ == "__main__":
    main()

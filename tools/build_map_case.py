"""경남 지도 재현 사례 — 지난 호우를 500m 격자 그대로 굳혀 저장소에 둔다.

    .venv\\Scripts\\python.exe tools\\build_map_case.py geoje-20260816

기관키가 있어야 한다(config/api_keys.txt). 한 번 돌려 data/demo/map/{사례}/ 를 커밋하면
화면은 기상청을 다시 부르지 않는다 — 데모 사례(data/demo/*.json)와 같은 원칙이다.

만드는 것
  obs60/{YYYYMMDDHHMI}.u16.gz  매시 정각 60분 강수(= 그 앞 한 시간), 경남 bbox, gridstore 형식
  meta.json                    제목·기간·프레임, 시군별 시계열(1시간·3시간·12시간·누적 최대와
                               그 칸의 읍면동), 산출 호우특보, 확인한 관측소 값,
                               관측소 매시 RN_HR1(awsh.php) — 지도 '관측소' 층이 격자 옆에 놓는다

⚠️ 특보 이력 API(wrn_met_data.php)는 이 키로 403 이다. 그래서 격자의 3시간·12시간 합에
   호우 기준을 적용한 **산출** 특보만 담는다(종합 화면 데모와 같은 원칙). 화면에 '산출'이라 적는다.
   기준(시간당 ㎜): 주의보 3시간 60 또는 12시간 110 · 경보 3시간 90 또는 12시간 180.
   실제 특보는 특보구역·예보를 함께 보므로 산출과 다를 수 있다.
⚠️ 누적은 매시 60분 값을 칸마다 더한 것이다(결측 칸은 결측으로 남긴다 — 0 으로 치지 않는다).
"""
from __future__ import annotations

import asyncio
import gzip
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app import gridstore  # noqa: E402
from app.collectors.grid_rain import _fetch_hr  # noqa: E402
from app.collectors.rain import GN_STN, fetch_hour  # noqa: E402

OUT = ROOT / "data" / "demo" / "map"

CASES = {
    "geoje-20260816": {
        "title": "2026.8.16~17 거제 극한호우",
        "start": "202608160100",          # 8.16 00~01시 몫부터
        "end": "202608181200",
        # 사실 확인(2026-10-03, sfc_aws_day rn_day): 이 값으로 사례를 골랐다
        "checked": [
            {"stn": "294", "name": "거제", "days": {"0816": 273.3, "0817": 654.3}, "sum": 927.6},
            {"stn": "909", "name": "서이말", "days": {"0816": 324.5, "0817": 499.5}, "sum": 824.0},
            {"stn": "162", "name": "통영", "days": {"0816": 294.4, "0817": 457.7}, "sum": 752.1},
            {"stn": "947", "name": "명사", "days": {"0816": 392.0, "0817": 336.0}, "sum": 728.0},
        ],
    },
}
WATCH = {"h3": 60, "h12": 110}
WARN = {"h3": 90, "h12": 180}


def level(h3: float | None, h12: float | None) -> str | None:
    h3, h12 = h3 or 0, h12 or 0
    if h3 >= WARN["h3"] or h12 >= WARN["h12"]:
        return "warn"
    if h3 >= WATCH["h3"] or h12 >= WATCH["h12"]:
        return "watch"
    return None


async def station_hours(keys: list[str], old: dict | None) -> dict:
    """관측소 매시 1시간 강수(awsh.php RN_HR1) — 프레임과 같은 시각. 지난번에 받은 게 있으면 다시 안 부른다."""
    if old and old.get("frames") == keys and old.get("stations"):
        return old["stations"]
    h1: dict[str, list] = {s: [] for s in sorted(GN_STN)}
    for tm in keys:
        rows = await fetch_hour(datetime.strptime(tm, "%Y%m%d%H%M"))
        if not rows:
            raise SystemExit(f"{tm} 관측소 정시자료가 비었다 — 멈춘다")
        for s in h1:
            v = (rows.get(s) or {}).get("rn_hr1")
            h1[s].append(None if v is None or v < 0 else v)
    return {"src": "기상청 정시자료(awsh.php) RN_HR1 매시", "h1": h1}


def stats(arr: np.ndarray) -> dict:
    """{시군: (최대, 평균, 읍면동)} — 최대 칸의 읍면동까지."""
    out = {}
    for r in gridstore.sigun_stats(arr):
        if r["kind"] != "gn":
            continue
        out[r["sigun"]] = (r["max"], r["mean"], (r["where"] or {}).get("emd"))
    return out


async def main(slug: str) -> None:
    c = CASES[slug]
    d = OUT / slug
    (d / "obs60").mkdir(parents=True, exist_ok=True)
    t = datetime.strptime(c["start"], "%Y%m%d%H%M")
    end = datetime.strptime(c["end"], "%Y%m%d%H%M")
    keys, arrs = [], []
    while t <= end:
        tm = t.strftime("%Y%m%d%H%M")
        p = d / "obs60" / f"{tm}.u16.gz"
        if p.exists():
            a = gridstore.decode(gzip.decompress(p.read_bytes()), "hr")
        else:
            full = await _fetch_hr("rn_60m", tm)
            if full is None:
                print(tm, "없음 — 건너뜀")
                t += timedelta(hours=1)
                continue
            a = gridstore.crop_hr(full)
            p.write_bytes(gzip.compress(gridstore.encode(a), 9, mtime=0))
            a = gridstore.decode(gridstore.encode(a), "hr")     # 저장한 값 그대로(0.1㎜)로 계산
        keys.append(tm)
        arrs.append(a)
        print(tm, f"경남 최대 {np.nanmax(a):.1f}")
        t += timedelta(hours=1)

    names = [s["name"] for s in gridstore.geo()["sigun"] if s["kind"] == "gn"]
    ser = {s: {k: [] for k in ("h1", "h1m", "h1w", "h3", "h12", "acc", "accw", "lv")} for s in names}
    total = {"h1": [], "h1m": [], "acc": []}
    acc = np.zeros_like(arrs[0])
    for i, a in enumerate(arrs):
        acc = acc + a                                       # 결측은 결측으로 남는다
        h3 = sum(arrs[max(0, i - 2):i + 1])
        h12 = sum(arrs[max(0, i - 11):i + 1])
        s1, sa, s3, s12 = stats(a), stats(acc), stats(h3), stats(h12)
        for s in names:
            ser[s]["h1"].append(s1[s][0]); ser[s]["h1m"].append(s1[s][1]); ser[s]["h1w"].append(s1[s][2])
            ser[s]["acc"].append(sa[s][0]); ser[s]["accw"].append(sa[s][2])
            ser[s]["h3"].append(s3[s][0]); ser[s]["h12"].append(s12[s][0])
            ser[s]["lv"].append(level(s3[s][0], s12[s][0]))
        gv = gridstore.sigun_values(a)["경남"]
        total["h1"].append(gv[0])
        total["h1m"].append(gv[1])
        total["acc"].append(gridstore.sigun_values(acc)["경남"][0])
    peak = int(np.argmax(total["h1"]))
    mp = d / "meta.json"
    stn = await station_hours(keys, json.loads(mp.read_text("utf-8")) if mp.exists() else None)
    # 관측소 매시 합이 일자료(checked)와 맞는지 — 날(01시~다음날 00시)마다 견준다
    for ck in c["checked"]:
        h = stn["h1"].get(ck["stn"])
        if not h:
            continue
        for day, want in ck["days"].items():
            idx = [i for i, k in enumerate(keys)
                   if (datetime.strptime(k, "%Y%m%d%H%M") - timedelta(minutes=1)).strftime("%m%d") == day]
            got = round(sum(h[i] or 0 for i in idx), 1)
            print(f"관측소 {ck['name']} {day}: 매시 합 {got} / 일자료 {want}"
                  + ("" if abs(got - want) < 0.15 and len(idx) == 24 else "  ← 다르다"))
    meta = {
        "slug": slug, "title": c["title"], "start": keys[0], "end": keys[-1], "frames": keys,
        "peak": keys[peak], "checked": c["checked"],
        "criteria": {"watch": WATCH, "warn": WARN, "note": "산출 — 격자 3시간·12시간 합에 호우 기준을 적용. 실제 발표 내역이 아니다"},
        "source": "기상청 고해상도 격자(500m) rn_60m 매시 정각 · sfc_grid_nc_down.php",
        "series": [{"sigun": s, **ser[s]} for s in names], "total": total, "stations": stn,
        "built": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False), "utf-8")
    top = sorted(((v["acc"][-1] or 0, s, v["accw"][-1]) for s, v in ser.items()), reverse=True)[:5]
    print(f"{len(keys)}장 · 봉우리 {keys[peak]} (경남 1시간 최대 {total['h1'][peak]}㎜)")
    print("사례 누적 최대:", ", ".join(f"{s} {v:.1f}({w})" for v, s, w in top))
    size = sum(f.stat().st_size for f in (d / "obs60").glob("*.gz"))
    print(f"격자 {size / 1024:.0f}KB")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1] if len(sys.argv) > 1 else "geoje-20260816"))

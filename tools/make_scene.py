"""가상 시연에 하천 · 조위 · 도로 상황을 얹는다 — 시연 서버는 이 자료를 받지 않으므로 scene.json 으로 넣어 준다(발표 · 훈련용, 실제 아님).

    .venv\\Scripts\\python.exe tools\\make_scene.py fake-20261019-x2 river.json tide.json

river.json · tide.json 은 서버의 /api/river · /api/tide 응답 — 지점 · 제원 · 기준 수위 · 물결은 실제 것을 쓰고 값만 시나리오로 바꾼다.
예보도 시나리오다 — 마지막 3시간에 온 비의 분포가 앞으로 아홉 시간 이어진다고 보고 초단기(읍면동 전부 · 격자) · 단기 격자를 채운다.
기준 숫자는 새로 만들지 않는다. 단계는 river.stage · tide.stage 가 제원 · 고조정보 기준으로 낸다.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from app import config, gridstore, river, tide  # noqa: E402

# 지점 코드 → (지금 수위, 홍수예보 종류 · 단계, 발표, 도달 예상, 주의 지역)
WL = {"2019625": (3.42, ("홍수주의보 발령", 2, "202610190010", "202610190150", "고성군,진주시")),     # 진주 옥산교 — 지금은 정상, 예보는 주의보
      "2019610": (3.74, ("홍수경보 변경발령", 3, "202610182350", "202610190100", "고성군")),            # 고성 두문교 — 지금 주의보, 예보는 경보
      "2504660": (3.66, ("홍수경보 발령", 3, "202610182320", "202610182350", "창원시")),                # 창원 창원천 — 이미 경보 수위
      "2504655": (3.21, ("홍수주의보 발령", 2, "202610190000", "202610190110", "창원시")),              # 창원 진북2교
      "2018692": (3.95, ("홍수주의보 발령", 2, "202610190005", "202610190140", "사천시")),              # 사천 검정리 — 관심, 예보는 주의보
      "2502630": (2.96, ("홍수주의보 발령", 2, "202610190015", "202610190120", "남해군")),              # 남해 봉천교 — 관심, 예보는 주의보
      "2020671": (3.31, None)}                                                                      # 김해 주천교 — 관심 앞
RAINY = {"창원", "고성", "진주", "통영", "사천", "남해"}
FC_CURVE = [.9, 1.1, 1.25, 1.2, 1.0, .8, .6, .4, .25]         # 지금부터 한 시간째 · 두 시간째 … — 세 시간 뒤가 봉우리
ROAD = [("창원시", "202610182310", 12), ("고성군", "202610182340", 0)]
SPRING = {"now": True, "from": "2026-10-17", "to": "2026-10-21"}


def _river(src: dict, now: datetime) -> dict:
    stamp = f"{now:%Y%m%d%H%M}"
    rows, fc = [], 0
    for i, s in enumerate(src["rows"]):
        o = dict(s)
        if s["kind"] != "wl":
            o |= {"t": stamp, "stale": False}
            if s["name"] == "남강댐":                                 # 진주 위 댐 — 방류를 늘리는 중
                o |= {"v": 40.62, "inf": 1850.0, "out": 1200.0, "rise": True, "d1h": 480.0, "hist": [320 + k * 24.0 for k in range(37)]}
            rows.append(o)
            continue
        top = next((t for t in (s["thr"] or []) if t), 0)
        v, f = WL.get(s["id"], (round(top * (.5 if s.get("sigun") in RAINY else .3) + (i % 7) * .03 + .2, 2), None))
        base = s | {"pfh": s.get("pfh")}
        river._HIST[s["id"]] = []
        for k in range(36, -1, -1):                                  # 지금까지 여섯 시간 — 비가 오면서 오른 꼴
            t = now - timedelta(minutes=10 * k)
            river._push(s["id"], f"{t:%Y%m%d%H%M}", round(v * (.55 + .45 * ((36 - k) / 36) ** 2), 2))
        o = river._row(base, {"ymdhm": stamp, "wl": v, "fw": ""})
        o["stale"] = False
        if f:
            o["fc"] = dict(zip(("kind", "lv", "at", "eta", "area"), f))
            fc += 1
        rows.append(o)
    return {"at": now.isoformat(timespec="seconds"), "err": None, "rows": rows, "fld": [], "nfld": fc}


def _tide(src: dict, now: datetime) -> dict:
    """실제 물결을 시연 시각으로 옮기고 대조기 만조 높이로 키운다. 다음 만조가 7일 최고 예측 + 4% 가 되게."""
    shift = datetime.strptime(src["rows"][0]["series"][0][0], "%Y%m%d%H%M") - (now.replace(minute=30) - timedelta(hours=11))   # 다음 만조가 한 시간쯤 뒤에 오게
    by = {s["code"]: s for s in tide.STATIONS}
    rows = []
    for r in src["rows"]:
        ser = r["series"]
        mid = sum(p for _, _, p in ser) / len(ser)
        k = (r["top"]["h"] * 1.04 - mid) / (r["next"]["h"] - mid)
        grow = lambda v: None if v is None else round(mid + (v - mid) * k, 1)     # noqa: E731
        moved = [(t2 := f"{datetime.strptime(t, '%Y%m%d%H%M') - shift:%Y%m%d%H%M}", grow(p) + 14 if t2 <= f"{now:%Y%m%d%H%M}" else None, grow(p)) for t, _, p in ser]   # 실측 = 예측 + 14 ㎝(기압 · 바람 몫)
        rows.append(tide.build(by[r["code"]], moved, [], now))
    return {"at": f"{now:%Y-%m-%d %H:%M}", "err": None, "rows": [x for x in rows if x], "spring": SPRING}


def _forecast(db: sqlite3.Connection, cache: Path, now: datetime) -> dict:
    """앞으로 올 비 — 마지막 3시간 시우량(5km 칸 최대)에 FC_CURVE 를 곱해 예측 층에 얹는다. 원래 예보보다 낮추지는 않는다."""
    gridstore.ROOT = cache / "grid"
    ks = sorted(k for k in gridstore.keys("obs60") if k.endswith("00") and k <= f"{now:%Y%m%d%H%M}")[-3:]
    rate = sum(np.nan_to_num(gridstore.load("obs60", k)) for k in ks) / len(ks)
    h, w = gridstore.shape("dfs")
    idx, flat = gridstore._dfs_index().ravel(), rate.ravel()
    ok = idx >= 0
    base = np.zeros(h * w)
    np.maximum.at(base, idx[ok], flat[ok])
    base = base.reshape(h, w)
    h0 = now.replace(minute=0, second=0, microsecond=0)
    field = {f"{h0 + timedelta(hours=i + 1):%Y%m%d%H}": base * c for i, c in enumerate(FC_CURVE)}
    n = {"vsrt": 0, "shrt": 0}
    for layer in n:
        for k in gridstore.keys(layer):
            f = field.get(k.split("_")[1][:10])
            if f is not None:
                a = gridstore.load(layer, k)
                gridstore.save(layer, k, np.where(np.isnan(a), a, np.maximum(a, f)))
                n[layer] += 1
    b = gridstore.geo()["dfs"]["bbox"]
    rows = [(float(np.nan_to_num(field[e[:10]][y - 1 - b["j0"], x - 1 - b["i0"]])), v, t, e, x, y)
            for t, e, x, y, v in db.execute("SELECT tmfc, tmef, x, y, val FROM fcst_short WHERE var='PCP'") if e[:10] in field]
    db.executemany("UPDATE fcst_short SET val=MAX(?, ?) WHERE tmfc=? AND tmef=? AND x=? AND y=? AND var='PCP'", rows)
    names = [s["name"] for s in gridstore.geo()["sigun"] if s["kind"] == "gn"]
    tmfcs = [r[0] for r in db.execute("SELECT DISTINCT tmfc FROM fcst_rn1")]
    old = {(t, e, s, m): v for t, e, s, m, v in db.execute("SELECT tmfc, tmef, sigun, emd, rn1 FROM fcst_rn1")}
    db.execute("DELETE FROM fcst_rn1")
    stamp = f"{now:%Y-%m-%d %H:%M}"
    for i in range(6):                                           # 읍면동 전부 — 예보가 비는 읍면동이 없게
        e = f"{h0 + timedelta(hours=i + 1):%Y%m%d%H}00"
        stats = gridstore.emd_stats(gridstore.to_hr(field[e[:10]]), names)
        for t in tmfcs:
            db.executemany("INSERT INTO fcst_rn1(tmfc, tmef, sigun, emd, rn1, fetched_at) VALUES(?,?,?,?,?,?)",
                           [(t, e, r["sig"], r["name"], max(round(r["max"] or 0, 1), old.get((t, e, r["sig"], r["name"]), 0)), stamp) for r in stats])
    return {**n, "fcst_short": len(rows), "peak": round(float(base.max() * max(FC_CURVE)), 1)}


def main(argv=None) -> None:
    name, rf, tf = (argv or sys.argv[1:])[:3]
    d = config.SNAPS / name
    m = json.loads((d / "meta.json").read_text("utf-8"))
    now = datetime.strptime(m["now"], "%Y%m%d%H%M") - timedelta(minutes=4)
    scene = {"river": _river(json.loads(Path(rf).read_text("utf-8")), now),
             "tide": _tide(json.loads(Path(tf).read_text("utf-8")), now),
             "road": {"at": now.isoformat(timespec="seconds"), "err": None, "rows": [{"name": n, "type": "D03", "at": t, "links": k} for n, t, k in ROAD]}}
    (d / "scene.json").write_text(json.dumps(scene, ensure_ascii=False), "utf-8")
    c = sqlite3.connect(d / "state" / "gnweather.db")
    print(_forecast(c, d / "state" / "cache", now))
    map_set = json.loads(c.execute("SELECT value FROM setting WHERE key='map'").fetchone()[0])
    map_set |= {"overlays": ["alerts", "river", "tide"], "layer": "acc"}
    c.execute("UPDATE setting SET value=? WHERE key='map'", (json.dumps(map_set, ensure_ascii=False),))
    c.commit()
    c.close()
    m["note"] = m["note"].split(" 하천 수위 · ")[0].split(" 앞으로의 초단기")[0] + " 앞으로의 초단기 · 단기 예보(격자 · 읍면동) · 하천 수위 · 홍수예보 · 댐 방류 · 조위 · 대조기 · 지하차도 경보도 지점만 실제이고 값은 시나리오(가상)."
    (d / "meta.json").write_text(json.dumps(m, ensure_ascii=False, indent=1), "utf-8")
    wl = [r for r in scene["river"]["rows"] if r["kind"] == "wl" and (r.get("stage", -1) >= 1 or r.get("fc"))]
    print([(r["name"], r["v"], r["stage"], (r.get("fc") or {}).get("lv")) for r in wl])
    print([(r["name"], r["v"], r["stage"], r["next"], r["wet"]) for r in scene["tide"]["rows"]])


if __name__ == "__main__":
    main()

"""가상 시연(scene.json)에 재난안전데이터 — 산사태 예보 · 예측 · 위험저수지 · 침수흔적 — 를 얹고, 시연 화면 설정(재생목록 · 레이어)을 넣는다.
시연 서버는 이 자료를 받지 않으므로(키 없음 · 수집 안 함) 실황 서버의 응답을 바탕으로 만든다(발표 · 훈련용, 실제 아님).

    .venv/Scripts/python.exe -X utf8 tools/scene_extra.py fake-20261019-x2 safety.json flood.json

safety.json · flood.json 은 실황 서버의 /api/safety · /api/safety/flood 응답.
- 침수흔적: 실제 과거 침수 구역 그대로(지난 일이라 시연에도 맞다) → 스냅숏 폴더 flood.json
- 위험저수지: 실제 계측기 자리 · 이름, 발령은 시나리오(RES — 비가 많은 시군 몇 곳)
- 산사태 예보(시장 · 군수) · 예측(산림청): 시나리오 — 호우경보 시군은 경보, 주의보 시군은 주의보
- 시연 DB 설정: 재생목록 '시연'(?show=시연) · 레이어 켬 — 외부에 주는 주소가 슬라이드쇼로 시작하게
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import snaps  # noqa: E402

# (시군, 종류, 발령 몇 분 전) — 산사태 예보는 시장 · 군수 발령, 예측은 산림청 분석
FCST = [("창원", "경보", 20), ("고성", "경보", 15), ("통영", "주의보", 40), ("사천", "주의보", 30), ("남해", "주의보", 55)]
PRED = [("창원", "경보", 10), ("고성", "경보", 10), ("진주", "주의보", 10), ("통영", "주의보", 10), ("사천", "주의보", 10), ("남해", "주의보", 10)]
RES = {"창원": 3, "고성": 3, "통영": 2, "진주": 2}          # 그 시군 첫 계측기를 이 단계로(2 주의 · 3 경계)
RES_LV = ["", "관심", "주의", "경계", "심각", "대피"]
SHOW = {"name": "시연", "items": [
    {"t": "acc_h", "b": "aws", "h": 6, "sec": 30}, {"t": "acc_h", "b": "grid", "h": 6, "sec": 20},
    {"t": "h1", "b": "aws", "sec": 15}, {"t": "flow", "b": "grid", "sec": 40},
    {"t": "vsrt", "n": 1, "sec": 15}, {"t": "vsrt", "n": 3, "sec": 15}, {"t": "shrt_today", "sec": 15}]}
OVERLAYS = ["alerts", "stations", "river", "slide", "reservoir", "flood", "tide", "district"]


def build(safety: dict, now: datetime) -> dict:
    f = lambda m: (now - timedelta(minutes=m)).strftime("%Y-%m-%d %H:%M")  # noqa: E731
    fcst = [{"sigun": s, "kind": k, "lv": 2 if k == "경보" else 1, "stts": "발령", "at": f(m), "on": True} for s, k, m in FCST]
    pred = [{"sigun": s, "kind": k, "lv": 2 if k == "경보" else 1, "at": f(m), "on": True} for s, k, m in PRED]
    res, done = [], set()
    for r in safety.get("res") or []:
        r = {**r, "on": False}
        if r.get("sigun") in RES and r["sigun"] not in done:
            done.add(r["sigun"])
            lv = RES[r["sigun"]]
            r.update(on=True, lv=lv, lvn=RES_LV[lv], at=f(25), cn=f"(가상) 수위계 {RES_LV[lv]} 수위 넘음 — 시연 시나리오")
        res.append(r)
    at = now.isoformat(timespec="seconds")
    return {"at": {"fcst": at, "pred": at, "res": at, "flood": at}, "err": {}, "fcst": fcst, "pred": pred, "res": res}


def main(argv=None) -> None:
    name, sf, ff = (argv or sys.argv[1:])[:3]
    d = snaps.root() / snaps.check_name(name)
    meta = json.loads((d / "meta.json").read_text("utf-8"))
    now = datetime.strptime(meta["now"], "%Y%m%d%H%M")
    scene = json.loads((d / "scene.json").read_text("utf-8"))
    scene["safety"] = build(json.loads(Path(sf).read_text("utf-8")), now)
    (d / "scene.json").write_text(json.dumps(scene, ensure_ascii=False, separators=(",", ":")), "utf-8")
    fl = json.loads(Path(ff).read_text("utf-8"))
    (d / "flood.json").write_text(json.dumps(fl, ensure_ascii=False, separators=(",", ":")), "utf-8")
    c = sqlite3.connect(d / "state" / "gnweather.db")
    m = json.loads(c.execute("SELECT value FROM setting WHERE key='map'").fetchone()[0])
    m["shows"] = [x for x in m.get("shows") or [] if x.get("name") != SHOW["name"]] + [SHOW]
    m["overlays"] = sorted(set(m.get("overlays") or []) | set(OVERLAYS))
    c.execute("UPDATE setting SET value=? WHERE key='map'", (json.dumps(m, ensure_ascii=False),))
    c.commit()
    c.close()
    meta["pin"] = True                                     # 시연 서버가 이것으로 뜬다(config._newest_snap)
    (d / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), "utf-8")
    s = scene["safety"]
    print(f"산사태 예보 {len(s['fcst'])} · 예측 {len(s['pred'])} · 저수지 {len(s['res'])}곳(발령 {sum(r['on'] for r in s['res'])}) · 침수흔적 {len(fl)} → {d}")


if __name__ == "__main__":
    main()

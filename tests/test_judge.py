"""상황판단 모드 — 판단 기록(서버 공유) · 도달 시각을 단기예보까지 · 만약에 배수."""
from fastapi.testclient import TestClient

from app import ai, main


def test_decisions_record_list_delete(tdb):
    c = TestClient(main.app)
    assert c.post("/api/ai/decisions", json={"sigun": "창원", "act": "발송"}).status_code == 400   # 모르는 결정
    r = c.post("/api/ai/decisions", json={"sigun": "창원", "emd": "진동면", "fam": "산사태", "stage": "긴급대피",
                                          "act": "보류", "pct": 62, "eta": "02"}).json()["rows"]
    assert r[0]["act"] == "보류" and r[0]["pct"] == 62 and r[0]["eta"] == "02"
    c.post("/api/ai/decisions", json={"sigun": "거제", "act": "메모", "note": "x"})
    assert len(c.get("/api/ai/decisions?sigun=창원").json()["rows"]) == 1
    c.delete(f"/api/ai/decisions/{r[0]['id']}")
    assert c.get("/api/ai/decisions?sigun=창원").json()["rows"] == []


def test_eta_runs_into_short_forecast():
    """초단기 6시간 안에 안 닿아도 단기예보(eta_hours)를 이어 '내일 01' 같은 시각을 낸다 — 산사태 긴급대피 누적 270㎜."""
    r = {"rain": {"1h": 5, "3h": 10, "24h": 245, "48h": 245}, "fc_peak": 4, "fc_run30": 0, "m15": 1, "ante": 0,
         "fc_hours": [4] * 6, "fc_labels": ["19", "20", "21", "22", "23", "00"]}
    pick = lambda r: next(x for x in ai.ladders(r, False, [])["산사태"] if x["rule"].startswith("누적"))  # noqa: E731
    assert pick(r)["gap"]["eta"]["at"] is None                     # 245 + 24 = 269
    r |= {"eta_hours": [4] * 6 + [10, 10], "eta_labels": r["fc_labels"] + ["내일 01", "내일 02"]}
    assert pick(r)["gap"]["eta"]["at"] == "내일 01"


def test_judge_pack_picks_best_per_stage_and_site_rule():
    """지구 한 줄 — 단계마다 가장 많이 찬 조건, 충족은 100 이상으로, 그 지구 대피기준 % 는 원문이 같은 sites 에서."""
    from app import judge
    e = {"rain": {"1h": 50, "3h": 90, "24h": 120}, "sites": [{"rule": "누적강우 250mm이상", "max_pct": 48}],
         "ladders": {"산사태": [{"stage": "통제", "st": "met", "rule": "a", "gap": {"pct": 92}},
                               {"stage": "통제", "st": "no", "rule": "b", "gap": {"pct": 99}},
                               {"stage": "긴급대피", "st": "no", "rule": "c", "gap": {"pct": 62, "eta": {"at": "02"}}}]}}
    p = judge.pack(e, "산사태", "누적강우 250mm이상")
    assert {k: p["st"]["통제"][k] for k in ("pct", "met", "unk", "eta", "rule")} == {"pct": 100, "met": True, "unk": False, "eta": None, "rule": "a"}
    assert p["st"]["긴급대피"]["eta_h"] is None and p["st"]["통제"]["parts"] == []
    assert p["st"]["긴급대피"]["eta"] == "02" and "사전대피" not in p["st"]
    assert p["site"] == 48 and p["top"] == 100


def test_slide_rule_sites_follow_landslide_forecast():
    """'산사태 경보 발령 시' 지구는 강수가 아니라 발령으로 — 경보면 100, 주의보뿐이면 0. '예보 발령 시'는 주의보도."""
    from app import judge
    warn, watch, none = {"fcst": {"lv": 2}, "pred": None}, {"fcst": None, "pred": {"lv": 1}}, {"fcst": None, "pred": None}
    assert judge.slide_site("산사태 경보 발령 시", warn) == 100 and judge.slide_site("산사태 경보 발령 시", watch) == 0
    assert judge.slide_site("산사태예보 발령 시", watch) == 100 and judge.slide_site("산사태예보 발령 시", none) == 0
    assert judge.slide_site("누적강우 250mm이상", warn) is None


def test_district_point_rain_redoes_ladder_and_site_rule():
    """지구 좌표가 있으면 그 자리 비로 사다리 · 지구 대피기준을 다시 — 읍면동 최대 칸(270)보다 지구 자리(120)가 적으면 % 도 낮다."""
    from app import judge
    e = {"emd": "북면", "rain": {"1h": 40, "3h": 90, "12h": 200, "24h": 270, "48h": 270}, "m15": 10, "fc_peak": 4, "fc_run30": 0,
         "ante": 0, "fc_hours": [4] * 6, "fc_labels": [str(h) for h in range(6)], "sites": [], "ladders": {}}
    s = {"night": False, "alerts": [], "river": None, "flood": None}
    assert judge.at_point(e, None, s, "산사태", "") is e                     # 좌표 없으면 읍면동 그대로
    p = judge.at_point(e, {"1h": 10, "3h": 30, "24h": 120, "48h": 120, "15m": 2}, s, "산사태", "누적강우 250mm이상")
    assert p["rain"]["24h"] == 120 and p["rain"]["12h"] == 200 and p["m15"] == 2   # 없는 창은 읍면동 값
    assert p["sites"][0]["max_pct"] == 48 and set(p["ladders"]) == {"산사태"}
    full = judge.pack({**e, "ladders": ai.ladders(e, False, [])}, "산사태", "")
    assert judge.pack(p, "산사태", "누적강우 250mm이상")["top"] < full["top"]


def test_point_max_looks_at_neighbours():
    import numpy as np
    from app import gridview
    a = np.zeros((5, 5)); a[1, 1] = 9; a[4, 4] = np.nan
    assert gridview._pt_max(a, [("x", 2, 2), ("y", 4, 4)]) == {"x": 9.0, "y": 0.0}
    assert gridview._pt_max(np.full((3, 3), np.nan), [("z", 1, 1)]) == {}

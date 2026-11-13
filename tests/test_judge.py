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
    """초단기 6시간 안에 안 닿아도 단기예보(eta_hours)를 이어 '내일 01' 같은 시각을 낸다 — 산사태 긴급대피 24시간 210㎜."""
    r = {"rain": {"1h": 5, "3h": 10, "12h": 100, "24h": 185, "48h": 245}, "fc_peak": 4, "fc_run30": 0, "m15": 1, "ante": 0,
         "fc_hours": [4] * 6, "fc_labels": ["19", "20", "21", "22", "23", "00"]}
    pick = lambda r: next(x for x in ai.ladders(r, False, [])["산사태"] if x["rule"].startswith("24시간 210"))  # noqa: E731
    acc = lambda r: pick(r)["gap"]["parts"][0]["eta"]  # noqa: E731
    assert acc(r)["at"] is None                                    # 185 + 24 = 209
    r |= {"eta_hours": [4] * 6 + [10, 10], "eta_labels": r["fc_labels"] + ["내일 01", "내일 02"]}
    assert acc(r)["at"] == "내일 01"


def test_site_rule_becomes_the_urgent_stage():
    """시군 지구 기준이 지침 긴급대피보다 더 찼으면 그 지구의 긴급대피로 — 덜 찼으면 지침 줄 그대로."""
    from app import judge
    v = {"site": 104, "site_parts": [{"label": "3시간"}], "st": {"긴급대피": {"pct": 40, "met": False, "rule": "12시간 150㎜↑(실황)"}}}
    judge.site_urgent(v, "3시간 90mm이상")
    u = v["st"]["긴급대피"]
    assert u["met"] and u["pct"] == 104 and u["rule"] == "시군 지구 기준 — 3시간 90mm이상" and u["by_site"]
    w = {"site": 30, "st": {"긴급대피": {"pct": 40, "met": False, "rule": "r"}}}
    judge.site_urgent(w, "x")
    assert w["st"]["긴급대피"]["rule"] == "r"
    n = {"site": None, "st": {}}
    judge.site_urgent(n, "x")
    assert n["st"] == {}


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
    p = judge.at_point(e, {"1h": 10, "12h": 100, "24h": 120, "48h": 120, "15m": 2}, s, "산사태", "누적강우 250mm이상")
    assert p["rain"]["24h"] == 120 and p["rain"]["3h"] == 90 and p["m15"] == 2     # 없는 창은 읍면동 값
    assert p["sites"][0]["max_pct"] == 48 and set(p["ladders"]) == {"산사태"}
    full = judge.pack({**e, "ladders": ai.ladders(e, False, [])}, "산사태", "")
    acc = lambda x: next(q["now"] for q in x["st"]["긴급대피"]["parts"] if q["label"] == "12시간")  # noqa: E731
    assert acc(judge.pack(p, "산사태", "누적강우 250mm이상")) == 100 and acc(full) == 200


def test_point_max_looks_at_neighbours():
    import numpy as np
    from app import gridview
    a = np.zeros((5, 5)); a[1, 1] = 9; a[4, 4] = np.nan
    assert gridview._pt_max(a, [("x", 2, 2), ("y", 4, 4)]) == {"x": 9.0, "y": 0.0}
    assert gridview._pt_max(np.full((3, 3), np.nan), [("z", 1, 1)]) == {}


def test_series_adds_forecast_hour_by_hour():
    """앞으로 시간별 % — 누적은 예보를 더해 오르고, 1시간 조건은 그 시각 예보 시우량으로."""
    from app import judge
    e = {"emd": "북면", "rain": {"1h": 10, "3h": 20, "12h": 60, "24h": 80, "48h": 80}, "m15": 2, "fc_peak": 20, "fc_run30": 0, "ante": 0,
         "fc_hours": [20, 20, 20], "fc_labels": ["19", "20", "21"], "sites": [], "ladders": {}}
    s = {"night": False, "alerts": [], "river": None, "flood": None}
    sr = judge.series_of(e, s, "산사태", "누적강우 250mm이상")
    assert sr["t"] == ["19", "20"] and len(sr["v"]) == 2            # 예보 끝 시각은 뺀다(뒤 예보가 없어 % 가 튄다)
    assert sr["v"][0] <= sr["v"][1]                                 # 비가 계속 오면 % 는 내려가지 않는다
    assert judge.series_of({**e, "fc_hours": []}, s, "산사태", "") is None


def test_plane_splits_accumulated_and_hourly():
    from app import judge
    lad = [{"stage": "긴급대피", "rule": "r", "gap": {"parts": [{"label": "1시간", "pct": 111}, {"label": "24시간", "pct": 60}]}},
           {"stage": "통제", "rule": "w", "gap": {"parts": [{"label": "수위", "pct": 126}]}},
           {"stage": "사전대피", "rule": "u", "gap": {"parts": [{"label": "예보 시우량", "pct": None}]}}]
    assert judge.plane(lad, "긴급대피", "r") == ([60, 111], ["24시간", "1시간"])        # 가로 누적 · 세로 시간당
    assert judge.plane(lad, "통제", "w")[0] == [126, 126]                                 # 조건 하나면 대각선
    assert judge.plane(lad, "사전대피", "u") is None and judge.plane(lad, "통제", "x") is None


def test_regions_and_site_area():
    r = ai.regions()
    assert set(r) == {"산사태", "하천", "지하공간"} and r["지하공간"]["x"] == "15분"
    kinds = [(a["stage"], a["kind"]) for a in r["산사태"]["areas"]]
    assert ("긴급대피", "vband") in kinds and ("사전대피", "band") in kinds and r["산사태"]["x"] == "24시간"   # 별표 4 — 누적만으로, 예보만으로
    assert any("발령" in t["text"] for t in r["하천"]["texts"])                         # 비가 아닌 조건은 글로
    a = ai.site_area("누적강우 250mm이상, 일강우 200mm이상")
    assert [(x["kind"], x["x"]) for x in a] == [("vband", 250), ("vband", 200)]         # 쉼표 = 또는
    a = ai.site_area("누적강우 250mm 이상 관측 시간당 50mm 이상 예상")
    assert [x["kind"] for x in a] == ["vband", "band"]                                    # 적힌 게 없으면 또는
    a = ai.site_area("누적강우 250mm 이상 & 시간당 50mm 이상")
    assert len(a) == 1 and a[0]["kind"] == "rect" and (a[0]["x"], a[0]["y"]) == (250, 50)   # & = 그리고
    a = ai.site_area("누적강우 200mm 이상 또는 시간당 50mm 이상")
    assert [x["kind"] for x in a] == ["vband", "band"]                                    # 또는 = 의자 모양
    assert ai.site_area("") == []


def test_soil_site_only_obvious():
    """토양함수율 90% — 산림청 경보면 충족, 주의보면 확인 필요, 발령 없음이면 미충족(80% 미만), 못 받았으면 모름. 75% 는 주의보면 충족."""
    from app import judge
    r90, r75 = "누적 250mm ※ 토양함수율 90% 이상 적용", "산사태정보시스템토양함수지수실황및1시간예측75%이상유지될경우"
    assert [judge.soil_site(r90, lv)["st"] for lv in (2, 1, 0, None)] == ["met", "check", "no", "unknown"]
    assert judge.soil_site(r75, 0)["need"] == 75 and [judge.soil_site(r75, lv)["st"] for lv in (1, 0)] == ["met", "check"]
    assert judge.soil_site("토양함수량 100% 도달 시", 1)["st"] == "check" and judge.soil_site("누적 250mm", 2) is None


def test_pack_splits_forecast_and_observed():
    lad = {"산사태": [{"stage": "통제", "rule": "24시간 90㎜↑(실황)", "st": "near", "gap": {"pct": 75}, "basis": "obs"},
                    {"stage": "사전대피", "rule": "시간당 50㎜↑ 예보", "st": "met", "gap": {"pct": 110}, "basis": "fc"},
                    {"stage": "긴급대피", "rule": "산림청 산사태 예측정보 경보(시군)", "st": "unknown", "basis": "fc"}]}
    from app import judge
    p = judge.pack({"ladders": lad, "rain": {}, "sites": []}, "산사태", "")
    assert (p["fc"]["pct"], p["fc"]["stage"], p["fc"]["met"]) == (110, "사전대피", True)
    assert (p["obs"]["pct"], p["obs"]["stage"], p["obs"]["met"]) == (75, "통제", False)

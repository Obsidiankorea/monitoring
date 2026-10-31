from app import ai, aireport


def _gap_c(stage, st, pct):
    return {"stage": stage, "st": st, "rule": "r", "gap": {"pct": pct, "left": 20, "unit": "㎜", "by": "일/누적", "partial": False, "eta": None, "parts": []}}


def _sit(alerts, ladders, relay=False):
    return {"sigun": "함양", "tm": "202610310004", "alerts": alerts,
            "emd": [{"emd": "서하면", "relay": relay, "cbs": False, "ladders": {"산사태": ladders}}]}


def test_flash_sigun_names_level_reason_and_strongest_rule():
    f = aireport._flash_sigun(_sit(["호우주의보"], [_gap_c("통제", "near", 80), _gap_c("사전대피", "near", 75)]), "함양군")
    assert f["lv"] == 3
    assert "함양군 레벨 3 통제" in f["text"] and "근거: 사전대피 기준 근접" in f["text"]
    assert "서하면 산사태 사전대피 — 기준 75%" in f["text"]       # 단계가 센 규칙이 '가장 센 기준'


def test_flash_sigun_calm():
    f = aireport._flash_sigun(_sit([], [{"stage": "통제", "st": "no", "rule": "r"}]), "함양군")
    assert f["lv"] == 1 and "평상" in f["text"] and "근거" not in f["text"]


def test_flash_all_uses_situations_for_scanned_and_alerts_for_rest():
    rows = [{"sigun": "함양", "alerts": [], "relay": False, "cbs": False},
            {"sigun": "창원", "alerts": ["호우주의보"], "relay": False, "cbs": False}]
    f = aireport._flash_all({"tm": "202610310004"}, rows, [_sit([], [_gap_c("긴급대피", "met", 110)])])
    assert f["lv"] == 5 and "함양" in f["text"] and "레벨 2 이상 2개 시군" in f["text"]
    calm = aireport._flash_all({"tm": "202610310004"}, [{"sigun": "함양", "alerts": [], "relay": False, "cbs": False}], [])
    assert calm["lv"] == 1 and "평상" in calm["text"]

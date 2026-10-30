from app import ai


def _row(**kw):
    r = {"rain": {"1h": 5, "3h": 12, "24h": 78, "48h": 80}, "fc_peak": 25, "fc_run30": 0, "m15": 2, "ante": 10,
         "fc_hours": [10, 12, 15, 5, 0, 0], "fc_labels": ["14", "15", "16", "17", "18", "19"]}
    r.update(kw)
    return r


def _rule(lad, fam, stage, start):
    return next(c for c in lad[fam] if c["stage"] == stage and c["rule"].startswith(start))


def test_eta_first_hour_that_reaches_the_need():
    assert ai._eta(80, 100, [10, 12, 15], ["14", "15", "16"]) == {"at": "15", "i": 1}


def test_eta_none_when_already_met_or_no_forecast():
    assert ai._eta(100, 100, [10], ["14"]) is None
    assert ai._eta(None, 100, [10], ["14"]) is None
    assert ai._eta(80, 100, [], []) is None


def test_eta_not_reached_within_forecast_hours():
    assert ai._eta(10, 100, [5, 5], ["14", "15"]) == {"at": None, "i": None}


def test_gap_binding_is_the_farthest_condition():
    g = ai._gap(ai._part("일/누적", 80, 100), ai._part("예보 시우량", 5, 20, "㎜/h"))
    assert (g["pct"], g["left"], g["unit"], g["by"]) == (25, 15, "㎜/h", "예보 시우량")
    assert g["partial"] is False and g["eta"] is None        # 시우량은 안 쌓이는 값 — 닿는 시각을 말하지 않는다


def test_gap_partial_when_a_condition_is_unknown():
    g = ai._gap(ai._part("선행 5일", 60, 120), ai._part("산림청 예보", None, 1))
    assert g["pct"] == 50 and g["partial"] is True and g["eta"] is None
    assert ai._gap(ai._part("산림청 예보", None, 1)) is None


def test_ladder_landslide_control_gap_and_eta():
    c = _rule(ai.ladders(_row(), False, []), "산사태", "통제", "일/누적 100")
    assert c["st"] == "near"
    g = c["gap"]
    assert (g["pct"], g["left"], g["by"]) == (80, 20, "일/누적")
    assert g["eta"] == {"at": "15", "i": 1}                   # 80 + 10 + 12 = 102 ≥ 100
    assert ai.gap_text(c) == "기준 80% · 남은 20㎜(일/누적) · 예보대로면 15시경 닿음"


def test_ladder_gap_without_forecast_has_no_eta():
    c = _rule(ai.ladders(_row(fc_hours=[], fc_labels=[]), False, []), "산사태", "통제", "일/누적 100")
    assert c["gap"]["eta"] is None and "예보대로면" not in ai.gap_text(c)


def test_ladder_capped_forecast_makes_50mm_condition_unknown():
    row = _row(fc_peak=30, rain={"1h": 5, "3h": 12, "24h": 210, "48h": 210})
    c = _rule(ai.ladders(row, False, []), "산사태", "사전대피", "일/누적 200")
    assert c["st"] == "unknown" and c["gap"]["partial"] is True
    assert "일부 조건은 모름" in ai.gap_text(c)


def test_ladder_actual_rain_rule_mixes_hourly_and_cumulative():
    c = _rule(ai.ladders(_row(), False, []), "산사태", "긴급대피", "50㎜/h")
    g = c["gap"]
    assert (g["pct"], g["by"], g["unit"]) == (10, "1시간", "㎜/h")
    assert g["eta"] is None                                    # 1시간 실황은 예보로 닿는 시각을 못 말한다


def test_ladder_rules_without_numbers_have_no_gap():
    lad = ai.ladders(_row(), False, ["호우경보"])
    assert "gap" not in _rule(lad, "하천", "긴급대피", "호우경보")
    assert ai.gap_text(_rule(lad, "하천", "긴급대피", "호우경보")) == ""


def test_night_rule_gap_only_at_night():
    assert _rule(ai.ladders(_row(), False, []), "산사태", "사전대피", "취약시간대")["gap"] is None
    assert _rule(ai.ladders(_row(), True, []), "산사태", "사전대피", "취약시간대")["gap"]["pct"] == 83

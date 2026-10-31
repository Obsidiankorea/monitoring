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


def _c(stage, st):
    return {"stage": stage, "st": st}


def test_rain_state_uses_wiki_stage_names_strongest_first():
    assert ai.rain_state([_c("통제", "no"), _c("긴급대피", "unknown")]) == (0, "")
    assert ai.rain_state([_c("통제", "near")]) == (1, "통제 근접")
    assert ai.rain_state([_c("통제", "met")]) == (2, "통제 충족")
    tone, txt = ai.rain_state([_c("통제", "near"), _c("사전대피", "met"), _c("통제", "met"), _c("긴급대피", "near")])
    assert tone == 3 and txt == "사전대피 충족 · 통제 충족 · 긴급대피 근접"


# ── 시군 자체 비상단계 (거제 · 통영 매뉴얼) ──
def test_sigun_stage_geoje_follows_alert_kind():
    f = lambda al, pd=(): ai.sigun_stage("거제", list(al), list(pd))["stage"]   # noqa: E731
    assert f([]) == "평시"
    assert f([], ["호우"]) == "준비(관심)" and f(["강풍주의보"]) == "준비(관심)"
    assert f(["호우주의보"]) == "비상 1단계" and f([], ["태풍"]) == "비상 1단계"
    assert f(["호우경보"]) == "비상 2단계" and f(["호우주의보", "호우경보"]) == "비상 2단계"
    assert f(["태풍경보"]) == "비상 3단계"


def test_sigun_stage_tongyeong_and_missing_manual():
    t = ai.sigun_stage("통영", ["호우주의보"], [])
    assert t["stage"] == "비상 1단계" and t["draft"] is True and t["why"] == "호우주의보"
    assert ai.sigun_stage("통영", ["호우경보"], [])["stage"] == "비상 2·3단계"
    assert ai.sigun_stage("통영", [], [])["stage"] == "평시 및 초기대응"
    assert ai.sigun_stage("함양", ["호우경보"], []) is None          # 매뉴얼이 위키에 없으면 만들어 내지 않는다


def test_stage_text_marks_draft_and_independence_from_do():
    assert "도 단계와 별개" in ai.stage_text("거제", ai.sigun_stage("거제", ["호우주의보"], []))
    assert "참고본" in ai.stage_text("통영", ai.sigun_stage("통영", [], []))
    assert "참고본" not in ai.stage_text("거제", ai.sigun_stage("거제", [], []))


def test_sigun_stages_from_alert_snapshot():
    data = {"groups": [{"name": "호우주의보", "siguns": ["거제", "통영"], "sea": False},
                       {"name": "풍랑주의보", "siguns": ["거제"], "sea": True}],
            "pending": [{"name": "태풍", "sigun": "통영"}]}
    r = ai.sigun_stages(data)
    assert r["sigun"]["거제"]["stage"] == "비상 1단계" and r["sigun"]["통영"]["stage"] == "비상 1단계"
    assert r["do"]["stage"] == "초기대응"                              # 호우주의보 2개 시군 — 도 기준은 별개


def test_sigun_stage_human_override_keeps_the_alert_basis():
    d = ai.sigun_stage("거제", ["호우주의보"], [], {"stage": "비상 2단계", "at": "202610311200"})
    assert d["stage"] == "비상 2단계" and d["auto"] == "비상 1단계" and d["set"] is True and d["set_at"] == "202610311200"
    assert "수동 입력" in ai.stage_text("거제", d) and "특보 기준 비상 1단계" in ai.stage_text("거제", d)
    assert d["do"].startswith("풍수해재난팀 6명")                      # 지금 단계(비상 2단계)의 근무 편성
    bad = ai.sigun_stage("거제", ["호우주의보"], [], {"stage": "비상 9단계", "at": "202610311200"})
    assert bad["stage"] == "비상 1단계" and bad["set"] is False       # 매뉴얼에 없는 단계는 무시


def test_sigun_stage_fixed_by_alert_when_no_override():
    assert ai.sigun_stage("거제", ["태풍경보"], [])["stage"] == "비상 3단계"     # 태풍경보는 비상 3단계로 고정
    d = ai.sigun_stage("통영", ["호우경보"], [])
    assert d["order"] == ["평시 및 초기대응", "비상 1단계", "비상 2·3단계"] and d["set"] is False


def test_override_set_validates_names_and_expires(monkeypatch):
    store = {}
    import app.db as db
    monkeypatch.setattr(db, "get_setting", lambda k, d: store.get(k, d))
    monkeypatch.setattr(db, "put_setting", lambda k, v: store.__setitem__(k, v))
    ai.set_override("거제", "비상 2단계")
    assert ai.overrides()["거제"]["stage"] == "비상 2단계"
    import pytest
    with pytest.raises(ValueError):
        ai.set_override("함양", "비상 1단계")                           # 매뉴얼이 없는 시군
    with pytest.raises(ValueError):
        ai.set_override("통영", "비상 3단계")                           # 통영 매뉴얼에는 '비상 2·3단계'뿐
    ai.set_override("거제", None)
    assert ai.overrides() == {}
    store["sigun_stage_over"] = {"거제": {"stage": "비상 3단계", "at": "202001010000"}}   # 24시간이 훨씬 지난 값
    assert ai.overrides() == {}

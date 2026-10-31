from app import ai, aireport


def _gap_c(stage, st, pct):
    return {"stage": stage, "st": st, "rule": "r", "gap": {"pct": pct, "left": 20, "unit": "㎜", "by": "일/누적", "partial": False, "eta": None, "parts": []}}


def _sit(alerts, ladders, sigun="함양", pending=()):
    return {"sigun": sigun, "tm": "202610310004", "alerts": alerts, "pending": list(pending),
            "emd": [{"emd": "서하면", "relay": False, "cbs": False, "ladders": {"산사태": ladders}}]}


def test_flash_sigun_names_rain_state_and_strongest_rule(monkeypatch):
    monkeypatch.setattr(ai, "overrides", lambda: {})
    f = aireport._flash_sigun(_sit(["호우주의보"], [_gap_c("통제", "near", 80), _gap_c("사전대피", "near", 75)]), "함양군")
    assert f["tone"] == 1
    assert "함양군 · 우려지역 기준: 사전대피 근접 · 통제 근접" in f["text"]
    assert "서하면 산사태 사전대피 — 기준 75%" in f["text"]       # 단계가 센 규칙이 '가장 센 기준'
    assert "비상단계" not in f["text"]                            # 함양 매뉴얼은 위키에 없다 — 단계를 만들지 않는다


def test_flash_sigun_calm(monkeypatch):
    monkeypatch.setattr(ai, "overrides", lambda: {})
    f = aireport._flash_sigun(_sit([], [{"stage": "통제", "st": "no", "rule": "r"}]), "함양군")
    assert f["tone"] == 0 and "닿은 곳 없음" in f["text"]


def test_flash_sigun_shows_manual_stage_and_human_override(monkeypatch):
    monkeypatch.setattr(ai, "overrides", lambda: {})
    f = aireport._flash_sigun(_sit(["호우주의보"], [], "거제"), "거제시")
    assert "거제시 비상단계 비상 1단계 · 우려지역 기준: 닿은 곳 없음" in f["text"]
    monkeypatch.setattr(ai, "overrides", lambda: {"거제": {"stage": "비상 2단계", "at": "202610310100"}})
    t = aireport._flash_sigun(_sit(["호우주의보"], [], "거제"), "거제시")["text"]
    assert "비상단계 비상 2단계(수동 입력 · 특보 기준 비상 1단계)" in t


def test_flash_all_lists_do_stage_own_stages_and_rain_hits():
    own = {"거제": ai.sigun_stage("거제", ["호우경보"], []), "통영": ai.sigun_stage("통영", [], [])}
    o = {"tm": "202610310004", "stage": {"stage": "초기대응", "why": "호우주의보 2개 시군"}}
    f = aireport._flash_all(o, [_sit([], [_gap_c("통제", "met", 110)])], own)
    assert f["tone"] == 2
    assert "도 비상단계 초기대응(호우주의보 2개 시군)" in f["text"]
    assert "시군 비상단계 거제시 비상 2단계" in f["text"] and "통영" not in f["text"]      # 평시인 시군은 적지 않는다
    assert "우려지역 기준: 함양 통제 충족" in f["text"]


def test_flash_all_calm():
    own = {"거제": ai.sigun_stage("거제", [], []), "통영": ai.sigun_stage("통영", [], [])}
    f = aireport._flash_all({"tm": "202610310004", "stage": None}, [_sit([], [])], own)
    assert f["tone"] == 0 and "경남 전체 평시" in f["text"]

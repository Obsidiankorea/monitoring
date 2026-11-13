from app import aiwatch


def test_diff_alerts_only_new_or_escalated():
    """같은 상태는 다시 보내지 않고, 새로 생기거나 근접→충족으로 오르면 보낸다. 안 보인 지 오래된 것은 상태에서 지운다."""
    now = {"a": ("near", ("창원", "진동면", "산사태", "긴급대피", "r")), "b": ("met", ("창원", "진동면", "하천", "긴급대피", "r2"))}
    new, st = aiwatch._diff(now, {}, 1000.0)
    assert len(new) == 2
    new, st = aiwatch._diff(now, st, 1300.0)
    assert new == []
    now["a"] = ("met", ("창원", "진동면", "산사태", "긴급대피", "r"))
    new, st = aiwatch._diff(now, st, 1600.0)
    assert len(new) == 1 and new[0][0] == "met"
    new, st = aiwatch._diff({}, st, 1600.0 + aiwatch.KEEP_S + 1)      # 한 시간 넘게 안 보이면 지운다
    assert st == {}


def test_mask_hides_token(monkeypatch):
    monkeypatch.setitem(aiwatch.config.KEYS, "TELEGRAM_BOT_TOKEN", "123:SECRET")
    assert "SECRET" not in aiwatch._mask("POST https://api.telegram.org/bot123:SECRET/sendMessage 404")


def test_msg_groups_by_emd():
    new = [("met", ("창원", "진동면", "산사태", "긴급대피", "a")), ("near", ("창원", "진동면", "하천", "사전대피", "b")),
           ("met", ("고성", "동해면", "산사태", "사전대피", "c")), ("met", ("도", "비상 2단계", "비상단계", "", "호우경보 11개 시군"))]
    m = aiwatch._msg(new, "10.19 00:10")
    assert "2곳" in m and "비상 2단계 진입" in m and m.count("창원 진동면") == 1 and "산사태 🚨 긴급대피 충족" in m and "산사태 🚶 충족" in m   # 처음만 이름, 다음부터 그림글자


def test_snapshot_items_carry_the_gap_text(monkeypatch):
    """화면 목록에는 '기준 N% · 남은 ㎜ · 닿는 시각' 글이 같이 간다(알림 문자는 그대로)."""
    gap = {"pct": 80, "left": 20, "unit": "㎜", "by": "일/누적", "partial": False, "eta": {"at": "15", "i": 1}, "parts": []}
    lad = {"산사태": [{"stage": "사전대피", "rule": "r", "st": "near", "gap": gap},
                    {"stage": "긴급대피", "rule": "호우경보 발령", "st": "met"}]}
    monkeypatch.setattr(aiwatch.aireport, "overview", lambda base: {
        "stage": None, "groups": [{"name": "호우주의보", "siguns": ["거제"], "sea": False}], "pending": [],
        "rows": [{"sigun": "함양", "relay": True, "cbs": False, "alerts": [], "fc_sum": 0, "fc_peak": 0}]})
    monkeypatch.setattr(aiwatch.aireport, "situation", lambda sg, base: {
        "alerts": [], "emd": [{"emd": "서하면", "ladders": lad, "relay": False, "cbs": False}]})
    monkeypatch.setitem(aiwatch._SNAP, "v", None)
    items = aiwatch.snapshot("http://x")["items"]
    by = {i["rule"]: i for i in items}
    assert by["r"]["gap"] == "기준 80% · 남은 20㎜(일/누적) · 예보대로면 15시경 닿음"
    assert by["호우경보 발령"]["gap"] == ""
    assert by["r"]["pct"] == 80 and by["호우경보 발령"]["pct"] is None
    snap = aiwatch.snapshot("http://x")
    assert snap["stages"]["거제"]["stage"] == "비상 1단계" and snap["stages"]["통영"]["stage"] == "평시"
    assert snap["stages"]["함양"]["std"] is True                          # 시군 매뉴얼이 위키에 없는 시군 — 거제 기준 준용


def test_diff_holds_the_30_minute_peak():
    """충족 → 근접 → 충족을 30분 안에 오르내리면 다시 알리지 않는다. 30분 넘게 내려가 있다가 오르면 알린다."""
    x = ("창원", "진동면", "산사태", "사전대피", "r")
    new, st = aiwatch._diff({"k": ("met", x)}, {}, 0.0)
    assert len(new) == 1
    new, st = aiwatch._diff({"k": ("near", x)}, st, 600.0)
    assert not new and st["k"] == ["met", 0.0]                     # 높았던 상태를 붙든다
    new, st = aiwatch._diff({"k": ("met", x)}, st, 1200.0)
    assert not new
    new, st = aiwatch._diff({"k": ("near", x)}, st, 1200.0 + aiwatch.HOLD_S + 1)
    assert not new and st["k"][0] == "near"
    new, st = aiwatch._diff({"k": ("met", x)}, st, 1200.0 + aiwatch.HOLD_S + 600)
    assert len(new) == 1


def test_event_opens_logs_and_closes(tdb):
    from datetime import datetime, timedelta
    from app import events
    t0 = datetime(2026, 7, 1, 10, 0)
    g = [{"name": "호우주의보", "sea": False}, {"name": "풍랑주의보", "sea": True}]
    assert events.record(t0, [], False, []) is None                # 아무 일 없으면 열지 않는다
    eid = events.record(t0, g, True, [("near", ("함양", "안의면", "산사태", "사전대피", "r")), ("met", ("도", "비상 1단계", "비상단계", "", "w"))], {0: 80})
    with tdb.tx() as con:
        con.execute("INSERT INTO decision(at, sigun, act) VALUES(?,?,?)", ((t0 + timedelta(minutes=30)).isoformat(timespec="seconds"), "함양", "사전대피 권고"))
    assert events.record(t0 + timedelta(hours=1), [{"name": "호우경보", "sea": False}], False, []) == eid
    assert events.record(t0 + timedelta(hours=3), [], False, []) == eid          # 조용해도 6시간은 열어 둔다
    assert events.record(t0 + timedelta(hours=8), [], False, []) is None
    ev = events.listing()[0]
    assert ev["alerts"] == ["호우경보", "호우주의보"] and ev["log"] == 1 and ev["decisions"] == 1 and ev["siguns"] == ["함양"]
    assert ev["end"] == (t0 + timedelta(hours=1)).isoformat(timespec="seconds")
    d = events.detail(eid)
    assert [r["kind"] for r in d["rows"]] == ["stage", "decision"] and d["rows"][0]["pct"] == 80
    assert events.detail(999) is None

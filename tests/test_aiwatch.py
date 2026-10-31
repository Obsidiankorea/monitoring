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
    assert "2곳" in m and "비상 2단계 진입" in m and m.count("창원 진동면") == 1 and "산사태 긴급대피 충족" in m


def test_snapshot_items_carry_the_gap_text(monkeypatch):
    """화면 목록에는 '기준 N% · 남은 ㎜ · 닿는 시각' 글이 같이 간다(알림 문자는 그대로)."""
    gap = {"pct": 80, "left": 20, "unit": "㎜", "by": "일/누적", "partial": False, "eta": {"at": "15", "i": 1}, "parts": []}
    lad = {"산사태": [{"stage": "사전대피", "rule": "r", "st": "near", "gap": gap},
                    {"stage": "긴급대피", "rule": "호우경보 발령", "st": "met"}]}
    monkeypatch.setattr(aiwatch.aireport, "overview", lambda base: {
        "stage": None, "rows": [{"sigun": "함양", "relay": True, "cbs": False, "alerts": [], "fc_sum": 0, "fc_peak": 0}]})
    monkeypatch.setattr(aiwatch.aireport, "situation", lambda sg, base: {
        "alerts": [], "emd": [{"emd": "서하면", "ladders": lad, "relay": False, "cbs": False}]})
    monkeypatch.setitem(aiwatch._SNAP, "v", None)
    items = aiwatch.snapshot("http://x")["items"]
    by = {i["rule"]: i for i in items}
    assert by["r"]["gap"] == "기준 80% · 남은 20㎜(일/누적) · 예보대로면 15시경 닿음"
    assert by["호우경보 발령"]["gap"] == ""
    assert by["r"]["pct"] == 80 and by["호우경보 발령"]["pct"] is None
    snap = aiwatch.snapshot("http://x")
    assert snap["levels"]["함양"]["lv"] == 5 and "긴급대피" in snap["levels"]["함양"]["act"]

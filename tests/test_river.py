from app import river


def test_dms_and_sigun():
    assert round(river._dms("128-33-04"), 4) == 128.5511
    assert river._dms("x") is None
    assert river._sigun("경상남도 합천군 야로면", "") == "합천"
    assert river._sigun("경상남도 거제시", "") == "거제"
    assert river._sigun("", "창녕·함안보") == "창녕" and river._sigun("경상북도 안동시", "안동댐") is None


def test_stage_walks_the_four_levels_and_names_the_next():
    thr = [3.0, 4.0, 5.0, 6.0]
    assert river.stage(2.0, thr) == (0, 3.0)
    assert river.stage(3.0, thr) == (1, 4.0)
    assert river.stage(5.2, thr) == (3, 6.0)
    assert river.stage(7.0, thr) == (4, None)
    assert river.stage(2.0, [None, None, None, None]) == (-1, None)      # 제원 수위가 없으면 단계를 내지 않는다
    assert river.stage(None, thr) == (-1, None)
    assert river.stage(1.0, [0.0, 0.0, 0.0, 0.0]) == (-1, None)          # 0 은 비어 있다는 뜻


def test_pick_keeps_gyeongnam_and_nakdong_upstream_only():
    row = lambda code, nm, ad, **k: {"obsnm": nm, "addr": ad, "lon": "128-00-00", "lat": "35-30-00", **k}   # noqa: E731
    infos = {"waterlevel": [row("", "적포교", "경상남도 합천군", wlobscd="2017620", attwl="8", wrnwl="9", almwl="10", srswl="11"),
                            row("", "한강", "서울특별시", wlobscd="1018683")],
             "dam": [row("", "합천댐", "경상남도 합천군", dmobscd="2015110"), row("", "안동댐", "경상북도 안동시", dmobscd="2001110"),
                     row("", "대곡댐", "울산광역시", dmobscd="2201231"), row("", "충주댐", "충청북도", dmobscd="1003110")],
             "bo": [row("", "달성보", "경상북도 고령군", boobscd="2014801"), row("", "낙동강하굿둑", "부산", boobscd="2022510")]}
    got = {(s["name"], s["up"]) for s in river.pick(infos)}
    assert got == {("적포교", False), ("합천댐", False), ("안동댐", True), ("달성보", True)}


def test_row_stage_gap_and_one_hour_change():
    river._HIST.clear()
    s = {"id": "1", "kind": "wl", "name": "x", "agency": "", "addr": "", "sigun": "합천", "up": False, "x": 1, "y": 1, "pfh": None, "lim": None,
         "thr": [3.0, 4.0, 5.0, 6.0]}
    river._push("1", "202610311500", 2.0)
    river._push("1", "202610311600", 3.5)
    o = river._row(s, {"ymdhm": "202610311600", "wl": "3.5", "fw": "10"})
    assert o["stage"] == 1 and o["next"] == 4.0 and o["gap"] == 0.5 and o["d1h"] == 1.5
    assert river._row(s, None)["stage"] == -1


def test_dam_release_rise_is_flagged_only_when_it_really_grows():
    river._HIST.clear()
    s = {"id": "d", "kind": "dam", "name": "d", "agency": "", "addr": "", "sigun": "합천", "up": False, "x": 1, "y": 1, "pfh": None, "lim": 100.0, "thr": None}
    river._push("d", "202610311500", 5.0)
    assert river._row(s, {"ymdhm": "202610311600", "swl": "90", "inf": "30", "tototf": "50"})["rise"] is True
    river._HIST.clear()
    river._push("d", "202610311500", 50.0)
    assert river._row(s, {"ymdhm": "202610311600", "swl": "90", "inf": "30", "tototf": "52"})["rise"] is False


def _wl(id_, name, stage, v, thr=(3.0, 4.0, 5.0, 6.0), **k):
    return {"id": id_, "kind": "wl", "name": name, "up": False, "sigun": "합천", "stage": stage, "v": v, "thr": list(thr),
            "gap": k.get("gap"), "d1h": k.get("d1h"), "t": "202610311600", **{x: y for x, y in k.items() if x not in ("gap", "d1h")}}


def test_alerts_fire_once_per_new_level_and_reset_below_attention():
    rows = [_wl("a", "적포교", 2, 4.1), {"id": "d", "kind": "dam", "name": "합천댐", "up": False, "rise": True, "out": 180.0, "d1h": 120.0}]
    new, st = river._diff_alerts(rows, {})
    assert len(new) == 2 and "주의보 수위 도달" in new[0] and "방류 늘어남" in new[1]
    assert river._diff_alerts(rows, st)[0] == []                            # 같은 단계 · 같은 방류는 다시 알리지 않는다
    rows[0] = _wl("a", "적포교", 3, 5.2)
    assert "경보" in river._diff_alerts(rows, st)[0][0]                     # 한 단계 더 오르면 다시
    rows[0] = _wl("a", "적포교", 0, 2.0)
    rows[1]["rise"] = False
    assert river._diff_alerts(rows, st)[1] == {}                            # 내려오면 지운다
    assert river._diff_alerts([_wl("u", "위쪽", 3, 9.0, **{})] and [{**_wl("u", "위쪽", 3, 9.0), "up": True}], {})[0] == []   # 위쪽 수위는 알리지 않는다


def test_summary_text_and_tone(monkeypatch):
    monkeypatch.setitem(river._LIVE, "rows", [_wl("a", "적포교", 0, 2.4, gap=0.6), _wl("b", "황강교", 0, 1.0, gap=2.0)])
    s = river.summary()
    assert s["tone"] == 0 and "관심 수위 이상 없음" in s["text"] and "적포교" in s["text"]
    monkeypatch.setitem(river._LIVE, "rows", [_wl("a", "적포교", 3, 5.3, gap=0.7)])
    s = river.summary()
    assert s["tone"] == 3 and s["n"] == 1 and s["top"] == "적포교 경보"


def test_ai_river_rules_in_ladder():
    from app import ai
    rv = {"stage": 2, "name": "적포교", "wl": 4.2, "thr": [3.0, 4.0, 5.0, 6.0], "gap": 0.8, "d1h": 0.1, "t": "x", "n": 3, "dams": []}
    row = {"rain": {"1h": 0, "3h": 0, "24h": 0, "48h": 0}, "fc_peak": 0, "fc_run30": 0, "m15": 0, "ante": 0}
    lad = ai.ladders(row, False, [], rv)["하천"]
    ctl = next(c for c in lad if c["rule"].startswith("홍수주의보 수준"))
    evac = next(c for c in lad if c["rule"].startswith("홍수경보 수준"))
    assert ctl["st"] == "met" and ctl["stage"] == "통제"
    assert evac["st"] == "near" and evac["gap"]["left"] == 0.8             # 경보 수위 5.0 − 4.2
    assert next(c for c in ai.ladders(row, False, [], None)["하천"] if c["rule"].startswith("홍수경보"))["st"] == "unknown"
    assert "적포교 4.20m 주의보" in ai.river_text(rv) and "자료가 없다" in ai.river_text(None)

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

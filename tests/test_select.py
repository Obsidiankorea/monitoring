"""지도 시군 고르기 — 여러 시군(Ctrl+클릭, 3곳까지) 읍면동 표 · 읍면동 값 · 스방 지점 임시 위치."""
import json
from datetime import datetime

import numpy as np
import pytest

from app import db, gridstore, gridview, queries, sites

CASE = "geoje-20260816"


def test_siguns_of_validates():
    assert gridview.siguns_of(None) == [] and gridview.siguns_of("") == []
    assert gridview.siguns_of(" 함양, 거창,함양") == ["함양", "거창"]        # 겹치면 하나로, 순서는 그대로
    with pytest.raises(LookupError):
        gridview.siguns_of("함양,부산")                                  # 경남 밖(이웃)은 고를 수 없다
    with pytest.raises(LookupError):
        gridview.siguns_of("함양,거창,산청,합천")                         # 3곳까지


def test_acc_table_several_siguns():
    g = gridstore.geo()
    acc = np.zeros((g["hr"]["bbox"]["h"], g["hr"]["bbox"]["w"]))
    rows = gridview.acc_table(acc, [acc], "함양,거창")
    want = [e for e in g["emd"] if e["sigun"] in ("함양", "거창")]
    assert len(rows) == len(want) and {r["sig"] for r in rows} == {"함양", "거창"}
    assert len(gridview.acc_table(acc, [acc], "함양")) == sum(1 for e in want if e["sigun"] == "함양")


def test_emd_values_case_sum():
    one = gridview.emd("거제", case=CASE, hours=1)
    three = gridview.emd("거제", case=CASE, hours=3)
    assert one["hours"] == 1 and three["hours"] == 3
    a = {r["name"]: r["max"] for r in one["rows"]}
    b = {r["name"]: r["max"] for r in three["rows"]}
    assert a.keys() == b.keys() and all(b[k] >= a[k] for k in a if a[k] is not None)   # 3시간 합 ≥ 1시간
    top = max(three["rows"], key=lambda r: r["max"] or 0)
    assert top["col"] is not None and top["sig"] == "거제"
    with pytest.raises(LookupError):
        gridview.emd("", case=CASE)


def test_emd_values_test_layers():
    r = gridview.emd("창원,김해", "obs15", test=True)
    assert {x["sig"] for x in r["rows"]} == {"창원", "김해"} and r["siguns"] == ["창원", "김해"]
    v = gridview.emd("창원", "vsrt+3", test=True)                       # 5km 초단기도 500m 칸으로 펼쳐 읽는다
    assert v["n"] == 3 and len(v["rows"]) > 50


def test_bangjae_name_to_emd():
    assert sites.emd_of("시천면(가상)", "산청") == "시천면"
    assert sites.emd_of("시천", "산청") == "시천면"                        # 읍·면·동을 붙여 찾는다
    assert sites.emd_of("덕산(시천면)", "산청") == "시천면"                # 괄호 안
    assert sites.emd_of("회원", "창원") is None                            # 회원1동·회원2동 — 정하지 않는다
    assert sites.emd_of("지리산", "산청") is None
    p = sites.position("X1", "마천", "함양")
    assert p["est"] and p["emd"] == "마천면"
    # 이름 자리(안쪽 가장 깊은 점)는 그 읍면동 칸 안에 떨어진다
    g = gridstore.geo()
    _, memd = gridstore.masks()
    e = next(x for x in g["emd"] if x["sigun"] == "함양" and x["name"] == "마천면")
    hb = g["hr"]["bbox"]
    assert memd[round(p["y"]) - hb["j0"], round(p["x"]) - hb["i0"]] == e["id"]


def test_bangjae_override_wins(tmp_path, monkeypatch):
    f = tmp_path / "bangjae_sites.json"
    f.write_text(json.dumps({"sites": {"BJ9": {"lon": 127.7, "lat": 35.45}}}), "utf-8")
    monkeypatch.setattr(sites, "OVERRIDE", f)
    p = sites.position("BJ9", "마천", "함양")
    assert p["est"] is False and "emd" not in p
    assert sites.position("BJ8", "마천", "함양")["est"] is True             # 적지 않은 지점은 그대로 짐작


def test_test_rain_fake_stations_have_positions():
    rows = gridview.test_rain(2)["rows"]
    fake = [r for r in rows if r["stn"].startswith("T")]
    assert fake and all(r["pos"] and r["pos"]["est"] for r in fake)
    assert all("pos" not in r for r in rows if not r["stn"].startswith("T"))   # 기상청 지점은 화면이 안다


def test_forecast_several_siguns(tdb):
    with db.tx() as con:
        for sg, emd, v in (("함양", "마천면", 5), ("거창", "북상면", 10), ("산청", "시천면", 20)):
            con.execute("INSERT INTO fcst_rn1(tmfc, tmef, sigun, emd, rn1, fetched_at) VALUES (?,?,?,?,?,?)",
                        ("202610171100", "2026101712", sg, emd, v, "x"))
    r = queries.forecast(6, now=datetime(2026, 10, 17, 11, 10), sigun="함양,거창")
    assert {e["sigun"] for e in r["emd_sigun"]} == {"함양", "거창"}


def test_emd_day_windows_and_layers():
    assert [gridview._win_of(f"20261018{h:02d}") for h in (1, 6, 7, 12, 13, 18, 19, 23)] == [0, 0, 1, 1, 2, 2, 3, 3]
    assert gridview._win_of("2026101900") == 3                          # 00시 = 그 전날 24시
    r = gridview.emd_day("shrt_tomorrow", test=True)
    assert r["labels"] == ["06", "12", "18", "24"] and len(r["rows"]) == len(gridstore.geo()["emd"])
    sums = [x["sum"] or 0 for x in r["rows"]]
    assert sums == sorted(sums, reverse=True)                            # 그날 합 큰 순
    assert all(len(x["w"]) == 4 for x in r["rows"])
    s = gridview.emd_day("shrt_today", "함양,거창", test=True)
    assert {x["sig"] for x in s["rows"]} == {"함양", "거창"} and s["siguns"] == ["함양", "거창"]
    with pytest.raises(LookupError):
        gridview.emd_day("vsrt+1", test=True)                            # 단기 오늘·내일만


def test_acc_fc_setting(monkeypatch):
    monkeypatch.setattr(gridview.db, "get_setting", lambda k, d: dict(d))
    monkeypatch.setattr(gridview.db, "put_setting", lambda k, v: None)
    assert gridview.SETTING_DEFAULT["acc_fc"] is True
    assert gridview.put_setting({"acc_fc": False})["acc_fc"] is False


def test_emd_day_hourly(monkeypatch):
    r = gridview.emd_day("shrt_tomorrow", "의령", test=True)
    assert len(r["times"]) == 24 and r["times"][-1].endswith("00")       # 01시 … 다음 날 00시(=24시)
    x = r["rows"][0]
    assert len(x["h"]) == 24 and abs(sum(v or 0 for v in x["h"]) - x["sum"]) < 1.0   # 매시 최대의 합 ≈ 그날 합
    monkeypatch.setattr(gridview.db, "get_setting", lambda k, d: dict(d))
    monkeypatch.setattr(gridview.db, "put_setting", lambda k, v: None)
    assert gridview.SETTING_DEFAULT["acc_h1"] is True and gridview.put_setting({"acc_h1": 0})["acc_h1"] is False


def test_span_hours_today_yesterday():
    from datetime import datetime
    end = datetime(2026, 10, 18, 15, 0)
    assert gridview.span_hours(None, end, 12) == 12
    assert gridview.span_hours("today", end) == 15                  # 01 … 15시 정시 열다섯 장(0시~15시)
    assert gridview.span_hours("yesterday", end) == 39               # 어제 0시부터
    assert gridview.span_hours("today", datetime(2026, 10, 18, 0, 0)) == 1    # 0시 정각 — 한 장이라도
    assert gridview.span_hours("yesterday", datetime(2026, 10, 18, 23, 0)) == 47
    r = gridview.acc(12, None, datetime(2026, 10, 18, 15, 20), True, "today")
    assert len(r["frames"]) == 15 and r["frames"][0].endswith("0100") and r["frames"][-1].endswith("1500")


def test_acc_from_setting(monkeypatch):
    monkeypatch.setattr(gridview.db, "get_setting", lambda k, d: dict(d))
    monkeypatch.setattr(gridview.db, "put_setting", lambda k, v: None)
    assert gridview.SETTING_DEFAULT["acc_from"] == "hours"
    assert gridview.put_setting({"acc_from": "today"})["acc_from"] == "today"
    with pytest.raises(ValueError):
        gridview.put_setting({"acc_from": "week"})

"""관측소 층 · 격자 누적 표 — 격자와 같은 시각의 실측, 결측과 '못 받음' 가르기, 빠진 정각 메우기."""
import asyncio
from datetime import datetime

import numpy as np
import pytest

from app import gridcase, gridview
from app.collectors import grid_rain, rain
from app.domain import gridproj

CASE = "geoje-20260816"


def test_sites_file_positions():
    s = gridview.station_sites()
    assert len(s["stations"]) == 55 and {m["stn"] for m in s["missing"]} == {"161"}   # 사천공항은 자료가 없다
    gj = next(x for x in s["stations"] if x["stn"] == "294")
    assert gj["sigun"] == "거제" and gj["emd"]
    x, y = gridproj.hr_xy(gj["lon"], gj["lat"])                   # 칸 좌표는 위경도에서(타원체 람베르트)
    assert abs(x - gj["x"]) < 0.01 and abs(y - gj["y"]) < 0.01


def test_live_values_only_at_the_same_time(tdb):
    rain.store_minute("2026-10-03 15:10", {
        "155": {"rn_15m": 1.0, "rn_60m": 4.5, "rn_day": 9.0},
        "162": {"rn_15m": None, "rn_60m": None, "rn_day": None}}, "x")
    r = gridview.stations("obs60", "202610031510")
    by = {x["stn"]: x for x in r["rows"]}
    assert r["status"] == "ok" and by["155"]["v"] == 4.5 and by["155"]["q"] == "ok"
    assert by["162"]["q"] == "missing" and by["162"]["v"] is None     # 기상청 결측
    assert by["192"]["q"] == "none"                                   # 그 시각 행이 없다 — 결측과 다르다
    assert {x["stn"]: x["v"] for x in gridview.stations("obs15", "202610031510")["rows"]}["155"] == 1.0
    # 가까운 시각으로 메우지 않는다
    r2 = gridview.stations("obs60", "202610031520")
    assert r2["status"] == "none" and all(x["q"] == "none" for x in r2["rows"])


def test_hourly_fallback_only_on_the_hour(tdb):
    with tdb.tx() as con:
        con.execute("INSERT INTO obs_hourly (stn, tm, rn_hr1, rn_day, ta, quality, fetched_at) "
                    "VALUES ('155', '2026-10-03 15:00', 3.0, 7.0, 20, 'ok', 'x')")
    r = gridview.stations("obs60", "202610031500")
    assert r["status"] == "ok" and "정시" in r["src"]
    assert {x["stn"]: x["v"] for x in r["rows"]}["155"] == 3.0
    assert {x["stn"]: x["v"] for x in gridview.stations("obsday", "202610031500")["rows"]}["155"] == 7.0
    assert gridview.stations("obs15", "202610031500")["status"] == "none"   # 15분은 정시 대신이 없다


def test_forecast_layers_give_positions_only():
    r = gridview.stations("vsrt+2")
    assert r["status"] == "forecast" and len(r["rows"]) == 55 and all(x["v"] is None for x in r["rows"])


def test_case_stations_match_daily_check():
    # 8.18 00시까지(이틀) 매시 합 = 일자료 927.6 — 사례를 고른 근거와 같다
    r = gridview.stations("acc", "202608180000", case=CASE)
    gj = next(x for x in r["rows"] if x["stn"] == "294")
    assert gj["v"] == pytest.approx(927.6) and gj["q"] == "ok"
    peak = {x["name"]: x["v"] for x in gridview.stations("obs60", "202608171200", case=CASE)["rows"]}
    assert peak["명사"] == 70.5


def test_case_acc_rows_by_emd():
    j = gridcase.acc_rows(CASE, None, "거제")
    top = max(j["rows"], key=lambda r: r["sum"] or 0)
    assert top["name"] == "일운면" and top["sum"] == pytest.approx(767.7)
    assert len(top["d"]) == len(j["frames"]) and sum(v or 0 for v in top["d"]) == pytest.approx(767.7, abs=0.5)
    s = gridcase.acc_rows(CASE, None, None)
    assert len(s["rows"]) == 18 and all(r["name"] for r in s["rows"] if (r["sum"] or 0) >= 0.1)
    with pytest.raises(LookupError):
        gridcase.acc_rows(CASE, None, "부산")


def test_live_acc_sums_on_the_hour_and_counts_missing(store):
    gridview._ACC_CACHE.clear()
    hb = store.geo()["hr"]["bbox"]
    st = next(x for x in gridview.station_sites()["stations"] if x["stn"] == "155")   # 창원 땅 한 칸
    r, c = round(st["y"]) - hb["j0"], round(st["x"]) - hb["i0"]
    a = np.zeros(store.shape("hr"))
    a[r, c] = 5.0
    store.save("obs60", "202610031300", a)
    store.save("obs60", "202610031500", a * 2)
    store.save("obs60", "202610031510", a * 9)             # 10분 칸은 더하지 않는다
    j = gridview.acc(3, now=datetime(2026, 10, 3, 15, 20))
    assert j["frames"] == ["202610031300", "202610031400", "202610031500"] and j["missing"] == 1
    cw = next(x for x in j["rows"] if x["sig"] == "창원")
    assert cw["sum"] == 15.0 and cw["d"] == [5.0, None, 10.0] and cw["name"] == st["emd"]
    emd = gridview.acc(3, "창원", now=datetime(2026, 10, 3, 15, 20))
    assert max(x["sum"] or 0 for x in emd["rows"]) == 15.0


def test_put_setting_basis_and_station_layers(monkeypatch):
    monkeypatch.setattr(gridview.db, "get_setting", lambda k, d: dict(d))
    monkeypatch.setattr(gridview.db, "put_setting", lambda k, v: None)
    assert gridview.put_setting({"acc_basis": "grid"})["acc_basis"] == "grid"
    assert gridview.put_setting({"overlays": ["stations", "stnval"]})["overlays"] == ["stations", "stnval"]
    with pytest.raises(ValueError):
        gridview.put_setting({"acc_basis": "radar"})


def test_stations_at_fetches_once_per_time(tdb, monkeypatch):
    calls = []

    async def fake(at):
        calls.append(at)
        return {"155": {"rn_15m": 0.5, "rn_60m": 2.0, "rn_day": 3.0}}

    monkeypatch.setattr(grid_rain.rain, "fetch_minute", fake)
    n, failed = asyncio.run(grid_rain.stations_at(["202610031510", "202610031510"], "x"))
    assert n == 1 and not failed and calls == [datetime(2026, 10, 3, 15, 10)]
    n, _ = asyncio.run(grid_rain.stations_at(["202610031510"], "x"))
    assert n == 0 and len(calls) == 1                       # 이미 있으면 다시 부르지 않는다


def test_backfill_recent_hours_first_and_capped(store, tdb, monkeypatch):
    got = []

    async def fake(obs, tm):
        got.append(tm)
        return np.zeros((2049, 2049))

    monkeypatch.setattr(grid_rain, "_fetch_hr", fake)
    now = datetime(2026, 10, 3, 15, 20)
    assert asyncio.run(grid_rain._backfill_hours(now, [])) == grid_rain.BACKFILL
    assert got[:2] == ["202610031500", "202610031400"]      # 최근 것부터
    asyncio.run(grid_rain._backfill_hours(now, []))
    assert got[grid_rain.BACKFILL] == "202610031100"        # 다음 주기는 이어서

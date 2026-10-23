"""관측소 층 · 격자 누적 표 — 격자와 같은 시각의 실측, 결측과 '못 받음' 가르기, 빠진 정각 메우기."""
import asyncio
from datetime import datetime

import numpy as np
import pytest

from app import gridcase, gridview, sites
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
    assert r["status"] == "forecast" and len(r["rows"]) == 55 + 216 and all(x["v"] is None for x in r["rows"])
    assert sum(x["org"] == "gn" for x in r["rows"]) == 216                 # 경남 AWS 도 자리를 짚는다


def test_aws_layer_from_stations_only(store, tdb, monkeypatch):
    """AWS 누적 면 — 기상청(obs_hourly) + 경남 AWS(스방, 목록 위치)의 구간 합을 IDW. 땅 밖은 0, 관측소 자리는 그 값 가까이."""
    gridview._ACC_CACHE.clear(); gridview._SUM_CACHE.clear(); gridview._AWS_CACHE.clear()
    monkeypatch.setattr(gridview, "setting", lambda: {"acc_hours": 2, "acc_from": "hours"})
    a = np.zeros(store.shape("hr"))
    for k in ("202610031400", "202610031500"):
        store.save("obs60", k, a)
    hl = next(s for s in sites.gn_sites() if s["sigun"] == "고성" and s["name"] == "학림")
    with tdb.tx() as c:
        for tm in ("2026-10-03 14:00", "2026-10-03 15:00"):                       # 기상청 창원 10㎜씩
            c.execute("INSERT INTO obs_hourly VALUES('155', ?, 10, 0, 0, 'ok', 'x')", (tm,))
        for tm in ("2026-10-03 13:00", "2026-10-03 14:00"):                       # 스방 13시 = 기상청 14시 칸
            c.execute("INSERT INTO bangjae_hourly VALUES(?, 'BJ7', '학림', '고성', 30, 'x')", (tm,))
        c.execute("INSERT INTO bangjae_hourly VALUES('2026-10-03 14:00', '155', '창원', '창원', 99, 'x')")  # 기상청 번호 — 뺀다
    now = datetime(2026, 10, 3, 15, 20)
    monkeypatch.setattr(gridview.clock, "now", lambda: now)
    st = gridview.stations("aws")
    by = {x["stn"]: x for x in st["rows"]}
    assert by["155"]["v"] == 20.0 and by[hl["stn"]]["v"] == 60.0 and by[hl["stn"]]["org"] == "gn"
    assert "경남 AWS" in st["src"]
    fr = gridview.frame("aws", now=now)
    assert fr["n"] == 2 and fr["n_gn"] == 1 and fr["from"] == "202610031400"
    hb = store.geo()["hr"]["bbox"]
    v = fr["arr"][round(hl["y"]) - hb["j0"], round(hl["x"]) - hb["i0"]]
    assert 45 < v <= 60                                                      # 학림 자리 — 그 값 가까이
    assert float(fr["arr"][0, 0]) == 0.0                                     # 경남 땅 밖은 칠하지 않는다



def test_aws_hour_layer_is_one_hour_of_the_same_stations(store, tdb, monkeypatch):
    """AWS 1시간 면 — 정시 하나의 관측소 값(기상청 + 경남 AWS)을 누적 층과 같은 IDW 로.
    '지금'은 관측소 값이 든 가장 최근 정시(정시 격자가 있어도 정시자료가 아직이면 그 앞 정시)."""
    gridview._AWS_CACHE.clear()
    a = np.zeros(store.shape("hr"))
    for k in ("202610031400", "202610031500"):
        store.save("obs60", k, a)
    hl = next(s for s in sites.gn_sites() if s["sigun"] == "고성" and s["name"] == "학림")
    with tdb.tx() as c:
        c.execute("INSERT INTO obs_hourly VALUES('155', '2026-10-03 14:00', 7, 0, 0, 'ok', 'x')")
        c.execute("INSERT INTO bangjae_hourly VALUES('2026-10-03 13:00', 'BJ7', '학림', '고성', 22, 'x')")  # = 14시 칸
    now = datetime(2026, 10, 3, 15, 20)
    monkeypatch.setattr(gridview.clock, "now", lambda: now)
    assert gridview.aws_hour_latest(now) == "202610031400"            # 15시 정시자료는 아직 — 14시
    fr = gridview.frame("aws60", now=now)
    assert (fr["tm"], fr["n"], fr["n_gn"]) == ("202610031400", 2, 1)
    hb = store.geo()["hr"]["bbox"]
    assert 15 < fr["arr"][round(hl["y"]) - hb["j0"], round(hl["x"]) - hb["i0"]] <= 22
    by = {x["stn"]: x for x in gridview.stations("aws60", "202610031400")["rows"]}
    assert by["155"]["v"] == 7.0 and by[hl["stn"]]["v"] == 22.0
    with pytest.raises(LookupError):
        gridview.frame("aws60", "202610031510", now=now)               # 정시만
    with pytest.raises(LookupError):
        gridview.frame("aws60", "202610031500", now=now)               # 그 정시에 값 있는 관측소가 없다
    meta = {x["id"]: x for x in gridview.meta(now)["layers"]}
    assert meta["aws60"]["tm"] == "202610031400"


def test_flow_from_aws_is_hourly_then_vsrt():
    """재생 흐름 src=aws — 지난 N시간 AWS 1시간(정시마다) → 초단기 +1~6h. 시군 값도 그 면에서."""
    gridview._AWS_CACHE.clear()
    now = datetime(2026, 10, 3, 15, 20)
    f = gridview.flow(hours=3, now=now, test=True, src="aws")
    obs = [x for x in f["frames"] if x["kind"] == "obs"]
    assert [x["t"] for x in obs] == ["202610031300", "202610031400", "202610031500"]
    assert all(x["layer"] == "aws60" for x in obs) and f["step"] == 60 and f["src"] == "aws"
    assert [x["layer"] for x in f["frames"] if x["kind"] == "fcst"] == [f"vsrt+{n}" for n in range(1, 7)]
    assert len(f["total"]["max"]) == len(f["frames"])
    assert gridview.flow(hours=1, now=now, test=True)["frames"][0]["layer"] == "obs60"   # 기본은 격자 그대로

def test_aws_layer_tells_missing_hours(store, tdb, monkeypatch):
    """한 시간이 빠진 경남 AWS — 합은 있는 시각만(part), 몇 시간 빠졌나(miss). 화면은 숫자만 쓰고 툴팁에 miss."""
    gridview._ACC_CACHE.clear(); gridview._SUM_CACHE.clear(); gridview._AWS_CACHE.clear()
    monkeypatch.setattr(gridview, "setting", lambda: {"acc_hours": 2, "acc_from": "hours"})
    for k in ("202610031400", "202610031500"):
        store.save("obs60", k, np.zeros(store.shape("hr")))
    hl = next(s for s in sites.gn_sites() if s["sigun"] == "고성" and s["name"] == "학림")
    with tdb.tx() as c:
        c.execute("INSERT INTO bangjae_hourly VALUES('2026-10-03 13:00', 'BJ7', '학림', '고성', 30, 'x')")   # 14시 칸만
    monkeypatch.setattr(gridview.clock, "now", lambda: datetime(2026, 10, 3, 15, 20))
    r = next(x for x in gridview.stations("aws")["rows"] if x["stn"] == hl["stn"])
    assert r["v"] == 30.0 and r["q"] == "part" and r["miss"] == 1


def test_bangjae_hourly_fills_midnight_from_daily_row():
    """경남 AWS 는 시간 줄 00시가 비어 온다 — 같은 응답의 일누적 00시로 메운다. 다른 빈 칸은 그대로 결측."""
    from app import bangjae

    def row(stn, gubun, vals):
        return {"lnk_id": stn, "rtu_name": "학림", "org_name": "고성", "gubun": gubun,
                **{f"times{h:02d}": v for h, v in enumerate(vals)}}
    got = [row("8438", "시간", ["", "1.0", "", "2.5"] + [""] * 20), row("8438", "일", ["4.0", "5.0", "", "11.5"] + [""] * 20),
           row("155", "시간", ["0.5"] + [""] * 23), row("155", "일", ["9.9"] + [""] * 23)]

    async def run():
        async with bangjae.Client() as c:
            async def fake(path, **kw):
                return got
            c.get = fake
            return await c.station_hourly("20261019")
    by = {s["stn"]: s["mm"] for s in asyncio.run(run())}
    assert by["8438"][:4] == [4.0, 1.0, None, 2.5]          # 00시 = 일누적 00시, 02시 빈 칸은 메우지 않는다
    assert by["155"][0] == 0.5                              # 시간 줄에 있으면 그대로


def test_aws_match_report(tdb):
    from app import queries
    with tdb.tx() as c:
        for stn, nm, sg in (("BJ1", "학림", "고성"), ("BJ2", "없는지점이름", "고성"), ("155", "창원", "창원"),
                            ("8857", "신등", "사천"), ("8299", "북상", "거창")):
            c.execute("INSERT INTO bangjae_hourly VALUES('2026-10-03 14:00', ?, ?, ?, 1, 'x')", (stn, nm, sg))
    j = queries.aws_match()
    src = {r["name"]: r["src"] for r in j["rows"]}
    assert src == {"학림": "aws", "없는지점이름": "none", "창원": "kma", "신등": "aws", "북상": "aws"}
    assert j["rows"][0]["name"] == "없는지점이름"
    by = {r["stn"]: r for r in j["rows"]}
    assert by["8857"]["sigun"] == "산청" and by["8857"]["sigun_bj"] == "사천" and by["8857"]["emd"] == "신등면"
    assert by["8299"]["org"] == "gn" and by["8299"]["list_name"] == "거창북상"     # 기상청 북상(946)과 가른다
    assert j["list"]["total"] == 270 and j["list"]["seen"] == 4 and j["list"]["unseen"] == 266   # 학림 · 창원 · 신등 · 거창북상
    un = {(x["sigun"], x["name"], x["org"]) for x in j["unseen"]}
    assert ("고성", "학림", "gn") not in un and ("산청", "신등", "gn") not in un and ("거창", "거창북상", "gn") not in un
    assert ("거창", "북상", "kma") in un                                      # 기상청 북상은 안 왔다


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


def test_map_acc_layer_is_the_card_window(store, monkeypatch):
    """지도 '누적' 층 = 강수 누적 카드와 같은 구간 · 같은 정시 격자 합. 구간을 안 주면 지도 설정을 따른다."""
    gridview._ACC_CACHE.clear()
    gridview._SUM_CACHE.clear()
    a = np.zeros(store.shape("hr"))
    a[10, 10] = 4.0
    for k in ("202610022300", "202610030000", "202610031400", "202610031500"):
        store.save("obs60", k, a)
    now = datetime(2026, 10, 3, 15, 20)
    fr = gridview.frame("acc", now=now, hours=2, since="hours")
    assert (fr["from"], fr["tm"], fr["n"], fr["missing"]) == ("202610031400", "202610031500", 2, 0)
    assert float(fr["arr"][10, 10]) == 8.0
    fr = gridview.frame("acc", now=now, since="today")                 # 오늘 0시부터 — 00시 칸(어제 23~24시)은 빼고
    assert fr["from"] == "202610030100" and float(fr["arr"][10, 10]) == 8.0 and fr["missing"] == 13
    monkeypatch.setattr(gridview, "setting", lambda: {"acc_hours": 12, "acc_from": "yesterday"})
    fr = gridview.frame("acc", now=now)                                 # 카드 설정 — 어제 0시부터
    assert fr["from"] == "202610020100" and float(fr["arr"][10, 10]) == 16.0


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


def test_test_rain_shape_and_unsited_fakes():
    from datetime import datetime as dt
    r = gridview.test_rain(6, now=dt(2026, 10, 3, 15, 20))
    assert r["labels"] == ["10", "11", "12", "13", "14", "15"] and r["base_hour"] == "15:00"
    sites = {x["stn"] for x in gridview.station_sites()["stations"]}
    fake = [x for x in r["rows"] if x["stn"] not in sites]
    # 시군마다 '스방 흉내' 지점 — 번호가 기상청 지점번호가 아니라 위치를 화면에 주지 않는다
    assert fake and all(x["stn"].startswith("T") and x["name"].endswith("(가상)") for x in fake)
    assert {x["sigun"] for x in fake} == {s["name"] for s in gridview.gridstore.geo()["sigun"] if s["kind"] == "gn"}
    assert all(len(x["d"]) == 6 for x in r["rows"])
    # 기상청 자리 값은 관측소 층(테스트)과 같은 비율 — 지도와 카드가 같은 비를 보인다
    assert gridview._tfac("155") == 0.7 + 0.6 * ((155 * 37) % 100) / 100

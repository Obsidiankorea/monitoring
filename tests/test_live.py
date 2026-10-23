"""지도 AWS 층의 '지금' 칸 — 실시간 감시(aws_live)를 켜면 마지막 정시 뒤 매분자료(1분 수집기)로 잇는다.
종합 화면 강수량 판과 같은 셈. 끄면 정시까지만."""
import asyncio
from datetime import datetime

import numpy as np
import pytest

from app import gridview, maint, queries, sites
from app.collectors import rain


def _grids(store, *keys):
    for k in keys:
        store.save("obs60", k, np.zeros(store.shape("hr")))


def _minute(c, tm, stn, rn_day, rn_60m):
    c.execute("INSERT INTO obs_minute(stn, tm, rn_60m, rn_day, quality, fetched_at) VALUES(?, ?, ?, ?, 'ok', 'x')",
              (stn, tm, rn_60m, rn_day))


def _clear():
    gridview._ACC_CACHE.clear(); gridview._SUM_CACHE.clear(); gridview._AWS_CACHE.clear()


def test_aws_acc_now_cell_adds_since_the_hour(store, tdb, monkeypatch):
    """AWS 누적 = 정시 합 + 정시부터 지금까지 — 기상청은 RN_DAY 증분, 경남 AWS 는 스방 진행 칸. 격자 누적의 점은 정시까지만.
    실시간 감시를 끄면 정시까지만(위 카드도 tail=0 으로 같은 정시)."""
    _clear()
    live = {"acc_hours": 2, "acc_from": "hours", "aws_live": True}
    monkeypatch.setattr(gridview, "setting", lambda: live)
    _grids(store, "202610031400", "202610031500")
    hl = next(s for s in sites.gn_sites() if s["sigun"] == "고성" and s["name"] == "학림")
    with tdb.tx() as c:
        c.execute("INSERT INTO obs_hourly VALUES('155', '2026-10-03 14:00', 10, 10, 0, 'ok', 'x')")
        c.execute("INSERT INTO obs_hourly VALUES('155', '2026-10-03 15:00', 10, 20, 0, 'ok', 'x')")
        for tm, mm in (("2026-10-03 13:00", 30), ("2026-10-03 14:00", 30), ("2026-10-03 15:00", 4)):   # 15시 = 진행 칸
            c.execute("INSERT INTO bangjae_hourly VALUES(?, 'BJ7', '학림', '고성', ?, 'x')", (tm, mm))
        _minute(c, "2026-10-03 15:20", "155", 23.5, 6.0)
    now = datetime(2026, 10, 3, 15, 21)
    monkeypatch.setattr(gridview.clock, "now", lambda: now)
    st = gridview.stations("aws")
    by = {x["stn"]: x for x in st["rows"]}
    assert st["tm"] == st["live"] == "202610031520" and "15:00~15:20(매분)" in st["src"]
    assert by["155"]["v"] == 23.5 and by["155"]["q"] == "ok"                 # 10 + 10 + 3.5
    assert by[hl["stn"]]["v"] == 64.0 and by[hl["stn"]]["q"] == "ok"           # 30 + 30 + 4
    fr = gridview.frame("aws", now=now)
    assert (fr["tm"], fr["live"], fr["from"]) == ("202610031520", "202610031520", "202610031400")
    meta = {x["id"]: x for x in gridview.meta(now)["layers"]}
    assert (meta["aws"]["tm"], meta["aws"]["live"]) == ("202610031520", True)
    assert (meta["acc"]["tm"], meta["acc"]["live"]) == ("202610031500", False)
    # 격자 누적의 관측소 점은 격자와 같은 시각(정시)까지만
    assert {x["stn"]: x for x in gridview.stations("acc")["rows"]}["155"]["v"] == 20.0
    # 종합 화면 강수량 판도 같은 셈(마지막 칸 = 15:00~15:20)
    k = queries.rain(2, now)
    assert k["labels"][-1] == "15:20" and next(r for r in k["rows"] if r["stn"] == "155")["d"][-1] == 3.5
    # 실시간 감시를 끄면 정시까지만 — 지도도 위 카드(tail=0)도
    live["aws_live"] = False
    _clear()
    assert gridview.stations("aws")["tm"] == gridview.frame("aws", now=now)["tm"] == "202610031500"
    assert {x["id"]: x for x in gridview.meta(now)["layers"]}["aws"]["live"] is False
    k = queries.rain(2, now, tail=False)
    assert k["labels"][-1] == "15" and k["minute_tm"] is None
    live["aws_live"] = True
    # 매분이 오래 멈췄으면 '지금' 칸을 잇지 않는다(지난 값을 지금이라 하지 않게)
    _clear()
    late = datetime(2026, 10, 3, 17, 0)
    monkeypatch.setattr(gridview.clock, "now", lambda: late)
    assert gridview.stations("aws")["tm"] == "202610031500"


def test_minute_tail_waits_for_hourly_with_the_hour_minute(tdb):
    """정시자료(awsh)가 늦으면 그 정시의 매분자료 RN_DAY 를 기준으로 — 비어 있던 '지금' 칸이 채워진다."""
    with tdb.tx() as c:
        _minute(c, "2026-10-03 15:00", "155", 20.0, 9.0)
        _minute(c, "2026-10-03 15:07", "155", 21.5, 8.0)
    tm, tail, m60 = queries.minute_tail("2026-10-03 15:00")
    assert tm == "2026-10-03 15:07" and tail["155"] == 1.5 and m60["155"] == 8.0
    assert queries.minute_tail("2026-10-03 15:00", "2026-10-03 15:00")[0] is None      # 정시 그 자체는 칸이 아니다


def test_aws_hour_now_is_the_minute_60(store, tdb, monkeypatch):
    """AWS 1시간 '지금' = 마지막 정시 뒤 그 분의 직전 60분(기상청 RN-60m). 경남 AWS 는 자리만. 재생 흐름 끝 칸도 그것."""
    _clear()
    live = {"aws_live": True}
    monkeypatch.setattr(gridview, "setting", lambda: live)
    _grids(store, "202610031400", "202610031500")
    other = gridview.station_sites()["stations"][1]["stn"]
    with tdb.tx() as c:
        c.execute("INSERT INTO obs_hourly VALUES('155', '2026-10-03 15:00', 7, 0, 0, 'ok', 'x')")
        _minute(c, "2026-10-03 15:20", "155", 0, 6.0)
        _minute(c, "2026-10-03 15:20", other, 0, 1.5)
    now = datetime(2026, 10, 3, 15, 21)
    monkeypatch.setattr(gridview.clock, "now", lambda: now)
    assert gridview.aws_hour_latest(now) == "202610031500" and gridview.aws_hour_now(now) == "202610031520"
    fr = gridview.frame("aws60", now=now)
    assert (fr["tm"], fr["live"], fr["n"], fr["n_gn"]) == ("202610031520", "202610031520", 2, 0)
    st = gridview.stations("aws60")
    by = {x["stn"]: x for x in st["rows"]}
    assert st["tm"] == "202610031520" and by["155"]["v"] == 6.0 and "직전 60분" in st["src"]
    assert all(x["q"] == "none" for x in st["rows"] if x["stn"].startswith("G"))
    assert {x["stn"]: x for x in gridview.stations("aws60", "202610031500")["rows"]}["155"]["v"] == 7.0   # 정시는 정시자료
    f = gridview.flow(hours=3, now=now, src="aws")
    obs = [x for x in f["frames"] if x["kind"] == "obs"]
    assert [x["t"] for x in obs] == ["202610031500", "202610031520"] and obs[-1]["live"]
    meta = {x["id"]: x for x in gridview.meta(now)["layers"]}
    assert (meta["aws60"]["tm"], meta["aws60"]["live"]) == ("202610031520", True)
    with pytest.raises(LookupError):
        gridview.frame("aws60", "202610031510", now=now)               # 그 분 매분자료가 없다
    live["aws_live"] = False                                              # 끄면 정시마다
    _clear()
    assert gridview.aws_hour_now(now) == gridview.frame("aws60", now=now)["tm"] == "202610031500"
    assert [x["t"] for x in gridview.flow(hours=3, now=now, src="aws")["frames"] if x["kind"] == "obs"] == ["202610031500"]


def test_collect_minute_once_per_minute(tdb, monkeypatch):
    """1분 수집기 — 실시간 감시를 켠 동안만. 지금 −1분 한 시각만, 이미 받은 분은 다시 부르지 않고, 아직이면 −2분."""
    calls = []

    async def fake(at):
        calls.append(at.strftime("%H:%M"))
        if at.minute == 19:
            return {}                                    # 아직 안 올라왔다
        return {"155": {"rn_15m": 0.5, "rn_60m": 2.0, "rn_day": 9.0}}

    monkeypatch.setattr(rain, "fetch_minute", fake)
    assert asyncio.run(rain.collect_minute(datetime(2026, 10, 3, 15, 20, 30)))["skipped"] and not calls   # 감시 꺼짐 — 안 부른다
    tdb.put_setting("map", {"aws_live": True})
    r = asyncio.run(rain.collect_minute(datetime(2026, 10, 3, 15, 20, 30)))
    assert r["minute_at"] == "2026-10-03 15:18" and calls == ["15:19", "15:18"]
    r = asyncio.run(rain.collect_minute(datetime(2026, 10, 3, 15, 19, 5)))
    assert r.get("skipped") and calls == ["15:19", "15:18"]                 # 15:18 은 이미 있다 — 부르지 않는다


def test_thin_old_minutes_keeps_ten_minute_slots(tdb):
    with tdb.tx() as c:
        for tm in ("2026-10-01 10:03", "2026-10-01 10:10", "2026-10-03 10:03"):
            _minute(c, tm, "155", 0, 0)
    assert maint.thin_minutes(datetime(2026, 10, 3, 12, 0)) == 1
    with tdb.tx() as c:
        left = [r["tm"] for r in c.execute("SELECT tm FROM obs_minute ORDER BY tm")]
    assert left == ["2026-10-01 10:10", "2026-10-03 10:03"]


def test_new_collector_gets_default_interval(tdb):
    """저장해 둔 수집 주기에 없는 새 수집기(minute)도 기본 주기로 돈다."""
    from app import main
    tdb.put_setting("intervals", {"rain": 300})
    iv = main.intervals()
    assert iv["rain"] == 300 and iv["minute"] == 60 and "minute" in main.COLLECTORS


def test_grid_acc_now_cell_from_daily_grid(store, monkeypatch):
    """격자 누적 = 정시 60분 합 + 마지막 정시 뒤 가장 최근 일강수 격자의 증분(10분마다 는다).
    카드 줄 마지막 칸 = 그 몫, 빗금(최근 1시간)은 그 시각 60분 격자. 음수 칸은 0. 0시 정각 뒤는 그날 일강수 그대로."""
    _clear()
    monkeypatch.setattr(gridview, "setting", lambda: {"acc_hours": 2, "acc_from": "hours"})
    sh = store.shape("hr")
    one = np.ones(sh)
    for k in ("202610031400", "202610031500"):
        store.save("obs60", k, one)
    store.save("obs60", "202610031540", np.full(sh, 2.5))
    store.save("obsday", "202610031500", np.full(sh, 10.0))
    cur = np.full(sh, 13.0)
    cur[0, 0] = 9.0                                         # 일강수가 줄어든 칸(분석 잡음) — 0 으로
    store.save("obsday", "202610031540", cur)
    now = datetime(2026, 10, 3, 15, 45)
    monkeypatch.setattr(gridview.clock, "now", lambda: now)
    fr = gridview.frame("acc", now=now)
    assert (fr["tm"], fr["live"], fr["from"]) == ("202610031540", "202610031540", "202610031400")
    assert float(fr["arr"][5, 5]) == 5.0 and float(fr["arr"][0, 0]) == 2.0      # 1 + 1 + 3 · 1 + 1 + 0
    t = gridview.acc(2, now=now)
    assert t["frames"][-1] == t["tm"] == t["tail"] == "202610031540" and "15:00~15:40(일강수 차)" in t["src"]
    r = next(x for x in t["rows"] if x["sum"])
    assert r["d"] == [1.0, 1.0, 3.0] and r["sum"] == 5.0 and r["h1"] == 2.5
    meta = {x["id"]: x for x in gridview.meta(now)["layers"]}
    assert (meta["acc"]["tm"], meta["acc"]["live"]) == ("202610031540", True)
    # 기준(정시 일강수)이 없으면 잇지 않는다 — 정시까지만
    _clear()
    store.save("obs60", "202610031600", one)
    store.save("obsday", "202610031620", cur)
    assert gridview.frame("acc", now=datetime(2026, 10, 3, 16, 25))["tm"] == "202610031600"
    # 0시 정각 뒤는 그날 일강수가 곧 0시부터의 합
    _clear()
    store.save("obs60", "202610032300", one)
    store.save("obs60", "202610040000", one)
    store.save("obsday", "202610040020", np.full(sh, 1.5))
    fr = gridview.frame("acc", now=datetime(2026, 10, 4, 0, 25))
    assert fr["tm"] == "202610040020" and float(fr["arr"][5, 5]) == 3.5          # 23·00시 정시 + 1.5


def test_bangjae_rain_is_empty_without_bangjae(tdb):
    """스방 지점이 하나도 없으면(서버 · 집) 빈 줄 — 화면이 기상청(매분 보강 마지막 칸 포함)으로 물러선다.
    ⚠️ 기상청 줄을 늘 덧붙이자 화면이 물러서지 않아 서버 화면에서 매분 칸이 사라졌다."""
    with tdb.tx() as c:
        c.execute("INSERT INTO obs_hourly VALUES('155', '2026-10-03 14:00', 4, 4, 0, 'ok', 'x')")
        _minute(c, "2026-10-03 14:20", "155", 5.5, 3.0)
    now = datetime(2026, 10, 3, 14, 21)
    assert queries._rain_bangjae(2, now)["rows"] == []
    k = queries.rain(2, now)
    assert k["minute_tm"] == "14:20" and next(r for r in k["rows"] if r["stn"] == "155")["d"][-1] == 1.5


def test_grid_acc_stations_stay_on_the_hour_without_minute_at_the_slot(store, tdb, monkeypatch):
    """격자 누적 '지금' 칸 시각에 매분자료가 없으면 관측소 점은 정시 시각 그대로 — 지금 칸 시각을 달고 정시 값을 보이지 않는다."""
    _clear()
    monkeypatch.setattr(gridview, "setting", lambda: {"acc_hours": 1, "acc_from": "hours"})
    sh = store.shape("hr")
    store.save("obs60", "202610031500", np.ones(sh))
    store.save("obsday", "202610031500", np.full(sh, 10.0))
    store.save("obsday", "202610031540", np.full(sh, 12.0))
    with tdb.tx() as c:
        c.execute("INSERT INTO obs_hourly VALUES('155', '2026-10-03 15:00', 1, 10, 0, 'ok', 'x')")
    monkeypatch.setattr(gridview.clock, "now", lambda: datetime(2026, 10, 3, 15, 45))
    assert gridview.frame("acc")["tm"] == "202610031540"
    assert gridview.stations("acc")["tm"] == "202610031500"            # 15:40 매분이 없다 — 정시로(화면은 점을 감춘다)
    with tdb.tx() as c:
        _minute(c, "2026-10-03 15:40", "155", 12.0, 2.0)
    st = gridview.stations("acc")
    assert st["tm"] == "202610031540" and {x["stn"]: x for x in st["rows"]}["155"]["v"] == 3.0


def test_disabled_aws_left_out_of_surface_cards_and_now(store, tdb, monkeypatch):
    """지도에서 비활성화한 AWS(map.aws_off) — 관측소 점은 q='off'(값은 남긴다), 면(IDW) · 카드(/api/rain) ·
    지금 오는 비에서 뺀다. 경남 AWS 는 '시군:목록 이름' 열쇠로(스방 장치코드와 지도 G 번호가 다르다)."""
    _clear()
    monkeypatch.setattr(gridview, "setting", lambda: {"acc_hours": 1, "acc_from": "hours"})
    _grids(store, "202610031500")
    hl = next(s for s in sites.gn_sites() if s["sigun"] == "고성" and s["name"] == "학림")
    with tdb.tx() as c:
        c.execute("INSERT INTO obs_hourly VALUES('155', '2026-10-03 15:00', 1, 1, 0, 'ok', 'x')")
        c.execute("INSERT INTO obs_hourly VALUES('162', '2026-10-03 15:00', 12, 12, 0, 'ok', 'x')")
        c.execute("INSERT INTO bangjae_hourly VALUES('2026-10-03 14:00', 'BJ7', '학림', '고성', 30, 'x')")
        _minute(c, "2026-10-03 15:00", "155", 1, 1)
        _minute(c, "2026-10-03 15:00", "162", 12, 12)
    now = datetime(2026, 10, 3, 15, 20)
    monkeypatch.setattr(gridview.clock, "now", lambda: now)
    assert gridview.frame("aws", now=now)["n"] == 3
    tdb.put_setting("map", {"aws_off": [{"id": "155", "name": "창원", "sigun": "창원", "org": "kma"},
                                        {"id": "gn:고성:학림", "name": "학림", "sigun": "고성", "org": "gn"}]})
    _clear()
    by = {x["stn"]: x for x in gridview.stations("aws")["rows"]}
    assert by["155"]["q"] == "off" and by["155"]["v"] == 1.0 and by[hl["stn"]]["q"] == "off"
    assert by["162"]["q"] == "ok"
    assert gridview.frame("aws", now=now)["n"] == 1                       # 162 만 — 면에서 둘을 뺐다
    assert all(r["stn"] != "155" for r in queries.rain(1, now)["rows"])
    assert all(r["stn"] != "155" for r in queries.minute_top(8)["r60"])
    assert all(r["name"] != "학림" for r in queries._rain_bangjae(1, now)["rows"])
    # 설정 검사 — 목록 · 줄 모양
    monkeypatch.setattr(gridview, "setting", lambda: dict(gridview.SETTING_DEFAULT))
    got = gridview.put_setting({"aws_off": [{"id": "192", "name": "진주", "sigun": "진주", "org": "kma"}] * 2})
    assert [x["id"] for x in got["aws_off"]] == ["192"]                   # 겹치면 하나로
    for bad in ({"aws_off": "192"}, {"aws_off": [{"name": "진주"}]}):
        with pytest.raises(ValueError):
            gridview.put_setting(bad)

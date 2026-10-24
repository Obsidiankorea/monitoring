"""층 이름 풀기, 단기예보 하루 합."""
import numpy as np
import pytest

from app import gridview


def test_split():
    assert gridview.split("vsrt+3") == ("vsrt", 3)
    assert gridview.split("vsrt3") == ("vsrt", 3)
    assert gridview.split("vsrt") == ("vsrt", 1)
    assert gridview.split("obs15") == ("obs15", 0)
    for bad in ("vsrt+7", "vsrt+0", "nope"):
        with pytest.raises(LookupError):
            gridview.split(bad)


def test_shrt_sum_day_missing_and_cap(store):
    shape = store.shape("dfs")
    tmfc = "2026100105"
    a = np.full(shape, 2.0)
    a[0, 0] = 30.0                    # 30 = '30㎜ 이상' — 합계는 하한
    b = np.full(shape, 1.0)
    b[1, 1] = np.nan                  # 한 시간이라도 결측이면 그 칸은 결측
    store.save("shrt", f"{tmfc}_2026100106", a)
    store.save("shrt", f"{tmfc}_2026100200", b)     # 00시 = 전날(10.1.) 23~24시 몫
    store.save("shrt", f"{tmfc}_2026100201", b)     # 10.2. 몫
    tmefs = ["2026100106", "2026100200", "2026100201"]
    s = gridview.shrt_sum(tmfc, tmefs, "20261001")
    assert s["hours"] == ["2026100106", "2026100200"]
    assert s["arr"][2, 2] == 3.0
    assert s["arr"][0, 0] == 31.0
    assert np.isnan(s["arr"][1, 1])
    assert s["capped"] == 1
    assert gridview.shrt_sum(tmfc, tmefs, "20261002")["hours"] == ["2026100201"]


def test_synth_is_stable_and_has_land_gap():
    a = gridview.synth("obs60", "hr")
    b = gridview.synth("obs60", "hr")
    assert np.array_equal(np.nan_to_num(a, nan=-1), np.nan_to_num(b, nan=-1))
    assert np.nanmax(a) > 30 and np.isnan(a).sum() > 0
    # 시각을 흘리면 모양이 바뀐다(재생하면 움직여 보이게)
    c = gridview.synth("obs60", "hr", 120)
    assert not np.array_equal(np.nan_to_num(a, nan=-1), np.nan_to_num(c, nan=-1))


def test_flow_test_mode_frames_and_series():
    from datetime import datetime
    f = gridview.flow(hours=3, step=30, now=datetime(2026, 10, 1, 23, 17), test=True)
    obs = [x for x in f["frames"] if x["kind"] == "obs"]
    fc = [x for x in f["frames"] if x["kind"] == "fcst"]
    # 실측은 30분 칸만(지난 3시간) + 가장 최근(23:10)은 간격과 상관없이, 예측은 1시간씩 여섯
    assert [x["t"][8:] for x in obs] == ["2030", "2100", "2130", "2200", "2230", "2300", "2310"]
    assert [x["layer"] for x in fc] == [f"vsrt+{n}" for n in range(1, 7)]
    assert len(f["series"]) == 18 and all(len(s["max"]) == len(f["frames"]) for s in f["series"])
    assert len(f["total"]["max"]) == len(f["frames"])


def test_put_setting_validates(monkeypatch):
    saved = {}
    monkeypatch.setattr(gridview.db, "get_setting", lambda k, d: dict(d))
    monkeypatch.setattr(gridview.db, "put_setting", lambda k, v: saved.update(v))
    assert gridview.put_setting({"flow_step": 30, "tl_on": 1})["flow_step"] == 30
    assert gridview.put_setting({"overlays": ["alerts", "alerts"]})["overlays"] == ["alerts"]
    assert gridview.SETTING_DEFAULT["sel_zoom"] is True
    assert gridview.put_setting({"sel_zoom": 0})["sel_zoom"] is False
    # 지도 색 — 기본 청색, 범례 색 띠를 누르면 기상청 레이더 색
    assert gridview.SETTING_DEFAULT["pal"] == "blue"
    assert gridview.put_setting({"pal": "kma"})["pal"] == "kma"
    assert gridview.put_setting({"pal": "rich"})["pal"] == "rich"            # 다양한 색조
    # 위 카드 — 줄 세우기(시군당 n · 0 = 시군 무관) · 패널 가득
    assert gridview.SETTING_DEFAULT["acc_per"] == 1 and gridview.SETTING_DEFAULT["acc_full"] is False
    got = gridview.put_setting({"acc_per": 0, "acc_full": 1})
    assert (got["acc_per"], got["acc_full"]) == (0, True)
    # AWS 실시간 감시 — 기본 끔(정시마다)
    assert gridview.SETTING_DEFAULT["aws_live"] is False and gridview.put_setting({"aws_live": 1})["aws_live"] is True
    # 오른쪽 아래 예측 분포 재생 — 기본 끔
    assert gridview.SETTING_DEFAULT["acc_qpf"] is False and gridview.put_setting({"acc_qpf": 1})["acc_qpf"] is True
    # 재생 빠르기 — 지도(play_ms) · 초단기예측 이미지(qpf_ms) 둘 다 설정에서
    assert gridview.SETTING_DEFAULT["qpf_ms"] == 600 and gridview.put_setting({"qpf_ms": 250, "play_ms": 3000})["qpf_ms"] == 250
    # 강수 누적 카드 머리 고정 — 기본 고정(늘 보임)
    assert gridview.SETTING_DEFAULT["acc_hdr_pin"] is True and gridview.put_setting({"acc_hdr_pin": 0})["acc_hdr_pin"] is False
    # 누적 눈금 — 기본 자동(0), 범례 오른쪽 클릭으로 끝 눈금 고정
    assert gridview.SETTING_DEFAULT["acc_scale"] == 0 and gridview.put_setting({"acc_scale": 150})["acc_scale"] == 150
    # 바다 위젯 — 기본 예측 상위, 지금 오는 비 · 끔(특보 탭은 뺐다 — 왼쪽 특보 줄로)
    assert gridview.SETTING_DEFAULT["sea_w"] == "fc" and gridview.put_setting({"sea_w": "now"})["sea_w"] == "now"
    for bad in ({"flow_step": 15}, {"play_ms": 50}, {"tl_stat": "sum"}, {"layer": "nope"},
                {"overlays": ["bars"]}, {"overlays": "alerts"}, {"pal": "rainbow"}, {"acc_per": 5}, {"qpf_ms": 50},
                {"acc_scale": 100}, {"sea_w": "big"}, {"sea_w": "alert"}):
        with pytest.raises((ValueError, LookupError)):
            gridview.put_setting(bad)


def test_acc_window_custom_date(monkeypatch):
    """누적 날짜 지정 — 그날 0시부터(오늘부터 7일 앞까지). 지난 N시간 · 오늘 · 어제는 48시간까지, 날짜는 192시간까지."""
    from datetime import datetime
    end = datetime(2026, 10, 23, 15, 0)
    assert gridview.span_hours("20261020", end) == 3 * 24 + 15
    assert gridview.span_hours("yesterday", end) == 39 and gridview.span_hours(None, end, 12) == 12
    assert gridview.span_hours("20261001", end) == gridview.ACC_SPAN_MAX           # 너무 앞이면 끝까지만
    monkeypatch.setattr(gridview, "setting", lambda: {"acc_from": "date", "acc_date": "20261020", "acc_hours": 12})
    assert gridview.acc_window() == (12, "20261020")
    saved = {}
    monkeypatch.setattr(gridview.db, "get_setting", lambda k, d: dict(d))
    monkeypatch.setattr(gridview.db, "put_setting", lambda k, v: saved.update(v))
    monkeypatch.setattr(gridview.clock, "now", lambda: end)
    monkeypatch.setattr(gridview, "setting", lambda: dict(gridview.SETTING_DEFAULT))
    got = gridview.put_setting({"acc_from": "date", "acc_date": "20261020"})
    assert (got["acc_from"], got["acc_date"]) == ("date", "20261020")
    for bad in ({"acc_date": "20261010"}, {"acc_date": "20261024"}, {"acc_date": "2026-10-20"}, {"acc_from": "date"}):
        with pytest.raises(ValueError):
            gridview.put_setting(bad)

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
    for bad in ({"flow_step": 15}, {"play_ms": 50}, {"tl_stat": "sum"}, {"layer": "nope"}):
        with pytest.raises((ValueError, LookupError)):
            gridview.put_setting(bad)

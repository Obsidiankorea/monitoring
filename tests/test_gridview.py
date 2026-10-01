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

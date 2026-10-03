"""재현 사례 — 저장소에 굳혀 둔 2026.8.16~17 거제 극한호우(data/demo/map/geoje-20260816)."""
import numpy as np
import pytest

from app import gridcase

SLUG = "geoje-20260816"


def test_listing_and_meta():
    assert any(c["slug"] == SLUG for c in gridcase.listing())
    m = gridcase.meta(SLUG)
    assert m["frames"][0] == m["start"] and m["frames"][-1] == m["end"]
    assert len(m["frames"]) == 60                       # 8.16 01시 ~ 8.18 12시 매시
    # 사례를 고른 근거 — 관측소 거제(294) 이틀 927.6㎜
    assert next(c for c in m["checked"] if c["stn"] == "294")["sum"] == pytest.approx(927.6)


def test_acc_is_sum_of_hours():
    m = gridcase.meta(SLUG)
    tm = m["frames"][10]
    want = sum(gridcase.obs(SLUG, t) for t in m["frames"][:11])
    got = gridcase.acc(SLUG, tm)
    ok = np.isfinite(want)
    assert np.allclose(got[ok], want[ok]) and np.array_equal(np.isnan(got), np.isnan(want))


def test_series_matches_frames_and_calc_alerts():
    m = gridcase.meta(SLUG)
    gj = next(s for s in m["series"] if s["sigun"] == "거제")
    n = len(m["frames"])
    assert all(len(gj[k]) == n for k in ("h1", "h3", "h12", "acc", "lv"))
    assert gj["acc"][-1] == max(gj["acc"])               # 누적은 줄지 않는다
    assert "warn" in gj["lv"]                            # 거제는 산출 경보 기준을 넘는다
    # 산출 기준은 3시간·12시간 합에서 나온다
    for h3, h12, lv in zip(gj["h3"], gj["h12"], gj["lv"]):
        if lv == "warn":
            assert h3 >= 90 or h12 >= 180


def test_flow_and_guards():
    f = gridcase.flow(SLUG)
    assert len(f["frames"]) == 60 and all(x["kind"] == "obs" for x in f["frames"])
    assert len(f["series"]) == 18
    for bad in ("../x", "nope", ""):
        with pytest.raises(LookupError):
            gridcase.meta(bad)
    with pytest.raises(LookupError):
        gridcase.frame(SLUG, "obs15", None)

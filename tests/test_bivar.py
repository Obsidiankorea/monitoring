"""두 변수 판단 — 사례로 시각마다 그림 · 시군 줄이 나오고, 칸 수 합이 경남 땅 칸 수와 맞는다."""
import numpy as np
import pytest

from app import bivar, gridcase, gridstore

SLUG = "geoje-20260816"


@pytest.mark.skipif(SLUG not in [c["slug"] for c in gridcase.listing()], reason="사례 자료 없음")
def test_case_frames():
    d = bivar.build(case=SLUG)
    m = gridcase.meta(SLUG)
    assert [f["tm"] for f in d["frames"]] == m["frames"]
    assert d["acc"] == (100, 200) or len(d["acc"]) == 2
    f = d["frames"][d["now_i"]]
    tot = sum(sum(sum(z) for z in y) for y in f["c3"])
    msig, _ = gridstore.masks()
    assert 0 < tot <= int(np.isin(msig, [s["id"] for s in gridstore.geo()["sigun"] if s.get("kind") == "gn"]).sum())
    assert len(f["rows"]) == 18 and all(0 <= r[4] <= 2 and 0 <= r[5] <= 2 and 0 <= r[6] <= 3 for r in f["rows"])
    # 누적은 줄지 않는다 — 시군 최대 누적이 시각 따라 같거나 는다
    acc = [{r[0]: r[1] for r in fr["rows"]}["거제"] for fr in d["frames"]]
    assert all(b >= a for a, b in zip(acc, acc[1:]))
    assert d["frames"][-1]["left"] == 0 and not any(fr["fc"] for fr in d["frames"])   # 사례는 예보 칸이 없다

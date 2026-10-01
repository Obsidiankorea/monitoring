"""격자 저장 — 자르기, uint16 부호화, 보관, 시군 통계."""
import gzip
from datetime import datetime

import numpy as np
import pytest

from app import gridstore as gs
from app.domain import gridproj


def test_encode_values():
    a = np.array([0, 0.04, 0.1, 12.34, 9999, np.nan, -1.0])
    u = np.frombuffer(gs.encode(a), "<u2").tolist()
    # 0.04 는 0.1㎜ 아래라 무강수로, 너무 큰 값은 65533 에서 막고, NaN·음수는 결측
    assert u == [0, 0, 1, 123, 65533, 65535, 65535]


def test_encode_decode_roundtrip():
    h, w = gs.shape("hr")
    rng = np.random.default_rng(0)
    a = np.round(rng.uniform(0, 80, (h, w)), 1)
    a[5, 7] = np.nan
    b = gs.decode(gs.encode(a), "hr")
    assert np.isnan(b[5, 7])
    ok = ~np.isnan(a)
    assert np.allclose(a[ok], b[ok], atol=1e-9)


def test_crop_hr_corners():
    full = np.arange(2049 * 2049, dtype="f8").reshape(2049, 2049)
    c = gs.crop_hr(full)
    b = gs.geo()["hr"]["bbox"]
    assert c.shape == (b["h"], b["w"])
    # 행은 남→북 그대로 — 뒤집지 않는다
    assert c[0, 0] == full[b["j0"], b["i0"]]
    assert c[-1, -1] == full[b["j1"], b["i1"]]


def test_crop_dfs_missing_and_size():
    g = gs.geo()["dfs"]
    vals = np.zeros(g["nx"] * g["ny"])
    b = g["bbox"]
    vals[(b["j0"] + 3) * g["nx"] + b["i0"] + 2] = -99
    vals[(b["j0"] + 4) * g["nx"] + b["i0"] + 2] = -999
    vals[(b["j0"] + 5) * g["nx"] + b["i0"] + 2] = 7.5
    c = gs.crop_dfs(vals)
    assert c.shape == (b["h"], b["w"])
    assert np.isnan(c[3, 2]) and np.isnan(c[4, 2]) and c[5, 2] == 7.5 and c[0, 0] == 0
    with pytest.raises(ValueError):
        gs.crop_dfs(vals[:-1])


def test_save_load_prune(store):
    h, w = store.shape("hr")
    a = np.zeros((h, w))
    a[1, 1] = 3.2
    store.save("obs60", "202609270000", a)       # 사흘 넘었다
    store.save("obs60", "202610010800", a)
    for t in ("0750", "0800", "0810", "0820"):  # 초단기 발표분 넷
        store.save("vsrt", f"20261001{t}_202610010900", np.zeros(store.shape("dfs")))
    assert store.load("obs60", "202610010800")[1, 1] == pytest.approx(3.2)
    raw = gzip.decompress(store.raw_gz("obs60", "202610010800"))
    assert len(raw) == h * w * 2
    store.prune(now=datetime(2026, 10, 1, 9, 0))
    assert store.keys("obs60") == ["202610010800"]
    assert [k[:12] for k in store.keys("vsrt")] == ["202610010800", "202610010810", "202610010820"]


def _cell_of(name):
    """그 시군 안쪽 칸 하나(마스크 기준)."""
    sig = next(s for s in gs.geo()["sigun"] if s["name"] == name)
    msig, _ = gs.masks()
    rr, cc = np.nonzero(msig == sig["id"])
    k = len(rr) // 2
    return int(rr[k]), int(cc[k])


def test_sigun_stats_max_where_and_missing():
    h, w = gs.shape("hr")
    a = np.zeros((h, w))
    r, c = _cell_of("창원")
    a[r, c] = 42.5
    jr, jc = _cell_of("진주")
    a[jr, jc] = np.nan
    a[jr, jc + 1] = 4.0
    rows = {x["sigun"]: x for x in gs.sigun_stats(a)}
    cw = rows["창원"]
    assert cw["max"] == 42.5
    hb = gs.geo()["hr"]["bbox"]
    assert (cw["where"]["col"], cw["where"]["row"]) == (c + hb["i0"], r + hb["j0"])
    _, memd = gs.masks()
    emd = next((e for e in gs.geo()["emd"] if e["id"] == int(memd[r, c])), None)
    if emd and emd["sigun"] == "창원":
        assert cw["where"]["emd"] == emd["name"]
    # 결측은 평균에서 빼고 따로 센다 — 0 으로 치지 않는다
    jj = rows["진주"]
    assert jj["missing"] == 1
    assert jj["mean"] == pytest.approx(4.0 / (jj["cells"] - 1), abs=0.01)
    # 비가 없으면 위치도 없다
    assert rows["거창"]["max"] == 0.0 and rows["거창"]["where"] is None


def test_to_hr_places_5km_cell_on_right_spot():
    """창원 관측소가 드는 5km 칸(X=89, Y=75)을 펼치면 관측소의 500m 칸에 그 값이 온다."""
    b = gs.geo()["dfs"]["bbox"]
    a5 = np.zeros(gs.shape("dfs"))
    a5[74 - b["j0"], 88 - b["i0"]] = 10.0
    hr = gs.to_hr(a5)
    col, row = gridproj.hr_xy(128.57282, 35.17019)
    hb = gs.geo()["hr"]["bbox"]
    assert hr[round(row) - hb["j0"], round(col) - hb["i0"]] == 10.0
    # 5km 칸 하나 ≈ 500m 칸 100개
    assert 80 <= int((hr == 10.0).sum()) <= 120

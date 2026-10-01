"""500m NetCDF 읽기와 수집 시각 규칙."""
import asyncio
import io
from datetime import datetime

import numpy as np
import pytest

h5py = pytest.importorskip("h5py")

from app.collectors import grid_rain  # noqa: E402
from app.kma import KmaError  # noqa: E402


def _nc(**attrs) -> bytes:
    """기상청 NetCDF 와 같은 꼴(전역 속성 + int16 data, data_scale 10)."""
    buf = io.BytesIO()
    with h5py.File(buf, "w") as f:
        for k, v in {**grid_rain.FRAME, **attrs}.items():
            f.attrs[k] = np.array([v], dtype="f4")
        d = np.zeros((2049, 2049), dtype="i2")
        d[900, 1300] = 123            # 12.3㎜
        d[0, 0] = -9990               # 결측
        ds = f.create_dataset("data", data=d)
        ds.attrs["data_scale"] = np.array([10.0], dtype="f4")
    return buf.getvalue()


def test_parse_nc_values_and_order():
    a = grid_rain.parse_nc(_nc())
    assert a.shape == (2049, 2049)
    assert a[900, 1300] == pytest.approx(12.3)   # 행·열을 뒤집지 않는다
    assert np.isnan(a[0, 0])
    assert a[1, 1] == 0


def test_parse_nc_refuses_changed_frame():
    """원점 칸이 바뀐 격자는 그리지 않는다 — 경계와 어긋난 자리에 비가 그려진다."""
    with pytest.raises(KmaError, match="격자 틀"):
        grid_rain.parse_nc(_nc(map_sx=881))


@pytest.mark.parametrize("now,want", [
    (datetime(2026, 10, 1, 8, 13, 20), ["202610010805", "202610010800"]),
    (datetime(2026, 10, 1, 8, 10, 59), ["202610010800", "202610010755"]),
])
def test_hr_slots(now, want):
    assert [t.strftime("%Y%m%d%H%M") for t in grid_rain.hr_slots(now)] == want


def test_collect_skips_midnight_day_total(store, monkeypatch):
    """일강수 00:00(전날 총량)·00:05(반쯤 리셋)는 받지 않는다."""
    calls = []

    async def fake(obs, tm):
        calls.append((obs, tm))
        return np.zeros((2049, 2049))

    monkeypatch.setattr(grid_rain, "_fetch_hr", fake)
    monkeypatch.setattr(grid_rain.db, "log_collect", lambda *a, **k: None)
    asyncio.run(grid_rain.collect(now=datetime(2026, 10, 2, 0, 11)))     # 슬롯 00:05, 00:00
    assert ("rn_day", "202610020005") not in calls
    assert ("rn_day", "202610020000") not in calls
    assert ("rn_60m", "202610020005") in calls
    assert store.keys("obsday") == []


def test_collect_steps_back_when_not_ready(store, monkeypatch):
    async def fake(obs, tm):
        return None if tm.endswith("0805") else np.zeros((2049, 2049))   # 08:05 는 아직

    monkeypatch.setattr(grid_rain, "_fetch_hr", fake)
    monkeypatch.setattr(grid_rain.db, "log_collect", lambda *a, **k: None)
    res = asyncio.run(grid_rain.collect(now=datetime(2026, 10, 1, 8, 13)))
    assert res["got"] == {"obs15": "202610010800", "obs60": "202610010800", "obsday": "202610010800"}

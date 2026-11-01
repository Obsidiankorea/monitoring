"""조위 — 응답 읽기 · 단계 · 만조 찾기 · 대조기 계산 · 지점 묶기."""
from datetime import date, datetime, timedelta

import pytest

from app import tide

MASAN = next(s for s in tide.STATIONS if s["name"] == "마산")
TONG = next(s for s in tide.STATIONS if s["name"] == "통영")
SAM = next(s for s in tide.STATIONS if s["name"] == "삼천포")


def test_parse_and_error():
    j = {"header": {"resultCode": "00"}, "body": {"items": {"item": [{"obsrvnDt": "2026-11-01 08:30", "bscTdlvHgt": 75.0, "tdlvHgt": 73.8}]}}}
    assert tide.parse(j) == [("202611010830", 75.0, 73.8)]
    with pytest.raises(RuntimeError):
        tide.parse({"header": {"resultCode": "22", "resultMsg": "LIMITED"}})


def test_stage_by_station():
    assert [tide.stage(MASAN, v) for v in (75, 162, 181.9, 228, 300)] == [0, 1, 1, 3, 4]
    assert tide.stage(TONG, 322) == 1 and tide.stage(SAM, 200) is None
    assert [x["name"] for x in tide.STATIONS if "창원" in x["sigun"]][0] == "마산"    # 창원 보고는 마산 값으로


def test_highs():
    p = [("a", 1.0), ("b", 3.0), ("c", 2.0), ("d", 4.0), ("e", 4.0), ("f", 1.0)]
    assert [h[0] for h in tide.highs(p)] == ["b", "e"]


def test_spring_real_series():
    v = [190, 186, 196, 208, 221, 232, 242, 260, 276, 285, 284, 275, 259, 238, 221, 212, 213, 219, 224, 228, 241, 250, 254, 254, 250, 244, 235, 224, 211, 199, 190, 189, 193, 201]
    days = [(date(2026, 10, 18) + timedelta(days=i), float(x)) for i, x in enumerate(v)]     # 통영 2026-10-18~ 실제 예측
    s = tide.spring(days, date(2026, 11, 1))
    assert s == {"now": False, "from": "2026-11-07", "to": "2026-11-12"}
    assert tide.spring(days, date(2026, 11, 9))["now"]


def test_build_and_text():
    now = datetime(2026, 11, 1, 8, 35)
    today = [("202611010800", 80.0, 79.0), ("202611010830", 75.0, 73.8), ("202611010840", None, 72.0)]
    base = datetime(2026, 11, 1, 9, 0)
    pred = [((base + timedelta(hours=i)).strftime("%Y%m%d%H%M"), 100 + (90 if i in (5, 29) else 0) + (i == 29) * 30.0) for i in range(60)]
    r = tide.build({**MASAN}, today, pred, now)
    assert r["v"] == 75.0 and r["diff"] == 1.2 and r["stage"] == 0
    assert r["next"]["t"] == "202611011400" and r["next"]["stage"] == 2      # 190cm — 주의
    assert r["top"]["h"] == 220 and r["top"]["stage"] == 2                   # 7일 안 최고
    assert r["wet"] == ["진해 용원 의창수협"]                                  # 220 ≥ 지반고 182 만
    t = tide.text(r, 12)
    assert "다음 만조" in t and "앞으로 6시간 비 12㎜" in t and "의창수협" in t


def test_no_observed_row_is_none():
    assert tide.build({**MASAN}, [("202611010000", None, 1.0)], [], datetime(2026, 11, 1)) is None


def test_spring_shows_in_sigun_text_and_summary(monkeypatch):
    r = tide.build({**MASAN}, [("202611010830", 75.0, 73.8)], [], datetime(2026, 11, 1, 8, 35))
    monkeypatch.setitem(tide._LIVE, "rows", [r])
    monkeypatch.setitem(tide._LIVE, "spring", {"now": True, "from": "2026-11-07", "to": "2026-11-11"})
    assert "대조기" in tide.text(r)
    s = tide.summary()
    assert len(s) == 1 and "11-07 ~ 11-11" in s[0]                      # 평소 지점 줄은 없고 대조기 한 줄만
    monkeypatch.setitem(tide._LIVE, "spring", {"now": False, "from": "2026-11-07", "to": "2026-11-11"})
    assert tide.summary() == [] and "대조기" not in tide.text(r)

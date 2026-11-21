"""폭염 화면 — 시군 최고 지점 · 변화 · 오늘 최고 · 결측 거르기."""
from app import heat
from app.queries import STN_SIGUN

SIG = next(iter(set(STN_SIGUN.values())))
STNS = [s for s, v in STN_SIGUN.items() if v == SIG]


def test_empty():
    assert heat.build([]) == {"tm": None, "n": 0, "rows": []}


def test_sigun_max_delta_and_high():
    a = STNS[0]
    obs = [(a, "2026-08-01 13:00", 34.0), (a, "2026-08-01 14:00", 35.5), (a, "2026-08-01 15:00", 35.0),
           (a, "2026-07-31 23:00", 28.0), (a, "2026-08-01 15:00", -99.0)]
    r = heat.build(obs)
    row = r["rows"][0]
    assert r["tm"] == "2026-08-01 15:00" and row["ta"] == 35.0
    assert row["dt"] == -0.5 and row["hi"] == 35.5                    # 어제 값은 오늘 최고에 넣지 않는다
    assert row["d"] == [28.0, 34.0, 35.5, 35.0]


def test_off_station_is_dropped():
    assert heat.build([(STNS[0], "2026-08-01 15:00", 35.0)], {STNS[0]})["rows"] == []

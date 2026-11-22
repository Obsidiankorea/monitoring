"""겨울 화면 — 체감온도 · 실효습도 · 특보 기준 단계 · 시군 묶기."""
from app import cold
from app.queries import STN_SIGUN

SIG = next(iter(set(STN_SIGUN.values())))
STNS = [s for s, v in STN_SIGUN.items() if v == SIG]


def test_feel():
    assert cold.feel(5.0, 1.0) == 5.0                     # 바람 약하면 기온 그대로
    assert cold.feel(15.0, 10.0) == 15.0                  # 10℃ 넘으면 그대로
    assert cold.feel(-5.0, 5.0) == -11.2                  # 18 km/h


def test_effective_hm():
    assert cold.effective_hm([50, 50, 50, 50, 50]) == round(0.3 * 50 * (1 + .7 + .49 + .343 + .2401), 1)
    assert cold.effective_hm([50, None, 50, 50, 50]) is None


def test_levels():
    assert cold.levels(-12.5, None, 3, 5, 60)["cold"] == "watch"
    assert cold.levels(2.0, 11, 3, 5, 60)["cold"] == "watch"         # 10℃ 넘게 내려 3℃ 이하
    assert cold.levels(-16, None, 0, 0, None) == {"cold": "warn", "wind": "", "dry": ""}
    assert cold.levels(0, 0, 9, 21, 30) == {"cold": "", "wind": "watch", "dry": "watch"}
    assert cold.levels(0, 0, 11, 0, 44)["dry"] == "near"


def test_build_sigun_worst_station():
    a, b = STNS[0], (STNS[1] if len(STNS) > 1 else STNS[0])
    obs = [(a, "2026-11-21 06:00", 4.0, 1.0, 60.0), (a, "2026-11-22 06:00", -11.0, 2.0, 40.0),
           (a, "2026-11-22 10:00", -3.0, 6.0, 35.0), (b, "2026-11-22 10:00", -1.0, 9.0, 50.0)]
    r = cold.build(obs, {b: 15.5})
    row = r["rows"][0]
    assert r["tm"] == "2026-11-22 10:00" and row["ta"] == -3.0 and row["tmin"] == -11.0
    assert row["drop"] == 15.0 and row["lv"]["cold"] == "warn"      # 전날보다 15℃ 내려 3℃ 이하 = 경보 기준
    assert row["ws"] == (9.0 if b != a else 6.0)
    assert row["he"] is None and r["he_ready"] is False              # 앞 4일 습도가 없다


def test_empty():
    assert cold.build([]) == {"tm": None, "n": 0, "rows": []}

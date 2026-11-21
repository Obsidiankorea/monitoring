"""전망 — 특보 · 단기예보를 새 발표일수록 무겁게. 지금 비가 같은 말을 하면 묵어도 깎지 않는다."""
from datetime import datetime

from app import ai
from app.collectors import alerts

NOW = datetime(2026, 10, 30, 17, 0)
AL = lambda at: [{"name": "호우경보", "at": at}]    # noqa: E731


def test_newer_alert_weighs_more():
    new = ai.outlook(AL("202610301630"), [], {}, 0, 0, 0, NOW)
    old = ai.outlook(AL("202610301300"), [], {}, 0, 0, 0, NOW)
    assert new["score"] > old["score"]
    assert new["level"] == "높음"


def test_backed_by_rain_keeps_full_weight():
    o = ai.outlook(AL("202610301000"), [], {}, 50, 30, 10, NOW)     # 7시간 묵었지만 80㎜ 가 왔거나 온다
    p = next(x for x in o["parts"] if x["src"] == "특보")
    assert p["backed"] and p["w"] == 1.0


def test_active_alert_never_low():
    o = ai.outlook([{"name": "호우주의보", "at": "202610290000"}], [], {}, 0, 0, 0, NOW)
    assert o["level"] == "주의"                                     # 하한 — 발효 중인 특보를 없는 셈 치지 않는다


def test_short_forecast_and_quiet():
    o = ai.outlook([], [], {"today": {"max": 120, "tmfc": "202610301400"}}, 0, 0, 0, NOW)
    assert o["parts"][0]["src"] == "단기예보" and o["score"] >= .3
    assert ai.outlook([], [], {"today": {"max": 5, "tmfc": "202610301400"}}, 0, 0, 0, NOW)["level"] == "낮음"


def test_old_hhmm_and_unknown_time():
    assert ai._fc_dt("23:50", NOW) == datetime(2026, 10, 29, 23, 50)  # 옛 스냅숏 — 지금보다 늦으면 어제
    assert ai.weight(None, False) == 1.0


def test_collector_keeps_time_per_sigun():
    row = lambda reg, fc: ["", "경상남도", "", reg, fc, "202610301000", "호우", "주의", "발표", ""]    # noqa: E731
    d = alerts.normalize("\n".join(",".join(row(r, f)) for r, f in (("창원시", "202610301000"), ("창원시", "202610301500"), ("진주시", "202610301200"))),
                         NOW)
    g = d["groups"][0]
    assert g["at"]["창원"] == "202610301500" and g["at"]["진주"] == "202610301200"
    assert ai.alert_times(d["groups"], "창원") == [{"name": g["name"], "at": "202610301500"}]

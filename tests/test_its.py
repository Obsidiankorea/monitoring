from datetime import datetime

from app import its

NOW = datetime(2026, 8, 21, 18, 30)


def _x(name, end="-", links="", kind="D03", at="20260821181000"):
    return {"eventType": kind, "socName": name, "linkId": links, "endDate": end, "startDate": at}


def test_parse_keeps_live_gyeongnam_flood_events_only():
    items = [_x(" [침수위험경보]합천군중부"), _x("밀양시 호우경보", "202608211858", "3860006902,3860338500"), _x("호우경보", links="3870206300"),
             _x("서울서북권", links="1120026000"), _x("호우경보"), _x("거창군", "202608211800"), _x("경상남도 하동군 산불", kind="D07")]
    got = its.parse({"body": {"items": items}}, NOW)
    assert [(r["name"], r["links"]) for r in got] == [("합천군중부", 0), ("밀양시", 2), ("지역 이름 없음", 1)]
    assert its.parse({"body": {}}, NOW) == []


def test_calls_reset_each_month(monkeypatch):
    monkeypatch.setattr(its.db, "get_setting", lambda k, d: {"ym": "202608", "n": 7})
    assert its.calls(NOW) == 7 and its.calls(datetime(2026, 9, 1)) == 0

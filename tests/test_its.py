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


def test_link_lines_from_nodelink(monkeypatch):
    """경남 링크 번호 → 표준노드링크 선(칸 좌표). 모르는 번호 · 다른 도 번호는 뺀다. status 의 줄마다 lines."""
    any_id = "3860006902"                                      # 밀양(2026 여름 실제 응답의 링크) — 표준노드링크 2026-11-11 판에 있다
    got = its.link_lines([any_id, "3899999999", "1120026000"])
    assert len(got) == 1 and len(got[0]) >= 2 and all(len(p) == 2 for p in got[0])
    rows = its.parse({"body": {"items": [_x("밀양시 호우경보", links=f"{any_id},1120026000")]}}, NOW)
    assert rows[0]["ids"] == [any_id] and rows[0]["links"] == 2
    monkeypatch.setitem(its._LIVE, "rows", rows)
    monkeypatch.setattr(its, "hoou", lambda: True)
    assert its.status()["rows"][0]["lines"] == got


def test_gyeongnam_links_by_place_not_prefix():
    """경남 링크는 38x 만이 아니다 — 창원 418x · 합천 398x 도 경남, 세종 413x 는 아니다(이름 없는 경보로)."""
    items = [_x("호우경보", links="4180000100"), _x("호우경보", links="3980000100", at="20260821180500"), _x("호우경보", links="4130126900")]
    got = its.parse({"body": {"items": items}}, NOW)
    assert [r["ids"] for r in got] == [["4180000100"], ["3980000100"]]

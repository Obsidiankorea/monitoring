"""상황판단회의 자료 셋(app/meeting.py) — 특보 시군 고르기 · 우려지역 · 과거 사례(A 등급 · 종류 먼저) · 조위(해당할 때만) · 켜고 끄기."""
from app import ai, contacts, judge, meeting, queries, terrain, tide

EV = "event_id,재해유형,신뢰도\n20250716_호우,호우,A\n20220905_태풍힌남노,태풍,A\n20030912_태풍매미,태풍,B\n"
DMG = ("event_id,시군,총피해액_천원,특별재난지역여부,산사태복구건수,max1h,max1h_stn,max24h\n"
       "20250716_호우,합천군,108440000,Y,64,81.5,삼가,395.5\n20220905_태풍힌남노,합천군,200000000,,,,,\n"
       "20030912_태풍매미,합천군,999999999,Y,,,,\n")


def _alerts(groups, pending=()):
    return lambda: {"fetched_at": "2026-11-17T10:00", "data": {"groups": groups, "pending": list(pending)}}


def test_alert_siguns_only_disaster_kinds(monkeypatch):
    monkeypatch.setattr(queries, "alerts", _alerts([{"name": "호우주의보", "siguns": ["합천", "창원"]}, {"name": "건조주의보", "siguns": ["진주"]}],
                                                   [{"name": "강풍", "sigun": "거제"}]))
    sgs, names, at = meeting.alert_siguns()
    assert sgs == ["창원", "거제", "합천"] and names == ["호우주의보", "강풍 예비"] and at == "2026-11-17T10:00"   # 경남 차례 · 건조는 뺀다


def test_past_lines_grade_a_kind_first(tmp_path, monkeypatch):
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "경남 풍수해 사건 이력.csv").write_text(EV, "utf-8")
    (tmp_path / "data" / "경남 풍수해 사건×시군 피해.csv").write_text(DMG, "utf-8")
    monkeypatch.setattr(ai, "wiki", lambda: tmp_path)
    got = meeting.past_lines(["합천"], ["호우"])
    assert got[0]["text"] == "**합천군** — 2025.7 호우: 피해 1,084.4억 · 1시간 최대 81.5mm(삼가) · 24시간 395.5mm · 산사태 복구 64건 · 특별재난지역"
    assert got[0]["subs"] == ["- 2022.9 태풍힌남노: 피해 2,000.0억"]                   # 호우가 먼저(피해는 태풍이 커도) · B 등급 매미는 없다
    assert got[-1]["text"].startswith("※ 경남도 피해현황 및 복구계획(A 등급")
    assert meeting.past_lines([], ["호우"]) == meeting.NO_ALERT


def test_district_lines_counts_and_no_names(monkeypatch):
    ds = [{"id": "a", "fam": "산사태", "name": "가지구"}, {"id": "b", "fam": "하천", "name": "나지구"}, {"id": "c", "fam": "산사태", "name": "다지구"}]
    monkeypatch.setattr(contacts, "districts", lambda sg: {"emd": {"읍": ds}})
    monkeypatch.setattr(terrain, "table", lambda: {"built": "2026-11-13", "rows": {"a": {"b100": 3, "b300": 10, "bo": 2}, "b": {"b100": 1, "b300": 5}}})
    monkeypatch.setattr(judge, "_BC", {("all",): (1.0, {"computed_at": "2026-11-17T09:58:00", "rows": [
        {"sigun": "합천", "b": {"grid": {"st": {"통제": {"met": True}, "사전대피": {"met": True}}}}},
        {"sigun": "합천", "b": {"grid": {"st": {"통제": {"met": True}}}}}]})})
    got, basis = meeting.district_lines(["합천"])
    assert got[0]["text"] == "**합천군** 우려지구 3곳 — 산사태 2 · 하천 1"
    assert got[0]["subs"] == ["- 지구 둘레 건물 100m 안 4동 · 300m 안 15동 · 그중 오래된 약한 구조 2동(지구끼리 겹쳐 센다)",
                              "- 지금 판정: 통제 필요 2 · 사전대피 1 · 긴급대피 0곳(판정한 2곳 가운데)"]
    assert got[-1]["text"].startswith("※ 판정 09:58 기준(지도 상황판단)") and basis[0]["at"] == "2026-11-17 09:58"
    assert "가지구" not in str(got)                                                    # 지구 이름 · 사람은 쓰지 않는다


def test_tide_only_when_relevant_and_toggles(monkeypatch):
    row = {"name": "마산", "sigun": ["창원"], "t": "202611170950", "cuts": [1], "scale": "고조정보", "names": ["안전", "관심"],
           "next": {"t": "202611171350", "h": 125.0, "stage": 0}, "wet": []}
    monkeypatch.setattr(tide, "status", lambda: {"rows": [row]})
    monkeypatch.setattr(tide, "_spring_text", lambda: None)
    assert meeting.tide_lines(["합천"], ["강풍주의보"]) == (None, [])                  # 해안 시군도 태풍 · 풍랑 · 호우도 아니다
    t, b = meeting.tide_lines(["창원"], ["강풍주의보"])
    assert t[0]["text"] == "다음 만조 — 마산 17일 13:50 125cm(고조정보 안전)" and b[0]["at"] == "11.17. 09:50 관측"
    monkeypatch.setattr(queries, "alerts", _alerts([]))
    body, _ = meeting.extras(["호우"], {"과거사례": False})
    assert body == {"특보지역현황": meeting.NO_ALERT}                                   # 특보 없음 · 과거는 끔 · 조위는 해당 없음(본문에 없다)

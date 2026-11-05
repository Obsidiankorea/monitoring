"""연락처 — 상황판단 모드(/api/contacts)에서만, AI 쪽 코드는 모른다, 잠금 번호."""
import re
from pathlib import Path

from fastapi.testclient import TestClient

from app import contacts, main

APP = Path(__file__).resolve().parent.parent / "app"


def test_ai_code_never_touches_contacts():
    """AI 맥락을 만드는 코드가 연락처 모듈 · 파일을 부르면 LLM 에 번호가 샐 수 있다."""
    for f in ("ai.py", "aireport.py", "llm.py", "aiwatch.py"):
        src = (APP / f).read_text("utf-8")
        assert not re.search(r"\bcontacts\b|contacts\.csv", src), f


def test_contacts_by_sigun_and_pin(tdb, tmp_path, monkeypatch):
    f = tmp_path / "contacts.csv"
    f.write_text("﻿지역ID,시군,읍면동,리,지구명,담당1,담당1_연락처,담당1_연락처_정규화,담당2,담당2_연락처,담당2_연락처_정규화,연락처확인\n"
                 "48125-3.2-001,창원시,북면,무곡리,가지구,과 주무관,010 0000 0001,010-0000-0001,이장,,,\n"
                 "48310-3.2-001,거제시,동부면,,나지구,과,055-000-0000,055-000-0000,,,,\n", "utf-8")
    monkeypatch.setattr(contacts, "FILE", f)
    contacts._C.clear()
    main._PIN_FAIL.clear()
    c = TestClient(main.app)
    j = c.get("/api/contacts?sigun=창원").json()
    assert list(j["people"]) == ["48125-3.2-001"] and j["people"]["48125-3.2-001"][0]["tel"] == "010-0000-0001"
    assert len(j["people"]["48125-3.2-001"]) == 2                     # 번호 없는 이장도 이름은 보인다
    assert c.put("/api/settings/contacts-pin", json={"new": "12"}).status_code == 400
    assert c.put("/api/settings/contacts-pin", json={"new": "4821"}).json()["locked"]
    assert c.get("/api/contacts?sigun=창원").status_code == 401
    assert c.get("/api/contacts?sigun=창원", headers={"x-pin": "4821"}).status_code == 200
    for _ in range(5):
        c.get("/api/contacts?sigun=창원", headers={"x-pin": "0000"})
    assert c.get("/api/contacts?sigun=창원", headers={"x-pin": "4821"}).status_code == 429   # 많이 틀리면 잠시 막는다
    main._PIN_FAIL.clear()
    assert c.put("/api/settings/contacts-pin", json={"old": "0000", "new": ""}).status_code == 401


def test_districts_from_wiki_without_pin(tdb, tmp_path, monkeypatch):
    """지구 이름 · 주소는 위키 공개 자료 — 연락처 파일 · 잠금과 상관없이 보인다."""
    from app import ai
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "인명피해 우려지역.csv").write_text(
        "﻿유형,원문구분,시군,지구명,읍면동,리,지번,가구,인원,대피기준,대피장소,안전취약계층,지역ID\n"
        "산사태,x,창원시,가지구,진동면,교동리,12,1,1,누적강우 250mm이상,교동마을회관,,48120-3.2-001\n", "utf-8")
    monkeypatch.setattr(ai, "wiki", lambda: tmp_path)
    tdb.put_setting("contacts_pin", "x")                                 # 잠겨 있어도
    d = TestClient(main.app).get("/api/districts?sigun=창원").json()["emd"]["진동면"][0]
    assert (d["name"], d["ri"], d["jibun"], d["fam"], d["shelter"], d["rule"]) == ("가지구", "교동리", "12", "산사태", "교동마을회관", "누적강우 250mm이상")

"""현장 회신 — 지구마다 링크 하나: 담당자 등록 · 교대(둘까지, 지난 담당은 남는다) → 대시보드 연락처 반영 → 회신이 기록으로 쌓인다.
밖에 여는 서버에는 /r/ 만, 연락처 파일의 이름 · 번호는 현장 페이지에 안 나간다."""
import base64
import io
import re
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from app import ai, contacts, main, reply

CSV = ("﻿지역ID,시군,읍면동,리,지구명,담당1,담당1_연락처,담당1_연락처_정규화,담당2,담당2_연락처,담당2_연락처_정규화,연락처확인\n"
       "48125-3.2-001,창원시,북면,무곡리,가지구,김파일,010 0000 0001,010-0000-0001,이장,,,\n"
       "48125-3.2-002,창원시,북면,,나지구,김파일,010-0000-0001,010-0000-0001,,,,\n"
       "48310-3.2-001,거제시,동부면,,다지구,과,055-000-0000,055-000-0000,,,,\n")
A = "48125-3.2-001"


def _photo() -> str:
    b = io.BytesIO()
    Image.new("RGB", (3000, 2000), (40, 90, 160)).save(b, "JPEG")
    return "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()


def _setup(tmp_path, monkeypatch):
    f = tmp_path / "contacts.csv"
    f.write_text(CSV, "utf-8")
    monkeypatch.setattr(contacts, "FILE", f)
    monkeypatch.setattr(reply, "DIR", tmp_path / "replies")
    monkeypatch.setattr(ai, "wiki", lambda: tmp_path / "nowiki")        # 위키가 없어도 연락처 파일로 지구를 안다
    contacts._C.clear()
    main._PIN_FAIL.clear()


def test_duty_page(tdb, tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    c, pub = TestClient(main.app), TestClient(reply.public_app)
    j = c.post("/api/reply/ask", json={"rids": [A, "48125-3.2-002", "48310-3.2-001", "없는것"], "note": "통제 여부", "base": "https://r.example/"}).json()
    assert [z["name"] for z in j["nophone"]] == ["다지구"]               # 일반 전화뿐 — 링크만
    (kim,) = j["people"]                                               # 같은 번호가 맡은 두 지구는 문자 하나에
    assert kim["tel"] == "01000000001" and kim["names"] == ["가지구", "나지구"] and kim["sms"].count("https://r.example/r/") == 2
    url = re.search(r"가지구 (\S+)", kim["sms"]).group(1)
    tok = url.rsplit("/", 1)[1]
    again = c.post("/api/reply/ask", json={"rids": [A], "base": "https://r.example"}).json()
    assert url in again["people"][0]["sms"]                            # 링크는 지구에 붙어 변하지 않는다

    assert pub.get(f"/r/{tok}").status_code == 200 and pub.get("/r/nope/data").status_code == 404
    d = pub.get(f"/r/{tok}/data")
    assert d.json()["name"] == "가지구" and d.json()["people"] == [] and [x["kind"] for x in d.json()["log"]] == ["ask", "ask"]
    assert "김파일" not in d.text and "0000" not in d.text               # 연락처 파일의 이름 · 번호는 안 나간다

    # 등록 전에는 회신을 못 올린다 → 등록(둘까지) → 셋째는 거절
    assert pub.post(f"/r/{tok}", json={"id": 1, "action": "done", "more": "no"}).status_code == 400
    assert pub.post(f"/r/{tok}/join", json={"rank": "주무관", "name": "", "tel": "010-1111-2222"}).status_code == 400
    assert pub.post(f"/r/{tok}/join", json={"rank": "주무관", "name": "박현장", "tel": "055-111-2222"}).status_code == 400
    p1 = pub.post(f"/r/{tok}/join", json={"rank": "주무관", "name": "박현장", "tel": "010-1111-2222"}).json()["id"]
    assert pub.post(f"/r/{tok}/join", json={"rank": "주무관", "name": "박현장", "tel": "01011112222"}).json()["id"] == p1   # 같은 번호로 또 눌러도 한 사람
    p2 = pub.post(f"/r/{tok}/join", json={"rank": "", "name": "최이장", "tel": "010-3333-4444"}).json()["id"]
    assert pub.post(f"/r/{tok}/join", json={"rank": "팀장", "name": "정셋째", "tel": "010-5555-6666"}).status_code == 409

    # 대시보드 연락처에 반영 — 등록한 사람이 파일의 담당자를 대신한다(다른 지구는 파일 그대로)
    ppl = c.get("/api/contacts?sigun=창원").json()["people"]
    assert ppl[A] == [{"who": "주무관 박현장", "tel": "01011112222"}, {"who": "최이장", "tel": "01033334444"}]
    assert ppl["48125-3.2-002"][0]["who"] == "김파일"
    assert A in c.get("/api/contacts?sigun=all").json()["people"] and A not in c.get("/api/contacts?sigun=거제").json()["people"]
    assert "01011112222" in c.post("/api/reply/ask", json={"rids": [A]}).json()["people"][0]["tel"]   # 다음 요청은 등록한 사람에게

    # 회신 — 고치지 않고 쌓인다
    assert pub.post(f"/r/{tok}", json={"id": p1, "action": "done"}).status_code == 400              # 추가 배치를 안 골랐다
    assert pub.post(f"/r/{tok}", json={"id": p1, "action": "doing", "more": "yes", "photo": "data:,xx"}).status_code == 400
    assert not any(x["kind"] == "reply" for x in pub.get(f"/r/{tok}/data").json()["log"])           # 깨진 사진이면 줄도 안 남는다
    assert pub.post(f"/r/{tok}", json={"id": p1, "action": "doing", "more": "yes", "memo": "차단봉 설치 중", "photo": _photo()}).status_code == 200
    assert pub.post(f"/r/{tok}", json={"id": p2, "action": "done", "more": "no"}).status_code == 200
    log = pub.get(f"/r/{tok}/data").json()["log"]
    assert [(x["who"], x["action"]) for x in log if x["kind"] == "reply"] == [("최이장", "done"), ("주무관 박현장", "doing")]
    lid = next(x["id"] for x in log if x["photo"])
    assert max(Image.open(io.BytesIO(pub.get(f"/r/{tok}/photo/{lid}").content)).size) == 1600        # 큰 사진은 줄여 둔다
    other = re.search(r"나지구 (\S+)", kim["sms"]).group(1).rsplit("/", 1)[1]
    assert pub.get(f"/r/{other}/photo/{lid}").status_code == 404                                    # 다른 지구 링크로는 못 본다

    # 교대 — 빠진 사람은 지난 담당으로 남고 자리가 난다
    assert pub.post(f"/r/{tok}/leave", json={"id": p1}).status_code == 200
    assert pub.post(f"/r/{tok}/leave", json={"id": p1}).status_code == 404
    assert pub.post(f"/r/{tok}", json={"id": p1, "action": "done", "more": "no"}).status_code == 400  # 빠진 사람 이름으로는 못 올린다
    assert pub.post(f"/r/{tok}/join", json={"rank": "팀장", "name": "정셋째", "tel": "010-5555-6666"}).status_code == 200
    d = pub.get(f"/r/{tok}/data").json()
    assert [p["name"] for p in d["people"]] == ["최이장", "정셋째"]
    assert [(p["name"], bool(p["until"])) for p in d["past"]] == [("박현장", True)]
    assert [x["kind"] for x in d["log"]][:2] == ["on", "off"]

    row = next(r for r in c.get("/api/reply/list").json()["rows"] if r["rid"] == A)
    assert row["reply"]["action"] == "done" and row["reply"]["who"] == "최이장" and not row["waiting"]
    assert len(row["people"]) == 2
    c.post("/api/reply/ask", json={"rids": [A], "note": "다시"})
    assert next(r for r in c.get("/api/reply/list").json()["rows"] if r["rid"] == A)["waiting"]      # 새 요청 뒤로는 다시 기다림


def test_pin_and_public_surface(tdb, tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    c = TestClient(main.app)
    assert c.put("/api/settings/contacts-pin", json={"new": "4821"}).json()["locked"]
    assert c.post("/api/reply/ask", json={"rids": [A]}).status_code == 401
    assert c.get("/api/reply/list").status_code == 401
    assert c.get("/api/reply/list", headers={"x-pin": "4821"}).status_code == 200
    assert all(r.path.startswith("/r/") for r in reply.router.routes)   # 밖에 여는 서버에는 /r/ 뿐
    pub = TestClient(reply.public_app)
    for p in ("/api/contacts?sigun=창원", "/api/reply/list", "/api/status", "/reply.html", "/docs", "/openapi.json"):
        assert pub.get(p).status_code == 404, p


def test_ai_code_never_touches_reply():
    """담당자 표에는 이름 · 번호가 있다 — AI 맥락을 만드는 코드가 부르면 LLM 에 샐 수 있다."""
    app = Path(__file__).resolve().parent.parent / "app"
    for f in ("ai.py", "aireport.py", "llm.py", "aiwatch.py"):
        assert not re.search(r"\breply\b|duty_(link|person|log)", (app / f).read_text("utf-8")), f


def test_preview_leaves_no_record(tdb, tmp_path, monkeypatch):
    """상황판단 미리보기(preview) — 글 · 링크는 같지만 요청(ask)은 남지 않고 현황에도 안 나온다. 실제로 보낼 때 남는다."""
    _setup(tmp_path, monkeypatch)
    c = TestClient(main.app)
    pv = c.post("/api/reply/ask", json={"rids": [A], "note": "통제 여부", "base": "https://r.example", "preview": True}).json()
    (link,) = pv["links"]
    assert link["url"] in pv["people"][0]["sms"] and pv["people"][0]["tel"] == "01000000001"
    assert c.get("/api/reply/list").json()["rows"] == []
    assert TestClient(reply.public_app).get(link["url"].replace("https://r.example", "") + "/data").json()["log"] == []
    j = c.post("/api/reply/ask", json={"rids": [A], "note": "통제 여부", "base": "https://r.example"}).json()
    assert j["people"][0]["sms"] == pv["people"][0]["sms"]               # 미리 본 글 그대로 나간다
    (row,) = c.get("/api/reply/list").json()["rows"]
    assert row["waiting"] and row["note"] == "통제 여부"


def test_demo_preview_only(tdb, tmp_path, monkeypatch):
    """시연 — 미리보기는 되고(휴대폰 틀의 /r/ 화면도 열린다) 실제 요청 · 현장 등록은 막는다."""
    from app import config
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "DEMO", True)
    c = TestClient(main.app)
    pv = c.post("/api/reply/ask", json={"rids": [A], "base": "https://r.example", "preview": True}).json()
    assert pv["demo"] and pv["people"]
    path = pv["links"][0]["url"].replace("https://r.example", "")
    assert c.get(path).status_code == 200 and c.get(path + "/data").json()["log"] == []
    assert c.post("/api/reply/ask", json={"rids": [A]}).status_code == 403
    assert c.post(path + "/join", json={"name": "x", "tel": "010-1111-2222"}).status_code == 403

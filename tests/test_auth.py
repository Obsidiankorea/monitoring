"""로그인 — 계정이 없으면 열림, 생기면 로그인 요구 · 역할(관리자만 설정 쓰기 · 계정) · 기계 열쇠(연락처 금지) · 잠금 · 마지막 관리자."""
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_(tdb, monkeypatch):
    from app import auth, main
    auth.init()
    auth._FAIL.clear()
    monkeypatch.setenv("GN_API_KEY", "machine-test-key")
    return main, auth


def _login(c, login, pw):
    return c.post("/api/auth/login", json={"login": login, "password": pw})


def test_no_accounts_means_open(app_):
    main, auth = app_
    c = TestClient(main.app)
    assert c.get("/api/auth/me").json()["open"] is True
    assert c.get("/api/status").status_code == 200
    # 계정이 없을 때 첫 관리자는 같은 망 화면에서 만들 수 없다(서버 CLI 로)
    r = c.post("/api/auth/users", json={"login": "a", "password": "12345678", "role": "admin"})
    assert r.status_code == 403


def test_login_required_once_an_account_exists(app_):
    main, auth = app_
    auth.add("boss", "password-1", "admin", "관리자")
    c = TestClient(main.app)
    assert c.get("/api/alerts").status_code == 401
    r = c.get("/map.html", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login.html?next=")
    assert c.get("/login.html").status_code == 200                     # 로그인 화면 · 상태 확인 · 현장 회신은 열려 있다
    assert c.get("/api/status").status_code == 200
    assert _login(c, "boss", "wrong-pass").status_code == 401
    r = _login(c, "boss", "password-1")
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    assert "httponly" in r.headers["set-cookie"].lower()
    assert c.get("/api/auth/me").json()["user"]["login"] == "boss"
    c.post("/api/auth/logout")
    assert c.get("/api/auth/users").status_code == 401


def test_roles(app_):
    main, auth = app_
    auth.add("boss", "password-1", "admin")
    auth.add("do1", "password-2", "do")
    auth.add("cw", "password-3", "sigun", sigun="창원")
    with pytest.raises(ValueError):
        auth.add("bad", "password-4", "sigun")                         # 시군 사용자는 시군을 골라야
    c = TestClient(main.app)
    _login(c, "do1", "password-2")
    assert c.get("/api/auth/users").status_code == 403                  # 계정 목록은 관리자만
    assert c.put("/api/settings/map", json={}).status_code == 403       # 설정 쓰기는 관리자만
    assert c.get("/admin.html").status_code == 403
    a = TestClient(main.app)
    _login(a, "boss", "password-1")
    assert a.get("/api/auth/users").status_code == 200
    u = a.post("/api/auth/users", json={"login": "jj", "password": "password-5", "role": "sigun", "sigun": "진주"}).json()
    assert (u["role"], u["sigun"]) == ("sigun", "진주")


def test_machine_key_reads_but_never_contacts(app_):
    main, auth = app_
    auth.add("boss", "password-1", "admin")
    c = TestClient(main.app)
    h = {"x-gn-key": "machine-test-key"}
    assert c.get("/api/status", headers=h).status_code == 200
    assert c.get("/api/contacts?sigun=창원", headers=h).status_code == 403
    assert c.get("/api/reply/list", headers=h).status_code == 403
    assert c.put("/api/settings/map", json={}, headers=h).status_code == 403
    assert c.get("/api/alerts", headers={"x-gn-key": "wrong"}).status_code == 401


def test_lockout_and_last_admin(app_):
    main, auth = app_
    a = auth.add("boss", "password-1", "admin")
    for _ in range(10):
        with pytest.raises(ValueError):
            auth.login("boss", "nope")
    with pytest.raises(PermissionError):
        auth.login("boss", "password-1")                                # 맞아도 15분은 막힌다
    with pytest.raises(ValueError):
        auth.update(a["id"], role="do")                                 # 마지막 관리자는 내릴 수 없다
    with pytest.raises(ValueError):
        auth.update(a["id"], active=False)


def test_password_change_ends_sessions(app_):
    main, auth = app_
    a = auth.add("boss", "password-1", "admin")
    auth.add("boss2", "password-9", "admin")
    tok, _ = auth.login("boss", "password-1")
    assert auth.who(tok)["login"] == "boss"
    auth.update(a["id"], pw="password-new")
    assert auth.who(tok) is None
    assert auth.check_pw("password-new", auth.hash_pw("password-new"))


def test_sigun_user_sees_only_own_contacts_and_dispatch(app_, monkeypatch):
    main, auth = app_
    from app import reply, contacts
    auth.add("cw", "password-3", "sigun", sigun="창원")
    monkeypatch.setattr(main, "_contacts_pin", lambda pin: None)
    monkeypatch.setattr(contacts, "of_sigun", lambda sg: {"sigun": sg, "people": {}})
    monkeypatch.setattr(reply, "_districts", lambda: {"48120-1": ("창원시", "가", "", "", {}), "48170-1": ("진주시", "나", "", "", {})})
    monkeypatch.setattr(reply, "rows", lambda: [{"rid": "48120-1"}, {"rid": "48170-1"}])
    monkeypatch.setattr(reply, "ask", lambda rids, *a, **k: {"rids": rids})
    c = TestClient(main.app)
    _login(c, "cw", "password-3")
    assert c.get("/api/contacts?sigun=창원").status_code == 200
    assert c.get("/api/contacts?sigun=진주").status_code == 403
    assert [r["rid"] for r in c.get("/api/reply/list").json()["rows"]] == ["48120-1"]
    assert c.post("/api/reply/ask", json={"rids": ["48170-1"], "preview": True}).status_code == 403
    assert c.post("/api/reply/ask", json={"rids": ["48120-1"], "preview": True}).status_code == 200


def test_first_admin_from_web_only_once(app_):
    main, auth = app_
    c = TestClient(main.app)
    r = c.post("/api/auth/setup", json={"login": "boss", "password": "password-1", "name": "상황실"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "admin"
    assert c.get("/api/auth/users").status_code == 200                 # 만든 채로 로그인돼 있다
    r = TestClient(main.app).post("/api/auth/setup", json={"login": "evil", "password": "password-2"})
    assert r.status_code == 403                                         # 계정이 생긴 뒤에는 처음 설정이 닫힌다
    assert TestClient(main.app).post("/api/auth/setup", json={"login": "x", "password": "short"}).status_code == 403


def test_board_groups_by_sigun_without_names(app_, monkeypatch):
    main, auth = app_
    from app import reply, db
    monkeypatch.setattr(reply, "_districts", lambda: {"r1": ("창원시", "가", "", "", {}), "r2": ("창원시", "나", "", "", {}),
                                                      "r3": ("진주시", "다", "", "", {})})
    with db.tx() as con:
        for rid, sg, nm in (("r1", "창원시", "가지구"), ("r2", "창원시", "나지구"), ("r3", "진주시", "다지구")):
            con.execute("INSERT INTO duty_link VALUES (?,?,?,?,?)", (rid, "t" + rid, sg, nm, sg))
        con.execute("INSERT INTO duty_log (rid, at, kind, who, memo) VALUES ('r1','2026-11-18 09:00','ask','상황실','')")
        con.execute("INSERT INTO duty_log (rid, at, kind, who, action, memo) VALUES ('r1','2026-11-18 09:03','reply','김','done','')")
        con.execute("INSERT INTO duty_log (rid, at, kind, who, memo) VALUES ('r2','2026-11-18 09:00','ask','상황실','')")
        con.execute("INSERT INTO duty_log (rid, at, kind, who, memo) VALUES ('r3','2026-11-16 09:00','ask','상황실','')")   # 24시간 밖
    out = reply.board(24, now="2026-11-18 09:30")
    assert [g["sigun"] for g in out] == ["창원"]
    g = out[0]
    assert (g["n"], g["warn"], g["steps"]["조치 완료"]) == (2, 1, 1)
    assert g["rows"][0]["name"] == "나지구" and "확인 없음" in g["rows"][0]["warn"]   # 확인 없는 지구가 위로
    assert "people" not in g["rows"][0] and "tel" not in str(g)                      # 이름 · 번호 없음


def test_sigun_request_is_recorded_with_sender_and_visible_to_do(app_, monkeypatch):
    main, auth = app_
    from app import reply, contacts
    auth.add("cw", "password-3", "sigun", "창원 담당", sigun="창원")
    auth.add("do1", "password-2", "do", "도 상황실")
    monkeypatch.setattr(main, "_contacts_pin", lambda pin: None)
    monkeypatch.setattr(reply, "_districts", lambda: {"r1": ("창원시", "가지구", "창원시 진동면", "창원시 진동면", {})})
    monkeypatch.setattr(contacts, "_rows", lambda: {"r1": {"담당1": "김", "담당1_연락처": "010-1234-5678"}})
    c = TestClient(main.app)
    _login(c, "cw", "password-3")
    j = c.post("/api/reply/ask", json={"rids": ["r1"], "note": "현장 확인"}).json()
    assert j["people"][0]["sms"].startswith("[창원시 재난상황실]")             # 문자 머리글은 보낸 시군
    d = TestClient(main.app)
    _login(d, "do1", "password-2")
    b = d.get("/api/reply/board").json()["siguns"]
    assert b[0]["sigun"] == "창원" and b[0]["rows"][0]["by"] == "창원시 · 창원 담당"   # 도 현황판에서 누가 보냈는지 보인다
    j = d.post("/api/reply/ask", json={"rids": ["r1"], "note": "재확인"}).json()
    assert j["people"][0]["sms"].startswith("[경남도 재난상황실]")             # 도도 같은 지구에 보낼 수 있다


def test_sigun_without_password_until_admin_turns_it_off(app_):
    main, auth = app_
    auth.add("boss", "password-1", "admin")
    c = TestClient(main.app)
    assert c.get("/api/auth/me").json()["sigun_open"] is True
    r = c.post("/api/auth/sigun", json={"sigun": "창원"})
    assert r.status_code == 200 and (r.json()["user"]["role"], r.json()["user"]["sigun"]) == ("sigun", "창원")
    assert c.get("/api/auth/me").json()["user"]["sigun"] == "창원"
    assert c.get("/api/contacts?sigun=진주").status_code == 403           # 손님도 자기 시군만
    assert c.post("/api/auth/sigun", json={"sigun": "서울"}).status_code == 400
    assert all(u["login"] != "시군-창원" for u in auth.users())            # 계정 목록에는 안 보인다
    assert auth.any_user() and TestClient(main.app).post("/api/auth/setup", json={"login": "x", "password": "password-9"}).status_code == 403
    a = TestClient(main.app)
    _login(a, "boss", "password-1")
    assert a.put("/api/settings/sigun-open", json={"on": False}).status_code == 200
    assert c.get("/api/alerts").status_code == 401                         # 끄면 들어와 있던 시군 접속도 끊긴다
    assert TestClient(main.app).post("/api/auth/sigun", json={"sigun": "창원"}).status_code == 403
    with pytest.raises(ValueError):
        auth.login("시군-창원", "!")


def test_guest_does_not_count_as_account(app_):
    main, auth = app_
    auth.guest_sigun("창원")                                                # 계정이 없을 때 손님이 생겨도
    assert auth.any_user() is False                                        # 서버는 여전히 '계정 없음'(처음 설정 가능)


def test_demo_opens_as_do_user(app_, monkeypatch):
    main, auth = app_
    from app import config
    auth.add("boss", "password-1", "admin")
    monkeypatch.setattr(config, "DEMO", True)
    c = TestClient(main.app)
    me = c.get("/api/auth/me").json()
    assert me["open"] is False and me["user"]["role"] == "do" and me["user"]["demo"]
    assert c.get("/map.html", follow_redirects=False).status_code == 200   # 로그인 화면으로 보내지 않는다


def test_writes_are_allowlisted_per_role(app_):
    """A1 — 관리자가 아니면 허용 목록의 쓰기만. 비밀번호 없는 시군 손님은 현장 요청뿐, 판단 기록 지우기는 관리자만(지운 표시만 남는다)."""
    from app import db
    main, auth = app_
    auth.add("boss", "password-1", "admin", "관리자")
    auth.add("do1", "password-2", "do", "도담당")
    g = TestClient(main.app)
    assert g.post("/api/auth/sigun", json={"sigun": "창원"}).status_code == 200
    assert g.post("/api/ai/decisions", json={"sigun": "창원", "act": "메모"}).status_code == 403
    assert g.put("/api/ai/sigunstage", json={}).status_code == 403
    assert g.post("/api/reports/run", json={"id": "weather"}).status_code == 403
    assert g.post("/api/law/run").status_code == 403
    assert auth.write_ok("sigun", "POST", "/api/reply/ask") and not auth.write_ok("sigun", "DELETE", "/api/ai/decisions/1")
    d = TestClient(main.app)
    _login(d, "do1", "password-2")
    rows = d.post("/api/ai/decisions", json={"sigun": "창원", "act": "메모"}).json()["rows"]
    assert rows[0]["who"] == "도담당(도 사용자)"
    did = rows[0]["id"]
    assert d.delete(f"/api/ai/decisions/{did}").status_code == 403
    a = TestClient(main.app)
    _login(a, "boss", "password-1")
    assert a.delete(f"/api/ai/decisions/{did}").status_code == 200
    assert a.get("/api/ai/decisions").json()["rows"] == []
    with db.tx() as con:
        assert "관리자(도 관리자)" in con.execute("SELECT gone FROM decision WHERE id=?", (did,)).fetchone()[0]   # 줄은 남는다


def test_loopback_needs_local_host_and_same_origin(app_):
    """A3 — 127.0.0.1 이라도 Host 가 다른 이름(DNS 되붙이기)이면 관리자로 안 보고, 다른 사이트 Origin 의 쓰기는 막는다."""
    main, auth = app_
    auth.add("boss", "password-1", "admin")
    assert auth.decide("/api/alerts", "GET", "127.0.0.1", None, None, "localhost:8000")[1]["local"]
    assert auth.decide("/api/alerts", "GET", "127.0.0.1", None, None, "[::1]:8000")[1]["local"]
    assert auth.decide("/api/alerts", "GET", "127.0.0.1", None, None, "evil.example:8000")[0] == 401
    assert auth.decide("/api/keys", "PUT", "127.0.0.1", None, None, "127.0.0.1:8000", "http://evil.example")[0] == 403
    assert auth.decide("/api/keys", "PUT", "127.0.0.1", None, None, "127.0.0.1:8000", "http://127.0.0.1:8000")[0] == 0
    c = TestClient(main.app)
    _login(c, "boss", "password-1")
    assert c.put("/api/settings/map", json={}, headers={"origin": "https://evil.example"}).status_code == 403


def test_field_name_strips_markup():
    """A4 — 현장 페이지에서 받은 직급 · 성명은 꺾쇠 · 따옴표 · 제어 문자를 뺀다(여러 화면이 그대로 그린다). 화면 escH 도 따옴표를 바꾼다."""
    from pathlib import Path
    from app import reply
    assert reply._plain('<img src=x onerror="a">홍\'길`동\x01 ') == "img src=x onerror=a홍길동"
    js = (Path(__file__).parent.parent / "app/web/static/js/09-prefs.js").read_text("utf-8")
    assert "&quot;" in js.split("const escH", 1)[1].split("\n", 1)[0]

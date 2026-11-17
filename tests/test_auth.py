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

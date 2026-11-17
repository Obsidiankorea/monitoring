"""로그인 — 도 관리자(admin) · 도 사용자(do) · 시군 사용자(sigun, 자기 시군 하나).

  · 계정 · 접속은 같은 SQLite(state DB). 비밀번호는 scrypt 해시만, 접속 쿠키(gn_sess)는 sha256 만 DB 에 둔다(DB 가 새도 그대로 못 쓴다).
  · **계정이 하나도 없으면 예전처럼 열어 둔다** — 관리자를 처음 만들면(아래 CLI) 그때부터 로그인을 요구한다(쓰던 화면이 갑자기 막히지 않게).
  · 서버가 자기 자신을 부르는 요청(127.0.0.1 — 판정 · AI 가 /api/… 를 부른다)은 관리자로 통과. PC 에서 직접 켠 대시보드도 같다.
    shortcut: 같은 컴퓨터의 역방향 프록시가 앞에 서면 모두 127.0.0.1 로 보인다 — 그때는 프록시가 보낸 사람 주소를 넘기게 바꾼다.
  · 기계 열쇠(X-GN-Key = api_keys 의 GN_API_KEY) — Hermes 같은 AI 도구용. 읽기(GET)만, 연락처 · 회신은 안 된다(연락처는 사람이 상황판단 모드에서만).

처음 관리자 만들기(NAS):  docker exec -it gn-monitor python -m app.auth add <아이디> --role admin --name 관리자
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from . import config, db

ROLES = {"admin": "도 관리자", "do": "도 사용자", "sigun": "시군 사용자"}
COOKIE = "gn_sess"
DAYS = 14                                          # 접속 유지(마지막 사용부터) — 벽에 걸어 두는 화면이라 넉넉히
SIGUNS = ("창원", "진주", "통영", "사천", "김해", "밀양", "거제", "양산", "의령",
          "함안", "창녕", "고성", "남해", "하동", "산청", "함양", "거창", "합천")

def init() -> None:
    """표는 db.SCHEMA 에 있다(app_user · app_session) — db.init() 이 만든다. 여기서는 기억만 비운다."""
    _forget()


# ── 비밀번호 ──────────────────────────────────────────────
def hash_pw(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return "scrypt$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(h).decode()


def check_pw(pw: str, stored: str) -> bool:
    try:
        kind, s, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=base64.b64decode(s), n=2 ** 14, r=8, p=1, dklen=32)
        return kind == "scrypt" and hmac.compare_digest(got, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def _pw_ok(pw: str) -> str | None:
    """비밀번호 규칙 — 어기면 까닭, 맞으면 None."""
    return "비밀번호는 8자 이상" if len(pw or "") < 8 else None


# ── 계정 ──────────────────────────────────────────────────
def _row(r) -> dict:
    return {"id": r["id"], "login": r["login"], "name": r["name"], "role": r["role"], "role_name": ROLES[r["role"]],
            "sigun": r["sigun"], "active": bool(r["active"]), "created": r["created"], "last_login": r["last_login"]}


def _check(role: str, sigun: str | None) -> str | None:
    if role not in ROLES:
        return "역할은 admin · do · sigun 중 하나"
    if role == "sigun" and sigun not in SIGUNS:
        return "시군 사용자는 시군(창원 … 합천)을 골라야 한다"
    return None


def users() -> list[dict]:
    with db.tx() as con:
        return [_row(r) for r in con.execute(f"SELECT * FROM app_user WHERE pw<>'{NOPW}' ORDER BY role, sigun, login")]


def add(login: str, pw: str, role: str, name: str = "", sigun: str | None = None) -> dict:
    login = (login or "").strip()
    sigun = sigun if role == "sigun" else None
    why = (None if login and len(login) <= 40 else "아이디를 넣는다(40자 이하)") or _check(role, sigun) or _pw_ok(pw)
    if why:
        raise ValueError(why)
    with db.tx() as con:
        if con.execute("SELECT 1 FROM app_user WHERE login=?", (login,)).fetchone():
            raise ValueError("이미 있는 아이디")
        con.execute("INSERT INTO app_user (login, name, role, sigun, pw, created) VALUES (?,?,?,?,?,?)",
                    (login, (name or "").strip()[:40], role, sigun, hash_pw(pw), _now()))
    _forget()
    return next(u for u in users() if u["login"] == login)


_SETUP = threading.Lock()
NOPW = "!"                                         # 비밀번호 없는 시군 손님 계정 — check_pw 가 늘 실패하는 값(아이디로는 못 들어온다)


def sigun_open() -> bool:
    """시군은 비밀번호 없이 들어오기(로그인 화면에서 시군만 고른다) — 관리자가 끈다. 지금은 기본 켬."""
    return bool(db.get_setting("sigun_open", True))


def set_sigun_open(on: bool) -> None:
    db.put_setting("sigun_open", bool(on))
    if not on:                                     # 끄면 그렇게 들어와 있던 접속도 끊는다
        with db.tx() as con:
            con.execute(f"DELETE FROM app_session WHERE user_id IN (SELECT id FROM app_user WHERE pw='{NOPW}')")
    _forget()


def guest_sigun(sigun: str, ip: str = "") -> tuple[str, dict]:
    """시군 손님 접속 — 그 시군의 비밀번호 없는 계정(없으면 만든다)으로 쿠키를 준다."""
    if not sigun_open():
        raise PermissionError("시군도 아이디 · 비밀번호로 들어온다 — 도 관리자에게 계정을 받는다")
    if sigun not in SIGUNS:
        raise ValueError("시군을 고른다")
    login_ = f"시군-{sigun}"
    with db.tx() as con:
        r = con.execute("SELECT * FROM app_user WHERE login=?", (login_,)).fetchone()
        if not r:
            con.execute("INSERT INTO app_user (login, name, role, sigun, pw, created) VALUES (?,?,?,?,?,?)",
                        (login_, f"{sigun} 담당", "sigun", sigun, NOPW, _now()))
            r = con.execute("SELECT * FROM app_user WHERE login=?", (login_,)).fetchone()
        tok = secrets.token_urlsafe(32)
        con.execute("INSERT INTO app_session VALUES (?,?,?,?,?)", (_h(tok), r["id"], _now(), _later(), (ip or "")[:64]))
        con.execute("UPDATE app_user SET last_login=? WHERE id=?", (_now(), r["id"]))
    return tok, _row(r)


def first_admin(login: str, pw: str, name: str = "") -> dict:
    """처음 관리자 — 계정이 하나도 없을 때만. 둘이 동시에 눌러도 하나만 된다(잠금 + 표 안에서 다시 본다)."""
    with _SETUP:
        with db.tx() as con:
            if con.execute(f"SELECT 1 FROM app_user WHERE pw<>'{NOPW}' LIMIT 1").fetchone():
                raise PermissionError("이미 계정이 있다 — 관리자에게 계정을 받는다")
        return add(login, pw, "admin", name or "관리자")


def update(uid: int, *, role: str | None = None, sigun: str | None = None, name: str | None = None,
           active: bool | None = None, pw: str | None = None) -> dict:
    with db.tx() as con:
        r = con.execute("SELECT * FROM app_user WHERE id=?", (uid,)).fetchone()
        if not r:
            raise LookupError("없는 계정")
        nr = role or r["role"]
        ns = (sigun if sigun is not None else r["sigun"]) if nr == "sigun" else None
        why = _check(nr, ns) or (_pw_ok(pw) if pw is not None else None)
        if why:
            raise ValueError(why)
        na = r["active"] if active is None else int(bool(active))
        if r["role"] == "admin" and (nr != "admin" or not na):        # 마지막 관리자를 잃지 않게
            n = con.execute("SELECT COUNT(*) FROM app_user WHERE role='admin' AND active=1 AND id<>?", (uid,)).fetchone()[0]
            if n == 0:
                raise ValueError("마지막 관리자는 내리거나 멈출 수 없다")
        con.execute("UPDATE app_user SET role=?, sigun=?, name=?, active=? WHERE id=?",
                    (nr, ns, (name if name is not None else r["name"]).strip()[:40], na, uid))
        if pw is not None:
            con.execute("UPDATE app_user SET pw=? WHERE id=?", (hash_pw(pw), uid))
        if pw is not None or not na or nr != r["role"] or ns != r["sigun"]:
            con.execute("DELETE FROM app_session WHERE user_id=?", (uid,))    # 권한 · 비밀번호가 바뀌면 다시 로그인
    _forget()
    return next(u for u in users() if u["id"] == uid)


# ── 접속 ──────────────────────────────────────────────────
_FAIL: dict[str, list[float]] = {}                  # 아이디 → 실패 시각들(15분) — 10번 넘으면 잠시 막는다
_LOCK = threading.Lock()


def login(login: str, pw: str, ip: str = "") -> tuple[str, dict]:
    """맞으면 (쿠키 값, 사용자). 틀리면 ValueError(같은 말 — 아이디가 있는지 알려 주지 않는다)."""
    key = (login or "").strip().lower()
    now = time.time()
    with _LOCK:
        fails = [t for t in _FAIL.get(key, []) if now - t < 900]
        _FAIL[key] = fails
        if len(fails) >= 10:
            raise PermissionError("잘못 넣은 횟수가 많다 — 15분 뒤에 다시")
    with db.tx() as con:
        r = con.execute("SELECT * FROM app_user WHERE login=? AND active=1", ((login or "").strip(),)).fetchone()
        ok = bool(r) and check_pw(pw or "", r["pw"])
        if not ok:
            with _LOCK:
                _FAIL.setdefault(key, []).append(now)
            raise ValueError("아이디 또는 비밀번호가 맞지 않다")
        tok = secrets.token_urlsafe(32)
        con.execute("INSERT INTO app_session VALUES (?,?,?,?,?)",
                    (_h(tok), r["id"], _now(), _later(), (ip or "")[:64]))
        con.execute("UPDATE app_user SET last_login=? WHERE id=?", (_now(), r["id"]))
        con.execute("DELETE FROM app_session WHERE expires < ?", (_now(),))
    with _LOCK:
        _FAIL.pop(key, None)
    return tok, _row(r)


def logout(tok: str) -> None:
    with db.tx() as con:
        con.execute("DELETE FROM app_session WHERE token_hash=?", (_h(tok),))
    _forget()


_SEEN: dict[str, tuple[float, dict | None]] = {}    # 쿠키 해시 → (본 시각, 사용자) — 지도 조각 수백 번마다 DB 를 열지 않게(60초)
_ANY: dict = {"t": 0.0, "v": False}


def any_user() -> bool:
    """계정이 하나라도 있나(10초 기억) — 없으면 로그인을 요구하지 않는다."""
    if time.time() - _ANY["t"] > 10 or _ANY.get("db") != str(db.DB_PATH):     # DB 를 바꾸면(시험) 다시 본다
        try:
            with db.tx() as con:
                v = bool(con.execute(f"SELECT 1 FROM app_user WHERE active=1 AND pw<>'{NOPW}' LIMIT 1").fetchone())
        except sqlite3.OperationalError:                   # 표가 아직 없다(db.init 전) = 계정 없음
            v = False
        _ANY.update(t=time.time(), db=str(db.DB_PATH), v=v)
    return _ANY["v"]


def who(tok: str | None) -> dict | None:
    if not tok:
        return None
    h = _h(tok)
    ck = h + "|" + str(db.DB_PATH)
    hit = _SEEN.get(ck)
    if hit and time.time() - hit[0] < 60:
        return hit[1]
    with db.tx() as con:
        r = con.execute("SELECT u.*, s.expires FROM app_session s JOIN app_user u ON u.id=s.user_id "
                        "WHERE s.token_hash=? AND u.active=1", (h,)).fetchone()
        u = None
        if r and r["expires"] >= _now():
            u = _row(r)
            if r["expires"] < _later(DAYS - 1):           # 하루에 한 번만 늘린다(쓰기를 줄인다)
                con.execute("UPDATE app_session SET expires=? WHERE token_hash=?", (_later(), h))
    if len(_SEEN) > 2000:
        _SEEN.clear()
    _SEEN[ck] = (time.time(), u)
    return u


def _forget() -> None:
    _SEEN.clear()
    _ANY["t"] = 0.0


def _h(tok: str) -> str:
    return hashlib.sha256(tok.encode()).hexdigest()


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _later(days: int = DAYS) -> str:
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")


# ── 요청 거르기(main.py 미들웨어가 부른다) ─────────────────
OPEN = ("/login.html", "/api/auth/login", "/api/auth/me", "/api/auth/setup", "/api/auth/sigun", "/api/status", "/favicon.ico", "/r/")
ADMIN_ONLY = ("/api/settings", "/api/keys", "/api/update", "/api/server-update", "/api/origin", "/api/storage",
              "/api/snaps", "/api/ai/wiki", "/api/ai/task", "/api/ai/llm", "/api/districts/geo", "/api/auth/users", "/admin.html")
# 관리자가 아닌 사람의 쓰기(POST · PUT · DELETE)는 여기 있는 것만 — 새 쓰기 라우트는 기본으로 관리자 전용(허용 목록)
WRITE_OK = {
    "sigun": ("POST /api/auth/logout", "POST /api/reply/ask", "POST /api/refresh/",   # 현장 요청 · 판단 기록은 자기 시군만(main 이 거른다)
              "POST /api/ai/ask", "POST /api/ai/decisions"),
    "do": ("POST /api/auth/logout", "POST /api/reply/ask", "POST /api/ai/ask",
           "POST /api/ai/decisions", "PUT /api/ai/sigunstage",                  # 판단 기록 남기기 · 도 비상단계 표시(지우기는 관리자)
           "POST /api/reports/run", "POST /api/reports/wait", "DELETE /api/reports/wait", "POST /api/refresh/"),
}


def write_ok(role: str, method: str, path: str) -> bool:
    if role == "admin" or method in ("GET", "HEAD", "OPTIONS"):
        return True
    return any(f"{method} {path}" == w or (w.endswith("/") and f"{method} {path}".startswith(w)) for w in WRITE_OK.get(role, ()))


NO_MACHINE = ("/api/contacts", "/api/reply", "/api/auth")
MACHINE = {"login": "machine", "name": "기계 열쇠", "role": "do", "sigun": None, "machine": True}
LOCAL = {"login": "local", "name": "이 컴퓨터", "role": "admin", "sigun": None, "local": True}
DEMO = {"login": "demo", "name": "시연", "role": "do", "sigun": None, "demo": True}   # 시연 서버(8001) — 로그인 없이 도 사용자로


def machine_key() -> str:
    return (os.environ.get("GN_API_KEY") or config.KEYS.get("GN_API_KEY") or "").strip()


def _hostname(h: str | None) -> str:
    """'localhost:8000' · '[::1]:8000' · 'http://127.0.0.1:8000' → 이름만(소문자)."""
    h = (h or "").lower().split("://", 1)[-1].split("/", 1)[0]
    return h[1:h.index("]")] if h.startswith("[") and "]" in h else h.rsplit(":", 1)[0] if h.count(":") == 1 else h


LOOP_NAMES = ("localhost", "127.0.0.1", "::1")


def decide(path: str, method: str, host: str, cookie: str | None, key: str | None,
           hhost: str | None = None, origin: str | None = None) -> tuple[int, dict | None]:
    """→ (0 = 통과 | 401 로그인 필요 | 403 권한 없음, 사용자). 계정이 없으면 늘 통과.
    hhost = 요청의 Host 머리, origin = Origin 머리 — 다른 사이트가 보낸 쓰기(브라우저가 Origin 을 붙인다)는 막는다."""
    if method not in ("GET", "HEAD", "OPTIONS") and origin and origin != "null" and hhost is not None             and origin.lower().split("://", 1)[-1].rstrip("/") != hhost.lower():
        return 403, None
    if any(path == p or (p.endswith("/") and path.startswith(p)) for p in OPEN):
        return 0, None
    if config.DEMO:                                 # 시연 — 가짜 자료뿐이라 막지 않는다(계정 · 설정 쓰기는 시연이 따로 막는다)
        return 0, DEMO
    if host in ("127.0.0.1", "::1") and (hhost is None or _hostname(hhost) in LOOP_NAMES):
        return 0, LOCAL                              # 이 컴퓨터 · 서버 자신 — 다른 이름(Host)으로 온 것(DNS 되붙이기)은 아래처럼 따진다
    if not any_user():
        return 0, None
    mk = machine_key()
    if key and mk and hmac.compare_digest(key.encode(), mk.encode()):
        if method != "GET" or path.startswith(NO_MACHINE):
            return 403, MACHINE
        return 0, MACHINE
    u = who(cookie)
    if not u:
        return 401, None
    if path.startswith(ADMIN_ONLY) and u["role"] != "admin":
        # 설정 읽기(GET)는 화면이 늘 부른다 — 바꾸기(쓰기)만 관리자. 계정 · 키 · 관리 화면은 읽기도 관리자
        if method != "GET" or path.startswith(("/api/keys", "/api/auth/users", "/admin.html")):
            return 403, u
    if not write_ok(u["role"], method, path):
        return 403, u
    return 0, u


def _cli(argv: list[str]) -> int:
    import argparse
    import getpass
    ap = argparse.ArgumentParser(prog="python -m app.auth", description="대시보드 계정")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="계정 만들기(비밀번호는 물어본다)")
    a.add_argument("login")
    a.add_argument("--role", choices=list(ROLES), required=True)
    a.add_argument("--sigun", choices=SIGUNS)
    a.add_argument("--name", default="")
    p = sub.add_parser("passwd", help="비밀번호 바꾸기")
    p.add_argument("login")
    sub.add_parser("list", help="계정 목록")
    o = ap.parse_args(argv)
    db.init()
    init()
    if o.cmd == "list":
        for u in users():
            print(f"{u['id']:>3} {u['login']:<16} {u['role_name']:<6} {u['sigun'] or '':<4} {'켬' if u['active'] else '멈춤'} {u['name']}")
        return 0
    pw = getpass.getpass("비밀번호: ")
    if pw != getpass.getpass("한 번 더: "):
        print("두 번 넣은 비밀번호가 다르다")
        return 1
    try:
        if o.cmd == "add":
            u = add(o.login, pw, o.role, o.name, o.sigun)
        else:
            uid = next((u["id"] for u in users() if u["login"] == o.login), None)
            if uid is None:
                print("없는 아이디")
                return 1
            u = update(uid, pw=pw)
    except ValueError as e:
        print(e)
        return 1
    print(f"됐다 — {u['login']} ({u['role_name']}{' · ' + u['sigun'] if u['sigun'] else ''})")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))

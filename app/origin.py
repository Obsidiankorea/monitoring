"""자료를 어디서 받나 — 이 PC 에서 직접 수집(local) / 언레이드 서버가 받아 둔 것(server)
/ 서버 + 이 PC 스방(mix): 기상청 자료는 서버(gisang.day)에서 읽고, 스방(내부망)만 이 PC 가 수집한다.

mix — 행망 PC 용. 서버는 집에 있어 스방에 닿지 않고, 이 PC 는 기상청 호출을 아끼고 싶다.
   · 이 PC 는 스방 수집기만 돌린다(기상청 수집 · 상황판단 미리 계산 등은 멈춤 — 서버가 한다).
   · 화면의 읽기(GET)는 서버로, 스방 자료 · 설정 · 보고서는 이 PC 가 답한다(MIX_LOCAL · src=bangjae).
   · 쓰기(POST · PUT · DELETE)는 넘기지 않는다 — 이 PC 에서 서버로는 아무것도 보내지 않는다(보안).
   · 서버는 로그인이 걸려 있어 기계 열쇠로 읽는다 — 이 PC config/api_keys.txt 의 GN_SERVER_KEY(서버의 GN_API_KEY 값, 읽기 전용).

서버에서 받으면 이 PC 는 수집을 멈추고(같은 기상청 키로 호출이 두 배가 되지 않게), 화면이 부르는
`/api/…` 를 서버로 그대로 넘긴다. 화면 파일(index.html · map.html)은 이 PC 것을 쓴다.

⚠️ 이 PC 에 남겨야 하는 것은 넘기지 않는다(LOCAL_ONLY):
   - 받는 곳 설정 자체(`/api/origin`) — 넘기면 서버에서 서버를 고르는 꼴이 된다
   - 업데이트(`/api/update…`) — 이 PC 의 저장소를 git pull · 다시 띄우는 것
   - 저장공간·보관(`/api/storage…`, `/api/settings/retention`) — 이 PC 의 DB·캐시를 치우는 것
⚠️ 설정은 이 PC 의 DB 에 둔다(서버 DB 가 아니다). 기본은 local — 아무것도 안 고르면 예전과 같다.
"""
from __future__ import annotations

import logging
from urllib.parse import urlsplit

import httpx

from . import db

log = logging.getLogger("origin")

DEFAULT = {"mode": "local", "url": "https://gisang.day"}
MODES = ("local", "server", "mix")
LOCAL_ONLY = ("/api/origin", "/api/update", "/api/storage", "/api/settings/retention")
# mix 에서 이 PC 가 답하는 것 — 스방 자료(서버에는 없다) · 설정(이 PC DB) · 보고서(이 PC 보고서 엔진, app/reports.py)
MIX_LOCAL = ("/api/bangjae", "/api/settings", "/api/reports", "/api/auth", "/api/keys", "/api/status")   # status 는 서버 것 + 이 PC 스방(main.api_status)
TIMEOUT = httpx.Timeout(20.0, connect=5.0)
# 넘길 때 버리는 머리 — 길이·압축은 httpx 가 푼 몸에 맞지 않는다(gzip 을 풀어 받는다)
_DROP = {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive", "server", "date"}

_client: httpx.AsyncClient | None = None


def cfg() -> dict:
    c = {**DEFAULT, **(db.get_setting("origin", {}) or {})}
    if c.get("mode") not in MODES:
        c["mode"] = "local"
    return c


def mode() -> str:
    return cfg()["mode"]


def remote() -> str | None:
    """서버에서 받는 중(server · mix)이면 그 주소(끝 / 없이), 아니면 None."""
    c = cfg()
    return c["url"].rstrip("/") if c["mode"] in ("server", "mix") and c.get("url") else None


def check_url(url: str) -> str:
    """http(s)://호스트[:포트] 만 — 경로·질의는 떼고, 이상하면 ValueError."""
    u = urlsplit((url or "").strip())
    if u.scheme not in ("http", "https") or not u.hostname:
        raise ValueError("서버 주소는 http://주소:포트 꼴이어야 한다")
    return f"{u.scheme}://{u.netloc}"


def put(body: dict) -> dict:
    c = cfg()
    if "url" in body:
        c["url"] = check_url(str(body["url"]))
    if "mode" in body:
        if body["mode"] not in MODES:
            raise ValueError("mode 는 local · server · mix 중 하나")
        c["mode"] = body["mode"]
    db.put_setting("origin", c)
    return c


def should_proxy(path: str, method: str = "GET", query: str = "") -> bool:
    if not path.startswith("/api/") or path.startswith(LOCAL_ONLY):
        return False
    if mode() == "mix":
        if method not in ("GET", "HEAD") or path.startswith(MIX_LOCAL):
            return False                         # 쓰기는 서버로 보내지 않는다 · 스방 · 설정 · 보고서는 이 PC
        if path.startswith("/api/rain") and "src=bangjae" in (query or ""):
            return False                         # 스방 지점별 강수 — 이 PC 가 받은 것
    return True


def _key() -> str:
    """서버 읽기용 기계 열쇠(서버의 GN_API_KEY 값) — 이 PC config/api_keys.txt 의 GN_SERVER_KEY. 없으면 ''."""
    from . import config
    return (config.KEYS.get("GN_SERVER_KEY") or "").strip()


def _ssl():
    """행망은 HTTPS 를 보안 프록시가 다시 서명한다 — 윈도 인증서 저장소로 확인하고, 그 인증서에 없는 '기관 키 식별자'로
    막히는 파이썬 3.13 엄격 검사(VERIFY_X509_STRICT)만 끈다(재난상황보고서 server_sync 와 같다, 2026-11-24)."""
    import ssl
    c = ssl.create_default_context()
    c.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
    return c


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        import urllib.request
        proxy = urllib.request.getproxies().get("https")      # 행망은 프록시로만 바깥에 나간다(윈도 설정)
        _client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False, verify=_ssl(), proxy=proxy or None)
    return _client


async def forward(base: str, method: str, path: str, query: str, body: bytes,
                  ctype: str | None) -> tuple[int, bytes, dict]:
    """서버로 한 번 넘긴다 → (상태, 몸, 머리). 연결하지 못하면 502 와 까닭."""
    url = f"{base}{path}" + (f"?{query}" if query else "")
    try:
        head = {"content-type": ctype} if ctype else {}
        if _key():
            head["X-GN-Key"] = _key()            # 서버 로그인 — 기계 열쇠(읽기만)
        r = await client().request(method, url, content=body or None, headers=head or None)
    except httpx.HTTPError as e:
        log.warning("서버에 연결하지 못했다(%s): %s", base, e)
        msg = f"서버({base})에 연결하지 못했다 — {type(e).__name__}"
        return 502, ('{"detail": "%s"}' % msg).encode(), {"content-type": "application/json"}
    head = {k: v for k, v in r.headers.items() if k.lower() not in _DROP}
    return r.status_code, r.content, head


async def test(url: str) -> dict:
    """그 주소에 대시보드 서버가 있나 — /api/status 를 한 번 불러 본다."""
    base = check_url(url)
    try:
        r = await client().get(f"{base}/api/status", timeout=httpx.Timeout(6.0, connect=4.0))
        r.raise_for_status()
        st = r.json().get("collect", {})
        # 로그인이 걸린 읽기 하나 — /api/status 는 로그인 없이 열려 있어 그것만 보면 '됨'인데 화면 자료는 401 로 텅 빈다
        k = await client().get(f"{base}/api/alerts", headers={"X-GN-Key": _key()} if _key() else None,
                               timeout=httpx.Timeout(8.0, connect=4.0))
        if k.status_code in (401, 403):
            why = ("서버가 기계 열쇠(GN_SERVER_KEY)를 받지 않는다 — 서버의 GN_API_KEY 값인지 확인" if _key()
                   else "서버에 로그인이 걸려 있다 — 설정 › 시스템 › API 키의 GN_SERVER_KEY(서버 기계 열쇠)를 넣는다")
            return {"ok": False, "url": base, "error": why}
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "url": base, "error": f"{type(e).__name__}: {e}"[:200]}
    ok = sorted(k for k, v in st.items() if isinstance(v, dict) and v.get("ok"))
    return {"ok": True, "url": base, "collect_ok": ok, "n": len(st)}

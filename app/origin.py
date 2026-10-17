"""자료를 어디서 받나 — 이 PC 에서 직접 수집(local) / 언레이드 서버가 받아 둔 것(server).

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

DEFAULT = {"mode": "local", "url": "http://100.106.116.92:8000"}
LOCAL_ONLY = ("/api/origin", "/api/update", "/api/storage", "/api/settings/retention")
TIMEOUT = httpx.Timeout(20.0, connect=5.0)
# 넘길 때 버리는 머리 — 길이·압축은 httpx 가 푼 몸에 맞지 않는다(gzip 을 풀어 받는다)
_DROP = {"content-length", "content-encoding", "transfer-encoding", "connection", "keep-alive", "server", "date"}

_client: httpx.AsyncClient | None = None


def cfg() -> dict:
    c = {**DEFAULT, **(db.get_setting("origin", {}) or {})}
    if c.get("mode") not in ("local", "server"):
        c["mode"] = "local"
    return c


def remote() -> str | None:
    """서버에서 받는 중이면 그 주소(끝 / 없이), 아니면 None."""
    c = cfg()
    return c["url"].rstrip("/") if c["mode"] == "server" and c.get("url") else None


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
        if body["mode"] not in ("local", "server"):
            raise ValueError("mode 는 local · server 중 하나")
        c["mode"] = body["mode"]
    db.put_setting("origin", c)
    return c


def should_proxy(path: str) -> bool:
    return path.startswith("/api/") and not path.startswith(LOCAL_ONLY)


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=False)
    return _client


async def forward(base: str, method: str, path: str, query: str, body: bytes,
                  ctype: str | None) -> tuple[int, bytes, dict]:
    """서버로 한 번 넘긴다 → (상태, 몸, 머리). 닿지 않으면 502 와 까닭."""
    url = f"{base}{path}" + (f"?{query}" if query else "")
    try:
        r = await client().request(method, url, content=body or None,
                                   headers={"content-type": ctype} if ctype else None)
    except httpx.HTTPError as e:
        log.warning("서버에 닿지 않는다(%s): %s", base, e)
        msg = f"서버({base})에 닿지 않는다 — {type(e).__name__}"
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
    except (httpx.HTTPError, ValueError) as e:
        return {"ok": False, "url": base, "error": f"{type(e).__name__}: {e}"[:200]}
    ok = sorted(k for k, v in st.items() if isinstance(v, dict) and v.get("ok"))
    return {"ok": True, "url": base, "collect_ok": ok, "n": len(st)}

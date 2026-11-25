"""기상청 API 호출 한 곳.

여기서만 HTTP를 친다. 실측으로 배운 함정을 전부 여기서 막는다.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from . import config
from .config import HTTP_RETRY, HTTP_TIMEOUT, KMA_HOST, VERIFY_SSL

log = logging.getLogger("kma")

# HTTP 200인데 본문이 에러인 경우가 있다. raise_for_status()만으로는 못 걸러낸다.
ERROR_MARKS = ("활용신청이 필요한", "인증키", "SERVICE_KEY", "등록되지 않은", "ERROR CODE")


class KmaError(RuntimeError):
    """조회 실패. ⚠️ '자료 없음'과 절대 같이 다루지 않는다."""


# 보고서 서버가 같은 요청을 하는 원문 — 받은 그대로 30시간 둔다(db.kma_raw, /api/kma/raw)
RAW_PATHS = ("/api/typ01/cgi-bin/url/nph-aws2_min", "/api/typ01/cgi-bin/url/nph-dfs_vsrt_grd", "/api/typ01/url/sfc_aws_day.php")


def raw_key(path: str, params) -> str:
    """원문 열쇠 — 경로 + 인자(인증키 · disp=0 · help=0 은 빼고 이름순). 재난상황보고서 kma_guard.raw_key 와 같아야 한다.
    ⚠️ disp=0 이 기본값이 아닌 API 가 있다(sfc_aws_day 는 빼면 쉼표 꼴) — 그런 것은 받을 때 disp=0 을 꼭 붙인다(prefetch)."""
    items = params.items() if isinstance(params, dict) else params
    q = sorted((str(k), str(v)) for k, v in items if str(k).lower() != "authkey" and not (k in ("disp", "help") and str(v) == "0"))
    return path + "?" + "&".join(f"{k}={v}" for k, v in q)


def _has_rows(body: bytes) -> bool:
    """자료 줄이 있나 — 머리말(#)만 온 것('아직 없음')은 두지 않는다."""
    return any(ln and not ln.startswith(b"#") and any(c in b"0123456789" for c in ln) for ln in body.splitlines()[:40])


def _url(path: str) -> str:
    return f"{KMA_HOST}{path}"


async def fetch_text(path: str, params: dict, *, encoding: str = "euc-kr") -> str:
    """텍스트 응답. 실패는 KmaError로 올린다 — 빈 문자열을 돌려주지 않는다."""
    raw = await fetch_bytes(path, params)
    return raw.decode(encoding, errors="replace")


async def fetch_bytes(path: str, params: dict) -> bytes:
    return (await fetch_resp(path, params))[1]


# ── 보고서 서버 대신 받기(/api/kma/pass) — 기상청 키 · 호출을 이 서버 한 곳으로 ──────────────
PASS_PREFIX = ("/api/typ01/", "/api/typ02/", "/api/typ03/")
PASS_TTL = 60            # 같은 요청은 1분 안에는 다시 묻지 않는다(보고서 일꾼 여럿이 같은 것을 부른다)
_pass_sem = asyncio.Semaphore(3)   # 같은 키 동시 요청은 3개까지 — 6개부터 30초 끌다 끊긴다(재난상황보고서 kma_guard 2026-11-21 실측)
_pass_cache: dict[str, tuple[float, str, bytes]] = {}


async def passthrough(path: str, params) -> tuple[str, bytes]:
    """보고서 서버가 부탁한 기상청 요청을 이 서버 키로 — (content-type, 본문). 실패는 KmaError.
    shortcut: 1분 캐시는 메모리 · 크기 무제한에 가깝다(200개 넘으면 오래된 것부터 비움), 보고서 호출이 수천 종류로 늘면 DB(kma_raw)로."""
    if not path.startswith(PASS_PREFIX) or ".." in path:
        raise ValueError("받아 주지 않는 경로")
    key = raw_key(path, params)
    now = asyncio.get_running_loop().time()
    hit = _pass_cache.get(key)
    if hit and now - hit[0] < PASS_TTL:
        return hit[1], hit[2]
    async with _pass_sem:
        ctype, body = await fetch_resp(path, dict(params))
    if len(_pass_cache) > 200:
        for k in sorted(_pass_cache, key=lambda k: _pass_cache[k][0])[:100]:
            _pass_cache.pop(k, None)
    _pass_cache[key] = (now, ctype, body)
    return ctype, body


async def fetch_resp(path: str, params: dict) -> tuple[str, bytes]:
    """(content-type, 본문). fetch_bytes 와 같은 검사 · 재시도."""
    if not config.ORG_API_KEY:                     # 화면에서 바꾼 키가 바로 쓰이게 부를 때마다 읽는다
        raise KmaError("ORG_API_KEY 없음 — config/api_keys.txt 를 확인하세요")

    q = {**params, "authKey": config.ORG_API_KEY}
    last: Exception | None = None

    for attempt in range(HTTP_RETRY + 1):
        try:
            # verify=False 는 내부망 프록시 때문이다(config.DISABLE_SSL_VERIFICATION 참고).
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True,
                                         verify=VERIFY_SSL) as c:
                r = await c.get(_url(path), params=q)
                r.raise_for_status()
                body = r.content

                # 이미지가 아니면 본문에 에러 문구가 섞였는지 본다
                if not r.headers.get("content-type", "").startswith("image"):
                    head = body[:400].decode("euc-kr", errors="replace")
                    for mark in ERROR_MARKS:
                        if mark in head:
                            raise KmaError(f"응답 본문이 오류다: {head.strip()[:120]}")
                if not body:
                    raise KmaError("빈 응답")
                if path in RAW_PATHS and _has_rows(body):
                    try:
                        from . import db
                        db.put_kma_raw(raw_key(path, params), r.headers.get("content-type", ""), body)
                    except Exception:                    # noqa: BLE001 — 보관 실패는 수집을 막지 않는다
                        log.warning("기상청 원문 보관 실패", exc_info=True)
                return r.headers.get("content-type", ""), body
        except Exception as e:                      # noqa: BLE001
            last = e
            if attempt < HTTP_RETRY:
                await asyncio.sleep(0.8)
    # ⚠️ httpx 오류 글에는 주소가 통째로(authKey 까지) 들어 있다 — 수집 기록 · /api/status · 로그로 나가기 전에 가린다
    raise KmaError(f"{path} 실패: {str(last).replace(config.ORG_API_KEY, '***')}")


def parse_rows(text: str) -> list[list[str]]:
    """'#'으로 시작하는 주석과 빈 줄을 걷어내고 공백으로 나눈다."""
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(line.split())
    return rows


def num(v: str) -> float | None:
    """기상청 결측은 음수(-9, -99, -50 이하 등)로 온다."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f <= -9 else f

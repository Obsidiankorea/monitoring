"""기상청 API 호출 한 곳.

여기서만 HTTP를 친다. 실측으로 배운 함정을 전부 여기서 막는다.
"""
from __future__ import annotations

import asyncio
import logging

import httpx

from .config import HTTP_RETRY, HTTP_TIMEOUT, KMA_HOST, ORG_API_KEY

log = logging.getLogger("kma")

# HTTP 200인데 본문이 에러인 경우가 있다. raise_for_status()만으로는 못 걸러낸다.
ERROR_MARKS = ("활용신청이 필요한", "인증키", "SERVICE_KEY", "등록되지 않은", "ERROR CODE")


class KmaError(RuntimeError):
    """조회 실패. ⚠️ '자료 없음'과 절대 같이 다루지 않는다."""


def _url(path: str) -> str:
    return f"{KMA_HOST}{path}"


async def fetch_text(path: str, params: dict, *, encoding: str = "euc-kr") -> str:
    """텍스트 응답. 실패는 KmaError로 올린다 — 빈 문자열을 돌려주지 않는다."""
    raw = await fetch_bytes(path, params)
    return raw.decode(encoding, errors="replace")


async def fetch_bytes(path: str, params: dict) -> bytes:
    if not ORG_API_KEY:
        raise KmaError("ORG_API_KEY 없음 — config/api_keys.txt 를 확인하세요")

    q = {**params, "authKey": ORG_API_KEY}
    last: Exception | None = None

    for attempt in range(HTTP_RETRY + 1):
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT, follow_redirects=True) as c:
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
                return body
        except Exception as e:                      # noqa: BLE001
            last = e
            if attempt < HTTP_RETRY:
                await asyncio.sleep(0.8)
    raise KmaError(f"{path} 실패: {last}")


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

"""휴대폰 공유 링크 — 태풍 브리핑(/t/<토큰>). 로그인 없이 열린다(auth.OPEN 의 '/t/').

담는 것은 보고서 서버(jaenan typhoon_brief)가 만든 공개 기상 자료뿐 — 진로 · 반경 · 바탕도 · 경남 강풍권 시간(이름 · 연락처 없음).
토큰은 추측할 수 없는 무작위(secrets), 30일 지나면 지운다. 같은 자료를 다시 올리면 새 토큰(보고서마다 그때의 판).
"""
from __future__ import annotations

import json
import re
import secrets
import time

from . import config

DIR = config.STATE / "share"
KEEP_DAYS = 30
MAX = 3 * 1024 * 1024                               # 브리핑 자료 하나(바탕도 JPEG 포함) — 보통 100~200KB
OK = re.compile(r"^[A-Za-z0-9_-]{12,32}$")


def base() -> str:
    """밖에서 여는 주소 — Cloudflare 터널(cf-gn)이 이 서버(:8000)로 잇는다. 설정 키 PUBLIC_URL 로 바꾼다."""
    return (config.KEYS.get("PUBLIC_URL") or "https://gisang.day").rstrip("/")


def _prune() -> None:
    cut = time.time() - KEEP_DAYS * 86400
    for p in DIR.glob("*.json"):
        try:
            if p.stat().st_mtime < cut:
                p.unlink()
        except OSError:
            pass


def save(data: bytes) -> str:
    """브리핑 자료(JSON) → 토큰. 꼴이 이상하면 ValueError."""
    if len(data) > MAX:
        raise ValueError("브리핑 자료가 너무 크다")
    d = json.loads(data.decode("utf-8"))
    if not isinstance(d, dict) or not isinstance(d.get("frames"), list) or not str(d.get("base", "")).startswith("data:image/"):
        raise ValueError("브리핑 자료 꼴이 아니다")
    DIR.mkdir(parents=True, exist_ok=True)
    _prune()
    tok = secrets.token_urlsafe(12)
    (DIR / f"{tok}.json").write_bytes(data)
    return tok


def path(tok: str):
    """토큰 → 파일 경로, 없거나 꼴이 틀리면 None."""
    if not OK.match(tok or ""):
        return None
    p = DIR / f"{tok}.json"
    return p if p.is_file() else None


def url(tok: str) -> str:
    return f"{base()}/t/{tok}"

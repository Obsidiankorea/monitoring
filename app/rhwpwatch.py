"""rhwp 새 판 알림 — 보고서 서버(재난상황보고서)가 한글 파일을 만드는 rhwp 의 새 판이 GitHub 에 나오면 텔레그램으로 한 번 알린다.

하루 한 번: GitHub 최신 릴리스 태그 ↔ 보고서 서버 /health 의 rhwp(이미지에 박힌 판). 다르면 알리고 그 태그를 기억한다(같은 판은 다시 안 알림).
**올리지는 않는다** — 판마다 동작이 바뀔 수 있어(0.9.1: replace-text 0건이 파일 없이 성공) 사람이 시험 뒤 Dockerfile 을 고쳐 배포한다.
"""
from __future__ import annotations

import logging

import httpx

from . import aiwatch, db, reports

log = logging.getLogger("rhwpwatch")
LATEST = "https://api.github.com/repos/edwardkim/rhwp/releases/latest"


def _fetch() -> tuple[dict, str]:
    """(GitHub 최신 릴리스, 보고서 서버의 rhwp 판 — 모르면 '')."""
    with httpx.Client(timeout=20) as c:
        rel = c.get(LATEST, headers={"Accept": "application/vnd.github+json"}).raise_for_status().json()
        try:
            have = c.get(f"{reports.url()}/health").json().get("rhwp") or ""
        except (httpx.HTTPError, ValueError):
            have = ""
    return rel, have


def decide(rel: dict, have: str, told: str) -> str | None:
    """알릴 글 — 새 판이 아니거나 이미 알렸으면 None."""
    tag = rel.get("tag_name") or ""
    if not tag or tag == have or tag == told:
        return None
    return (f"🧩 rhwp 새 판 {tag} — 보고서 서버는 {have or '판 모름'}\n{rel.get('name') or ''}\n{rel.get('html_url') or ''}\n"
            "올리려면 Claude 에게 'rhwp 올려줘'(시험 뒤 커푸배).")


async def run() -> dict:
    import asyncio
    try:
        rel, have = await asyncio.to_thread(_fetch)
    except Exception as e:                                 # noqa: BLE001
        log.warning("rhwp 새 판 확인 실패: %s", e)
        return {"error": str(e)[:200]}
    tag = rel.get("tag_name") or ""
    msg = decide(rel, have, db.get_setting("rhwp_told", "") or "")
    if msg and aiwatch.ready():
        try:
            await aiwatch.send(msg)
            db.put_setting("rhwp_told", tag)
        except Exception as e:                             # noqa: BLE001
            log.warning("rhwp 알림 실패: %s", aiwatch._mask(e)[:100])
    return {"latest": tag, "have": have, "told": bool(msg)}

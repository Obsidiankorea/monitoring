"""지금 시각 — 시연(스냅숏)이면 그 시각에 멈춘다(GN_NOW=YYYYMMDDHHMM, config 가 정한다).

화면 · 질의가 '지금'을 쓰는 곳은 datetime.now() 대신 이것을 부른다. 수집기는 시연에서 돌지 않는다.
"""
from __future__ import annotations

import os
from datetime import datetime

from . import config  # noqa: F401 — 시연이면 GN_NOW 를 거기서 정한다

_PIN = os.environ.get("GN_NOW")
PINNED: datetime | None = datetime.strptime(_PIN, "%Y%m%d%H%M") if _PIN else None


def now() -> datetime:
    return PINNED or datetime.now()


def epoch_ms() -> int | None:
    """멈춘 시각(KST)을 브라우저용 ms 로. 실황이면 None."""
    if not PINNED:
        return None
    from zoneinfo import ZoneInfo
    return int(PINNED.replace(tzinfo=ZoneInfo("Asia/Seoul")).timestamp() * 1000)

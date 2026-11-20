"""보고서용 미리 받기 — 재난상황보고서 서버가 보고서를 만들 때 기상청에 묻던 것을 지도 서버가 10분마다 받아 둔다(app/kma.py RAW_PATHS 에 원문 보관).

지금은 일 최대순간풍속(sfc_aws_day obs=ws_ins_max) — 보고서 기본 기간(전날 00시~지금)과 오늘 하루, 두 가지 날짜 묶음.
보고서 서버 kma_guard 가 같은 요청이면 /api/kma/raw 에서 가져간다(없으면 기상청에 한 번만, 못 받으면 문서에 '직접 확인').
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .. import db
from ..kma import KmaError, fetch_text

WIND = "/api/typ01/url/sfc_aws_day.php"


async def collect(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    at = now.strftime("%Y-%m-%d %H:%M")
    today, yday = now.strftime("%Y%m%d"), (now - timedelta(days=1)).strftime("%Y%m%d")
    errs = []
    for d1 in (yday, today):
        try:
            # disp=0 · help=0 을 꼭 — 이 API 는 disp 를 빼면 쉼표 꼴로 답한다(보고서는 빈칸 꼴을 읽는다). 열쇠(raw_key)는 둘을 빼고 만든다
            await fetch_text(WIND, {"tm1": d1, "tm2": today, "obs": "ws_ins_max", "stn": "0", "disp": "0", "help": "0"})
        except KmaError as e:
            errs.append(f"순간풍속 {d1[4:]}~: {str(e)[:60]}")
    db.log_collect("prefetch", not errs, at, "; ".join(errs) or "순간최대풍속 2묶음")
    return {"err": errs or None}

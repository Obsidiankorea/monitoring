"""AWS 강수량 수집 — 정시(awsh) + 최근 구간 보강(매분자료).

⚠️ awsh.php는 매시 00분 자료만 있다. 분단위를 넣으면 빈 응답이다.
   06시 직후엔 06:00 자료가 아직 없을 수 있어 직전 정시로 폴백한다(최대 3시간).
⚠️ 정시 자료만 쓰면 최근 1~2시간이 비어 긴급 상황에서 못 쓴다.
   매분자료(nph-aws2_min)로 그 구간을 메운다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .. import db
from ..domain.regions import stations
from ..kma import KmaError, fetch_text, num, parse_rows

log = logging.getLogger("collect.rain")

GN_STN = {s["stn"] for s in stations()}


def _hour_slots(now: datetime, back: int) -> list[datetime]:
    top = now.replace(minute=0, second=0, microsecond=0)
    return [top - timedelta(hours=i) for i in range(back)]


async def fetch_hour(slot: datetime) -> dict[str, dict]:
    """한 정시의 전 지점 자료. 컬럼: YYMMDDHHMI STN TA WD WS RN_DAY RN_HR1 …"""
    text = await fetch_text("/api/typ01/url/awsh.php",
                            {"tm": slot.strftime("%Y%m%d%H00"), "help": "0"})
    out: dict[str, dict] = {}
    for p in parse_rows(text):
        if len(p) < 7 or p[1] not in GN_STN:
            continue
        out[p[1]] = {"ta": num(p[2]), "rn_day": num(p[5]), "rn_hr1": num(p[6])}
    return out


async def fetch_minute(at: datetime) -> dict[str, dict]:
    """매분자료. 컬럼: … RN-15m(10) RN-60m(11) RN-12H(12) RN-DAY(13). 결측 -50 이하."""
    text = await fetch_text("/api/typ01/cgi-bin/url/nph-aws2_min",
                            {"tm2": at.strftime("%Y%m%d%H%M"), "stn": "0"})
    out: dict[str, dict] = {}
    for p in parse_rows(text):
        if len(p) < 14 or p[1] not in GN_STN:
            continue

        def v(i: int) -> float | None:
            try:
                f = float(p[i])
            except ValueError:
                return None
            return None if f <= -50 else f

        out[p[1]] = {"rn_60m": v(11), "rn_day": v(13)}
    return out


async def collect(now: datetime | None = None, back_hours: int = 26) -> dict:
    """정시 자료를 채우고, 마지막 정시 이후 구간을 매분자료로 보강한다."""
    now = now or datetime.now()
    at = now.strftime("%Y-%m-%d %H:%M")
    filled, failed = 0, []

    # 이미 있는 정시는 다시 부르지 않는다 — 같은 자료를 두 번 받을 이유가 없다
    with db.tx() as con:
        have = {r["tm"] for r in con.execute(
            "SELECT tm FROM obs_hourly WHERE tm >= ? GROUP BY tm",
            ((now - timedelta(hours=back_hours)).strftime("%Y-%m-%d %H:00"),))}

    for slot in _hour_slots(now, back_hours):
        tm = slot.strftime("%Y-%m-%d %H:00")
        if tm in have:
            continue
        try:
            rows = await fetch_hour(slot)
        except KmaError as e:
            # ⚠️ 실패를 '자료 없음'으로 저장하지 않는다. 다음 주기에 다시 시도한다.
            failed.append(f"{tm}: {e}")
            continue

        with db.tx() as con:
            for stn in GN_STN:
                r = rows.get(stn)
                q = "ok" if r and r["rn_hr1"] is not None else "missing"
                con.execute(
                    """INSERT OR REPLACE INTO obs_hourly
                       (stn, tm, rn_hr1, rn_day, ta, quality, fetched_at) VALUES(?,?,?,?,?,?,?)""",
                    (stn, tm, (r or {}).get("rn_hr1"), (r or {}).get("rn_day"),
                     (r or {}).get("ta"), q, at))
        filled += 1

    # 정시 이후 구간 보강 — 화면에 표시할 '실제 최신 시각'이 여기서 나온다
    minute_at = None
    try:
        mark = now.replace(second=0, microsecond=0) - timedelta(minutes=1)
        rows = await fetch_minute(mark)
        if rows:
            minute_at = mark.strftime("%Y-%m-%d %H:%M")
            with db.tx() as con:
                for stn, r in rows.items():
                    con.execute(
                        """INSERT OR REPLACE INTO obs_minute
                           (stn, tm, rn_60m, rn_day, quality, fetched_at) VALUES(?,?,?,?,?,?)""",
                        (stn, minute_at, r["rn_60m"], r["rn_day"],
                         "ok" if r["rn_60m"] is not None else "missing", at))
    except KmaError as e:
        failed.append(f"매분자료: {e}")

    ok = filled > 0 or minute_at is not None
    db.log_collect("rain", ok, at, f"정시 {filled}건 · 보강 {minute_at or '없음'}"
                                   + (f" · 실패 {len(failed)}" if failed else ""))
    return {"filled": filled, "minute_at": minute_at, "failed": failed}

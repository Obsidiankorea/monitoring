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

# 값이 하나도 없는 정시를 몇 시간까지 다시 물어볼 것인가.
# ⚠️ 이게 없으면 정시 직후(HH:00~HH:09)에 한 번 비어 온 시각이 영영 빈 채로 굳는다.
#    실측: 18·19·20시가 전부 '결측'으로 남았는데 기상청에는 19시 3.5mm가 있었다.
RETRY_HOURS = 6

# 화면이 요구한 만큼만 과거를 채운다. 기본 26시간, 화면이 더 긴 구간을 고르면
# 그만큼 늘어난다(줄지는 않는다 — 이미 받아 둔 과거를 버릴 이유가 없다).
# ⚠️ 이게 없으면 '2일'을 골라도 26시간 앞은 영원히 빈 채로 남는다. 실제로 그랬다.
DEPTH_DEFAULT = 26
DEPTH_MAX = 96


def depth() -> int:
    return int(db.get_setting("rain_depth", DEPTH_DEFAULT))


def want_depth(hours: int) -> bool:
    """화면이 요구한 구간을 보관 깊이에 반영한다. 늘어났으면 True."""
    cur, want = depth(), min(DEPTH_MAX, max(1, int(hours)) + 2)   # 여유 2시간
    if want <= cur:
        return False
    db.put_setting("rain_depth", want)
    log.info("보관 깊이 %d → %d시간", cur, want)
    return True


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

        out[p[1]] = {"rn_15m": v(10), "rn_60m": v(11), "rn_day": v(13)}
    return out


async def collect(now: datetime | None = None, back_hours: int | None = None) -> dict:
    """정시 자료를 채우고, 마지막 정시 이후 구간을 매분자료로 보강한다.

    `back_hours` 를 주지 않으면 보관 깊이 설정을 따른다. 이미 값이 든 시각은
    건너뛰므로, 깊이를 늘린 직후 한 번만 실제로 과거를 받아 온다.
    """
    now = now or datetime.now()
    back_hours = int(back_hours or depth())
    at = now.strftime("%Y-%m-%d %H:%M")
    filled, blank, failed = 0, 0, []

    # 이미 '쓸 값이 든' 정시는 다시 부르지 않는다.
    # ⚠️ '한 줄이라도 저장됐는가'로 판정하면 안 된다. 정시 직후에는 아직 자료가
    #    올라오지 않아 전부 결측으로 저장되는데, 그걸 완료로 치면 영영 빈 채로 굳는다.
    #    값이 하나도 없는 시각은 RETRY_HOURS 안이면 다시 물어본다.
    with db.tx() as con:
        have = {r["tm"] for r in con.execute(
            "SELECT tm FROM obs_hourly WHERE tm >= ? GROUP BY tm HAVING SUM(quality='ok') > 0",
            ((now - timedelta(hours=back_hours)).strftime("%Y-%m-%d %H:00"),))}
        old = {r["tm"] for r in con.execute(
            "SELECT tm FROM obs_hourly WHERE tm < ? GROUP BY tm",
            ((now - timedelta(hours=RETRY_HOURS)).strftime("%Y-%m-%d %H:00"),))}
    have |= old        # 오래된 결측은 진짜 결측이다. 계속 물어봐야 소용없다.

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

        if not rows and slot >= now - timedelta(hours=RETRY_HOURS):
            # 최근이면 아직 안 올라온 것이다. 결측으로 굳히지 말고 다음 주기에 다시.
            continue
        if not rows:
            # ⚠️ 오래된 시각이 비어 오면 기상청에 그 자료가 **없는** 것이다.
            #    그냥 넘기면 행이 하나도 안 남아 매 주기마다 영영 다시 묻는다.
            #    결측으로 적어 둬야 `old` 가 잡아 준다.
            blank += 1

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
                           (stn, tm, rn_15m, rn_60m, rn_day, quality, fetched_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (stn, minute_at, r["rn_15m"], r["rn_60m"], r["rn_day"],
                         "ok" if r["rn_60m"] is not None else "missing", at))
    except KmaError as e:
        failed.append(f"매분자료: {e}")

    ok = filled > 0 or minute_at is not None
    db.log_collect("rain", ok, at,
                   f"정시 {filled}건 · 보강 {minute_at or '없음'} · 깊이 {back_hours}h"
                   + (f" · 빈시각 {blank}" if blank else "")
                   + (f" · 실패 {len(failed)}" if failed else ""))
    return {"filled": filled, "blank": blank, "minute_at": minute_at,
            "depth": back_hours, "failed": failed}

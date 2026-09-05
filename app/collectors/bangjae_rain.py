"""스방 시군별 **평균** 강수량 + **다우지점** 수집.

기상청(obs_hourly)과 **다른 관측망**이다. 경남 자체 AWS 212개소 + 기상청 53개소를
합쳐 시군 평균을 내므로 대표지점 하나를 보는 기상청 값과 다르다.
같은 표에 섞지 않고 `bangjae_rain` 에 따로 쌓는다 — 화면에서도 출처를 밝혀야 한다.
다우지점(그 시군에서 제일 많이 온 곳)도 같은 응답에서 함께 받는다. 따로 부르면
두 값의 기준시각이 어긋날 수 있다.

기간은 '어제 00시 ~ 지금'이 기본이다(일일·긴급 보고서가 쓰는 기본 기간과 같다).
스방이 주는 값 자체가 **기간 누적**이라 기간을 함께 저장한다.

시각은 `bangjae.as_of()` 규칙을 따른다 — 06:47 이면 **07시로 조회**하고(지금까지 온
비를 포함시키려고) **06:42 로 저장**한다. 거기 설명을 보라.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .. import db
from ..bangjae import BangjaeError, Client, as_of, available

log = logging.getLogger("collect.bangjae")

DAYS = 2          # 기간 일수(2 = 어제 00시부터). 1 이면 오늘 00시부터.


def _days(now: datetime) -> int:
    """화면이 보는 구간을 덮을 만큼의 날 수. 기상청 보관 깊이를 그대로 따른다.

    깊이가 48시간이면 지금이 07시라도 그저께 자정까지 필요하므로 3일이다.
    (시각으로 세지 않고 날짜 경계로 세야 첫날이 잘리지 않는다)
    """
    from .rain import depth
    시작 = now - timedelta(hours=depth())
    return (now.date() - 시작.date()).days + 1


async def collect(now: datetime | None = None, days: int | None = None) -> dict:
    now = now or datetime.now()
    days = int(days or _days(now))
    at = now.strftime("%Y-%m-%d %H:%M")
    기준, to_time = as_of(now)
    tm = 기준.strftime("%Y-%m-%d %H:%M")

    if not available():
        # 계정이 없으면 **조용히 건너뛴다**. 이 자료는 곁가지라 없다고 화면이 죽으면 안 된다.
        db.log_collect("bangjae", False, at, "스방 계정 없음 — 건너뜀")
        return {"skipped": "no-credentials"}

    fr = (now - timedelta(days=max(1, days) - 1)).strftime("%Y%m%d")
    to = now.strftime("%Y%m%d")
    try:
        async with Client() as c:
            rain = await c.sigun_rain(fr, to, to_time)
            hourly = await _hourly(c, now, days, at)
    except BangjaeError as e:
        # ⚠️ 실패를 '자료 없음'으로 저장하지 않는다. 지난 값이 화면에 남아 있어야 한다.
        db.log_collect("bangjae", False, at, f"조회 실패: {e}")
        return {"failed": str(e)}

    if not rain:
        db.log_collect("bangjae", False, at, "빈 응답(로그인·점검 확인)")
        return {"failed": "empty"}

    with db.tx() as con:
        for sigun, r in rain.items():
            con.execute(
                """INSERT OR REPLACE INTO bangjae_rain
                   (tm, sigun, mm, daw_name, daw_mm, fr, to_date, hour, fetched_at)
                   VALUES(?,?,?,?,?,?,?,?,?)""",
                (tm, sigun, r["mm"], r["daw_name"], r["daw_mm"], fr, to, to_time, at))

    최다 = max(rain.items(), key=lambda x: x[1]["mm"])
    다우 = 최다[1]["daw_name"]
    꼬리 = f"({다우} {최다[1]['daw_mm']:.1f})" if 다우 else ""
    db.log_collect("bangjae", True, at,
                   f"{len(rain)}개 시군 · {fr}~{to} {to_time:02d}시 → {tm} 기준 · "
                   f"최다 {최다[0]} {최다[1]['mm']:.1f}mm{꼬리} · 시간표 {hourly}칸")
    return {"count": len(rain), "tm": tm, "top": (최다[0], 최다[1]["mm"]),
            "hourly": hourly}


async def _hourly(c: Client, now: datetime, days: int, at: str) -> int:
    """지점별 시간강우량(dt096)을 하루씩 받아 쌓는다. 저장한 칸 수를 돌려준다.

    화면의 타임라인은 시각별 값이 있어야 그려진다. 시군 평균 하나만으로는
    막대 하나밖에 못 그린다. 265개소 × 24시간을 받아 두면 화면에서
    **다우지점**(그 시군 최대)도 **시군 평균**(전 지점 평균)도 다 나온다.
    기상청 56개소로 고르던 다우지점과는 후보 수 자체가 다르다.

    지난 날은 값이 더 바뀌지 않으므로 다시 받지 않는다. 다만 **그 날이 끝난 뒤에
    받아 둔 것이라야** 건너뛴다.

    ⚠️ 예전에는 '23시 칸이 있으면 건너뛴다'로 판정했는데, 이게 하루를 통째로
       얼려 버렸다. 그 날 아침에 한 번 받으면 아직 오지 않은 시각까지 빈 칸으로
       저장되고 — 23시 칸도 그때 생긴다 — 그 뒤로는 영영 건너뛰었다.
       실측: 9.3. 08:46 에 받은 뒤 얼어붙어, 그날 오후에 내린 비(사천 6.8㎜,
       창원 5.2㎜)가 대시보드에 끝까지 안 나왔다. 스방 앱에는 그대로 있었다.
       그래서 이제 **받은 때가 그 날 다음날 이후**인지로 판정한다.
    """
    span = max(1, int(days))
    오늘 = now.strftime("%Y-%m-%d")
    칸 = 0
    for i in range(span - 1, -1, -1):
        d = now - timedelta(days=i)
        날 = d.strftime("%Y-%m-%d")
        if 날 != 오늘:
            끝난뒤 = (d + timedelta(days=1)).strftime("%Y-%m-%d 00:00")
            with db.tx() as con:
                r = con.execute(
                    """SELECT COUNT(*) n FROM bangjae_hourly
                       WHERE tm BETWEEN ? AND ? AND fetched_at >= ?""",
                    (f"{날} 00:00", f"{날} 23:59", 끝난뒤)).fetchone()
            if r and r["n"]:
                continue                          # 그 날이 끝난 뒤에 받아 둔 것이다
        try:
            rows = await c.station_hourly(d.strftime("%Y%m%d"))
        except BangjaeError as e:
            log.warning("%s 시간강우 실패: %s", 날, e)
            continue
        with db.tx() as con:
            for st in rows:
                for h, mm in enumerate(st["mm"]):
                    if mm is None:
                        continue      # 아직 오지 않은 시각. 빈 칸으로 굳히지 않는다
                    con.execute(
                        """INSERT OR REPLACE INTO bangjae_hourly
                           (tm, stn, name, sigun, mm, fetched_at) VALUES(?,?,?,?,?,?)""",
                        (f"{날} {h:02d}:00", st["stn"], st["name"], st["sigun"], mm, at))
                    칸 += 1
    return 칸

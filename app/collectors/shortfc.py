"""단기예보 격자 수집 — nph-dfs_shrt_grd. 권역·시군 예보 판의 출처.

초단기예측(forecast.py)과 **같은 격자**(149 × 253, 약 5km)다. 읍면동 ↔ XY 매핑도
`data/gyeongnam_grids.json` 을 그대로 쓴다. 경남 18개 시군 206개 읍면동(격자 203칸).

받는 것
  PCP  1시간 강수량(mm). 대상시각 H 의 값은 (H-1)시~H시에 내리는 양이다.
       날짜별로 더해 '그날 예상강수량'을 만든다.
  TMN  일 최저기온 — 대상시각 D 06시에만 있다.
  TMX  일 최고기온 — 대상시각 D 15시에만 있다.

⚠️ 발표는 하루 8번(02·05·08·11·14·17·20·23시)이고 실제로는 +10분쯤 올라온다.
   격자는 그보다 늦을 수 있어 **한 발표분을 통째로 다 받아야 완료**로 친다.
   덜 받은 채 끊겼으면 다음 주기에 빠진 대상시각만 이어 받는다.
⚠️ 아직 안 나온 발표분을 주면 격자가 -99 로 가득 온다(초단기와 같은 성질로 본다).
   그때는 **직전 발표분**을 쓴다 — 화면이 비는 것보다 3시간 묵은 예보가 낫다.
⚠️ 선행시간 끝을 넘은 대상시각도 -99 로 가득 온다. 그 자리에서 PCP 를 멈춘다.
⚠️ **실측으로 확인하지 못한 가정이 있다** — tmfc 를 10자리(YYYYMMDDHH)로 준다는 것,
   PCP 가 숫자(mm)로 온다는 것. 틀리면 수집 상태에 '격자 매칭 없음'이 찍힌다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .. import db
from ..domain.regions import grids
from ..kma import KmaError, fetch_text
from .forecast import _parse_grid

log = logging.getLogger("collect.short")

BASES = (2, 5, 8, 11, 14, 17, 20, 23)
READY_MIN = 20          # 발표 +몇 분부터 받으러 가나
DAYS = 3                # 오늘·내일·모레
KEEP = 3                # 남겨 둘 발표분 수 — 직전 발표 대비(▲▼)에 하나는 있어야 한다


def base_of(now: datetime) -> datetime:
    """지금 받을 수 있는 가장 최근 발표시각."""
    t = now - timedelta(minutes=READY_MIN)
    for d in range(2):
        day = (t - timedelta(days=d)).replace(minute=0, second=0, microsecond=0)
        for h in reversed(BASES):
            b = day.replace(hour=h)
            if b <= t:
                return b
    raise AssertionError("unreachable")


def plan(base: datetime, today: datetime) -> list[tuple[str, datetime]]:
    """이 발표분에서 받을 (요소, 대상시각) 목록. 오늘·내일·모레만."""
    d0 = today.replace(hour=0, minute=0, second=0, microsecond=0)
    end = d0 + timedelta(days=DAYS)            # 모레 24시(=글피 00시)
    out: list[tuple[str, datetime]] = []
    t = base + timedelta(hours=1)
    while t <= end:
        out.append(("PCP", t))
        t += timedelta(hours=1)
    for i in range(DAYS):
        d = d0 + timedelta(days=i)
        for var, hh in (("TMN", 6), ("TMX", 15)):
            if d.replace(hour=hh) > base:
                out.append((var, d.replace(hour=hh)))
    return out


def cells() -> list[tuple[int, int]]:
    seen: dict[tuple[int, int], None] = {}
    for items in grids()["sigun_grids"].values():
        for it in items:
            seen[tuple(it["xy"])] = None
    return list(seen)


async def _grid(tmfc: str, tmef: str, var: str) -> list[float]:
    text = await fetch_text("/api/typ01/cgi-bin/url/nph-dfs_shrt_grd",
                            {"tmfc": tmfc, "tmef": tmef, "vars": var}, encoding="utf-8")
    return _parse_grid(text)


def _empty(vals: list[float]) -> bool:
    return not vals or max(vals) <= -90


def _done(tmfc: str) -> tuple[set[str], dict | None]:
    with db.tx() as con:
        got = {f"{r['var']}{r['tmef']}" for r in con.execute(
            "SELECT DISTINCT var, tmef FROM fcst_short WHERE tmfc=?", (tmfc,))}
        run = con.execute("SELECT * FROM fcst_short_run WHERE tmfc=?", (tmfc,)).fetchone()
    return got, (dict(run) if run else None)


async def _fill(base: datetime, now: datetime, at: str) -> dict:
    """한 발표분을 받는다. 이미 받은 대상시각은 건너뛴다."""
    tmfc = base.strftime("%Y%m%d%H")
    width = grids().get("grid_width", 149)
    xy = cells()
    got, run = _done(tmfc)
    if run and run["complete"]:
        return {"tmfc": tmfc, "saved": 0, "complete": True, "skipped": True}

    saved, failed, pcp_end = 0, [], None
    for var, t in plan(base, now):
        tmef = t.strftime("%Y%m%d%H")
        if var == "PCP" and pcp_end and tmef > pcp_end:
            continue                              # 선행시간 끝을 넘었다
        if f"{var}{tmef}" in got:
            continue
        try:
            vals = await _grid(tmfc, tmef + "00", var)
        except KmaError as e:
            failed.append(f"{var} {tmef}: {e}")
            if saved == 0 and not got:
                break                             # 첫 칸부터 막히면 더 두드리지 않는다
            continue
        if _empty(vals):
            if saved == 0 and not got:
                return {"tmfc": tmfc, "saved": 0, "complete": False, "missing": True}
            if var == "PCP":
                pcp_end = tmef                    # 여기부터는 이 발표분에 없다
            continue
        rows = []
        for x, y in xy:
            i = (y - 1) * width + (x - 1)
            v = vals[i] if 0 <= i < len(vals) else None
            rows.append((tmfc, tmef, var, x, y, None if v is None or v <= -90 else v, at))
        with db.tx() as con:
            con.executemany(
                """INSERT OR REPLACE INTO fcst_short(tmfc, tmef, var, x, y, val, fetched_at)
                   VALUES(?,?,?,?,?,?,?)""", rows)
        saved += 1

    complete = not failed
    with db.tx() as con:
        con.execute(
            """INSERT INTO fcst_short_run(tmfc, complete, fetched_at) VALUES(?,?,?)
               ON CONFLICT(tmfc) DO UPDATE SET complete=excluded.complete,
                 fetched_at=excluded.fetched_at""",
            (tmfc, 1 if complete else 0, at))
    return {"tmfc": tmfc, "saved": saved, "complete": complete, "failed": failed}


def _prune() -> None:
    with db.tx() as con:
        keep = [r["tmfc"] for r in con.execute(
            "SELECT tmfc FROM fcst_short_run ORDER BY tmfc DESC LIMIT ?", (KEEP,))]
        if len(keep) < KEEP:
            return
        con.execute("DELETE FROM fcst_short WHERE tmfc < ?", (keep[-1],))
        con.execute("DELETE FROM fcst_short_run WHERE tmfc < ?", (keep[-1],))


async def collect(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    at = now.strftime("%Y-%m-%d %H:%M")
    base = base_of(now)
    res = await _fill(base, now, at)
    if res.get("missing"):
        # 아직 안 올라왔다 — 직전 발표분이라도 온전히 갖춰 둔다
        prev = base_of(base - timedelta(minutes=1) + timedelta(minutes=READY_MIN))
        res = await _fill(prev, now, at)
        res["note"] = f"{base:%H}시 발표분 아직 없음"
    _prune()

    ok = res.get("complete") or res.get("saved", 0) > 0
    msg = f"발표 {res['tmfc'][8:10]}시"
    if res.get("skipped"):
        msg += " · 받아 둠"
    else:
        msg += f" · {res.get('saved', 0)}칸"
    if res.get("failed"):
        msg += f" · 실패 {len(res['failed'])}"
    if res.get("note"):
        msg += f" · {res['note']}"
    db.log_collect("short", bool(ok), at, msg)
    return res

"""초단기예측 RN1 격자 수집 — nph-dfs_vsrt_grd.

응답은 37,697개 float = 동네예보 격자 149 × 253. 인덱스 = (Y-1)*149 + (X-1).
-99는 결측/무강수.

⚠️ RN1은 선행 1시간 누적이라 값이 1시간 단위로만 바뀐다. 10분 간격으로 불러도
   같은 격자를 여섯 번 받는 셈이다 — 선행 1시간 구간당 한 번만 조회한다.
⚠️ 누적을 낼 때 칸을 그냥 더하면 3배가 된다. 1시간 구간마다 한 번씩만 더한다.
⚠️ 아직 안 나온 tmfc를 주면 최신 발표분으로 대체해 돌려준다.
⚠️ 발표분을 고정해 읽으면 막 올라오는 중에 빈 격자가 오기도 한다.
   0이 나오면 tmfc 없이 최신분으로 한 번 더 확인한다(pitfalls ★3).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from .. import db
from ..domain.regions import grids
from ..kma import KmaError, fetch_text

log = logging.getLogger("collect.forecast")

HOURS_AHEAD = 6


def _slot(now: datetime) -> datetime:
    """발표시각. 실측 지연 +2~8분이라 10분 슬롯에서 한 칸 물러선다."""
    t = now.replace(second=0, microsecond=0)
    t -= timedelta(minutes=t.minute % 10)
    return t - timedelta(minutes=10)


def _parse_grid(text: str) -> list[float]:
    vals: list[float] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        for tok in line.replace(",", " ").split():
            try:
                vals.append(float(tok))
            except ValueError:
                pass
    return vals


def _pick(vals: list[float], width: int) -> dict[str, dict[str, float]]:
    """격자 → 읍면동. 창원은 5개 구를 하나로 병합해 두었다."""
    g = grids()
    out: dict[str, dict[str, float]] = {}
    for sig, items in g["sigun_grids"].items():
        for it in items:
            x, y = it["xy"]
            i = (y - 1) * width + (x - 1)
            if 0 <= i < len(vals):
                v = vals[i]
                out.setdefault(sig, {})[it["emd"]] = 0.0 if v <= -90 else v
    return out


async def _grid(tmfc: str | None, tmef: str) -> list[float]:
    params = {"tmef": tmef, "vars": "RN1"}
    if tmfc:
        params["tmfc"] = tmfc
    text = await fetch_text("/api/typ01/cgi-bin/url/nph-dfs_vsrt_grd", params, encoding="utf-8")
    return _parse_grid(text)


async def collect(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    at = now.strftime("%Y-%m-%d %H:%M")
    base = _slot(now)
    tmfc = base.strftime("%Y%m%d%H%M")
    width = grids().get("grid_width", 149)

    # 같은 발표분을 이미 받아 뒀으면 다시 부르지 않는다
    with db.tx() as con:
        done = {r["tmef"] for r in con.execute(
            "SELECT DISTINCT tmef FROM fcst_rn1 WHERE tmfc=?", (tmfc,))}

    saved, failed = 0, []
    for h in range(1, HOURS_AHEAD + 1):
        target = (base + timedelta(hours=h)).replace(minute=0)
        tmef = target.strftime("%Y%m%d%H%M")
        if tmef in done:
            continue
        try:
            vals = await _grid(tmfc, tmef)
            if not vals or max(vals) <= -90:
                # 막 올라오는 중일 수 있다 — 최신분으로 한 번 더 확인한다
                vals = await _grid(None, tmef)
        except KmaError as e:
            failed.append(f"{tmef}: {e}")
            continue

        rows = _pick(vals, width)
        if not rows:
            failed.append(f"{tmef}: 격자 매칭 없음")
            continue

        with db.tx() as con:
            for sig, emds in rows.items():
                for emd, v in emds.items():
                    con.execute(
                        """INSERT OR REPLACE INTO fcst_rn1
                           (tmfc, tmef, sigun, emd, rn1, fetched_at) VALUES(?,?,?,?,?,?)""",
                        (tmfc, tmef, sig, emd, v, at))
        saved += 1

    ok = saved > 0 or bool(done)
    db.log_collect("forecast", ok, at, f"발표 {tmfc[8:12]} · {saved}구간"
                                       + (f" · 실패 {len(failed)}" if failed else ""))
    return {"tmfc": tmfc, "saved": saved, "failed": failed}

"""폭염 화면 — 시군별 관측 기온(obs_hourly.ta, 기상청 AWS 정시).

체감온도 · 사흘 예보는 아직 없다(습도 · 단기예보 기온을 받으면 붙인다). 화면은 기온만 실제 값이다.
"""
from __future__ import annotations

from . import db, sites
from .domain.regions import ORDER
from .queries import STN_NAME, STN_SIGUN

SPAN = 24                                 # 선 그래프 시간 수


def build(obs: list[tuple[str, str, float]], off: set[str] = frozenset()) -> dict:
    """(지점, 시각, 기온) → 시군마다 최고 지점 · 한 시간 변화 · 오늘 최고 · 24시간 시군 최고."""
    obs = [o for o in obs if o[0] in STN_SIGUN and o[0] not in off and -50 < o[2] < 60]
    tms = sorted({o[1] for o in obs})[-SPAN:]
    if not tms:
        return {"tm": None, "n": 0, "rows": []}
    at: dict[str, dict[str, tuple[float, str]]] = {}      # 시군 → 시각 → (최고, 지점)
    for stn, tm, ta in obs:
        c = at.setdefault(STN_SIGUN[stn], {})
        if tm in tms and (tm not in c or ta > c[tm][0]):
            c[tm] = (ta, stn)
    last, prev = tms[-1], tms[-2] if len(tms) > 1 else None
    rows = []
    for sig in ORDER:
        c = at.get(sig, {})
        if last not in c:
            continue
        ta, stn = c[last]
        today = [v[0] for t, v in c.items() if t[:10] == last[:10]]
        rows.append({"sigun": sig, "stn": STN_NAME[stn], "ta": ta, "hi": max(today),
                     "dt": round(ta - c[prev][0], 1) if prev in c else None,
                     "d": [c[t][0] if t in c else None for t in tms]})
    return {"tm": last, "n": len({o[0] for o in obs if o[1] == last}), "rows": rows}


def status() -> dict:
    with db.tx() as con:
        r = con.execute("SELECT MAX(tm) AS tm FROM obs_hourly WHERE ta IS NOT NULL").fetchone()
        if not r or not r["tm"]:
            return build([])
        obs = [(x["stn"], x["tm"], x["ta"]) for x in con.execute(
            "SELECT stn, tm, ta FROM obs_hourly WHERE ta IS NOT NULL AND tm >= datetime(?, '-1 day')", (r["tm"],))]
    return build(obs, sites.off_keys())

"""겨울 화면 — 시군별 기온 · 체감온도 · 바람 · 실효습도와 한파 · 강풍 · 건조 특보 기준까지 얼마나 남았나.

자료는 기상청 AWS 정시(obs_hourly: ta · ws · hm)와 매분자료의 최대순간풍속(obs_minute.wss).
시군 값은 가장 나쁜 지점 — 기온 · 체감 · 습도는 가장 낮은 곳, 바람은 가장 센 곳.

특보 기준(기상청, 육상):
  한파  주의보 아침 최저 -12℃ 이하 또는 전날보다 10℃ 이상 내려 3℃ 이하 · 경보 -15℃ 또는 15℃ 이상 내려 3℃ 이하
  강풍  주의보 풍속 14m/s 또는 순간 20m/s · 경보 21m/s 또는 순간 26m/s (산지 기준은 따로 두지 않는다)
  건조  주의보 실효습도 35% 이하 · 경보 25% 이하 (2일 이상 지속 예상 — 예보 판단은 사람 몫, 여기는 지금 값)
'지금 값이 기준을 넘었다'는 특보 발표가 아니다. 카드는 '얼마나 가까운가'만 보여 준다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db, sites
from .domain.regions import ORDER
from .queries import STN_NAME, STN_SIGUN

SPAN = 24
MORNING = 9                       # 아침 최저 = 0시 ~ 9시
R = 0.7                           # 실효습도 감쇠 계수


def feel(ta: float | None, ws: float | None) -> float | None:
    """겨울 체감온도(기상청 식). 10℃ 이하 · 풍속 1.3m/s(4.8km/h) 이상일 때만, 아니면 기온 그대로."""
    if ta is None:
        return None
    if ws is None or ta > 10 or ws < 1.3:
        return ta
    v = (ws * 3.6) ** 0.16
    return round(13.12 + 0.6215 * ta - 11.37 * v + 0.3965 * v * ta, 1)


def effective_hm(days: list[float | None]) -> float | None:
    """실효습도 He = (1-r)(H0 + rH1 + r²H2 + r³H3 + r⁴H4). days = [오늘, 1일 전, …, 4일 전] 평균습도. 하루라도 비면 None."""
    if len(days) < 5 or any(h is None for h in days[:5]):
        return None
    return round((1 - R) * sum(h * R ** i for i, h in enumerate(days[:5])), 1)


def levels(tmin, drop, ws, wss, he) -> dict:
    """특보 기준에 비춘 단계 — 'warn' 경보 기준 · 'watch' 주의보 기준 · 'near' 다가감 · '' 멂."""
    def cold():
        if tmin is None:
            return ""
        if tmin <= -15 or (drop is not None and drop >= 15 and tmin <= 3):
            return "warn"
        if tmin <= -12 or (drop is not None and drop >= 10 and tmin <= 3):
            return "watch"
        return "near" if tmin <= -9 or (drop is not None and drop >= 7 and tmin <= 5) else ""

    def wind():
        w, g = ws or 0, wss or 0
        if w >= 21 or g >= 26:
            return "warn"
        if w >= 14 or g >= 20:
            return "watch"
        return "near" if w >= 10 or g >= 15 else ""

    def dry():
        if he is None:
            return ""
        return "warn" if he <= 25 else "watch" if he <= 35 else "near" if he <= 45 else ""
    return {"cold": cold(), "wind": wind(), "dry": dry()}


def build(obs: list[tuple], gust: dict[str, float] | None = None, off: set[str] = frozenset()) -> dict:
    """obs = (지점, 시각, 기온, 풍속, 습도). gust = 지점 → 최근 1시간 최대순간풍속."""
    gust = gust or {}
    obs = [o for o in obs if o[0] in STN_SIGUN and o[0] not in off]
    tms = sorted({o[1] for o in obs if o[2] is not None})
    if not tms:
        return {"tm": None, "n": 0, "rows": []}
    last = tms[-1]
    today = last[:10]
    yday = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
    days = [(datetime.strptime(today, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(5)]
    span = tms[-SPAN:]

    st: dict[str, dict] = {}                     # 지점 → 모은 값
    for stn, tm, ta, ws, hm in obs:
        s = st.setdefault(stn, {"ta": {}, "hm": {}})
        if ta is not None and -50 < ta < 50:
            s["ta"][tm] = ta
        if hm is not None and 0 <= hm <= 100:
            s["hm"].setdefault(tm[:10], []).append(hm)
        if tm == last:
            s.update(now_ta=ta, ws=ws, hm_now=hm)

    def morning(s, day):
        v = [t for tm, t in s["ta"].items() if tm[:10] == day and int(tm[11:13]) <= MORNING]
        return min(v) if v else None

    by: dict[str, list] = {}
    for stn, s in st.items():
        if s.get("now_ta") is None:
            continue
        tmin, tmin_y = morning(s, today), morning(s, yday)
        means = [round(sum(v) / len(v), 1) if (v := s["hm"].get(d)) else None for d in days]
        by.setdefault(STN_SIGUN[stn], []).append({
            "stn": stn, "ta": s["now_ta"], "feel": feel(s["now_ta"], s.get("ws")), "ws": s.get("ws"),
            "wss": gust.get(stn), "hm": s.get("hm_now"), "he": effective_hm(means),
            "tmin": tmin, "drop": round(tmin_y - tmin, 1) if tmin is not None and tmin_y is not None else None,
            "d": [s["ta"].get(t) for t in span]})

    def lo(v, k):
        x = [r for r in v if r[k] is not None]
        return min(x, key=lambda r: r[k]) if x else None

    def hi(v, k):
        x = [r for r in v if r[k] is not None]
        return max(x, key=lambda r: r[k]) if x else None

    rows = []
    for sig in ORDER:
        v = by.get(sig)
        if not v:
            continue
        c, f, w, g, h, m = lo(v, "ta"), lo(v, "feel"), hi(v, "ws"), hi(v, "wss"), lo(v, "he"), lo(v, "tmin")
        dr = hi(v, "drop")
        row = {"sigun": sig, "stn": STN_NAME[c["stn"]], "ta": c["ta"],
               "feel": f and f["feel"], "ws": w and w["ws"], "ws_stn": w and STN_NAME[w["stn"]],
               "wss": g and g["wss"], "hm": (lo(v, "hm") or {}).get("hm"), "he": h and h["he"], "he_stn": h and STN_NAME[h["stn"]],
               "tmin": m and m["tmin"], "drop": dr and dr["drop"],
               "d": [min((r["d"][i] for r in v if r["d"][i] is not None), default=None) for i in range(len(span))]}
        row["lv"] = levels(row["tmin"], row["drop"], row["ws"], row["wss"], row["he"])
        rows.append(row)
    return {"tm": last, "n": sum(1 for s in st.values() if s.get("now_ta") is not None), "rows": rows,
            "he_ready": any(r["he"] is not None for r in rows)}


def status() -> dict:
    with db.tx() as con:
        r = con.execute("SELECT MAX(tm) AS tm FROM obs_hourly WHERE ta IS NOT NULL").fetchone()
        if not r or not r["tm"]:
            return build([])
        obs = [(x["stn"], x["tm"], x["ta"], x["ws"], x["hm"]) for x in con.execute(
            "SELECT stn, tm, ta, ws, hm FROM obs_hourly WHERE tm >= datetime(?, '-5 days', 'start of day')", (r["tm"],))]
        gust = {x["stn"]: x["g"] for x in con.execute(
            "SELECT stn, MAX(wss) AS g FROM obs_minute WHERE wss IS NOT NULL AND tm > "
            "(SELECT strftime('%Y-%m-%d %H:%M', MAX(tm), '-60 minutes') FROM obs_minute WHERE wss IS NOT NULL) GROUP BY stn")}
    return build(obs, gust, sites.off_keys())

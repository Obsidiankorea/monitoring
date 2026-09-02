"""DB 읽기. 화면은 이 함수들만 부른다 — 기상청을 직접 부르지 않는다.

⚠️ 결측을 0으로 더하지 않는다. 뺀 시간 수를 함께 돌려줘 화면이 "N시간 결측"을
   붙일 수 있게 한다. 조용히 0으로 더하면 과소평가가 사실처럼 읽힌다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db
from .domain.regions import ORDER, REP_STN, by_sigun, stations

STN_NAME = {s["stn"]: s["name"] for s in stations()}
STN_SIGUN = {s["stn"]: s["sigun"] for s in stations()}


def _slots(hours: int, now: datetime) -> list[str]:
    top = now.replace(minute=0, second=0, microsecond=0)
    return [(top - timedelta(hours=i)).strftime("%Y-%m-%d %H:00") for i in range(hours - 1, -1, -1)]


def rain(hours: int = 12, now: datetime | None = None) -> dict:
    """지점별 시간대별 강수량 + 기간 누적. 마지막 칸은 매분자료로 보강한다."""
    now = now or datetime.now()
    slots = _slots(hours, now)
    lo, hi = slots[0], slots[-1]

    series: dict[str, dict[str, object]] = {}
    with db.tx() as con:
        for r in con.execute(
            "SELECT stn, tm, rn_hr1, quality FROM obs_hourly WHERE tm BETWEEN ? AND ?", (lo, hi)
        ):
            series.setdefault(r["stn"], {})[r["tm"]] = (
                r["rn_hr1"] if r["quality"] == "ok" else None
            )

        # 정시 이후 구간 — 실제 최신 시각을 화면에 그대로 쓴다.
        # 마지막 칸은 '정시부터 지금까지'다. 21:36이면 21:00~21:36.
        # ⚠️ RN-60m(직전 60분)을 쓰면 안 된다. 앞 정시 칸과 겹쳐 누적이 부풀고,
        #    칸이 가리키는 구간과 값이 담고 있는 구간이 어긋난다.
        #    RN-60m은 참고값으로 툴팁에만 붙인다.
        m = con.execute("SELECT MAX(tm) AS tm FROM obs_minute").fetchone()
        minute_tm = m["tm"] if m and m["tm"] else None
        minute: dict[str, float | None] = {}
        m60: dict[str, float | None] = {}
        if minute_tm:
            base_day = {r["stn"]: r["rn_day"] for r in con.execute(
                "SELECT stn, rn_day FROM obs_hourly WHERE tm=? AND quality='ok'", (slots[-1],))}
            for r in con.execute(
                "SELECT stn, rn_day, rn_60m, quality FROM obs_minute WHERE tm=?", (minute_tm,)
            ):
                b, cur = base_day.get(r["stn"]), r["rn_day"]
                # RN_DAY는 01시에 0으로 리셋된다 — 증분이 음수면 자정을 넘은 것이므로 버린다
                minute[r["stn"]] = (round(cur - b, 1) if r["quality"] == "ok"
                                    and b is not None and cur is not None and cur >= b else None)
                m60[r["stn"]] = r["rn_60m"] if r["quality"] == "ok" else None

    # ⚠️ 매분 보강값으로 마지막 정시 칸을 덮으면 그 한 시간이 통째로 사라진다.
    #    칸을 하나 더 붙여야 '정시까지'와 '정시 이후 지금까지'가 둘 다 남는다.
    labels = [s[11:13] for s in slots]
    partial = bool(minute_tm and minute_tm[11:16] > slots[-1][11:16])
    if partial:
        labels.append(minute_tm[11:16])

    out = []
    for stn, name in STN_NAME.items():
        vals = [series.get(stn, {}).get(s) for s in slots]
        if partial:
            vals.append(minute.get(stn))
        ok = [v for v in vals if v is not None]
        out.append({
            "stn": stn, "name": name, "sigun": STN_SIGUN[stn],
            "rep": REP_STN.get(STN_SIGUN[stn]) == stn,
            "d": vals,
            "m60": m60.get(stn) if partial else None,   # 참고 — 툴팁에만 쓴다
            "sum": round(sum(ok), 1),
            "bad": len(vals) - len(ok),
        })

    return {
        "labels": labels, "hours": hours,
        "base_hour": slots[-1][11:16],
        "minute_tm": minute_tm[11:16] if partial else None,
        "rows": out,
    }


def forecast(hours: int = 6, now: datetime | None = None) -> dict:
    """최신 발표분의 읍면동 예측. 시군 대표값은 그 시군 읍면동 최대값이다."""
    with db.tx() as con:
        row = con.execute("SELECT MAX(tmfc) AS t FROM fcst_rn1").fetchone()
        tmfc = row["t"] if row else None
        if not tmfc:
            return {"tmfc": None, "labels": [], "emd": [], "sigun": []}

        # ⚠️ 발표가 한 박자 늦으면 첫 예측 시각이 이미 지나간 시각이다.
        #    그대로 그리면 예측이 현재보다 뒤에 놓여 한 시간씩 밀린다. 지난 것은 버린다.
        now_h = (now or datetime.now()).strftime("%Y%m%d%H")
        tmefs = [r["tmef"] for r in con.execute(
            "SELECT DISTINCT tmef FROM fcst_rn1 WHERE tmfc=? ORDER BY tmef", (tmfc,))
            if r["tmef"] > now_h][:hours]
        rows = list(con.execute(
            "SELECT tmef, sigun, emd, rn1 FROM fcst_rn1 WHERE tmfc=?", (tmfc,)))

    idx = {t: i for i, t in enumerate(tmefs)}
    emd: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        if r["tmef"] not in idx:
            continue
        key = (r["sigun"], r["emd"])
        emd.setdefault(key, [0.0] * len(tmefs))[idx[r["tmef"]]] = r["rn1"]

    emd_list = [{"sigun": s, "emd": e, "d": d, "sum": round(sum(d), 1), "peak": max(d) if d else 0}
                for (s, e), d in emd.items()]
    # ⚠️ 순위는 시우량이 아니라 누적으로 매긴다. RN1이 정수 mm로 양자화돼
    #    시우량으로 줄 세우면 30·20에 동률이 쏟아진다.
    emd_list.sort(key=lambda x: (-x["sum"], -x["peak"]))

    sig: list[dict] = []
    for s in ORDER:
        mine = [e for e in emd_list if e["sigun"] == s]
        if not mine:
            continue
        top = mine[0]
        sig.append({"sigun": s, "emd": top["emd"], "d": top["d"],
                    "sum": top["sum"], "peak": top["peak"]})
    sig.sort(key=lambda x: (-x["sum"], -x["peak"]))

    return {"tmfc": tmfc, "labels": [t[8:10] for t in tmefs],
            "emd": emd_list[:24], "sigun": sig}


def alerts() -> dict:
    snap = db.latest_snapshot("alerts")
    return snap or {"base_time": None, "fetched_at": None,
                    "data": {"groups": [], "pending": []}}


def qpf_frames() -> dict:
    with db.tx() as con:
        row = con.execute("SELECT MAX(tmfc) AS t FROM qpf_frame").fetchone()
        tmfc = row["t"] if row else None
        if not tmfc:
            return {"tmfc": None, "frames": []}
        efs = [r["ef"] for r in con.execute(
            "SELECT ef FROM qpf_frame WHERE tmfc=? ORDER BY ef", (tmfc,))]
    return {"tmfc": tmfc, "frames": efs}


def status() -> dict:
    with db.tx() as con:
        rows = list(con.execute("SELECT kind, ok_at, tried_at, ok, detail FROM collect_log"))
    return {r["kind"]: {"ok_at": r["ok_at"], "tried_at": r["tried_at"],
                        "ok": bool(r["ok"]), "detail": r["detail"]} for r in rows}

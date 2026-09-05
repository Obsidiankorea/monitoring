"""DB 읽기. 화면은 이 함수들만 부른다 — 기상청을 직접 부르지 않는다.

⚠️ 결측을 0으로 더하지 않는다. 뺀 시간 수를 함께 돌려줘 화면이 "N시간 결측"을
   붙일 수 있게 한다. 조용히 0으로 더하면 과소평가가 사실처럼 읽힌다.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from . import db
from .bangjae import as_of as bj_as_of
from .domain.regions import ORDER, REP_STN, by_sigun, stations

STN_NAME = {s["stn"]: s["name"] for s in stations()}
STN_SIGUN = {s["stn"]: s["sigun"] for s in stations()}


def _slots(hours: int, now: datetime) -> list[str]:
    top = now.replace(minute=0, second=0, microsecond=0)
    return [(top - timedelta(hours=i)).strftime("%Y-%m-%d %H:00") for i in range(hours - 1, -1, -1)]


def rain(hours: int = 12, now: datetime | None = None, src: str = "kma") -> dict:
    """지점별 시간대별 강수량 + 기간 누적.

    `src`
      kma      기상청 AWS 56개소. 마지막 칸은 매분자료로 보강한다.
      bangjae  스방 265개소. 후보가 다섯 배라 **다우지점이 훨씬 촘촘하다**
               (고성 학림 500.5mm를 기상청 AWS는 아예 못 본다).
    """
    if src == "bangjae":
        return _rain_bangjae(hours, now)
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

    # 아직 한 줄도 안 받은 시각 — 화면이 '채우는 중'을 알아야 다시 물어본다.
    # ⚠️ 결측(quality='missing')과 다르다. 그건 기상청에 자료가 없는 것이고,
    #    이건 우리가 아직 안 받아 온 것이다.
    with db.tx() as con:
        have = {r["tm"] for r in con.execute(
            "SELECT DISTINCT tm FROM obs_hourly WHERE tm BETWEEN ? AND ?", (lo, hi))}
    return {
        "labels": labels, "hours": hours, "src": "kma",
        "src_label": "기상청 AWS", "count": len(out),
        "base_hour": slots[-1][11:16],
        "minute_tm": minute_tm[11:16] if partial else None,
        "missing": sum(1 for s in slots if s not in have),
        "rows": out,
    }


def _rain_bangjae(hours: int, now: datetime | None = None) -> dict:
    """스방 265개소로 같은 모양을 만든다.

    ⚠️ **한 칸 밀어 끼운다.** 스방의 'H시'는 H:00~H:59, 기상청의 'H시'는
       (H-1):00~H:00 이다. 그래서 기상청 H시 칸에는 스방 (H-1)시를 넣는다.
       (진행 중인 마지막 칸은 밀지 않는다 — 같은 구간이라서)
    """
    now = now or datetime.now()
    slots = _slots(hours, now)                       # 기상청 표기 칸
    back = {s: (datetime.strptime(s, "%Y-%m-%d %H:00")
                - timedelta(hours=1)).strftime("%Y-%m-%d %H:00") for s in slots}
    기준, _ = bj_as_of(now)
    진행 = now.strftime("%Y-%m-%d %H:00")            # 스방의 '지금 시각' 칸
    필요 = list(back.values()) + [진행]

    rows: dict[str, dict] = {}
    with db.tx() as con:
        q = ",".join("?" * len(필요))
        for r in con.execute(
            f"SELECT tm, stn, name, sigun, mm FROM bangjae_hourly WHERE tm IN ({q})", 필요
        ):
            st = rows.setdefault(r["stn"], {"name": r["name"], "sigun": r["sigun"], "v": {}})
            st["v"][r["tm"]] = r["mm"]
            st["name"], st["sigun"] = r["name"], r["sigun"]

    # 진행 중인 칸은 값이 있을 때만 붙인다(00분 직후에는 아직 비어 있다)
    partial = any(st["v"].get(진행) is not None for st in rows.values())
    labels = [s[11:13] for s in slots] + ([기준.strftime("%H:%M")] if partial else [])

    out = []
    for stn, st in rows.items():
        vals = [st["v"].get(back[s]) for s in slots]
        if partial:
            vals.append(st["v"].get(진행))
        ok = [v for v in vals if v is not None]
        out.append({
            "stn": stn, "name": st["name"], "sigun": st["sigun"],
            "rep": REP_STN.get(st["sigun"]) == stn,
            "d": vals, "m60": None,
            "sum": round(sum(ok), 1),
            "bad": len(vals) - len(ok),
        })
    out.sort(key=lambda r: (ORDER.index(r["sigun"]) if r["sigun"] in ORDER else 99, r["name"]))

    with db.tx() as con:
        have = {r["tm"] for r in con.execute(
            "SELECT DISTINCT tm FROM bangjae_hourly WHERE tm IN (%s)" % ",".join("?" * len(필요)),
            필요)}
    return {
        "labels": labels, "hours": hours, "src": "bangjae",
        "src_label": f"스방 {len(out)}개소", "count": len(out),
        "base_hour": slots[-1][11:16],
        "minute_tm": 기준.strftime("%H:%M") if partial else None,
        "missing": sum(1 for s in slots if back[s] not in have),
        "rows": out,
    }


def minute_top(n: int = 8) -> dict:
    """지금 **가장 세게 오고 있는 곳** — 15분·60분 강수량 상위 지점.

    ⚠️ 기상청 매분자료(`nph-aws2_min`)만 쓴다. 스방에는 분 단위가 없다.
    15분치를 앞에 두는 까닭은 그게 제일 빠르기 때문이다 — 60분치는 이미 지나간
    한 시간을 담고 있어서, 막 쏟아지기 시작한 곳을 한 박자 늦게 알린다.
    """
    n = max(1, min(20, int(n)))

    def top(con, key):
        """그 값이 **실제로 든** 가장 최근 시각을 골라 상위 n곳.

        ⚠️ 두 값의 시각을 하나로 묶으면 안 된다. 낡은 수집기가 15분치를 안 넣고
           덮어쓰면 그 시각에는 15분 칸이 통째로 비는데, 그때 화면을 비워 버리면
           멀쩡한 직전 자료까지 사라진다. 값마다 제 시각을 따로 찾는다.
        """
        r = con.execute(
            f"SELECT MAX(tm) AS tm FROM obs_minute WHERE {key} IS NOT NULL AND quality='ok'"
        ).fetchone()
        tm = r["tm"] if r and r["tm"] else None
        if not tm:
            return None, []
        out = [{"stn": x["stn"], "name": STN_NAME.get(x["stn"], x["stn"]),
                "sigun": STN_SIGUN.get(x["stn"], ""), "mm": x[key]}
               for x in con.execute(
                   f"SELECT stn, {key} FROM obs_minute WHERE tm=? AND quality='ok'", (tm,))
               if x[key] is not None]
        out.sort(key=lambda x: -x["mm"])
        return tm, out[:n]

    with db.tx() as con:
        tm15, r15 = top(con, "rn_15m")
        tm60, r60 = top(con, "rn_60m")

    tm = max(t for t in (tm15, tm60) if t) if (tm15 or tm60) else None
    return {"tm": tm[11:16] if tm else None, "n": n, "src": "기상청 매분자료",
            "tm15": tm15[11:16] if tm15 else None, "tm60": tm60[11:16] if tm60 else None,
            "r15": r15, "r60": r60}


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


def bangjae_rain() -> dict:
    """스방 시군별 평균 강수량(가장 최근 수집분).

    ⚠️ 기상청 값과 **뜻이 다르다**(시군 평균 vs 대표지점). 화면에서 출처를 밝힌다.
    """
    with db.tx() as con:
        row = con.execute("SELECT MAX(tm) AS t FROM bangjae_rain").fetchone()
        tm = row["t"] if row else None
        if not tm:
            return {"tm": None, "period": None, "source": "스방", "rows": []}
        rows = list(con.execute(
            """SELECT sigun, mm, daw_name, daw_mm, fr, to_date, hour, fetched_at
               FROM bangjae_rain WHERE tm=? ORDER BY mm DESC, sigun""", (tm,)))
    first = rows[0] if rows else None
    return {
        "tm": tm,
        "fetched_at": first["fetched_at"] if first else None,
        "period": ({"fr": first["fr"], "to": first["to_date"], "hour": first["hour"]}
                   if first else None),
        "source": "스방(경남 스마트 통합 방재시스템) 시군 평균",
        # daw = 그 시군 다우지점. 비가 안 오면 이름이 비어 온다 → None.
        "rows": [{"sigun": r["sigun"], "mm": r["mm"],
                  "daw": ({"name": r["daw_name"], "mm": r["daw_mm"]}
                          if r["daw_name"] else None)} for r in rows],
    }

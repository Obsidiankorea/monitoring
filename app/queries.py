"""DB 읽기. 화면은 이 함수들만 부른다 — 기상청을 직접 부르지 않는다.

⚠️ 결측을 0으로 더하지 않는다. 뺀 시간 수를 함께 돌려줘 화면이 "N시간 결측"을
   붙일 수 있게 한다. 조용히 0으로 더하면 과소평가가 사실처럼 읽힌다.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from . import clock, db, sites
from .bangjae import as_of as bj_as_of
from .domain.regions import ORDER, REP_STN, ZONES, by_sigun, grids, stations

STN_NAME = {s["stn"]: s["name"] for s in stations()}
STN_SIGUN = {s["stn"]: s["sigun"] for s in stations()}


def _slots(hours: int, now: datetime) -> list[str]:
    top = now.replace(minute=0, second=0, microsecond=0)
    return [(top - timedelta(hours=i)).strftime("%Y-%m-%d %H:00") for i in range(hours - 1, -1, -1)]


def minute_tail(after: str, at: str | None = None) -> tuple[str | None, dict, dict]:
    """정시 after('YYYY-MM-DD HH:00') 뒤 ~ 가장 최근 매분자료까지 지점마다 온 비 — RN_DAY 증분.
    → (매분 시각 'YYYY-MM-DD HH:MM', {stn: 증분|None}, {stn: RN-60m|None}). 매분이 after 보다 늦지 않으면 (None, {}, {}).
    at 을 주면 가장 최근 대신 그 매분 시각까지.

    종합 화면 강수량 판의 마지막 칸('정시부터 지금까지', 21:36 이면 21:00~21:36)과 지도 AWS 누적의 '지금' 칸이 같이 쓴다.
    ⚠️ RN-60m(직전 60분)을 쓰면 안 된다. 앞 정시 칸과 겹쳐 누적이 부풀고,
       칸이 가리키는 구간과 값이 담고 있는 구간이 어긋난다. RN-60m 은 참고값(툴팁 · 지도 AWS 1시간 '지금')이다.
    ⚠️ 정시자료(awsh)는 정시 뒤 몇 분~몇십 분 늦게 온다 — 그동안은 그 정시의 매분자료(1분 수집기가 받아 둔 HH:00)
       RN_DAY 를 기준으로 쓴다. 둘 다 없으면 그 지점은 None(결측 — 0 으로 치지 않는다)."""
    with db.tx() as con:
        if at:                                     # 그 매분 시각으로(지도 — 고른 '지금' 칸)
            minute_tm = at
        else:
            m = con.execute("SELECT MAX(tm) AS tm FROM obs_minute").fetchone()
            minute_tm = m["tm"] if m and m["tm"] else None
        if not minute_tm or minute_tm <= after:
            return None, {}, {}
        base_day = {r["stn"]: r["rn_day"] for r in con.execute(
            "SELECT stn, rn_day FROM obs_hourly WHERE tm=? AND quality='ok'", (after,)) if r["rn_day"] is not None}
        for r in con.execute("SELECT stn, rn_day FROM obs_minute WHERE tm=? AND quality='ok'", (after[:14] + "00",)):
            if r["rn_day"] is not None:
                base_day.setdefault(r["stn"], r["rn_day"])
        tail: dict[str, float | None] = {}
        m60: dict[str, float | None] = {}
        for r in con.execute("SELECT stn, rn_day, rn_60m, quality FROM obs_minute WHERE tm=?", (minute_tm,)):
            b, cur = base_day.get(r["stn"]), r["rn_day"]
            # RN_DAY는 01시에 0으로 리셋된다 — 증분이 음수면 자정을 넘은 것이므로 버린다
            tail[r["stn"]] = (round(cur - b, 1) if r["quality"] == "ok"
                              and b is not None and cur is not None and cur >= b else None)
            m60[r["stn"]] = r["rn_60m"] if r["quality"] == "ok" else None
    return minute_tm, tail, m60


def rain(hours: int = 12, now: datetime | None = None, src: str = "kma", tail: bool = True) -> dict:
    """지점별 시간대별 강수량 + 기간 누적.

    `src`
      kma      기상청 AWS 56개소. 마지막 칸은 매분자료로 보강한다.
      bangjae  스방 265개소. 후보가 다섯 배라 **다우지점이 훨씬 촘촘하다**
               (고성 학림 500.5mm를 기상청 AWS는 아예 못 본다).
    `tail`
      False 면 정시까지만 — 마지막 '정시 뒤 지금까지' 칸을 붙이지 않는다(지도 판 AWS 실시간 감시를 끈 동안).
    """
    if src == "bangjae":
        return _rain_bangjae(hours, now, tail)
    now = now or clock.now()
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

    # 정시 이후 구간 — 실제 최신 시각을 화면에 그대로 쓴다(지도 AWS 누적 '지금' 칸과 같은 셈, minute_tail).
    minute_tm, minute, m60 = minute_tail(slots[-1]) if tail else (None, {}, {})

    # ⚠️ 매분 보강값으로 마지막 정시 칸을 덮으면 그 한 시간이 통째로 사라진다.
    #    칸을 하나 더 붙여야 '정시까지'와 '정시 이후 지금까지'가 둘 다 남는다.
    labels = [s[11:13] for s in slots]
    partial = minute_tm is not None
    if partial:
        labels.append(minute_tm[11:16])

    off = sites.off_keys()                     # 지도 판에서 비활성화한 AWS — 카드 · 표에서 뺀다
    out = []
    for stn, name in STN_NAME.items():
        if stn in off:
            continue
        vals = [series.get(stn, {}).get(s) for s in slots]
        if partial:
            vals.append(minute.get(stn))
        ok = [v for v in vals if v is not None]
        out.append({
            "stn": stn, "name": name, "sigun": STN_SIGUN[stn], "org": "kma",
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


def aws_match() -> dict:
    """경남 AWS(스방) 지점이 경남 AWS 목록(aws_sites.json)과 짝지어졌나 — 내부망에서 한눈에 보려고.
    가장 최근 날 bangjae_hourly 의 지점마다 관리기관 · 위치 출처(kma 기상청 목록 | aws 목록 | emd 읍면동 가운데 | none)."""
    with db.tx() as con:
        last = con.execute("SELECT MAX(tm) t FROM bangjae_hourly").fetchone()["t"]
        got = [dict(r) for r in con.execute(
            "SELECT stn, name, sigun FROM bangjae_hourly WHERE tm >= ? GROUP BY stn",
            ((last or "")[:10] + " 00:00",))] if last else []
    rows = []
    for r in got:
        sg = sites.sigun_of(r["stn"], r["sigun"])
        if sg != r["sigun"]:
            r["sigun_bj"], r["sigun"] = r["sigun"], sg               # 스방이 준 시군은 남겨 둔다
        kma = r["stn"] in STN_NAME
        a = sites.aws_site(r["name"], r["sigun"], kma)
        pos = None if kma else sites.position(r["stn"], r["name"], r["sigun"])
        rows.append({**r, "org": sites.org_of(r["stn"], r["name"], r["sigun"], kma),
                     "src": "kma" if kma else (pos or {}).get("src", "none"),
                     "list_name": a["name"] if a else None, "emd": (pos or {}).get("emd")})
    order = {"none": 0, "emd": 1, "fix": 2, "aws": 3, "kma": 4}
    rows.sort(key=lambda x: (order.get(x["src"], 9), x["sigun"], x["name"]))
    n = {k: sum(x["src"] == k for x in rows) for k in order}
    # 목록(엑셀)에는 있는데 그날 스방에서 값이 한 번도 안 온 지점 — 수집기는 값이 있는 시각만 쌓는다
    # (고장 · 점검 · 강우계 없음이면 줄 자체가 없다). 이름이 달라 못 짝지은 것도 여기 든다(위 rows 의 none · emd 와 견줘 본다)
    seen = set()
    for r in rows:
        a = sites.aws_site(r["name"], r["sigun"], r["src"] == "kma")
        if a:
            seen.add((a["sigun"], a["name"], a["org"]))
    try:
        listed = json.loads(sites.AWS.read_text("utf-8"))["sites"]
    except (OSError, ValueError, KeyError):
        listed = []
    unseen = [{"sigun": x["sigun"], "name": x["name"], "org": x["org"], "addr": x.get("addr", "")}
              for x in listed if (x["sigun"], x["name"], x["org"]) not in seen]
    unseen.sort(key=lambda x: (x["org"], ORDER.index(x["sigun"]) if x["sigun"] in ORDER else 99, x["name"]))
    return {"day": (last or "")[:10] or None, "count": len(rows), "by_src": n,
            "list": {"total": len(listed), "seen": len(seen), "unseen": len(unseen),
                     "unseen_gn": sum(x["org"] == "gn" for x in unseen), "unseen_kma": sum(x["org"] == "kma" for x in unseen)},
            "note": "src: kma 기상청 지점번호(기상청 목록 위치) · aws 경남 AWS 목록(엑셀) · fix bangjae_sites.json · "
                    "emd 목록에 없어 읍면동 가운데(임시) · none 위치 없음. "
                    "unseen = 목록에는 있는데 그날 스방에서 값이 한 번도 안 온 지점(고장 · 점검 · 이름이 달라 못 짝지음)",
            "rows": rows, "unseen": unseen}


def _rain_bangjae(hours: int, now: datetime | None = None, tail: bool = True) -> dict:
    """스방 265개소로 같은 모양을 만든다.

    ⚠️ **한 칸 밀어 끼운다.** 스방의 'H시'는 H:00~H:59, 기상청의 'H시'는
       (H-1):00~H:00 이다. 그래서 기상청 H시 칸에는 스방 (H-1)시를 넣는다.
       (진행 중인 마지막 칸은 밀지 않는다 — 같은 구간이라서)
    """
    now = now or clock.now()
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
            st["name"], st["sigun"] = r["name"], sites.sigun_of(r["stn"], r["sigun"])

    # 진행 중인 칸은 값이 있을 때만 붙인다(00분 직후에는 아직 비어 있다)
    partial = tail and any(st["v"].get(진행) is not None for st in rows.values())
    labels = [s[11:13] for s in slots] + ([기준.strftime("%H:%M")] if partial else [])

    out = []
    off = sites.off_keys()
    for stn, st in rows.items():
        org = sites.org_of(stn, st["name"], st["sigun"], stn in STN_NAME)
        if sites.off_key(stn, st["name"], st["sigun"], org) in off:
            continue                                  # 지도 판에서 비활성화한 지점
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
            # 관리기관 — kma(기상청 AWS) | gn(경남 AWS). 화면이 막대 색을 가른다
            "org": org,
            # 위치 — 경남 AWS 목록(시군 + 장치명), 없으면 이름이 가리키는 읍면동 가운데(임시, est). 기상청 번호면 화면이 안다
            "pos": None if stn in STN_NAME else sites.position(stn, st["name"], st["sigun"]),
        })
    # 스방 지점이 하나도 없으면(내부망 밖 — 서버 · 집) 빈 줄로 돌려준다. 화면이 '경남 AWS 안 됨→기상청'으로 물러서
    # 기상청 자료(매분 보강 마지막 칸 포함)를 따로 받는다.
    # ⚠️ 아래에서 기상청 줄을 덧붙이자 줄이 늘 차서 화면이 물러서지 않았다 — 서버 화면에서 매분 칸이 사라졌다(10-23)
    if not rows:
        return {"labels": labels, "hours": hours, "src": "bangjae", "src_label": "경남+기상청 AWS 0개소",
                "count": 0, "base_hour": slots[-1][11:16], "minute_tm": None, "missing": len(slots), "rows": []}
    # 기상청 지점은 스방이 아니라 **기상청 API 값**(obs_hourly · 매분 보강)으로 — 스방이 기상청 몫을 떨군 적이 있고
    # (10.18. 11시~10.19., 54곳 다), 외부망 화면(기상청 직접)과 같은 지점이 다른 값이면 헷갈린다. 경남 AWS 만 스방에서.
    k = rain(hours, now, src="kma", tail=tail)
    kp = bool(k["minute_tm"])
    for r in k["rows"]:
        d = r["d"][:len(slots)] + ([r["d"][-1] if kp else None] if partial else [])
        ok = [v for v in d if v is not None]
        r.update(d=d, sum=round(sum(ok), 1), bad=len(d) - len(ok), m60=r["m60"] if partial and kp else None, pos=None)
    out = [r for r in out if r["stn"] not in STN_NAME] + k["rows"]
    out.sort(key=lambda r: (ORDER.index(r["sigun"]) if r["sigun"] in ORDER else 99, r["name"]))

    with db.tx() as con:
        have = {r["tm"] for r in con.execute(
            "SELECT DISTINCT tm FROM bangjae_hourly WHERE tm IN (%s)" % ",".join("?" * len(필요)),
            필요)}
    return {
        "labels": labels, "hours": hours, "src": "bangjae",
        "src_label": f"경남+기상청 AWS {len(out)}개소", "count": len(out),
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
    off = sites.off_keys()                     # 지도 판에서 비활성화한 AWS 는 빼고

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
               if x[key] is not None and x["stn"] not in off]
        out.sort(key=lambda x: -x["mm"])
        return tm, out[:n]

    with db.tx() as con:
        tm15, r15 = top(con, "rn_15m")
        tm60, r60 = top(con, "rn_60m")

    tm = max(t for t in (tm15, tm60) if t) if (tm15 or tm60) else None
    return {"tm": tm[11:16] if tm else None, "n": n, "src": "기상청 매분자료",
            "tm15": tm15[11:16] if tm15 else None, "tm60": tm60[11:16] if tm60 else None,
            "r15": r15, "r60": r60}


def forecast(hours: int = 6, now: datetime | None = None, sigun: str | None = None) -> dict:
    """최신 발표분의 읍면동 예측. 시군 대표값은 그 시군 읍면동 최대값이다.

    `sigun` 을 주면 그 시군 읍면동을 **전부** `emd_sigun` 에 더 준다(지도 판에서 시군을 골랐을 때).
    """
    with db.tx() as con:
        row = con.execute("SELECT MAX(tmfc) AS t FROM fcst_rn1").fetchone()
        tmfc = row["t"] if row else None
        if not tmfc:
            return {"tmfc": None, "labels": [], "emd": [], "sigun": []}

        # ⚠️ 발표가 한 박자 늦으면 첫 예측 시각이 이미 지나간 시각이다.
        #    그대로 그리면 예측이 현재보다 뒤에 놓여 한 시간씩 밀린다. 지난 것은 버린다.
        now_h = (now or clock.now()).strftime("%Y%m%d%H")
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

    out = {"tmfc": tmfc, "labels": [t[8:10] for t in tmefs],
           "emd": emd_list[:24], "sigun": sig}
    if sigun == "all":                         # 경남 읍면동 전부 — 지도 판 위 카드 줄 세우기(시군당 2·3곳 · 시군 무관)
        out["emd_sigun"] = emd_list
    elif sigun:                                # '함양,거창' — 여러 시군 읍면동(지도 판 비교)
        want = {x.strip() for x in sigun.split(",") if x.strip()}
        out["emd_sigun"] = [e for e in emd_list if e["sigun"] in want]
    return out


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
            return {"tm": None, "period": None, "source": "경남 AWS", "rows": []}
        rows = list(con.execute(
            """SELECT sigun, mm, daw_name, daw_mm, fr, to_date, hour, fetched_at
               FROM bangjae_rain WHERE tm=? ORDER BY mm DESC, sigun""", (tm,)))
    first = rows[0] if rows else None
    return {
        "tm": tm,
        "fetched_at": first["fetched_at"] if first else None,
        "period": ({"fr": first["fr"], "to": first["to_date"], "hour": first["hour"]}
                   if first else None),
        "source": "경남 AWS(경남 스마트 통합 방재시스템) 시군 평균",
        # daw = 그 시군 다우지점. 비가 안 오면 이름이 비어 온다 → None.
        "rows": [{"sigun": r["sigun"], "mm": r["mm"],
                  "daw": ({"name": r["daw_name"], "mm": r["daw_mm"]}
                          if r["daw_name"] else None)} for r in rows],
    }


# ── 단기예보 — 권역·시군 예보 판 ────────────────────────────────────────
# 기상청 예상강수량 문구의 범위들. 격자 분포의 가운데(20~80백분위)를 담는
# 가장 좁은 범위를 고른다 — 사람이 통보문에서 읽는 그 말로 옮기는 것이다.
RAIN_BINS = [(5, 10), (5, 20), (10, 40), (20, 60), (30, 80), (50, 100),
             (80, 150), (100, 200), (150, 300), (200, 400), (300, 500)]
_DAYNAME = ("오늘", "내일", "모레")


def _pct(vals: list[float], p: float) -> float:
    """선형 보간 백분위. vals 는 정렬돼 있어야 한다."""
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(vals) - 1)
    return vals[lo] + (vals[hi] - vals[lo]) * (k - lo)


def rain_phrase(lo: float, hi: float) -> str:
    if hi < 0.5:
        return "없음"
    if hi < 1:
        return "1 미만"
    if hi < 5:
        return "5 미만"
    lo = max(lo, 5)
    if hi > RAIN_BINS[-1][1]:
        return f"{RAIN_BINS[-1][1]} 이상"
    # 다 담는 범위 가운데 가장 좁은 것. 다 담는 것이 없으면(74~104 같은 경우)
    # 덜 담기는 양이 가장 작은 범위 — 문구는 늘 기상청이 쓰는 범위 중 하나로 낸다.
    a, b = min(RAIN_BINS, key=lambda x: (max(0, x[0] - lo) + max(0, hi - x[1]),
                                          x[1] - x[0], -x[0]))
    return f"{a}~{b}"


def _dist(vals: list[float]) -> dict | None:
    v = sorted(x for x in vals if x is not None)
    if not v:
        return None
    r = lambda x: round(x, 1)
    return {"n": len(v), "min": r(v[0]), "p10": r(_pct(v, .1)), "p20": r(_pct(v, .2)),
            "p50": r(_pct(v, .5)), "p80": r(_pct(v, .8)), "p90": r(_pct(v, .9)),
            "p95": r(_pct(v, .95)), "max": r(v[-1])}


def _day_of(tmef: str) -> str:
    """PCP 대상시각 H 는 (H-1)~H 시의 양이다. 00시 값은 전날 몫이다."""
    t = datetime.strptime(tmef, "%Y%m%d%H") - timedelta(hours=1)
    return t.strftime("%Y%m%d")


def _short_cells(con, tmfc: str, hours: set[str] | None = None) -> dict:
    """{날짜: {'pcp': {xy: 합계}, 'hours': set}}"""
    out: dict[str, dict] = {}
    for r in con.execute(
            "SELECT tmef, x, y, val FROM fcst_short WHERE tmfc=? AND var='PCP'", (tmfc,)):
        if hours is not None and r["tmef"] not in hours:
            continue
        d = out.setdefault(_day_of(r["tmef"]), {})
        d.setdefault("hours", set()).add(r["tmef"])
        if r["val"] is not None:
            p = d.setdefault("pcp", {})
            xy = (r["x"], r["y"])
            p[xy] = p.get(xy, 0.0) + r["val"]
    return out


def _short_groups() -> dict[str, list[dict]]:
    by_sig = {s: list(dict.fromkeys(tuple(it["xy"]) for it in items))
              for s, items in grids()["sigun_grids"].items()}
    zone = []
    for name, sigs, band, parent in ZONES:
        xy = list(dict.fromkeys(c for s in sigs for c in by_sig.get(s, [])))
        zone.append({"name": name, "members": sigs, "band": band, "parent": parent, "xy": xy})
    sigun = [{"name": s, "members": [s], "band": "", "parent": None, "xy": by_sig.get(s, [])}
             for s in ORDER if s in by_sig]
    return {"zone": zone, "sigun": sigun}


def _short_stats(cells: dict, groups: dict, days: list[str]) -> dict:
    out: dict[str, list[dict]] = {}
    for by, gs in groups.items():
        rows = []
        for g in gs:
            per = {}
            for d in days:
                c = cells.get(d, {})
                pcp = _dist([c.get("pcp", {}).get(xy) for xy in g["xy"]]) if c.get("hours") else None
                if pcp:
                    pcp["text"] = rain_phrase(pcp["p20"], pcp["p80"])
                per[d] = {"pcp": pcp}
            rows.append({"name": g["name"], "members": g["members"], "band": g["band"],
                         "parent": g["parent"],
                         "cells": len(g["xy"]), "days": per})
        out[by] = rows
    return out


def short(now: datetime | None = None) -> dict:
    """권역·시군별 단기예보 강수량 분포.

    강수량은 격자 칸마다 그날 PCP 를 더한 뒤 권역 안에서 분포를 낸다.
    ⚠️ '오늘'은 발표 뒤의 남은 시간만 담는다(14시 발표면 14~24시). 화면이 그 구간을 적는다.
    ⚠️ 직전 발표 대비(▲▼)는 **같은 시간대끼리** 견준다. 직전 발표는 오늘의 더 이른
       시간을 담고 있어 그냥 견주면 늘 줄어든 것처럼 보인다.
    """
    now = now or clock.now()
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    days = [(today + timedelta(days=i)).strftime("%Y%m%d") for i in range(3)]
    groups = _short_groups()
    with db.tx() as con:
        runs = [dict(r) for r in con.execute(
            "SELECT tmfc, complete, fetched_at FROM fcst_short_run ORDER BY tmfc DESC LIMIT 3")]
        # 다 받은 가장 최근 발표분. 없으면 받는 중인 것이라도 쓴다.
        done = [r for r in runs if r["complete"]]
        cur = done[0] if done else (runs[0] if runs else None)
        if not cur:
            return {"tmfc": None, "prev_tmfc": None, "days": [], "zone": [], "sigun": []}
        prev = next((r for r in done if r["tmfc"] < cur["tmfc"]), None)
        cells = _short_cells(con, cur["tmfc"])
        hours = set().union(*(c.get("hours", set()) for c in cells.values()))
        pcells = _short_cells(con, prev["tmfc"], hours) if prev else {}

    stats = _short_stats(cells, groups, days)
    pstats = _short_stats(pcells, groups, days) if prev else None

    # 직전 발표 대비 — 중앙값의 차
    if pstats:
        for by, rows in stats.items():
            for row, prow in zip(rows, pstats[by]):
                for d in days:
                    a, b = row["days"][d]["pcp"], prow["days"][d]["pcp"]
                    if a and b:
                        a["d"] = round(a["p50"] - b["p50"], 1)
                        a["d95"] = round(a["p95"] - b["p95"], 1)

    dinfo = []
    for i, d in enumerate(days):
        hs = sorted(cells.get(d, {}).get("hours", set()))
        dinfo.append({"day": d, "label": _DAYNAME[i],
                      "from": f"{int(hs[0][8:10]) - 1:02d}" if hs else None,
                      "to": f"{int(hs[-1][8:10]) or 24:02d}" if hs else None,
                      "hours": len(hs)})
    return {"tmfc": cur["tmfc"], "complete": bool(cur["complete"]),
            "fetched_at": cur["fetched_at"], "prev_tmfc": prev["tmfc"] if prev else None,
            "days": dinfo, **stats}

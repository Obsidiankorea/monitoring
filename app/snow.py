"""적설 — 기상청 적설관측(경남 55곳 남짓, 레이저 적설계 · 목측). 10분마다.

  · 늘: kma_snow1.php sd=tot (지금 쌓인 눈, cm) — 눈이 없는 날도 한 번(수집 지연 경고가 헛돌지 않게)
  · 눈이 있거나(어느 지점이든 > 0) 대설 특보 · 예비특보가 있을 때만: 3시간 · 24시간 · 일 신적설을 더 부른다
  · 지점 목록(stn_snow.php)은 하루 한 번 — 법정동코드(LAW_ID) 앞 5자리로 시군, 해발(HT)로 산지
화면(/api/snow): 지점 · 시군 대표(산지 뺀 최대) · 대설 특보 시군. 특보 기준 대조는 24시간 신적설(쌓인 눈이 아니다).
"""
from __future__ import annotations

import logging
from datetime import datetime

from . import db
from .kma import KmaError, fetch_text

log = logging.getLogger("collect.snow")
P_STN, P_SD = "/api/typ01/url/stn_snow.php", "/api/typ01/url/kma_snow1.php"
# 법정동코드 앞 5자리 → 시군(창원은 구마다 코드가 따로)
LAW_SIGUN = {"48121": "창원", "48123": "창원", "48125": "창원", "48127": "창원", "48129": "창원", "48170": "진주", "48220": "통영",
             "48240": "사천", "48250": "김해", "48270": "밀양", "48310": "거제", "48330": "양산", "48720": "의령", "48730": "함안",
             "48740": "창녕", "48820": "고성", "48840": "남해", "48850": "하동", "48860": "산청", "48870": "함양", "48880": "거창",
             "48890": "합천"}
MT_HT = 500     # shortcut: 해발 500m 이상을 산지로(지리산 · 가야산) — 기상청 '산지' 정의를 확인하면 바꾼다
NOISE = 0.5     # 레이저 적설계 잡음 — 이보다 적은 신적설 · 증가는 0 으로


def parse_stations(text: str) -> dict[str, dict]:
    """stn_snow 고정폭 — STN LON LAT SP HT AD 이름 FCT LAW. 경남(LAW 48…)만."""
    out = {}
    for line in text.splitlines():
        f = line.split()
        if not f or line.startswith("#") or not f[0].isdigit() or len(f) < 9:
            continue
        law = f[-1]
        sg = LAW_SIGUN.get(law[:5])
        if not sg:
            continue
        try:
            ht = float(f[4])
            out[f[0]] = {"stn": f[0], "name": " ".join(f[6:-2]), "sigun": sg, "lon": float(f[1]), "lat": float(f[2]),
                         "ht": ht, "mt": ht >= MT_HT, "sp": f[3]}
        except ValueError:
            continue
    return out


def parse_values(text: str) -> tuple[str | None, dict[str, float | None]]:
    """kma_snow1 CSV — TM, STN, 이름, LON, LAT, SP, SD. 음수 · 빈 칸은 결측(None), 0.0 만 0."""
    tm, out = None, {}
    for line in text.splitlines():
        if line.startswith("#") or "," not in line:
            continue
        f = [x.strip() for x in line.split(",")]
        if len(f) < 7 or not f[1].isdigit():
            continue
        tm = tm or f[0]
        try:
            v = float(f[6])
        except ValueError:
            v = None
        out[f[1]] = v if v is not None and v >= 0 else None
    return tm, out


def _alert_snow() -> list[str]:
    """대설 특보 · 예비특보가 걸린 시군(최신 특보 스냅숏)."""
    al = (db.latest_snapshot("alerts") or {}).get("data") or {}
    sg = {s for g in al.get("groups", []) if "대설" in g.get("name", "") and not g.get("sea") for s in g.get("siguns", [])}
    sg |= {p.get("sigun") for p in al.get("pending", []) if "대설" in p.get("name", "") and p.get("sigun")}
    return sorted(sg)


async def _stations(now: datetime) -> dict[str, dict]:
    got = db.get_setting("snow_stn", None) or {}
    if got.get("day") == now.strftime("%Y-%m-%d") and got.get("rows"):
        return got["rows"]
    try:
        rows = parse_stations(await fetch_text(P_STN, {"mode": "0", "tm": now.strftime("%Y%m%d%H%M")}))
        if rows:
            db.put_setting("snow_stn", {"day": now.strftime("%Y-%m-%d"), "rows": rows})
            return rows
    except KmaError as e:
        log.warning("적설 지점 목록 실패 — 어제 것을 쓴다: %s", e)
    if got.get("rows"):
        return got["rows"]
    raise KmaError("적설 지점 목록을 못 받았다(아직 한 번도)")


def build(stns: dict, tot: dict, more: dict[str, dict], alert: list[str], tm: str | None) -> dict:
    """화면 · AI 가 읽는 모양 — stations(지점) · siguns(시군 대표: 산지 뺀 최대) · alert(대설 특보 시군)."""
    def cut(v):
        return None if v is None else (0.0 if v < NOISE else v)
    rows = []
    for k, s in stns.items():
        if k not in tot:
            continue
        rows.append({**s, "sd": tot[k], "d3": cut(more.get("d3", {}).get(k)), "d24": cut(more.get("d24", {}).get(k)),
                     "day": cut(more.get("day", {}).get(k))})
    rows.sort(key=lambda r: -(r["sd"] or 0))
    sig: dict[str, dict] = {}
    for r in rows:
        if r["mt"] or r["sd"] is None:
            continue
        b = sig.get(r["sigun"])
        if b is None or (r["sd"] or 0) > (b["sd"] or 0):
            sig[r["sigun"]] = {"sd": r["sd"], "d3": r["d3"], "d24": r["d24"], "stn": r["name"]}
    for r in rows:                                       # 24시간 신적설은 시군 안 최대(특보 대조) — 산지 빼고
        if not r["mt"] and r["d24"] and r["sigun"] in sig:
            sig[r["sigun"]]["d24"] = max(sig[r["sigun"]]["d24"] or 0, r["d24"])
    active = any((r["sd"] or 0) > 0 for r in rows) or bool(alert)
    return {"tm": tm, "active": active, "alert": alert, "stations": rows,
            "siguns": {k: v for k, v in sig.items() if (v["sd"] or 0) > 0 or (v["d24"] or 0) > 0}}


async def collect(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    at = now.strftime("%Y-%m-%d %H:%M")
    try:
        stns = await _stations(now)
        tm, tot = parse_values(await fetch_text(P_SD, {"sd": "tot", "snow": "2"}))
        if not any(k in tot for k in stns):
            raise KmaError("경남 적설 지점 값이 하나도 없다")
    except KmaError as e:
        db.log_collect("snow", False, at, str(e))
        raise
    alert, more, errs = _alert_snow(), {}, []
    if alert or any((tot.get(k) or 0) > 0 for k in stns):     # 눈이 있을 때만 신적설 셋 — 하나가 실패해도 나머지는 그대로
        for sd, key in (("3hr", "d3"), ("24h", "d24"), ("day", "day")):
            try:
                more[key] = parse_values(await fetch_text(P_SD, {"sd": sd, "snow": "2"}))[1]
            except KmaError as e:
                errs.append(f"{sd}: {str(e)[:60]}")
    data = build(stns, tot, more, alert, tm)
    db.put_snapshot("snow", tm or at, at, data)
    n = sum(1 for r in data["stations"] if (r["sd"] or 0) > 0)
    db.log_collect("snow", True, at, (f"눈 {n}곳" if n else "눈 없음") + f" · {len(data['stations'])}곳" + (f" · 일부 실패 {'; '.join(errs)}" if errs else ""))
    return {"stations": len(data["stations"]), "snow": n, "err": errs or None}


def latest() -> dict:
    s = db.latest_snapshot("snow")
    return {**(s["data"] if s else {"active": False, "stations": [], "siguns": {}, "alert": []}),
            "fetched_at": s and s["fetched_at"]}


def text(sigun: str | None = None) -> str | None:
    """AI 보고 한 줄 — '적설: 거창 4.2cm(24시간 +3.1) · 함양 2.5cm — 대설주의보 기준(24시간 5cm) 넘은 곳: 거창'. 눈이 없으면 None."""
    d = latest()
    if not d.get("active"):
        return None
    sg = {k: v for k, v in d["siguns"].items() if not sigun or k == sigun}
    parts = [f"{k} {v['sd']:g}cm" + (f"(24시간 +{v['d24']:g})" if v.get("d24") else "") for k, v in sorted(sg.items(), key=lambda x: -(x[1]["sd"] or 0))[:6]]
    mt = [r for r in d["stations"] if r["mt"] and (r["sd"] or 0) > 0 and (not sigun or r["sigun"] == sigun)]
    over = [k for k, v in sg.items() if (v.get("d24") or 0) >= 5]
    mts = " · ".join("%s %gcm" % (r["name"], r["sd"]) for r in mt[:2])
    out = "적설: " + (" · ".join(parts) or "평지 지점 적설 없음") + (f" · 산지 {mts}" if mt else "")
    if over:
        out += f" — 24시간 신적설 5cm 넘은 시군(대설주의보 기준): {', '.join(over)}"
    return out

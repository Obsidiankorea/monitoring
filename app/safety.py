"""재난안전데이터공유플랫폼(safetydata.go.kr) 4종 — 지도 레이어 셋: 산사태(J) · 위험저수지(K) · 침수흔적(N).

  산사태 예보(DSSP-IF-00734) — 시장 · 군수가 낸 산사태 주의보 · 경보 발령 · 해제 기록. 10분마다(1쪽).
  산사태 예측(DSSP-IF-00735) — 산림청 예측정보: 분석 시각 · 시군구 · 주의보/경보. 30분마다(전체 약 8쪽).
    ⤷ 산사태 둘은 경남에 호우 · 태풍 특보(주의보 이상)가 있을 때만, 또는 사람이 '늘 받기'로 켰을 때만 부른다(설정 sd_slide).
  위험저수지(DSSP-IF-20592) — 재해위험 저수지 계측기(수위계 · 경사계) 경보 발령 · 해제 기록. 30분마다(약 4쪽).
  침수흔적도(DSSP-IF-00117) — 과거 침수 구역 다각형(2002~). 7일마다 전체(약 39쪽)를 받아 경남만 파일로 둔다.

요청 변수가 쪽(pageNo · numOfRows)뿐이라 걸러 부를 수 없다 — 다 받아 경남만 남긴다. 키는 API 마다 따로(config/api_keys.txt),
하루 1000건 · 만료 2027-11-02(포털 '데이터 이용 내역'). 하루 950건에서 멈춘다.
⚠️ 코드 뜻은 포털 명세에 없어 응답을 보고 읽었다(2026-11-03): 저수지 WRN_CD 01 관심 · 02 주의 · 03 경계 · 04 심각 · 05 대피,
   APNT_SE 1 발령 · 2 해제. 해제를 받지 못한 채 남은 발령도 있다(경남 10월 '경계 발령' 그대로) — 시각을 같이 보인다.
"""
from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timedelta

import httpx

from . import config, db

log = logging.getLogger("safety")

BASE = "https://www.safetydata.go.kr/V2/api/"
STOP_AT = 950
FCST_KEEP_H = 72          # shortcut: 해제를 못 받은 산사태 예보 발령은 72시간 뒤 지운다, 실제 최장 발령 기간을 보면 고친다
PRED_KEEP_H = 24          # 예측정보는 분석 시각 뒤 하루만 '지금'으로 본다
FLOOD_FILE = config.STATE / "cache" / "safety_flood.json"
# (이름, API, 키, 몇 분마다)
SETS = {"fcst": ("DSSP-IF-00734", "SD_SLIDE_FCST_KEY", 10), "pred": ("DSSP-IF-00735", "SD_SLIDE_PRED_KEY", 30),
        "res": ("DSSP-IF-20592", "SD_RESERVOIR_KEY", 30), "flood": ("DSSP-IF-00117", "SD_FLOODMAP_KEY", 7 * 24 * 60)}
RES_LV = ["", "관심", "주의", "경계", "심각", "대피"]
SLIDE = ("fcst", "pred")
SGG = {"4812": "창원", "48170": "진주", "48220": "통영", "48240": "사천", "48250": "김해", "48270": "밀양", "48310": "거제",
       "48330": "양산", "48720": "의령", "48730": "함안", "48740": "창녕", "48820": "고성", "48840": "남해", "48850": "하동",
       "48860": "산청", "48870": "함양", "48880": "거창", "48890": "합천"}

_LIVE: dict = {"at": {}, "err": {}, "fcst": [], "pred": [], "res": []}


def _key(name: str) -> str:
    return config.KEYS.get(SETS[name][1], "")


def sigun_of(addr: str) -> str | None:
    """'경상남도 창원시 의창구' → '창원'. 경남이 아니면 None."""
    p = (addr or "").split()
    return p[1][:-1] if p[:1] == ["경상남도"] and len(p) > 1 and p[1][-1] in "시군" else None


def sigun_of_code(code) -> str | None:
    c = str(code or "")
    return SGG.get(c[:4]) or SGG.get(c[:5])


def _calls(name: str, now: datetime) -> int:
    d = db.get_setting(f"sd_calls_{name}", {}) or {}
    return d.get("n", 0) if d.get("ymd") == f"{now:%Y%m%d}" else 0


async def _pages(cli: httpx.AsyncClient, name: str, now: datetime) -> list[dict]:
    """전체 쪽을 받는다(1000행씩). 하루 한도에 닿으면 멈춘다."""
    api, _, _ = SETS[name]
    out, page, total = [], 1, None
    while total is None or (page - 1) * 1000 < total:
        n = _calls(name, now)
        if n >= STOP_AT:
            raise RuntimeError(f"오늘 {n}건 — 내일까지 멈춤")
        db.put_setting(f"sd_calls_{name}", {"ymd": f"{now:%Y%m%d}", "n": n + 1})
        r = await cli.get(BASE + api, params={"serviceKey": _key(name), "returnType": "json", "numOfRows": 1000, "pageNo": page})
        r.raise_for_status()
        j = r.json()
        h = j.get("header") or {}
        if h.get("resultCode") != "00":
            raise RuntimeError(f"{h.get('resultCode')} {h.get('errorMsg') or h.get('resultMsg')}")
        out += j.get("body") or []
        total = int(j.get("totalCount") or 0)
        page += 1
    return out


def parse_fcst(rows: list[dict], now: datetime) -> list[dict]:
    """경남 시군의 산사태 예보 — 시군 · 종류마다 마지막 기록. on = 발령 중(해제 없음, 72시간 안)."""
    last: dict = {}
    for x in rows:
        sg = sigun_of(x.get("OCRN_FRCST_APNT_INST_NM"))
        if not sg:
            continue
        k = (sg, x.get("FRCST_APNT_KND_CD_NM"))
        if k not in last or (x.get("FRCST_APNT_DT") or "") > (last[k].get("FRCST_APNT_DT") or ""):
            last[k] = x
    out = []
    for (sg, kind), x in last.items():
        at = x.get("FRCST_APNT_DT") or ""
        try:
            age = (now - datetime.strptime(at[:16], "%Y-%m-%d %H:%M")).total_seconds() / 3600
        except ValueError:
            continue
        out.append({"sigun": sg, "kind": kind, "lv": 2 if kind == "경보" else 1, "stts": x.get("FRCST_APNT_STTS"), "at": at[:16],
                    "on": x.get("FRCST_APNT_STTS") == "발령" and age <= FCST_KEEP_H})
    return sorted(out, key=lambda r: (not r["on"], -r["lv"], r["at"]), reverse=False)


def parse_pred(rows: list[dict], now: datetime) -> list[dict]:
    """경남 시군의 산사태 예측정보 — 시군마다 가장 새 분석. on = 분석 하루 안 · 주의보 이상."""
    last: dict = {}
    for x in rows:
        sg = sigun_of(x.get("SGG_NM"))
        if sg and (x.get("PREDC_ANLS_DT") or "") > (last.get(sg, {}).get("PREDC_ANLS_DT") or ""):
            last[sg] = x
    out = []
    for sg, x in last.items():
        at, nm = (x.get("PREDC_ANLS_DT") or "")[:16], x.get("LNLD_FRCST_NM")
        try:
            age = (now - datetime.strptime(at, "%Y-%m-%d %H:%M")).total_seconds() / 3600
        except ValueError:
            continue
        out.append({"sigun": sg, "kind": nm or "없음", "lv": {"주의보": 1, "경보": 2}.get(nm, 0), "at": at,
                    "on": bool(nm) and age <= PRED_KEEP_H})
    return sorted(out, key=lambda r: r["at"], reverse=True)


def parse_res(rows: list[dict]) -> list[dict]:
    """경남 위험저수지 계측기 — 계측기마다 마지막 경보 기록. on = 발령(해제 전)."""
    last: dict = {}
    for x in rows:
        if not sigun_of_code(x.get("MNG_INST_CD")):
            continue
        k = (x.get("DST_RSK_DSTRCT_FCLTY_CD"), x.get("MEMENT_SENU"))
        key = (x.get("WRN_APNT_DT") or "", x.get("MDFCN_DT") or "")
        if k not in last or key > last[k][0]:
            last[k] = (key, x)
    out = []
    for _, x in last.values():
        try:
            lon, lat, lv = float(x["LOT"]), float(x["LAT"]), int(x.get("WRN_CD") or 0)
        except (KeyError, TypeError, ValueError):
            continue
        t = x.get("WRN_APNT_DT") or ""
        out.append({"name": x.get("MEMENT_NM") or "", "sigun": sigun_of_code(x.get("MNG_INST_CD")), "lon": lon, "lat": lat,
                    "lv": lv, "lvn": RES_LV[lv] if 0 < lv < len(RES_LV) else str(lv), "on": str(x.get("APNT_SE")) == "1",
                    "at": f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]}" if len(t) >= 12 else t,
                    "cn": (x.get("WRN_APNT_CN") or "").replace("* 계측기 고장 등에 의한 오측이 발생할수도 있으니 참고하시기 바랍니다.", "").strip()[:200]})
    return sorted(out, key=lambda r: (r["on"], r["lv"], r["at"]), reverse=True)


def _ll(x: float, y: float) -> tuple[float, float]:
    """웹 메르카토르(EPSG:3857) → 경위도."""
    return round(x / 6378137 * 180 / math.pi, 5), round((2 * math.atan(math.exp(y / 6378137)) - math.pi / 2) * 180 / math.pi, 5)


def parse_flood(rows: list[dict]) -> list[dict]:
    """경남(시도 48) 침수흔적 — 다각형 고리들을 경위도로(구멍도 같은 path 의 고리로, 그릴 때 evenodd)."""
    out = []
    for x in rows:
        if str(x.get("STDG_CTPV_CD")) != "48":
            continue
        rings = []
        for ring in re.findall(r"\(([^()]+)\)", x.get("GEOM") or ""):
            pts = []
            for pair in ring.split(","):
                try:
                    a, b = (float(v) for v in pair.split())
                except ValueError:
                    continue
                p = _ll(a, b)
                if not pts or p != pts[-1]:
                    pts.append(p)
            if len(pts) >= 3:
                rings.append(pts)
        if rings:
            out.append({"r": rings, "yr": x.get("FLDN_YR"), "nm": x.get("FLDN_DST_NM"), "dep": x.get("FLDN_DOWA"),
                        "sigun": sigun_of_code(x.get("STDG_SGG_CD")), "cs": (x.get("FLDN_CS_DTL_NM") or "")[:80],
                        "d": f"{x.get('FLDN_BGNG_YMD') or ''}~{x.get('FLDN_END_YMD') or ''}"})
    return out


def slide_mode() -> str:
    """auto = 호우 · 태풍 특보 때만 · on = 늘 받기."""
    m = (db.get_setting("sd_slide", {}) or {}).get("mode")
    return m if m in ("auto", "on") else "auto"


def slide_why() -> str | None:
    """산사태를 지금 받는 까닭 — 받지 않으면 None."""
    if slide_mode() == "on":
        return "늘 받기(수동)"
    from . import queries
    hit = sorted({g["name"] for g in queries.alerts()["data"]["groups"]
                  if not g.get("sea") and g["name"].startswith(("호우", "태풍"))})
    return " · ".join(hit) + " 중" if hit else None


def _due(name: str, now: datetime) -> bool:
    at = _LIVE["at"].get(name)
    if name == "flood" and not at and FLOOD_FILE.exists():
        at = datetime.fromtimestamp(FLOOD_FILE.stat().st_mtime).isoformat()
        _LIVE["at"]["flood"] = at
    return not at or now - datetime.fromisoformat(at) >= timedelta(minutes=SETS[name][2] - 1)


async def run() -> None:
    """스케줄러가 10분마다 — 키가 있고 때가 된 것만 받는다."""
    now = datetime.now()
    if config.DEMO:
        return
    slide = slide_why()
    async with httpx.AsyncClient(timeout=60, verify=config.VERIFY_SSL) as cli:
        for name in SETS:
            if not _key(name) or (name in SLIDE and not slide) or not _due(name, now):
                continue
            try:
                rows = await _pages(cli, name, now)
                if name == "fcst":
                    _LIVE["fcst"] = parse_fcst(rows, now)
                elif name == "pred":
                    _LIVE["pred"] = parse_pred(rows, now)
                elif name == "res":
                    _LIVE["res"] = parse_res(rows)
                else:
                    FLOOD_FILE.parent.mkdir(parents=True, exist_ok=True)
                    FLOOD_FILE.write_text(json.dumps(parse_flood(rows), ensure_ascii=False, separators=(",", ":")), "utf-8")
                _LIVE["at"][name] = now.isoformat(timespec="seconds")
                _LIVE["err"].pop(name, None)
            except Exception as e:                                   # noqa: BLE001
                _LIVE["err"][name] = str(e)[:160].replace(_key(name), "***")
                log.warning("safetydata %s 실패: %s", name, _LIVE["err"][name])


def status() -> dict:
    keys = {n: bool(_key(n)) or (config.DEMO and bool(_LIVE["at"].get(n))) for n in SETS}   # 시연은 가상 장면이 넣은 것
    return {"on": any(keys.values()), "demo": config.DEMO, "keys": keys, "at": _LIVE["at"], "err": _LIVE["err"],
            "slide": {"mode": slide_mode(), "why": slide_why()},
            "fcst": _LIVE["fcst"], "pred": _LIVE["pred"], "res": _LIVE["res"],
            "calls": {n: _calls(n, datetime.now()) for n in SETS}, "flood": FLOOD_FILE.exists()}


def flood() -> str:
    """침수흔적 다각형(경남) — 파일 그대로. 없으면 빈 목록."""
    try:
        return FLOOD_FILE.read_text("utf-8")
    except OSError:
        return "[]"

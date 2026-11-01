"""조위 — 경남 해안 조위관측소의 실측 · 예측(국립해양조사원, 공공데이터포털 GetSurveyTideLevelApiService).

오늘 값(실측 + 예측)은 수집 주기마다(설정 › API 절약을 따른다), 앞날 예측은 하루 한 번 받는다 — 예측은 하루 안에 바뀌지 않는다.
  · 응답 시각은 모두 KST, 높이는 cm. 앞날은 예측(tdlvHgt)만 오고 실측(bscTdlvHgt)은 null 이다.
  · ⚠️ 활용가이드의 예시와 달리 응답은 {"response": …} 로 감싸지 않고 header · body 로 바로 온다(2026-11 실측).
  · 단계: 마산은 해양조사원 고조정보 4단계(2026년 8월 해안침수 주의정보 — 기본수준면 기준, 그달 '주의' 이상 예상지역만 실려 경남은 마산뿐).
    거제도 · 통영 · 여수는 그 값을 아직 못 구해 기상청 예보업무규정 폭풍해일 주의보 · 경보 값(위키 [[재난경보와 폭풍해일 기준]])을 참고로 쓴다 — 고조정보와 다른 체계이고 기준면도 미확인이라 특보 판정이 아니다(특보는 기상청 발표).
    삼천포는 위키 기준이 없어 값만.
  · 대조기는 API 가 주지 않는다 — 예측 일 최고 만조의 봉우리 앞뒤 이틀로 계산한다(spring). 공식 날짜와 다를 수 있다.
키는 config/api_keys.txt 의 DATA_GO_KR_KEY(산림청 산사태와 같은 키).
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

import httpx

from . import config
from .domain.gridproj import hr_xy

log = logging.getLogger("tide")

URL = "https://apis.data.go.kr/1192136/surveyTideLevel/GetSurveyTideLevelApiService"
HI = ["정상", "관심", "주의", "경계", "위험"]
SURGE = ["정상", "주의보", "경보"]
SPRING_REF = "DT_0014"                                     # 대조기는 통영 예측으로 센다(남해안 한 곳이면 된다)
STALE_MIN = 90
PLOT_BACK, PLOT_FWD = 6, 18                                # 팝업 물결 — 지금 앞뒤(시간)

STATIONS = [
    {"code": "DT_0062", "name": "마산", "lat": 35.1975, "lon": 128.57638, "sigun": ["창원"], "cuts": [162, 182, 228, 280], "names": HI, "col": [0, 1, 2, 3, 4],
     "scale": "고조정보", "surge": [240, 290],
     "facil": [{"name": "진해 용원 의창수협", "h": 182}, {"name": "진해 용원 안골부두", "h": 252}, {"name": "마산합포구 한진수산 부근", "h": 280},
               {"name": "진해 용원 남양포구", "h": 291}, {"name": "마산합포구 서항부두", "h": 304}]},
    {"code": "DT_0029", "name": "거제도", "lat": 34.80138, "lon": 128.69916, "sigun": ["거제"], "cuts": [249, 281], "names": SURGE, "col": [0, 2, 4], "scale": "폭풍해일 기준(참고)"},
    {"code": "DT_0014", "name": "통영", "lat": 34.82777, "lon": 128.43472, "sigun": ["통영", "고성", "사천"], "cuts": [322, 370], "names": SURGE, "col": [0, 2, 4], "scale": "폭풍해일 기준(참고)"},
    {"code": "DT_0016", "name": "여수", "lat": 34.74722, "lon": 127.76555, "sigun": ["하동", "남해"], "cuts": [420, 440], "names": SURGE, "col": [0, 2, 4], "scale": "폭풍해일 기준(참고)"},
    {"code": "DT_0061", "name": "삼천포", "lat": 34.92416, "lon": 128.06972, "sigun": [], "cuts": [], "names": [], "col": [], "scale": None},
]

_LIVE: dict = {"at": None, "err": None, "rows": [], "spring": None}
_PRED: dict = {"day": None, "pts": {}, "days": []}         # 하루 한 번 — pts: 코드 → [(ymdhm, 예측)], days: [(date, 일 최고)]


def _key() -> str:
    return config.KEYS.get("DATA_GO_KR_KEY", "")


def _mask(e: object) -> str:
    t = str(e)
    return t.replace(_key(), "***") if _key() else t


def stage(st: dict, v: float | None) -> int | None:
    """그 높이가 몇 번째 단계인가(0 = 정상). 기준이 없으면 None."""
    if v is None or not st["cuts"]:
        return None
    return sum(1 for c in st["cuts"] if v >= c)


def parse(j: dict) -> list[tuple[str, float | None, float | None]]:
    """응답 → [(ymdhm, 실측, 예측)]. 오류 코드면 올린다 — '자료 없음'으로 숨기지 않는다."""
    h = j.get("header") or {}
    if str(h.get("resultCode")) not in ("00", "0"):
        raise RuntimeError(f"조위 API {h.get('resultCode')}: {h.get('resultMsg')}")
    items = ((j.get("body") or {}).get("items") or {}).get("item") or []
    return [(x["obsrvnDt"].replace("-", "").replace(":", "").replace(" ", "")[:12], x.get("bscTdlvHgt"), x.get("tdlvHgt")) for x in items]


def highs(pts: list[tuple[str, float]]) -> list[tuple[str, float]]:
    """예측 곡선의 만조 — 앞뒤보다 높은 점."""
    return [pts[i] for i in range(1, len(pts) - 1) if pts[i][1] is not None and pts[i - 1][1] is not None
            and pts[i + 1][1] is not None and pts[i - 1][1] <= pts[i][1] > pts[i + 1][1]]


def spring(days: list[tuple[date, float]], today: date) -> dict | None:
    """대조기(계산) — 일 최고 만조가 앞뒤 닷새 안에서 가장 높은 날의 앞뒤 이틀. 지금이 그 안이면 now, 아니면 다음 구간.
    양 끝 닷새는 봉우리를 판정하지 못하므로 쓰지 않는다."""
    v = [d[1] for d in days]
    peaks = [days[i][0] for i in range(5, len(days) - 5) if v[i] == max(v[i - 5:i + 6])]
    spans: list[list[date]] = []
    for p in peaks:
        a, b = p - timedelta(days=2), p + timedelta(days=2)
        if spans and a <= spans[-1][1]:
            spans[-1][1] = b
        else:
            spans.append([a, b])
    for a, b in spans:
        if b >= today:
            return {"now": a <= today, "from": a.isoformat(), "to": b.isoformat()}
    return None


async def _get(cli: httpx.AsyncClient, code: str, d: date, minute: int) -> list[tuple[str, float | None, float | None]]:
    r = await cli.get(URL, params={"serviceKey": _key(), "type": "json", "obsCode": code, "reqDate": d.strftime("%Y%m%d"),
                                   "min": minute, "numOfRows": 1440 // minute, "pageNo": 1})
    r.raise_for_status()
    return parse(r.json())


async def _daily(cli: httpx.AsyncClient, today: date) -> None:
    """앞날 예측 — 지점마다 어제 ~ 8일 뒤(10분), 대조기용으로 통영 앞뒤 한 달(1시간). 하루 한 번."""
    pts: dict[str, list] = {}
    for st in STATIONS:
        got: list = []
        for n in range(-1, 9):
            got += await _get(cli, st["code"], today + timedelta(days=n), 10)
        pts[st["code"]] = [(t, p) for t, _, p in got]
    days = []
    for n in range(-7, 23):
        d = today + timedelta(days=n)
        vals = [p for _, _, p in await _get(cli, SPRING_REF, d, 60) if p is not None]
        if vals:
            days.append((d, max(vals)))
    _PRED.update(day=today, pts=pts, days=days)


def build(st: dict, today_rows: list, pred: list[tuple[str, float]], now: datetime) -> dict | None:
    """지점 하나 — 지금 값 · 예측과 차이 · 단계 · 다음 만조 · 7일 최고 만조 · 팝업 물결."""
    obs = [(t, o, p) for t, o, p in today_rows if o is not None]
    if not obs:
        return None
    t, v, p = obs[-1]
    stamp = now.strftime("%Y%m%d%H%M")
    all_p = sorted({**dict(pred), **{a: c for a, _, c in today_rows if c is not None}}.items())
    hi = [h for h in highs(all_p) if h[0] > stamp]
    week = (now + timedelta(days=7)).strftime("%Y%m%d%H%M")
    next_ = hi[0] if hi else None
    top = max((h for h in hi if h[0] <= week), key=lambda h: h[1], default=None)
    o_by = {a: b for a, b, _ in today_rows if b is not None}
    a0 = (now - timedelta(hours=PLOT_BACK)).strftime("%Y%m%d%H%M")
    a1 = (now + timedelta(hours=PLOT_FWD)).strftime("%Y%m%d%H%M")
    x, y = hr_xy(st["lon"], st["lat"])
    mark = lambda h: h and {"t": h[0], "h": h[1], "stage": stage(st, h[1])}       # noqa: E731
    facil = st.get("facil") or []
    return {"code": st["code"], "name": st["name"], "sigun": st["sigun"], "x": x, "y": y, "t": t, "v": v, "pred": p,
            "diff": round(v - p, 1) if p is not None else None, "stage": stage(st, v), "cuts": st["cuts"], "names": st["names"],
            "col": st["col"], "scale": st["scale"], "surge": st.get("surge"), "next": mark(next_), "top": mark(top), "facil": facil,
            "wet": [f["name"] for f in facil if top and f["h"] <= top[1]],     # 7일 안 만조가 지반고에 닿는 시설
            "series": [[a, o_by.get(a), b] for a, b in all_p if a0 <= a <= a1 and a[10:12] in ("00", "30")],
            "stale": (now - datetime.strptime(t, "%Y%m%d%H%M")).total_seconds() > STALE_MIN * 60}


async def collect(now: datetime | None = None) -> dict:
    """수집 주기마다. 키가 없으면 건너뛴다. 한 지점이 실패해도 그 지점의 앞 값은 남긴다."""
    if not _key():
        return {"skipped": "DATA_GO_KR_KEY 없음"}
    now = now or datetime.now()
    today = now.date()
    errs, rows = [], {r["code"]: r for r in _LIVE["rows"]}
    async with httpx.AsyncClient(timeout=20, verify=config.VERIFY_SSL) as cli:
        if _PRED["day"] != today:
            try:
                await _daily(cli, today)
            except Exception as e:                         # noqa: BLE001
                errs.append(f"예측: {_mask(e)[:100]}")
        for st in STATIONS:
            try:
                got = await _get(cli, st["code"], today, 10)
                row = build(st, got, _PRED["pts"].get(st["code"], []), now)
                if row:
                    rows[st["code"]] = row
            except Exception as e:                         # noqa: BLE001
                errs.append(f"{st['name']}: {_mask(e)[:100]}")
    _LIVE.update(at=now.strftime("%Y-%m-%d %H:%M"), err="; ".join(errs)[:200] or None,
                 rows=[rows[s["code"]] for s in STATIONS if s["code"] in rows],
                 spring=spring(_PRED["days"], today) if _PRED["days"] else None)
    if errs:
        log.warning("조위 수집 일부 실패: %s", _LIVE["err"])
    return {"rows": len(_LIVE["rows"]), "err": _LIVE["err"]}


def status() -> dict:
    return {"on": bool(_key()), "demo": config.DEMO, **_LIVE}


def of_sigun(sigun: str) -> dict | None:
    return next((r for r in _LIVE["rows"] if sigun in r["sigun"]), None)


def _hm(t: str) -> str:
    return f"{int(t[4:6])}.{int(t[6:8])}. {t[8:10]}:{t[10:12]}"


def _spring_text() -> str | None:
    s = _LIVE["spring"]
    return f"대조기(계산, 공식 날짜와 다를 수 있다): {s['from'][5:]} ~ {s['to'][5:]}" if s and s["now"] else None


def text(r: dict | None, fc6h=None, spring: bool = True) -> str | None:
    """AI 보고 한 줄 — 만조와 비를 나란히 둘 뿐 겹침을 판정하지 않는다(위키에 그 기준이 없다)."""
    if not r:
        return None
    lab = lambda h: f"({r['scale']} {r['names'][h['stage']]})" if h.get("stage") is not None else ""   # noqa: E731
    out = f"조위({r['name']}): 지금 {r['v']:g}cm"
    if r["diff"] is not None:
        out += f"(예측보다 {r['diff']:+g})"
    if r["stage"] is not None:
        out += f" · {r['scale']} {r['names'][r['stage']]}"
    if r["next"]:
        out += f" · 다음 만조 {_hm(r['next']['t'])} {r['next']['h']:g}cm{lab(r['next'])}"
    if fc6h is not None:
        out += f" · 앞으로 6시간 비 {fc6h:g}㎜"
    if r["top"] and r["top"]["stage"]:
        out += f" · 7일 안 최고 {_hm(r['top']['t'])} {r['top']['h']:g}cm{lab(r['top'])}"
    if r["wet"]:
        out += f" · 7일 안 만조가 지반고에 닿는 시설: {', '.join(r['wet'])}"
    if spring and _spring_text():
        out += f" · {_spring_text()}"
    return out


def summary() -> list[str]:
    """경남 전체 보고용 — 평소에는 비고, 단계 · 대조기 · 시설 침수 우려가 있을 때만 줄을 낸다."""
    out = [_spring_text()] if _spring_text() else []
    for r in _LIVE["rows"]:
        if (r["stage"] or 0) >= 1 or ((r["next"] or {}).get("stage") or 0) >= 1 or r["wet"]:
            out.append(text(r, spring=False))
    return out

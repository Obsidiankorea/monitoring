"""보고서 창 — 언레이드 jaenan-weather(재난상황보고서 서버, :8765)가 만드는 한글 보고서를 지도에서 받기 · 텔레그램으로 보내기.

  · 등록부 REG — 보고서 한 줄 = {id, name, group, job, desc, opts, ready}. **보고서가 늘면 여기 한 줄**(썸네일은 static/img/reports/<id>.png, 없으면 자리표시).
  · fetch(id, opts, items) → [(파일 이름, 바이트)…]. jaenan `GET /api/run/<job>`(작성 창이 있는 보고서는 POST — 고른 문구를 본문 JSON 으로)
    → `GET /files/<이름>`(둘 다 Authorization: Bearer). 한글 보고서는 .hwp 하나, 그림 작업(움짤 · 종합 · 특보 · 기온표)은 만든 파일 전부.
    run() = fetch 를 한 파일로(여럿이면 zip) — 받기 · 17시 대기용. 텔레그램은 파일마다(send_tg — 그림은 사진 · 움짤은 애니메이션).
    jaenan 은 한 번에 한 작업(잠금) · 같은 인자 2분 캐시 — 풍수해는 1분 안팎이라 넉넉히 기다린다.
  · 텔레그램은 gn-monitor 가 직접 sendDocument(키는 aiwatch 와 같은 TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID).
  · 옵션 — 런처(윈도우 앱) 옵션 가운데 서버에서 뜻이 있는 것(jaenan server/jobs.py 인자정의 와 같은 키 · 범위). 화면은 정의대로 그린다.
    기본값은 런처 기본값 — 화면은 기본값과 다른 것만 보낸다(안 보낸 것은 서버 설정을 따른다).
  · 17시 대기 — 등록부 wait=True 인 보고서(기상상황보고). jaenan 은 기다리지 않고 '아직'(waiting)이면 바로 답하므로
    여기서 1분마다 다시 묻는다(wait_tick). 상태 · 파일은 STATE 아래(다시 떠도 이어진다), 18:30 까지 안 나오면 그만둔다.
⚠️ JAENAN_TOKEN · 텔레그램 토큰은 응답 · 로그 · 오류 글 어디에도 내지 않는다(_mask). 주소 · 토큰은 config/api_keys.txt(JAENAN_URL · JAENAN_TOKEN).
"""
from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timedelta
from urllib.parse import quote

import httpx

from . import config

URL0 = "http://100.106.116.92:8765"
TIMEOUT = 1500                                     # 풍수해보고는 1분 안팎 · 기상청이 느리면 몇 분(늦은 자료는 보고서 서버가 빼고 만든다) · 다른 작업이 잠금을 쥐고 있으면 그만큼 더
GROUPS = ("풍수해", "폭염", "일상", "긴급", "그림")
KINDS = ("호우", "태풍", "강풍", "풍랑", "대설", "한파", "폭염")       # 상황판단회의 재난 종류(문구 kinds 와 같은 말)


def _o(key, label, kind, default="", sec="", hint="", **k) -> dict:
    """옵션 하나 — kind: datetime(YYYYMMDDHHMM) · int(min, max) · choice(values=[[값, 글]]) · multi(values) · bool · text(max)."""
    return {"key": key, "label": label, "kind": kind, "default": default, "sec": sec, "hint": hint, **k}


_TM = _o("tm", "기준 일시", "datetime", sec="기준", hint="비우면 지금 — 그 시각 자료로 만든다")
_HWP = [_TM, _o("wicon", "날씨 칸", "choice", "icon", "날씨 칸", "시군이 가장 많은 날씨 하나를 그림으로 · 또는 집계 글자 전부",
                values=[["icon", "아이콘 하나"], ["text", "글자로 전부(맑음10,구름많음8)"]]),
        _o("wicon_mm", "아이콘 높이(mm)", "int", 8, "날씨 칸", min=3, max=30),
        _o("alert_compact", "특보 지역 축약", "bool", False, "특보", "빠진 곳이 몇 개 이하면 '전 시군(제외: …)'"),
        _o("alert_compact_n", "축약 — 제외 몇 개 이하", "int", 5, "특보", min=1, max=25)]
_DAW = [_o("daw_per", "시군당", "int", 2, "다우지점", "강수량 큰 곳부터 — 시군마다 최대 몇 곳", min=1, max=5),
        _o("daw_total", "모두", "int", 10, "다우지점", "모두 합쳐 몇 곳까지", min=1, max=30)]
_CODES = [["W", "강풍"], ["R", "호우"], ["C", "한파"], ["D", "건조"], ["O", "해일"], ["N", "지진해일"], ["V", "풍랑"], ["T", "태풍"],
          ["S", "대설"], ["Y", "황사"], ["H", "폭염"], ["F", "안개"], ["K", "열대야"]]

# 보고서 등록부 — 한 줄 더하면 창에 타일이 하나 는다. wait=True 면 옵션창에 '17시 발표 대기'(jaenan 인자 wait1700)
REG = [
    {"id": "weather", "name": "기상상황보고", "group": "일상", "job": "weather", "desc": "단기 · 중기 예보, 기온, 통보문, 특보", "opts": _HWP,
     "ready": True, "wait": True},
    {"id": "daily", "name": "일일상황보고", "group": "일상", "job": "daily", "desc": "기온 · 강수량 · 다우지점 · 예보 · 특보", "opts": _HWP + _DAW,
     "ready": True, "wait": False},                # 같은 엔진이라 wait=True 로 켜면 17시 대기가 된다(이번에는 기상상황보고만)
    {"id": "nature", "name": "풍수해보고", "group": "풍수해", "job": "nature", "desc": "호우 대처상황보고 — 특보 이력 · 기상전망 · 강우 현황 · 그림", "ready": True,
     "opts": [_o("start", "기간 시작", "datetime", sec="기간", hint="비우면 전일 00시"),
              _o("end", "기간 끝", "datetime", sec="기간", hint="비우면 지금"),
              _o("kind", "재난 이름", "text", "호우", "제목", "제목의 '호우 대처상황보고' 앞말", max=10),
              _o("tail", "제목 꼬리", "choice", "", "제목", values=[["", "없음"], ["(1보)", "(1보)"], ["(2보)", "(2보)"], ["(3보)", "(3보)"],
                                                              ["(4보)", "(4보)"], ["(최종)", "(최종)"]]),
              _o("wrn", "특보 이력에 넣을 종류", "multi", ["호우"], "특보 이력", values=[[x, x] for x in ("호우", "태풍", "강풍", "풍랑", "대설")]),
              _o("stage", "비상단계 칸", "text", "", "특보 이력", "예) 상시대비단계 (10.19. 02:00~) — 비우면 빈칸", max=60),
              _o("step", "특보 훑기 간격(분)", "int", 10, "특보 이력", "해제 시각은 분 단위로 다시 좁힌다", min=1, max=60)] + _DAW},
    {"id": "report", "name": "긴급상황보고", "group": "긴급", "job": "report", "desc": "강수량 · 다우지점 표(시제품)", "ready": True,
     "opts": [_TM,
              _o("codes", "강조할 특보", "multi", ["R"], "특보", "표로 넣을 특보 — 나머지는 아래 요약 줄", values=_CODES),
              _o("rain_mode", "강수 기간", "choice", "days", "강수량", values=[["days", "며칠(누적)"], ["hours", "최근 몇 시간"]]),
              _o("rain_days", "며칠", "int", 2, "강수량", min=1, max=7),
              _o("rain_hours", "몇 시간", "int", 3, "강수량", min=1, max=72),
              _o("per_sigun", "시군당 다우지점", "int", 3, "다우지점", min=1, max=10),
              _o("daw_max", "다우지점 모두", "int", 20, "다우지점", min=1, max=100),
              _o("forecast", "향후 강수 예측(읍면동) 표", "bool", True, "초단기예측"),
              _o("interval", "간격", "choice", "10", "초단기예측", values=[[x, f"{x}분"] for x in ("10", "20", "30", "60")]),
              _o("fc_hours", "예측 시간", "choice", "1", "초단기예측", values=[[x, f"{x}시간"] for x in ("1", "2", "3", "6")]),
              _o("fc_per", "시군당 읍면동", "int", 5, "초단기예측", min=1, max=20),
              _o("fc_max", "최대 줄", "int", 50, "초단기예측", min=1, max=200)]},
    {"id": "meeting", "name": "상황판단회의", "group": "풍수해", "job": "meeting", "ready": True, "compose": "meeting",
     "desc": "기상전망 · 예상강우 · 특보 + 고른 중점 유의사항 · 조치계획",
     "opts": [_o("kinds", "재난 종류", "multi", ["호우"], "회의", values=[[x, x] for x in KINDS]),
              _o("title", "회의 제목", "text", "", "회의", "비우면 「기간 종류 대비」", max=60),
              _o("start", "기간 시작", "datetime", sec="기간", hint="비우면 전일 00시"),
              _o("end", "기간 끝", "datetime", sec="기간", hint="비우면 지금")],
     # 서식 하천 수위 표의 열 차례(현수위1~10 · 수위상태1~10) — 홍수통제소 지점 이름의 괄호 안
     "river": ["성하리", "적포교", "남포동", "삼랑진교", "소랑교", "덕오리", "대사교", "황강교", "일중리", "읍내리"]},
    {"id": "heat", "name": "폭염 상황보고", "group": "폭염", "job": "", "desc": "준비 중 — 재난상황보고서 서버에 아직 없다", "opts": [], "ready": False},
    {"id": "temp", "name": "3일 기온표", "group": "폭염", "job": "temp", "ready": True,
     "desc": "시군별 일 최고기온(11~3월은 최저) 3일 + 내일 예상 · 대표지점 외 AWS (그림) — 런처 특보이미지의 기온표",
     "opts": [_TM, _o("extra_n", "대표지점 외 AWS", "int", 6, "목록", "표 아래 몇 곳", min=0, max=20)]},
    {"id": "gif", "name": "강수 예측 움짤", "group": "그림", "job": "gif", "ready": True, "opts": [],
     "desc": "앞으로 N시간 분포도 + 예측 표 (GIF) — 범위 · 시간은 런처 긴급보고서 설정"},
    {"id": "combo", "name": "강수현황 종합", "group": "그림", "job": "combo", "ready": True,
     "desc": "지금까지 · 최근 1시간 · 앞으로 · 특보 — 휴대폰 화면 1~2장 (그림)",
     "opts": [_o("pages", "장 수", "choice", "", "종합", values=[["", "런처 설정대로"], ["1", "1장"], ["2", "2장"]]),
              _o("theme", "바탕", "choice", "", "종합", values=[["", "런처 설정대로"], ["light", "밝게"], ["dark", "어둡게"]])]},
    {"id": "alert", "name": "특보이미지", "group": "그림", "job": "alert", "ready": True,
     "desc": "특보 지도 모자이크 + 지역 목록 (그림) — 표기는 런처 특보이미지 설정",
     "opts": [_o("wrn", "넣을 특보", "multi", [], "특보", "비우면 런처 설정대로", values=_CODES)]},
]
BY_ID = {r["id"]: r for r in REG}
THUMBS = config.ROOT / "app" / "web" / "static" / "img" / "reports"   # 썸네일 <id>.png — 없으면 화면이 문서 모양 자리표시


def url() -> str:
    return (config.KEYS.get("JAENAN_URL") or URL0).rstrip("/")


def _tok() -> str:
    return config.KEYS.get("JAENAN_TOKEN") or ""


def ready() -> bool:
    return bool(_tok())


def tg_ready() -> bool:
    return bool(config.KEYS.get("TELEGRAM_BOT_TOKEN") and config.KEYS.get("TELEGRAM_CHAT_ID"))


def _mask(text: object) -> str:
    """오류 글에서 토큰을 지운다 — jaenan 토큰 · 텔레그램 토큰."""
    t = str(text)
    for k in ("JAENAN_TOKEN", "TELEGRAM_BOT_TOKEN"):
        v = config.KEYS.get(k) or ""
        if v:
            t = t.replace(v, "***")
    return t


# 시연(8001) — 기상상황보고(LIVE)는 지금 시각으로 실제로 만들고(못 만들면 샘플), 나머지는 미리 받아 둔 샘플 파일을 준다.
# 샘플은 저장소에 넣지 않는다 — 서버 state/snaps/_reports/<id>.<확장자>(시연이 읽기 전용으로 받는 폴더, 이름이 '_' 라 시연 목록에 안 걸린다)
DEMO_LIVE = ("weather",)


def sample(rid: str):
    """시연 샘플 파일 경로(없으면 None)."""
    d = config.SNAPS / "_reports"
    return next((p for p in sorted(d.glob(f"{rid}.*")) if p.is_file()), None) if d.exists() else None


def listing() -> dict:
    return {"reports": [{**{k: r[k] for k in ("id", "name", "group", "desc", "opts", "ready")}, "wait": bool(r.get("wait")),
                         "compose": r.get("compose") or "",
                         **({"sample": bool(sample(r["id"])), "live": r["id"] in DEMO_LIVE and ready()} if config.DEMO else {}),
                         "thumb": (THUMBS / f"{r['id']}.png").is_file()} for r in REG],
            "groups": list(GROUPS),
            "ready": ready(), "tg": tg_ready(), "demo": config.DEMO,
            "missing": [n for n, ok in (("JAENAN_TOKEN", ready()), ("TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID", tg_ready())) if not ok]}


def _opts(r: dict, opts: dict) -> dict:
    """등록부에 정의된 옵션만, 꼴을 확인해서 jaenan 인자(글자)로 — 정의에 없는 것은 버리고, 꼴이 틀리면 ValueError(무엇이 틀렸는지)."""
    out = {}
    for o in r["opts"]:
        raw = (opts or {}).get(o["key"])
        if raw is None or raw == "" or raw == []:
            continue
        k, lab = o["kind"], o["label"]
        if k == "bool":
            out[o["key"]] = "1" if raw in (True, 1, "1", "true", "on") else "0"
        elif k == "multi":
            vs = raw if isinstance(raw, list) else str(raw).split(",")
            ok = {v for v, _ in o["values"]}
            got = [str(v).strip() for v in vs if str(v).strip() in ok]
            if not got:
                raise ValueError(f"{lab}을 하나 이상 골라 주세요")
            out[o["key"]] = ",".join(dict.fromkeys(got))
        else:
            v = str(raw).strip()
            if k == "datetime":
                v = re.sub(r"\D", "", v)[:12]
                try:
                    datetime.strptime(v, "%Y%m%d%H%M")
                except ValueError:
                    raise ValueError(f"{lab}은 YYYYMMDDHHMM 열두 자리로 넣어 주세요") from None
            elif k == "int":
                if not re.fullmatch(r"\d+", v) or not o["min"] <= int(v) <= o["max"]:
                    raise ValueError(f"{lab}은 {o['min']}~{o['max']} 사이 숫자로 넣어 주세요")
            elif k == "choice":
                if v not in {x for x, _ in o["values"]}:
                    raise ValueError(f"{lab}에서 고를 수 없는 값입니다")
            elif k == "text":
                v = v[:o.get("max", 60)]
            out[o["key"]] = v
    return out


def file_name(stored: str, r: dict) -> str:
    """jaenan 이 붙인 앞머리(YYYYMMDD_HHMMSS_<job>_)를 떼고 보고서 이름만 — 없으면 '<이름>_<시각>.hwp'."""
    m = re.match(r"\d{8}_\d{6}_[^_]+_(.+)$", stored)
    return m.group(1) if m else (stored or f"{r['name']}_{datetime.now():%Y%m%d%H%M}.hwp")


ITEM_MAX, TEXT_MAX, SUB_MAX = 30, 300, 6
GROUPS_ITEMS = ("중점유의사항", "조치계획")                     # 상황판단회의 Ⅱ장 두 칸(jaenan 서식 칸 이름)


def items(raw) -> dict:
    """작성 창이 고른 문구 → {칸: [{text, subs}]} — 개수 · 길이만 자르고 모르는 꼴은 버린다(jaenan 이 한 번 더 거른다)."""
    out = {}
    for g in GROUPS_ITEMS:
        got = []
        for x in ((raw or {}).get(g) if isinstance(raw, dict) else None) or []:
            if not isinstance(x, dict) or not str(x.get("text") or "").strip():
                continue
            subs = [str(y).strip()[:TEXT_MAX] for y in (x.get("subs") or []) if str(y).strip()] if isinstance(x.get("subs"), list) else []
            got.append({"text": str(x["text"]).strip()[:TEXT_MAX], "subs": subs[:SUB_MAX]})
        out[g] = got[:ITEM_MAX]
    return out


RIVER_ST = {0: "정상", 1: "관심", 2: "주의", 3: "경계", 4: "심각"}   # 서식 표의 행 이름(심각 · 경계 · 주의 · 관심)과 같은 말로


def river_rows(names: list[str]) -> list[dict]:
    """지도 서버가 10분마다 받는 홍수통제소 수위 → 서식 열 차례대로 [{name, v, st, t, late, thr}]. 못 찾은 지점 · 값 없음 · 늦은 값(90분)은 v=None.
    단계 · 기준 수위(thr = 관심 · 주의보 · 경보 · 심각)는 홍수통제소 제원 — 서식 표의 기준 수위 칸도 이것으로 채운다."""
    from . import river
    rows = [r for r in river.status().get("rows") or [] if r.get("kind") == "wl"]
    out = []
    for n in names:
        r = next((x for x in rows if f"({n})" in (x.get("name") or "")), None)
        v = r.get("v") if r and not r.get("stale") else None
        out.append({"name": n, "v": v, "st": RIVER_ST.get(r.get("stage"), "-") if v is not None else "-", "t": r.get("t") if r else None,
                    "late": bool(r and r.get("stale")), "thr": (r or {}).get("thr") or []})
    return out


_PH: dict = {"t": 0.0, "v": None}
PH_TTL = 300                                       # 문구 후보 — 5분 동안 다시 묻지 않는다(jaenan 파일이 바뀌는 일은 드물다)


def phrases(client: httpx.Client | None = None) -> dict:
    """상황판단회의 문구 후보(jaenan GET /api/phrases/meeting) — {유의사항: [...], 조치계획: [...]}, 항목 = {text, kinds, subs}."""
    import time
    if _PH["v"] is not None and time.time() - _PH["t"] < PH_TTL:
        return _PH["v"]
    j = _jaenan("GET", "/api/phrases/meeting", client).json()
    pick = lambda xs: [{"text": str(x.get("text") or ""), "kinds": [k for k in x.get("kinds") or [] if k in KINDS],   # noqa: E731
                        "subs": [str(y) for y in x.get("subs") or []]} for x in xs or [] if isinstance(x, dict) and x.get("text")]
    v = {"유의사항": pick(j.get("유의사항")), "조치계획": pick(j.get("조치계획"))}
    _PH.update(t=time.time(), v=v)
    return v


MEDIA = {".hwp": "application/x-hwp", ".hwpx": "application/x-hwp", ".png": "image/png", ".gif": "image/gif", ".zip": "application/zip"}


def media(name: str) -> str:
    return MEDIA.get(name[name.rfind("."):].lower() if "." in name else "", "application/octet-stream")


def bundle(files: list[tuple[str, bytes]], r: dict | None = None) -> tuple[str, bytes]:
    """여러 파일 → zip 하나(이름 = '<보고서>_<시각>.zip'), 하나면 그대로."""
    if len(files) == 1:
        return files[0]
    import io
    import zipfile
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:          # 그림 · GIF 는 이미 눌려 있다
        for n, d in files:
            z.writestr(n, d)
    return f"{(r or {}).get('name') or '보고서'}_{datetime.now():%Y%m%d%H%M}.zip", buf.getvalue()


class Waiting(Exception):
    """17시 대기 — jaenan 이 '아직 17시 발표 전'(waiting)이라고 답했다. 글 = 지금 상태('통보문 11시 · 단기예보 11시')."""


def progress() -> dict:
    """보고서 서버가 지금 만드는 것 — {running, job, elapsed, calls: [{label, ok, fail}], last: {label, ago}, basis: [{name, at}], jobs: [같은 꼴…]}.
    맨 위는 먼저 받은 것 하나(예전 꼴). 못 물으면 running False."""
    if not ready() or config.DEMO:
        return {"running": False}
    try:
        r = httpx.get(f"{url()}/api/progress", headers={"Authorization": f"Bearer {_tok()}", "User-Agent": "gn-monitor/1"}, timeout=4)
        j = r.json() if r.status_code == 200 else {}
    except (httpx.HTTPError, ValueError):
        return {"running": False, "err": "보고서 서버에 묻지 못했다"}
    keep = ("running", "job", "elapsed", "calls", "last", "basis")
    out = {k: j.get(k) for k in keep} if j else {"running": False}
    out["jobs"] = [{k: x.get(k) for k in keep} for x in (j.get("jobs") or [])]      # 동시에 만드는 보고서마다(보고서 서버 일꾼들)
    return out


def run(rid: str, opts: dict | None = None, client: httpx.Client | None = None, wait1700: bool = False) -> tuple[str, bytes]:
    """fetch 를 한 파일로(여럿이면 zip) — (내려받을 이름, 바이트)."""
    return bundle(fetch(rid, opts, client, wait1700), BY_ID.get(rid))


def fetch(rid: str, opts: dict | None = None, client: httpx.Client | None = None, wait1700: bool = False,
          picked: dict | None = None, extra: dict | None = None, meta: dict | None = None) -> list[tuple[str, bytes]]:
    """보고서 하나를 jaenan 에서 만들어 받는다 → [(내려받을 이름, 바이트)…]. 실패는 RuntimeError(토큰을 지운 글).
    wait1700 — 17시 발표가 아직이면 Waiting(만들지 않는다). picked — 작성 창이 고른 문구(items 꼴, compose 보고서만 — POST 본문)."""
    r = BY_ID.get(rid)
    if not r or not r["ready"]:
        raise ValueError("없거나 아직 준비 중인 보고서입니다")
    if not ready():
        raise RuntimeError("재난상황보고서 서버 토큰(JAENAN_TOKEN)이 없다 — 설정 › API 키")
    q = _opts(r, opts or {})
    if wait1700:
        q["wait1700"] = "1"
    hd = {"Authorization": f"Bearer {_tok()}"}
    c = client or httpx.Client(timeout=TIMEOUT)
    local: list[dict] = []
    try:
        if r.get("compose"):
            body = items(picked)
            basis = []
            if r.get("river") and not config.DEMO:
                body["수위"] = river_rows(r["river"])
                ts = [x["t"] for x in body["수위"] if x["v"] is not None and x.get("t")]
                if ts:
                    t = max(ts)
                    basis.append({"name": "하천 수위(홍수통제소)", "at": f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[8:10]}:{t[10:12]} 관측"})
            if r["compose"] == "meeting" and not config.DEMO:     # 특보 시군 자료 셋(켠 것만) — 계산은 여기(자료가 지도 서버에 있다)
                from . import meeting
                more, b = meeting.extras((q.get("kinds") or "호우").split(","), extra)
                body |= more
                basis += b
            local = basis
            res = c.post(f"{url()}/api/run/{r['job']}", params=q, headers=hd, json=body)
        else:
            res = c.get(f"{url()}/api/run/{r['job']}", params=q, headers=hd)
        try:
            j = res.json()
        except ValueError:
            j = {}
        if res.status_code == 200 and j.get("waiting"):
            raise Waiting(_mask(j.get("status") or "17시 발표 전"))
        if res.status_code != 200 or not j.get("ok") or not j.get("files"):
            raise RuntimeError(f"보고서 서버 {res.status_code} — {j.get('error') or '파일을 만들지 못했다'}")
        pairs = list(zip(j["files"], j.get("names") or [f.rsplit("/", 1)[-1] for f in j["files"]]))
        hwp = [x for x in pairs if x[0].lower().endswith((".hwp", ".hwpx"))]
        out = []
        for f, stored in hwp[:1] or pairs:          # 한글 보고서는 .hwp 하나, 그림 작업은 전부
            got = c.get(f"{url()}{f}", headers=hd)
            if got.status_code != 200 or not got.content:
                raise RuntimeError(f"보고서 파일을 받지 못했다({got.status_code})")
            out.append((file_name(stored, r), got.content))
        if meta is not None:                       # 화면 팝업 — 이번 파일에 쓴 기상청 자료 시각(jaenan) + 이번 요청에 넣은 우리 자료 시각
            meta["basis"] = [{"name": str(x.get("name"))[:60], "at": str(x.get("at"))[:120]}
                             for x in j.get("basis") or [] if isinstance(x, dict)][:20] + local
            meta["warn"] = warn_text(j.get("warn"))
            if meta["warn"]:                       # 기상청 조회가 끝내 실패한 자료 — 그 칸이 비었거나 지난 값일 수 있다(맨 위에)
                meta["basis"].insert(0, {"name": "⚠️ 기상청 조회 실패 — 그 칸 확인 필요", "at": meta["warn"], "warn": True})
        return out
    except httpx.HTTPError as e:
        raise RuntimeError(_mask(f"보고서 서버에 연결하지 못했다 — {type(e).__name__}: {e}")) from None
    except RuntimeError as e:
        raise RuntimeError(_mask(e)) from None
    finally:
        if client is None:
            c.close()


def warn_text(warn) -> str:
    """jaenan 의 warn [{label, fail, total}] → '기상특보 18/207번 · 파고 1/1번(못 받음)'."""
    out = []
    for x in warn or []:
        if isinstance(x, dict) and x.get("label") and isinstance(x.get("fail"), int) and isinstance(x.get("total"), int):
            out.append(f"{str(x['label'])[:20]} {x['fail']}/{x['total']}번" + ("(못 받음)" if x["fail"] >= x["total"] else ""))
    return " · ".join(out[:10])


TG_KIND = {"image/png": ("sendPhoto", "photo"), "image/gif": ("sendAnimation", "animation")}   # 그 밖은 sendDocument


def send_tg(name: str, data: bytes, caption: str = "", client: httpx.Client | None = None) -> None:
    """텔레그램으로 파일 보내기 — 그림은 사진(sendPhoto) · GIF 는 움짤(sendAnimation) · 한글 등은 파일(sendDocument).
    실패는 RuntimeError(토큰을 지운 글)."""
    tok, chat = config.KEYS.get("TELEGRAM_BOT_TOKEN"), config.KEYS.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        raise RuntimeError("텔레그램 키(TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID)가 없다")
    c = client or httpx.Client(timeout=60, verify=config.VERIFY_SSL)
    try:
        m, field = TG_KIND.get(media(name), ("sendDocument", "document"))
        r = c.post(f"https://api.telegram.org/bot{tok}/{m}", data={"chat_id": chat, "caption": caption[:1000]},
                   files={field: (name, data, media(name))})
        if r.status_code != 200:
            raise RuntimeError(f"텔레그램 {r.status_code}")
    except httpx.HTTPError as e:
        raise RuntimeError(_mask(f"텔레그램에 연결하지 못했다 — {type(e).__name__}: {e}")) from None
    finally:
        if client is None:
            c.close()


# ── 로고 — 보고서 [로고] 칸 그림(jaenan /api/logos). 토큰은 여기 안에만, 올리기 검사는 이쪽에서도 한 번 더.
LOGO_MAX = 2 * 1024 * 1024


def logo_kind(data: bytes) -> str | None:
    """그림 종류(머리 바이트로) — png · jpg · webp, 아니면 None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _jaenan(method: str, path: str, client: httpx.Client | None = None, **kw) -> httpx.Response:
    if not ready():
        raise RuntimeError("재난상황보고서 서버 토큰(JAENAN_TOKEN)이 없다 — 설정 › API 키")
    c = client or httpx.Client(timeout=30)
    try:
        r = c.request(method, f"{url()}{path}", headers={"Authorization": f"Bearer {_tok()}", **kw.pop("headers", {})}, **kw)
    except httpx.HTTPError as e:
        raise RuntimeError(_mask(f"보고서 서버에 연결하지 못했다 — {type(e).__name__}: {e}")) from None
    finally:
        if client is None:
            c.close()
    if r.status_code != 200:
        try:
            why = r.json().get("error")
        except ValueError:
            why = ""
        raise (ValueError if r.status_code == 400 else RuntimeError)(_mask(why or f"보고서 서버 {r.status_code}"))
    return r


def logos(client: httpx.Client | None = None) -> dict:
    j = _jaenan("GET", "/api/logos", client).json()
    return {"logos": [{"name": x["name"], "user": bool(x.get("user"))} for x in j.get("logos") or []], "selected": j.get("selected"), "default": j.get("default")}


def logo_select(name: str, client: httpx.Client | None = None) -> str:
    return _jaenan("PUT", "/api/logos/selected", client, json={"name": str(name or "")[:80]}).json().get("selected") or ""


def logo_upload(name: str, data: bytes, client: httpx.Client | None = None) -> str:
    """그림 올리기 — PNG · JPG · WEBP, 2MB 이하(jaenan 이 PNG 로 바꿔 /config/logos 에 둔다). 저장된 이름."""
    if not data or len(data) > LOGO_MAX:
        raise ValueError("그림은 2MB 이하로 올려 주세요")
    if not logo_kind(data):
        raise ValueError("PNG · JPG · WEBP 그림만 올릴 수 있습니다")
    return _jaenan("POST", "/api/logos", client, params={"name": str(name or "로고")[:80]}, content=data,
                   headers={"Content-Type": "application/octet-stream"}).json().get("name") or ""


def logo_img(name: str, client: httpx.Client | None = None) -> bytes:
    return _jaenan("GET", "/api/logos/img", client, params={"name": name}).content


def disposition(name: str) -> str:
    """첨부 머리 — 한글 이름은 RFC 5987(filename*), 옛 브라우저용 filename 은 ASCII 로."""
    ascii_ = re.sub(r"[^A-Za-z0-9._-]", "_", name) or "report.hwp"
    return f"attachment; filename=\"{ascii_}\"; filename*=UTF-8''{quote(name)}"


# ── 17시 대기 — 걸면 1분마다(wait_tick, 서버 스케줄러) jaenan 에 wait1700=1 로 묻는다. 나오면 만들어 STATE 에 두고(하루 뒤 지움), tg 면 보낸다.
WAIT_FILE = config.STATE / "reports_wait.json"
WAIT_DIR = config.STATE / "reports"
CUTOFF = (18, 30)                                  # 이때까지 17시 발표가 안 나오면 그만둔다(사유를 남긴다)
KEEP_S = 86400
_WL = threading.Lock()                             # 상태 파일 읽고 쓰기
_TICK = threading.Lock()                           # 한 번에 한 바퀴


def _wload() -> dict:
    try:
        return json.loads(WAIT_FILE.read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def _wsave(d: dict) -> None:
    WAIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    WAIT_FILE.write_text(json.dumps(d, ensure_ascii=False, indent=1), "utf-8")


def wait_state() -> dict:
    """화면에 줄 것 — {id: {state: waiting|ready|fail, status, since, until, name, tg, why}}. 파일 경로 · 옵션은 내지 않는다."""
    with _WL:
        d = _wload()
    return {k: {x: v.get(x) for x in ("state", "status", "since", "until", "at", "name", "tg", "tg_st", "why")} for k, v in d.items()}


def wait_set(rid: str, opts: dict | None, tg: bool, now: datetime | None = None) -> dict:
    """대기 걸기 — 오늘 17시 발표만(다음 날로 넘기지 않는다). 18:30 뒤에 걸면 이미 나왔을 것이니 바로 한 번 만들어 본다."""
    r = BY_ID.get(rid)
    if not r or not r.get("wait") or not r["ready"]:
        raise ValueError("이 보고서는 17시 대기를 걸 수 없습니다")
    _opts(r, opts or {})                           # 꼴이 틀리면 지금 알린다
    now = now or datetime.now()
    cut = now.replace(hour=CUTOFF[0], minute=CUTOFF[1], second=0, microsecond=0)
    until = cut if now < cut else now + timedelta(minutes=10)
    with _WL:
        d = _wload()
        d[rid] = {"state": "waiting", "opts": opts or {}, "tg": bool(tg), "since": now.isoformat(timespec="seconds"),
                  "until": until.isoformat(timespec="seconds"), "status": "", "why": ""}
        _wsave(d)
    return wait_state()


def wait_cancel(rid: str) -> dict:
    with _WL:
        d = _wload()
        x = d.pop(rid, None)
        _wsave(d)
    if x and x.get("file"):
        (WAIT_DIR / x["file"]).unlink(missing_ok=True)
    return wait_state()


def wait_file(rid: str) -> tuple[str, bytes]:
    with _WL:
        x = _wload().get(rid) or {}
    if x.get("state") != "ready" or not x.get("file") or not (WAIT_DIR / x["file"]).is_file():
        raise ValueError("준비된 17시 보고서가 없습니다")
    return x["name"], (WAIT_DIR / x["file"]).read_bytes()


def wait_any() -> bool:
    with _WL:
        return any(v.get("state") == "waiting" for v in _wload().values())


def _patch(rid: str, **kw) -> None:
    with _WL:
        d = _wload()
        if rid in d:
            d[rid].update(kw)
            _wsave(d)


def wait_tick(now: datetime | None = None, client: httpx.Client | None = None, tg_client: httpx.Client | None = None) -> int:
    """한 바퀴 — 대기 중인 것마다 jaenan 에 묻는다. 나오면 파일 · 텔레그램, 시간 넘기면 그만. 하루 지난 것은 지운다. 물어본 수."""
    if not _TICK.acquire(blocking=False):
        return 0
    try:
        now = now or datetime.now()
        with _WL:
            d = _wload()
        for rid, x in list(d.items()):                 # 하루 지난 것(준비됨 · 실패)은 파일과 함께 지운다
            if x.get("state") != "waiting" and (now - datetime.fromisoformat(x.get("at") or x["since"])).total_seconds() > KEEP_S:
                wait_cancel(rid)
        n = 0
        for rid, x in d.items():
            if x.get("state") != "waiting":
                continue
            if now >= datetime.fromisoformat(x["until"]):
                _patch(rid, state="fail", at=now.isoformat(timespec="seconds"),
                       why=f"{x['until'][11:16]} 까지 17시 발표가 나오지 않아 그만뒀다" + (f" ({x['status']})" if x.get("status") else ""))
                continue
            n += 1
            try:
                name, data = run(rid, x.get("opts") or {}, client, wait1700=True)
            except Waiting as e:
                _patch(rid, status=str(e), checked=now.isoformat(timespec="seconds"))
                continue
            except (RuntimeError, ValueError) as e:     # 서버에 연결 못 함 등 — 다음 바퀴에 다시(사유만 적어 둔다)
                _patch(rid, status=_mask(e)[:200], checked=now.isoformat(timespec="seconds"))
                continue
            WAIT_DIR.mkdir(parents=True, exist_ok=True)
            f = f"{rid}_{now:%Y%m%d%H%M%S}.hwp"
            (WAIT_DIR / f).write_bytes(data)
            st = None
            if x.get("tg"):
                try:
                    send_tg(name, data, f"📄 {BY_ID[rid]['name']} — 17시 발표가 나와 만들었다(경남 강수 지도)", tg_client)
                    st = "ok"
                except RuntimeError as e:
                    st = f"fail: {_mask(e)[:120]}"
            _patch(rid, state="ready", file=f, name=name, at=now.isoformat(timespec="seconds"), status="", tg_st=st)
        return n
    finally:
        _TICK.release()

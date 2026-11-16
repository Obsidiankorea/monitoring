"""보고서 창 — 언레이드 jaenan-weather(재난상황보고서 서버, :8765)가 만드는 한글 보고서를 지도에서 받기 · 텔레그램으로 보내기.

  · 등록부 REG — 보고서 한 줄 = {id, name, group, job, desc, opts, ready}. **보고서가 늘면 여기 한 줄**(썸네일은 static/img/reports/<id>.png, 없으면 자리표시).
  · run(id, opts) → (파일 이름, 바이트). jaenan `GET /api/run/<job>` → `GET /files/<이름>`(둘 다 Authorization: Bearer).
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
TIMEOUT = 300                                      # 풍수해보고는 1분 안팎 · 다른 작업이 잠금을 쥐고 있으면 그만큼 더
GROUPS = ("풍수해", "폭염", "일상", "긴급")


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
    {"id": "heat", "name": "폭염 상황보고", "group": "폭염", "job": "", "desc": "준비 중 — 재난상황보고서 서버에 아직 없다", "opts": [], "ready": False},
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


def listing() -> dict:
    return {"reports": [{**{k: r[k] for k in ("id", "name", "group", "desc", "opts", "ready")}, "wait": bool(r.get("wait")),
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


class Waiting(Exception):
    """17시 대기 — jaenan 이 '아직 17시 발표 전'(waiting)이라고 답했다. 글 = 지금 상태('통보문 11시 · 단기예보 11시')."""


def run(rid: str, opts: dict | None = None, client: httpx.Client | None = None, wait1700: bool = False) -> tuple[str, bytes]:
    """보고서 하나를 jaenan 에서 만들어 받는다 → (내려받을 이름, 바이트). 실패는 RuntimeError(토큰을 지운 글).
    wait1700 — 17시 발표가 아직이면 Waiting(만들지 않는다)."""
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
    try:
        res = c.get(f"{url()}/api/run/{r['job']}", params=q, headers=hd)
        try:
            j = res.json()
        except ValueError:
            j = {}
        if res.status_code == 200 and j.get("waiting"):
            raise Waiting(_mask(j.get("status") or "17시 발표 전"))
        if res.status_code != 200 or not j.get("ok") or not j.get("files"):
            raise RuntimeError(f"보고서 서버 {res.status_code} — {j.get('error') or '파일을 만들지 못했다'}")
        f = next((x for x in j["files"] if x.lower().endswith((".hwp", ".hwpx"))), j["files"][0])
        got = c.get(f"{url()}{f}", headers=hd)
        if got.status_code != 200 or not got.content:
            raise RuntimeError(f"보고서 파일을 받지 못했다({got.status_code})")
        stored = (j.get("names") or [f.rsplit("/", 1)[-1]])[0]
        return file_name(stored, r), got.content
    except httpx.HTTPError as e:
        raise RuntimeError(_mask(f"보고서 서버에 닿지 못했다 — {type(e).__name__}: {e}")) from None
    except RuntimeError as e:
        raise RuntimeError(_mask(e)) from None
    finally:
        if client is None:
            c.close()


def send_tg(name: str, data: bytes, caption: str = "", client: httpx.Client | None = None) -> None:
    """텔레그램으로 파일 보내기(sendDocument) — 실패는 RuntimeError(토큰을 지운 글)."""
    tok, chat = config.KEYS.get("TELEGRAM_BOT_TOKEN"), config.KEYS.get("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        raise RuntimeError("텔레그램 키(TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID)가 없다")
    c = client or httpx.Client(timeout=60, verify=config.VERIFY_SSL)
    try:
        r = c.post(f"https://api.telegram.org/bot{tok}/sendDocument", data={"chat_id": chat, "caption": caption[:1000]},
                   files={"document": (name, data, "application/octet-stream")})
        if r.status_code != 200:
            raise RuntimeError(f"텔레그램 {r.status_code}")
    except httpx.HTTPError as e:
        raise RuntimeError(_mask(f"텔레그램에 닿지 못했다 — {type(e).__name__}: {e}")) from None
    finally:
        if client is None:
            c.close()


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
            except (RuntimeError, ValueError) as e:     # 서버에 못 닿음 등 — 다음 바퀴에 다시(사유만 적어 둔다)
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

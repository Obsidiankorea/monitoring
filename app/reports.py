"""보고서 창 — 언레이드 jaenan-weather(재난상황보고서 서버, :8765)가 만드는 한글 보고서를 지도에서 받기 · 텔레그램으로 보내기.

  · 등록부 REG — 보고서 한 줄 = {id, name, group, job, desc, opts, ready}. **보고서가 늘면 여기 한 줄**(썸네일은 static/img/reports/<id>.png, 없으면 자리표시).
  · run(id, opts) → (파일 이름, 바이트). jaenan `GET /api/run/<job>` → `GET /files/<이름>`(둘 다 Authorization: Bearer).
    jaenan 은 한 번에 한 작업(잠금) · 같은 인자 2분 캐시 — 풍수해는 1분 안팎이라 넉넉히 기다린다.
  · 텔레그램은 gn-monitor 가 직접 sendDocument(키는 aiwatch 와 같은 TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID).
⚠️ JAENAN_TOKEN · 텔레그램 토큰은 응답 · 로그 · 오류 글 어디에도 내지 않는다(_mask). 주소 · 토큰은 config/api_keys.txt(JAENAN_URL · JAENAN_TOKEN).
"""
from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import quote

import httpx

from . import config

URL0 = "http://100.106.116.92:8765"
TIMEOUT = 300                                      # 풍수해보고는 1분 안팎 · 다른 작업이 잠금을 쥐고 있으면 그만큼 더
GROUPS = ("풍수해", "폭염", "일상", "긴급")

# 보고서 등록부 — 한 줄 더하면 창에 타일이 하나 는다. opts: 받을 때 고를 것 {key, label, kind: datetime(YYYYMMDDHHMM)|text, hint}
REG = [
    {"id": "weather", "name": "기상상황보고", "group": "일상", "job": "weather", "desc": "단기 · 중기 예보, 기온, 통보문, 특보", "opts": [], "ready": True},
    {"id": "daily", "name": "일일상황보고", "group": "일상", "job": "daily", "desc": "기온 · 강수량 · 다우지점 · 예보 · 특보", "opts": [], "ready": True},
    {"id": "nature", "name": "풍수해보고", "group": "풍수해", "job": "nature", "desc": "호우 대처상황보고 — 특보 이력 · 기상전망 · 강우 현황 · 그림", "opts": [], "ready": True},
    {"id": "report", "name": "긴급상황보고", "group": "긴급", "job": "report", "desc": "강수량 · 다우지점 표(시제품)",
     "opts": [{"key": "sample", "label": "기준 시각", "kind": "datetime", "hint": "비우면 지금 — 지난 시각은 저장본으로 다시 만든다"}], "ready": True},
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
    return {"reports": [{**{k: r[k] for k in ("id", "name", "group", "desc", "opts", "ready")}, "thumb": (THUMBS / f"{r['id']}.png").is_file()} for r in REG],
            "groups": list(GROUPS),
            "ready": ready(), "tg": tg_ready(), "demo": config.DEMO,
            "missing": [n for n, ok in (("JAENAN_TOKEN", ready()), ("TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID", tg_ready())) if not ok]}


def _opts(r: dict, opts: dict) -> dict:
    """등록부에 정의된 옵션만, 꼴을 확인해서 넘긴다(나머지는 버린다)."""
    out = {}
    for o in r["opts"]:
        v = str((opts or {}).get(o["key"]) or "").strip()
        if not v:
            continue
        if o["kind"] == "datetime":
            v = re.sub(r"\D", "", v)[:12]
            if len(v) != 12:
                raise ValueError(f"{o['label']}은 YYYYMMDDHHMM 열두 자리로 넣어 주세요")
        out[o["key"]] = v[:60]
    return out


def file_name(stored: str, r: dict) -> str:
    """jaenan 이 붙인 앞머리(YYYYMMDD_HHMMSS_<job>_)를 떼고 보고서 이름만 — 없으면 '<이름>_<시각>.hwp'."""
    m = re.match(r"\d{8}_\d{6}_[^_]+_(.+)$", stored)
    return m.group(1) if m else (stored or f"{r['name']}_{datetime.now():%Y%m%d%H%M}.hwp")


def run(rid: str, opts: dict | None = None, client: httpx.Client | None = None) -> tuple[str, bytes]:
    """보고서 하나를 jaenan 에서 만들어 받는다 → (내려받을 이름, 바이트). 실패는 RuntimeError(토큰을 지운 글)."""
    r = BY_ID.get(rid)
    if not r or not r["ready"]:
        raise ValueError("없거나 아직 준비 중인 보고서입니다")
    if not ready():
        raise RuntimeError("재난상황보고서 서버 토큰(JAENAN_TOKEN)이 없다 — 설정 › API 키")
    q = _opts(r, opts or {})
    hd = {"Authorization": f"Bearer {_tok()}"}
    c = client or httpx.Client(timeout=TIMEOUT)
    try:
        res = c.get(f"{url()}/api/run/{r['job']}", params=q, headers=hd)
        try:
            j = res.json()
        except ValueError:
            j = {}
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

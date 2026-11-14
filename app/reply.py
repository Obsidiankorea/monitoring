"""현장 회신 — 지구마다 변하지 않는 링크(/r/<토큰>) 하나. 그 페이지에서 담당자가 스스로 등록 · 교대하고, 조치 상황을 올린다.

  · 담당자: 직급 · 성명 · 연락처를 페이지에서 직접 넣는다(지구마다 둘까지). 등록하면 대시보드 연락처(contacts.of_sigun)에 바로 반영된다.
    링크를 다른 사람에게 넘기면 그 사람도 등록한다. 빠지면 '지난 담당'으로 남는다 — 누가 언제부터 언제까지 맡았는지.
  · 진행 기록: 상황실 요청 · 현장 회신(사진 · 조치 여부 · 추가 배치) · 담당 등록/빠짐이 한 줄씩 쌓인다(지우지 않는다).
    다음 담당자는 같은 링크에서 지금까지를 읽는다.
  · 상황실: 지구를 골라 요청(ask) → 지금 담당자(등록한 사람, 없으면 연락처 파일) 번호와 문자 글 → 현황(rows).

⚠️ 대시보드에는 로그인이 없다 — **밖에 여는 것은 이 파일의 public_app 뿐**이다(/r/ 만 있다).
     python -m app.reply            # 회신 전용 서버(GN_REPLY_PORT, 기본 8010) — 대시보드와 같은 상태 폴더(DB)를 본다
   현장 휴대폰이 닿는 주소(터널 · 프록시)는 이 포트에만 잇는다. 대시보드 포트(8000)는 잇지 않는다.
⚠️ 링크를 가진 사람은 그 지구의 담당자 이름 · 번호(페이지에서 스스로 넣은 것)와 기록을 보고, 담당자를 바꿀 수 있다 — 링크가 곧 열쇠다.
   연락처 파일(contacts.csv)의 이름 · 번호는 이 페이지에 내보내지 않는다.
⚠️ AI 쪽 코드는 이 모듈을 부르지 않는다(이름 · 번호가 들어 있다 — contacts.py 와 같은 약속).

shortcut: 본인 확인이 없다(링크만 있으면 누구 이름으로든 등록) — 잘못 등록하는 일이 생기면 문자 인증을 붙인다.
shortcut: 문자는 보내지 않는다 — 번호 · 문자 글 · 링크를 만들어 줄 뿐(화면에서 문자 앱 열기 · 복사).
"""
from __future__ import annotations

import base64
import csv
import io
import json
import re
import secrets
from datetime import datetime

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse

from . import config, db

DIR = config.STATE / "replies"                     # 사진 — <기록 번호>.jpg
PAGE = config.ROOT / "app" / "web" / "static" / "r.html"
ACTIONS = ("done", "doing", "not", "na")           # 조치함 · 조치 중 · 아직 · 해당 없음
MAX_PEOPLE = 2
MAX_BODY = 6 * 1024 * 1024                         # 화면이 사진을 줄여 보낸다(긴 변 1600) — 그래도 넘으면 받지 않는다


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _mobile(tel: str) -> str:
    """문자를 받을 수 있는 번호만(010 …). 아니면 ''."""
    d = re.sub(r"\D", "", tel or "")
    return d if re.fullmatch(r"01\d{8,9}", d) else ""


def _districts() -> dict[str, tuple[str, str, str]]:
    """지역ID → (시군, 지구 이름, 주소) — 위키 우려지역 표, 거기 없으면 연락처 파일."""
    from . import ai, contacts
    out = {}
    try:
        with open(ai.wiki() / "data" / "인명피해 우려지역.csv", encoding="utf-8-sig", newline="") as f:
            src = list(csv.DictReader(f))
    except OSError:
        src = []
    for w in list(contacts._rows().values()) + src:          # 뒤(위키)가 이긴다
        if w.get("지역ID"):
            out[w["지역ID"]] = (w.get("시군") or "", w.get("지구명") or w["지역ID"],
                              " ".join(x for x in (w.get("시군"), w.get("읍면동"), w.get("리")) if x))
    return out


def _current(con, rid: str) -> list[dict]:
    return [{"id": r[0], "rank": r[1], "name": r[2], "tel": r[3], "since": r[4]} for r in con.execute(
        "SELECT id, rank, name, tel, since FROM duty_person WHERE rid=? AND until IS NULL ORDER BY id", (rid,))]


def _who(p: dict) -> str:
    return f"{p['rank']} {p['name']}".strip()


def current_by_sigun(sigun_full: str | None) -> dict[str, list[dict]]:
    """대시보드 연락처에 얹을 것 — 지역ID → [{who, tel}] (페이지에서 등록한 지금 담당). sigun_full 이 None 이면 경남 전체."""
    with db.tx() as con:
        got = con.execute("SELECT p.rid, p.rank, p.name, p.tel FROM duty_person p JOIN duty_link l ON l.rid = p.rid"
                          " WHERE p.until IS NULL AND (? IS NULL OR l.sigun = ?) ORDER BY p.id", (sigun_full, sigun_full)).fetchall()
    out: dict[str, list[dict]] = {}
    for rid, rank, name, tel in got:
        out.setdefault(rid, []).append({"who": f"{rank} {name}".strip(), "tel": tel})
    return out


def ask(rids: list[str], note: str, base: str, preview: bool = False) -> dict:
    """지구들에 회신 요청 — 지구 링크를 (없으면) 만들고 기록에 요청을 남긴다.
    {people: [{who, tel, names, sms}] 번호마다 문자 하나(맡은 지구 링크를 모아), nophone: [{name, url}] 번호를 모르는 지구, links: [{rid, name, url}]}.
    preview — 요청(ask)을 남기지 않고 글 · 링크만(상황판단 미리보기). 링크는 지구마다 하나라 없으면 만든다(현황 rows 에는 기록이 생겨야 나온다)."""
    from . import contacts
    dz, csvrows = _districts(), contacts._rows()
    note = (note or "").strip()[:200]
    at = _now()
    by_tel: dict[str, dict] = {}
    nophone, links = [], []
    with db.tx() as con:
        for rid in dict.fromkeys(rids):
            if rid not in dz:
                continue
            sigun, name, addr = dz[rid]
            con.execute("INSERT OR IGNORE INTO duty_link(rid, token, sigun, name, addr) VALUES(?,?,?,?,?)",
                        (rid, secrets.token_urlsafe(9), sigun, name, addr))
            url = f"{base.rstrip('/')}/r/{con.execute('SELECT token FROM duty_link WHERE rid=?', (rid,)).fetchone()[0]}"
            links.append({"rid": rid, "name": name, "url": url})
            if not preview:
                con.execute("INSERT INTO duty_log(rid, at, kind, who, memo) VALUES(?,?,?,?,?)", (rid, at, "ask", "상황실", note))
            people = [(_who(p), p["tel"]) for p in _current(con, rid)]
            if not people:                                       # 아직 아무도 등록 안 한 지구 — 연락처 파일의 번호로
                r = csvrows.get(rid) or {}
                people = [(r.get(f"담당{i}") or "", t) for i in (1, 2)
                          if (t := _mobile(r.get(f"담당{i}_연락처_정규화") or r.get(f"담당{i}_연락처") or ""))]
            for who, tel in people:
                by_tel.setdefault(tel, {"who": who, "tel": tel, "items": []})["items"].append((name, url))
            if not people:
                nophone.append({"name": name, "url": url})
    head = f"[경남도 재난상황실] {note or '현장 조치 여부를 알려 주세요'}"
    return {"nophone": nophone, "links": links, "people": [
        {"who": p["who"], "tel": p["tel"], "names": [n for n, _ in p["items"]],
         "sms": "\n".join([head] + [u if len(p["items"]) == 1 else f"{n} {u}" for n, u in p["items"]])}
        for p in by_tel.values()]}


def rows() -> list[dict]:
    """상황실 현황 — 링크가 있는 지구마다: 지금 담당 · 마지막 요청 · 마지막 회신. 이름 · 번호가 들어 있다(잠금 번호 뒤에서만)."""
    out = []
    with db.tx() as con:
        for rid, token, name, addr in con.execute("SELECT rid, token, name, addr FROM duty_link").fetchall():
            last = {k: con.execute("SELECT id, at, who, action, more, memo, photo FROM duty_log WHERE rid=? AND kind=?"
                                   " ORDER BY id DESC LIMIT 1", (rid, k)).fetchone() for k in ("ask", "reply")}
            a, r = last["ask"], last["reply"]
            if not a and not r and not _current(con, rid):    # 미리보기로 링크만 생긴 지구 — 요청 · 회신 · 담당이 생기면 나온다
                continue
            out.append({"rid": rid, "token": token, "name": name, "addr": addr,
                        "people": [{"who": _who(p), "tel": p["tel"]} for p in _current(con, rid)],
                        "asked_at": a and a[1], "note": a and a[5],
                        "reply": r and {"id": r[0], "at": r[1], "who": r[2], "action": r[3], "more": r[4], "memo": r[5], "photo": bool(r[6])},
                        "waiting": bool(a and (not r or r[0] < a[0]))})     # 마지막 요청 뒤로 회신이 없다
    out.sort(key=lambda x: x["asked_at"] or "", reverse=True)
    out.sort(key=lambda x: not x["waiting"])                  # 회신을 기다리는 지구가 위로(그 안에서는 새 요청부터)
    return out


def _link(con, token: str) -> tuple[str, str, str]:
    got = con.execute("SELECT rid, name, addr FROM duty_link WHERE token=?", (token,)).fetchone()
    if not got:
        raise HTTPException(404, "없는 링크입니다")
    return got


def form(token: str) -> dict:
    """링크 페이지에 줄 것 — 지구 · 지금 담당 · 지난 담당 · 진행 기록(새 것부터 60줄)."""
    with db.tx() as con:
        rid, name, addr = _link(con, token)
        return {"name": name, "addr": addr, "max": MAX_PEOPLE, "people": _current(con, rid),
                "past": [{"rank": r[0], "name": r[1], "since": r[2], "until": r[3]} for r in con.execute(
                    "SELECT rank, name, since, until FROM duty_person WHERE rid=? AND until IS NOT NULL ORDER BY id DESC LIMIT 20", (rid,))],
                "log": [{"id": r[0], "at": r[1], "kind": r[2], "who": r[3], "action": r[4], "more": r[5], "memo": r[6], "photo": bool(r[7])}
                        for r in con.execute("SELECT id, at, kind, who, action, more, memo, photo FROM duty_log WHERE rid=?"
                                             " ORDER BY id DESC LIMIT 60", (rid,))]}


def _open() -> None:
    if config.DEMO:
        raise HTTPException(403, "시연 화면에서는 받지 않습니다")


def join(token: str, body: dict) -> dict:
    """담당자 등록 — {rank, name, tel}. 지구마다 둘까지(셋째는 누가 빠져야 한다). 등록한 사람의 id."""
    _open()
    rank, name = str(body.get("rank") or "").strip()[:20], str(body.get("name") or "").strip()[:20]
    tel = _mobile(str(body.get("tel") or ""))
    if not name or not tel:
        raise HTTPException(400, "성명과 휴대폰 번호(010…)를 넣어 주세요")
    with db.tx() as con:
        rid, _, _ = _link(con, token)
        now = _current(con, rid)
        if (same := next((p for p in now if p["tel"] == tel), None)):   # 같은 번호로 또 누름 — 그 사람 그대로
            return {"id": same["id"]}
        if len(now) >= MAX_PEOPLE:
            raise HTTPException(409, f"담당자는 {MAX_PEOPLE}명까지입니다. 교대라면 앞 사람을 먼저 빼 주세요")
        at = _now()
        pid = con.execute("INSERT INTO duty_person(rid, rank, name, tel, since) VALUES(?,?,?,?,?)", (rid, rank, name, tel, at)).lastrowid
        con.execute("INSERT INTO duty_log(rid, at, kind, who, memo) VALUES(?,?,?,?,?)", (rid, at, "on", f"{rank} {name}".strip(), ""))
    return {"id": pid}


def leave(token: str, body: dict) -> dict:
    """담당에서 빠짐 — {id}. 지난 담당으로 남는다."""
    _open()
    with db.tx() as con:
        rid, _, _ = _link(con, token)
        p = next((p for p in _current(con, rid) if p["id"] == body.get("id")), None)
        if not p:
            raise HTTPException(404, "지금 담당자가 아닙니다")
        at = _now()
        con.execute("UPDATE duty_person SET until=? WHERE id=?", (at, p["id"]))
        con.execute("INSERT INTO duty_log(rid, at, kind, who, memo) VALUES(?,?,?,?,?)", (rid, at, "off", _who(p), ""))
    return {"ok": True}


def _photo(log_id: int, data_url: str) -> str:
    """화면이 보낸 사진(data URL)을 JPEG 로 다시 써서 둔다 — 그림이 아니면 받지 않는다. 파일 이름."""
    from PIL import Image
    try:
        im = Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[-1])))
        im = im.convert("RGB")
        im.thumbnail((1600, 1600))
    except Exception as e:                                   # noqa: BLE001 — 깨진 그림 · 그림 아닌 것
        raise HTTPException(400, "사진을 읽지 못했습니다") from e
    DIR.mkdir(parents=True, exist_ok=True)
    im.save(DIR / f"{log_id}.jpg", "JPEG", quality=82)
    return f"{log_id}.jpg"


def answer(token: str, body: dict) -> dict:
    """현장 회신 한 줄 — {id 보내는 담당자, action, more: yes|no, memo, photo: data URL}. 고치지 않고 새 줄로 쌓는다."""
    _open()
    action, more = body.get("action"), body.get("more")
    if action not in ACTIONS or more not in ("yes", "no"):
        raise HTTPException(400, "조치 여부와 추가 배치 필요를 골라 주세요")
    with db.tx() as con:
        rid, _, _ = _link(con, token)
        p = next((p for p in _current(con, rid) if p["id"] == body.get("id")), None)
        if not p:
            raise HTTPException(400, "담당자로 등록한 뒤 보내 주세요")
        lid = con.execute("INSERT INTO duty_log(rid, at, kind, who, action, more, memo) VALUES(?,?,?,?,?,?,?)",
                          (rid, _now(), "reply", _who(p), action, more, str(body.get("memo") or "").strip()[:500])).lastrowid
        if body.get("photo"):                                # 사진이 깨졌으면 예외 → 이 줄도 함께 되돌린다
            con.execute("UPDATE duty_log SET photo=? WHERE id=?", (_photo(lid, body["photo"]), lid))
    return {"ok": True}


router = APIRouter()


async def _json(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > MAX_BODY:
        raise HTTPException(413, "사진이 너무 큽니다")
    try:
        body = json.loads(raw)
    except ValueError as e:
        raise HTTPException(400, "잘못된 요청") from e
    return body if isinstance(body, dict) else {}


@router.get("/r/{token}")
async def page(token: str):
    form(token)                                              # 없는 링크면 404
    return FileResponse(PAGE, media_type="text/html", headers={"Cache-Control": "no-store"})


@router.get("/r/{token}/data")
async def page_data(token: str):
    return form(token)


@router.post("/r/{token}")
async def page_answer(token: str, request: Request):
    return answer(token, await _json(request))


@router.post("/r/{token}/join")
async def page_join(token: str, request: Request):
    return join(token, await _json(request))


@router.post("/r/{token}/leave")
async def page_leave(token: str, request: Request):
    return leave(token, await _json(request))


@router.get("/r/{token}/photo/{log_id}")
async def page_photo(token: str, log_id: int):
    with db.tx() as con:
        rid, _, _ = _link(con, token)
        got = con.execute("SELECT photo FROM duty_log WHERE id=? AND rid=?", (log_id, rid)).fetchone()   # 다른 지구 사진은 못 본다
    if not got or not got[0] or not (DIR / got[0]).is_file():
        raise HTTPException(404)
    return FileResponse(DIR / got[0], media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


# 밖에 여는 서버 — /r/ 만 있다(대시보드 API · 연락처 · 설정은 여기 없다)
public_app = FastAPI(title="현장 회신", docs_url=None, redoc_url=None, openapi_url=None)
public_app.include_router(router)


if __name__ == "__main__":
    import os

    import uvicorn

    db.init()
    uvicorn.run(public_app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("GN_REPLY_PORT", "8010")))

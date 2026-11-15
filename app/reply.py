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
ACTIONS = ("done", "doing", "not", "na")           # 예전 회신 화면(한 번에 조치 여부 + 추가 배치) — 기록은 그대로 읽는다
# 단계 스탬프 — 큰 단추 한 번 = 기록 한 줄(kind reply · action). 요청(ask) · 열람(view)은 상황실 · 자동.
# 출동 상태 단추(접수 → 출동 → 도착 → 완료) · 호출 확인(받았다는 것 자체를 한 단계로) · 택배 조회 단계 표를 본떴다
STEPS = (("ask", "요청"), ("view", "열람"), ("ack", "확인"), ("doing", "조치 중"), ("done", "조치 완료"))
SIDE = {"na": "해당 없음", "help": "지원 필요"}
STAMPS = ("ack", "doing", "done", "na", "help", "undo")   # undo = 방금 누른 것 취소(지우지 않고 새 줄로 바로잡는다)
NOTE = "현장 조치 여부를 알려 주세요"
WARN_MIN = 10                                      # 요청하고 이만큼 확인이 없으면 상황실 화면에 경고
MAX_PEOPLE = 2
MAX_BODY = 6 * 1024 * 1024                         # 화면이 사진을 줄여 보낸다(긴 변 1600) — 그래도 넘으면 받지 않는다


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _mobile(tel: str) -> str:
    """문자를 받을 수 있는 번호만(010 …). 아니면 ''."""
    d = re.sub(r"\D", "", tel or "")
    return d if re.fullmatch(r"01\d{8,9}", d) else ""


def _districts() -> dict[str, tuple[str, str, str, str, dict]]:
    """지역ID → (시군, 지구 이름, 주소, 시군 읍면동, 지구 카드{유형 · 대피기준 · 대피장소}) — 위키 우려지역 표(공개 자료), 거기 없으면 연락처 파일(카드 없음)."""
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
                              " ".join(x for x in (w.get("시군"), w.get("읍면동"), w.get("리")) if x),
                              " ".join(x for x in (w.get("시군"), w.get("읍면동")) if x),
                              {k: (w.get(c) or "").strip() for k, c in (("kind", "유형"), ("rule", "대피기준"), ("shelter", "대피장소"))
                               if (w.get(c) or "").strip() not in ("", "–", "-")})
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


def sms_one(name: str, place: str, note: str, url: str) -> str:
    """지구 하나에 고정된 문자 글(상황판단에서 보낼 때) — 화면은 이것을 그대로 쓴다(글을 따로 만들지 않는다). % 같은 숫자는 넣지 않는다."""
    return f"[경남도 재난상황실] {name}({place}) — {note or NOTE}\n{url}"


def ask(rids: list[str], note: str, base: str, preview: bool = False, single: bool = False, info: str = "") -> dict:
    """지구들에 회신 요청 — 지구 링크를 (없으면) 만들고 기록에 요청을 남긴다.
    {people: [{who, tel, names, sms}] 번호마다 문자 하나(맡은 지구 링크를 모아), nophone: [{name, url}] 번호를 모르는 지구, links: [{rid, name, url}]}.
    preview — 요청(ask)을 남기지 않고 글 · 링크만(상황판단 미리보기). 링크는 지구마다 하나라 없으면 만든다(현황 rows 에는 기록이 생겨야 나온다).
    single — 지구마다 따로(같은 번호가 다른 지구를 맡아도 묶지 않는다) · 글은 sms_one. info — 그때의 단계 · %(요청 기록의 more 칸, 현장에는 안 보인다)."""
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
            sigun, name, addr, place, _ = dz[rid]
            con.execute("INSERT OR IGNORE INTO duty_link(rid, token, sigun, name, addr) VALUES(?,?,?,?,?)",
                        (rid, secrets.token_urlsafe(9), sigun, name, addr))
            url = f"{base.rstrip('/')}/r/{con.execute('SELECT token FROM duty_link WHERE rid=?', (rid,)).fetchone()[0]}"
            links.append({"rid": rid, "name": name, "url": url})
            if not preview:
                con.execute("INSERT INTO duty_log(rid, at, kind, who, more, memo) VALUES(?,?,?,?,?,?)",
                            (rid, at, "ask", "상황실", (info or "").strip()[:60] or None, note))
            # 받는 사람 자리 p — 링크에 붙여 누가 눌렀는지 안다(u<id> 현장 등록 담당 · 1 · 2 연락처 파일 담당1 · 2)
            people = [(_who(p), p["tel"], f"u{p['id']}") for p in _current(con, rid)]
            if not people:                                       # 아직 아무도 등록 안 한 지구 — 연락처 파일의 번호로
                r = csvrows.get(rid) or {}
                people = [(r.get(f"담당{i}") or "", t, str(i)) for i in (1, 2)
                          if (t := _mobile(r.get(f"담당{i}_연락처_정규화") or r.get(f"담당{i}_연락처") or ""))]
            for who, tel, pk in people:
                u = f"{url}?p={pk}"
                by_tel.setdefault((tel, rid) if single else tel, {"who": who, "tel": tel, "items": [], "one": sms_one(name, place, note, u)})["items"].append((name, u))
            if not people:
                nophone.append({"name": name, "url": url})
    head = f"[경남도 재난상황실] {note or NOTE}"
    return {"nophone": nophone, "links": links, "people": [
        {"who": p["who"], "tel": p["tel"], "names": [n for n, _ in p["items"]],
         "sms": p["one"] if single else "\n".join([head] + [u if len(p["items"]) == 1 else f"{n} {u}" for n, u in p["items"]])}
        for p in by_tel.values()]}


def _mins(a: str, b: str) -> int:
    f = "%Y-%m-%d %H:%M"
    return int((datetime.strptime(b, f) - datetime.strptime(a, f)).total_seconds() // 60)


def _mask(who: str, more: str | None) -> str:
    """연락처 파일에서 온 이름(more = csv1 · csv2) — 링크 페이지에서는 '담당자' · '담당자 2' 로만(링크는 넘겨질 수 있다)."""
    return {"csv1": "담당자", "csv2": "담당자 2"}.get(more or "", who)


def rounds(con, rid: str, n: int = 5, now: str | None = None, mask: bool = False) -> list[dict]:
    """진행 기록을 요청마다 묶은 단계 표 — 새 요청부터 n 개. 화면 셋(r.html · reply.html · 상황판단)은 이것을 그리기만 한다.
    {ask: {at, memo, info} | None(요청 없이 쌓인 것), steps: [{k, label, t, who, plus, st: done|skip|next|todo}], ev: [...], now, side, warn}
    예전 회신(action done · doing · not · na + more)도 읽는다 — '아직'은 받아 봤다(확인)로, more=yes 는 지원 필요로."""
    now = now or _now()
    out: list[dict] = []
    cur = None
    for lid, at, kind, who, action, more, memo, photo in con.execute(
            "SELECT id, at, kind, who, action, more, memo, photo FROM duty_log WHERE rid=? ORDER BY id", (rid,)):
        if kind == "ask":
            cur = {"ask": {"at": at, "memo": memo or NOTE, "info": more}, "ev": []}
            out.append(cur)
            continue
        if cur is None:
            cur = {"ask": None, "ev": []}
            out.append(cur)
        e = {"id": lid, "at": at, "who": _mask(who, more) if mask else who, "memo": memo or "", "photo": bool(photo)}
        if kind == "view":
            cur["ev"].append({**e, "k": "view", "who": ""})
        elif kind in ("on", "off", "note"):
            cur["ev"].append({**e, "k": kind})
        elif kind == "reply" and action == "undo":
            last = next((x for x in reversed(cur["ev"]) if x["k"] in STAMPS[:-1] and not x.get("x") and x["who"] == who), None)
            if last:
                last["x"] = True                                 # 취소된 스탬프 — 줄은 남고 단계에서만 빠진다
            cur["ev"].append({**e, "k": "undo", "of": last and last["k"]})
        elif kind == "reply":
            cur["ev"].append({**e, "k": {"not": "ack"}.get(action, action)})
            if more == "yes":
                cur["ev"].append({**e, "k": "help", "memo": "", "photo": False})
    for r in out:
        a = r["ask"]
        live = [x for x in r["ev"] if not x.get("x")]
        first = {k: next((x for x in live if x["k"] == k), None) for k, _ in STEPS[1:]}
        top = max([i for i, (k, _) in enumerate(STEPS) if first.get(k)] + [0 if a else -1])
        r["steps"] = []
        for i, (k, lab) in enumerate(STEPS):
            x = {"at": a["at"], "who": "상황실"} if k == "ask" and a else first.get(k)
            st = "done" if x else "skip" if i < top else "next" if i == top + 1 else "todo"
            r["steps"].append({"k": k, "label": lab, "st": st, "who": (x or {}).get("who", ""),
                               "t": _t(x["at"], a and a["at"]) if x else "", "plus": _mins(a["at"], x["at"]) if x and a else None})
        r["now"] = STEPS[top][1] if top >= 0 else "요청 없음"
        r["side"] = [SIDE[k] for k in SIDE if any(x["k"] == k for x in live)]
        r["warn"] = None
        if a and top < 2 and (m := _mins(a["at"], now)) >= WARN_MIN:
            r["warn"] = {"min": m, "text": f"{m}분째 확인 없음" + (" (열람함)" if top == 1 else "")}
        for x in r["ev"]:
            x["t"] = _t(x["at"], a and a["at"])
            x["plus"] = _mins(a["at"], x["at"]) if a else None
            x["label"] = dict(STEPS).get(x["k"]) or SIDE.get(x["k"]) or {"on": "담당자로 등록", "off": "담당에서 빠짐", "note": "덧붙임",
                                                                      "undo": f"취소 — {dict(STEPS, **SIDE).get(x.get('of'), '')}"}.get(x["k"], x["k"])
    return out[::-1][:n]


def _t(at: str, base: str | None) -> str:
    """HH:MM — 요청한 날과 다르면 날짜도."""
    return at[11:16] if base and at[:10] == base[:10] else f"{int(at[5:7])}.{int(at[8:10])}. {at[11:16]}"


def rows() -> list[dict]:
    """상황실 현황 — 링크가 있는 지구마다: 지금 담당 · 마지막 요청 · 마지막 회신. 이름 · 번호가 들어 있다(잠금 번호 뒤에서만)."""
    out = []
    with db.tx() as con:
        for rid, token, name, addr in con.execute("SELECT rid, token, name, addr FROM duty_link").fetchall():
            last = {k: con.execute("SELECT id, at, who, action, more, memo, photo FROM duty_log WHERE rid=? AND kind IN (?, ?)"
                                   " ORDER BY id DESC LIMIT 1", (rid, k, "note" if k == "reply" else k)).fetchone() for k in ("ask", "reply")}
            a, r = last["ask"], last["reply"]
            if not a and not r and not _current(con, rid):    # 미리보기로 링크만 생긴 지구 — 요청 · 회신 · 담당이 생기면 나온다
                continue
            rd = rounds(con, rid, 1)
            out.append({"rid": rid, "token": token, "name": name, "addr": addr, "round": rd[0] if rd else None,
                        "people": [{"who": _who(p), "tel": p["tel"]} for p in _current(con, rid)],
                        "asked_at": a and a[1], "note": a and a[5], "info": a and a[4],
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
        rd = rounds(con, rid, mask=True)
        for r in rd:
            if r["ask"]:
                r["ask"].pop("info")                             # 그때의 단계 · % 는 상황실 기록에만 — 현장에는 요청 문구만
        return {"name": name, "addr": addr, "card": (_districts().get(rid) or ("", "", "", "", {}))[4], "max": MAX_PEOPLE,
                "people": _current(con, rid), "rounds": rd,
                "now": _now(), "warn_min": WARN_MIN,
                "past": [{"rank": r[0], "name": r[1], "since": r[2], "until": r[3]} for r in con.execute(
                    "SELECT rank, name, since, until FROM duty_person WHERE rid=? AND until IS NOT NULL ORDER BY id DESC LIMIT 20", (rid,))],
                "log": [{"id": r[0], "at": r[1], "kind": r[2], "who": _mask(r[3], r[5]), "action": r[4],
                         "more": None if r[2] == "ask" or r[5] in ("csv1", "csv2") else r[5], "memo": r[6], "photo": bool(r[7])}
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


def seen(token: str) -> dict:
    """열람 — 링크를 연 때, 요청마다 한 번(이름 없이). 상황판단 미리보기(?pv=1) · 상황실 현황에서 연 것은 화면이 부르지 않는다."""
    _open()
    with db.tx() as con:
        rid, _, _ = _link(con, token)
        last = con.execute("SELECT kind FROM duty_log WHERE rid=? AND kind IN ('ask', 'view') ORDER BY id DESC LIMIT 1", (rid,)).fetchone()
        if last and last[0] == "ask":
            con.execute("INSERT INTO duty_log(rid, at, kind, who, memo) VALUES(?,?,?,?,?)", (rid, _now(), "view", "", ""))
            return {"ok": True, "new": True}
    return {"ok": True, "new": False}


def _actor(con, rid: str, body: dict) -> tuple[str, str | None]:
    """누가 눌렀나 → (who, more). 등록 없이 누른다 — 문자를 받은 사람이 그 지구 담당자(사용자 결정 2026-11-15).
    이 휴대폰에서 등록한 사람(id) → 링크의 받는 사람 자리 p(u<id> 등록 담당 · 1 · 2 연락처 파일 담당1 · 2, more=csv1 · csv2 로 표시) → '담당자'."""
    p = next((p for p in _current(con, rid) if p["id"] == body.get("id")), None)
    if p:
        return _who(p), None
    pk = str(body.get("p") or "")
    if pk[:1] == "u" and pk[1:].isdigit():
        got = con.execute("SELECT rank, name FROM duty_person WHERE id=? AND rid=?", (int(pk[1:]), rid)).fetchone()
        if got:
            return f"{got[0]} {got[1]}".strip(), None
    if pk in ("1", "2"):
        from . import contacts
        nm = ((contacts._rows().get(rid) or {}).get(f"담당{pk}") or "").strip()
        if nm and nm not in ("–", "-"):
            return nm, f"csv{pk}"
    return "담당자", None


def stamp(token: str, body: dict) -> dict:
    """단계 스탬프 — {id 이 휴대폰에서 등록한 담당(없어도 됨), p 받는 사람 자리, step}. 단추 한 번 = 한 줄. 메모 · 사진은 note 로 덧붙인다."""
    _open()
    step = body.get("step")
    if step not in STAMPS:
        raise HTTPException(400, "모르는 단계입니다")
    with db.tx() as con:
        rid, _, _ = _link(con, token)
        who, more = _actor(con, rid, body)
        at = _now()
        con.execute("INSERT INTO duty_log(rid, at, kind, who, action, more, memo) VALUES(?,?,?,?,?,?,?)", (rid, at, "reply", who, step, more, ""))
    return {"ok": True, "at": at}


def note(token: str, body: dict) -> dict:
    """스탬프 뒤에 덧붙이는 말 · 사진 — {id, p, memo, photo}. 둘 중 하나는 있어야 한다."""
    _open()
    memo = str(body.get("memo") or "").strip()[:500]
    if not memo and not body.get("photo"):
        raise HTTPException(400, "덧붙일 말이나 사진을 넣어 주세요")
    with db.tx() as con:
        rid, _, _ = _link(con, token)
        who, more = _actor(con, rid, body)
        lid = con.execute("INSERT INTO duty_log(rid, at, kind, who, more, memo) VALUES(?,?,?,?,?,?)", (rid, _now(), "note", who, more, memo)).lastrowid
        if body.get("photo"):
            con.execute("UPDATE duty_log SET photo=? WHERE id=?", (_photo(lid, body["photo"]), lid))
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


@router.post("/r/{token}/seen")
async def page_seen(token: str):
    return seen(token)


@router.post("/r/{token}/stamp")
async def page_stamp(token: str, request: Request):
    return stamp(token, await _json(request))


@router.post("/r/{token}/note")
async def page_note(token: str, request: Request):
    return note(token, await _json(request))


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

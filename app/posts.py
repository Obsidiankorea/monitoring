"""공지 · 요청 게시판 — 공지(관리자가 쓴다, '팝업'이면 지도를 열 때 한 번 뜬다) · 요청(누구나 — 고칠 것 · 바랄 것).

저장소가 공개(GitHub)라 요청은 서버에만 둔다. 관리자가 읽고 'GitHub 이슈로'를 누르면 내용이 채워진 이슈 쓰기 창이 열린다
(사람이 보고 다듬어 올린다 — 토큰도 자동 올림도 없다). 지우기는 숨김(gone)으로 — 기록은 남긴다.
"""
from __future__ import annotations

from datetime import datetime

from . import db

KINDS = ("notice", "request")
STATUS = {"open": "접수", "doing": "작업 중", "done": "반영함", "no": "보류"}
COLS = "id, kind, title, body, author, created, status, reply, popup, updated"


def _row(r) -> dict:
    d = dict(zip([c.strip() for c in COLS.split(",")], r))
    d["popup"] = bool(d["popup"])
    d["status_name"] = STATUS.get(d["status"], d["status"])
    return d


def all_posts() -> dict:
    with db.tx() as con:
        rows = [_row(r) for r in con.execute(f"SELECT {COLS} FROM post WHERE gone=0 ORDER BY id DESC LIMIT 300").fetchall()]
    return {k: [r for r in rows if r["kind"] == k] for k in KINDS} | {"status": STATUS}


def popups() -> list[dict]:
    with db.tx() as con:
        return [_row(r) for r in con.execute(f"SELECT {COLS} FROM post WHERE gone=0 AND kind='notice' AND popup=1 ORDER BY id DESC LIMIT 5")]


def add(kind: str, title: str, body: str, author: str, popup: bool = False) -> dict:
    if kind not in KINDS:
        raise ValueError("kind — notice · request")
    title, body = (title or "").strip()[:100], (body or "").strip()[:4000]
    if not title:
        raise ValueError("제목을 쓰세요")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    with db.tx() as con:
        cur = con.execute("INSERT INTO post(kind, title, body, author, created, updated, popup) VALUES(?,?,?,?,?,?,?)",
                          (kind, title, body, author[:40], now, now, int(bool(popup) and kind == "notice")))
        return _row(con.execute(f"SELECT {COLS} FROM post WHERE id=?", (cur.lastrowid,)).fetchone())


def update(pid: int, data: dict) -> dict:
    """관리자 — title · body · status · reply · popup 중 온 것만. gone=True 면 숨긴다."""
    sets, vals = [], []
    for k, n in (("title", 100), ("body", 4000), ("reply", 2000)):
        if k in data:
            sets.append(f"{k}=?"); vals.append(str(data[k] or "").strip()[:n])
    if "status" in data:
        if data["status"] not in STATUS:
            raise ValueError("status — " + " · ".join(STATUS))
        sets.append("status=?"); vals.append(data["status"])
    for k in ("popup", "gone"):
        if k in data:
            sets.append(f"{k}=?"); vals.append(int(bool(data[k])))
    if not sets:
        raise ValueError("바꿀 것이 없다")
    sets.append("updated=?"); vals.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
    with db.tx() as con:
        if not con.execute(f"UPDATE post SET {', '.join(sets)} WHERE id=?", (*vals, pid)).rowcount:
            raise KeyError(pid)
        return _row(con.execute(f"SELECT {COLS} FROM post WHERE id=?", (pid,)).fetchone())

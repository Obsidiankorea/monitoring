"""호우 사건 묶음 — 호우 하나를 시작~끝, 걸린 특보, 단계가 바뀐 이력, 그 사이의 판단 기록으로 묶는다(재난 온톨로지 로드맵 4단계).

5분마다 aiwatch.run 이 record() 를 부른다.
  · 열림: 경남 육상에 호우 · 태풍 특보가 있거나, 기준에 가까워진 곳(aiwatch._scan)이 하나라도 있으면
  · 닫힘: 둘 다 없는 채로 QUIET_H 시간이 지나면 — 끝 시각은 마지막으로 무언가 있던 때
  · 단계 이력(stage_log): 처음 그 단계에 이르렀거나 근접 → 충족으로 오른 때만 한 줄(30분 안에 내렸다 오른 것은 다시 적지 않는다 — aiwatch._diff)
판단 기록(decision 표)은 따로 묶지 않고 사건의 시작~끝 사이 것을 읽는다.
"""
from __future__ import annotations

import json
from datetime import datetime

from . import db

QUIET_H = 6


def alert_names(groups: list[dict]) -> list[str]:
    return sorted({g["name"] for g in groups or [] if not g.get("sea") and g.get("name", "").startswith(("호우", "태풍"))})


def _iso(t: datetime) -> str:
    return t.isoformat(timespec="seconds")


def record(now: datetime, groups: list[dict], hits: bool, new: list, pct: dict | None = None) -> int | None:
    """한 번 훑은 결과를 사건에 적는다 → 열린 사건 번호(없으면 None). new = [(상태, (시군, 읍면동, 유형, 단계, 기준))]."""
    names, at = alert_names(groups), _iso(now)
    with db.tx() as con:
        ev = con.execute("SELECT * FROM event WHERE end IS NULL ORDER BY id DESC LIMIT 1").fetchone()
        if names or hits:
            if ev:
                con.execute("UPDATE event SET last=?, alerts=? WHERE id=?",
                            (at, json.dumps(sorted(set(json.loads(ev["alerts"])) | set(names)), ensure_ascii=False), ev["id"]))
                eid = ev["id"]
            else:
                eid = con.execute("INSERT INTO event(start, last, alerts) VALUES(?,?,?)", (at, at, json.dumps(names, ensure_ascii=False))).lastrowid
        elif ev and (now - datetime.fromisoformat(ev["last"])).total_seconds() >= QUIET_H * 3600:
            con.execute("UPDATE event SET end=last WHERE id=?", (ev["id"],))
            return None
        else:
            eid = ev["id"] if ev else None
        if eid:
            con.executemany("INSERT INTO stage_log(event, at, sigun, emd, fam, stage, st, rule, pct) VALUES(?,?,?,?,?,?,?,?,?)",
                            [(eid, at, x[0], x[1], x[2], x[3], st, x[4], (pct or {}).get(i)) for i, (st, x) in enumerate(new) if x[2] != "비상단계"])
    return eid


def _span(ev) -> tuple[str, str]:
    return ev["start"], ev["end"] or "9999"


def listing(limit: int = 30) -> list[dict]:
    """사건 목록 — 새것부터. 단계 이력 · 판단 기록 건수와 걸린 시군."""
    with db.tx() as con:
        out = []
        for ev in con.execute("SELECT * FROM event ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)):
            a, b = _span(ev)
            lg = con.execute("SELECT COUNT(*) n, GROUP_CONCAT(DISTINCT sigun) sg FROM stage_log WHERE event=?", (ev["id"],)).fetchone()
            dn = con.execute("SELECT COUNT(*) FROM decision WHERE at>=? AND at<=?", (a, b)).fetchone()[0]
            out.append({"id": ev["id"], "start": ev["start"], "end": ev["end"], "last": ev["last"], "alerts": json.loads(ev["alerts"]),
                        "log": lg["n"], "siguns": (lg["sg"] or "").split(",") if lg["sg"] else [], "decisions": dn})
    return out


def detail(eid: int) -> dict | None:
    """사건 하나 — 단계 이력과 판단 기록을 시각 순으로 한 줄에(kind = stage · decision)."""
    with db.tx() as con:
        ev = con.execute("SELECT * FROM event WHERE id=?", (eid,)).fetchone()
        if not ev:
            return None
        a, b = _span(ev)
        rows = [{"kind": "stage", **dict(r)} for r in con.execute("SELECT * FROM stage_log WHERE event=?", (eid,))]
        rows += [{"kind": "decision", **dict(r)} for r in con.execute("SELECT * FROM decision WHERE at>=? AND at<=?", (a, b))]
    rows.sort(key=lambda r: (r["at"], r["kind"]))
    return {"id": ev["id"], "start": ev["start"], "end": ev["end"], "last": ev["last"], "alerts": json.loads(ev["alerts"]), "rows": rows}

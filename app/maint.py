"""저장공간 살피기와 정리.

자료는 두 군데에 쌓인다 — SQLite 파일 하나(`data/gnweather.db`)와
예측 분포 이미지 캐시(`data/cache/qpf/`). 이미지가 훨씬 빨리 자란다.
한 발표분이 수십 장이고 10분마다 새 발표분이 나오기 때문이다.

⚠️ **오늘 것을 지우지 않는다.** 보관 기간을 아무리 짧게 잡아도 최소 하루는 남긴다.
   화면이 보고 있는 구간을 지워 버리면 그래프가 통째로 빈다.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from . import db
from .config import CACHE, DB_PATH

log = logging.getLogger("maint")

#: 기본 보관 기간. 관측·예측은 날 수로, 예측 이미지는 발표분 수로 센다
#: (이미지는 시각보다 '몇 발표분'이 뜻이 통한다 — qpf 설정과 같은 단위).
RETENTION_DEFAULT = {"obs_days": 30, "log_days": 30, "auto": True}
DAY_CHOICES = (3, 7, 14, 30, 60, 90, 0)      # 0 = 지우지 않음

#: 날짜로 잘라내는 표 — (표, 시각칸). 시각칸은 'YYYY-MM-DD …' 로 시작한다.
_AGED = (("obs_hourly", "tm"), ("obs_minute", "tm"),
         ("bangjae_hourly", "tm"), ("bangjae_rain", "tm"))


def cfg() -> dict:
    c = dict(RETENTION_DEFAULT)
    c.update(db.get_setting("retention", {}) or {})
    return c


def put_cfg(body: dict) -> dict:
    c = cfg()
    if "obs_days" in body:
        v = int(body["obs_days"])
        if v not in DAY_CHOICES:
            raise ValueError(f"보관 기간은 {DAY_CHOICES} 중 하나여야 한다")
        c["obs_days"] = v
    if "log_days" in body:
        c["log_days"] = max(0, int(body["log_days"]))
    if "auto" in body:
        c["auto"] = bool(body["auto"])
    db.put_setting("retention", c)
    return c


def _dir_bytes(p) -> tuple[int, int]:
    """(바이트, 파일 수). 없는 폴더는 (0, 0)."""
    if not p.exists():
        return 0, 0
    n = tot = 0
    for f in p.rglob("*"):
        if f.is_file():
            tot += f.stat().st_size
            n += 1
    return tot, n


def usage() -> dict:
    """지금 얼마나 쓰고 있는지. 화면 설정창이 이걸 그대로 보여 준다."""
    dbf = DB_PATH
    db_bytes = dbf.stat().st_size if dbf.exists() else 0
    # WAL 은 별도 파일이다. 빼먹으면 실제보다 작게 보인다.
    for suf in ("-wal", "-shm"):
        w = dbf.with_name(dbf.name + suf)
        if w.exists():
            db_bytes += w.stat().st_size

    img_bytes, img_files = _dir_bytes(CACHE / "qpf")

    tables = []
    with db.tx() as con:
        for t, col in _AGED + (("fcst_rn1", None), ("qpf_frame", None),
                               ("snapshot", None), ("collect_log", None)):
            try:
                n = con.execute(f"SELECT COUNT(*) c FROM {t}").fetchone()["c"]
            except Exception:                        # noqa: BLE001 — 아직 없는 표
                continue
            span = None
            if col:
                r = con.execute(f"SELECT MIN({col}) a, MAX({col}) b FROM {t}").fetchone()
                if r and r["a"]:
                    span = [r["a"][:16], r["b"][:16]]
            tables.append({"table": t, "rows": n, "span": span})
        tmfcs = [r["tmfc"] for r in con.execute(
            "SELECT DISTINCT tmfc FROM qpf_frame ORDER BY tmfc DESC")]

    return {"db_bytes": db_bytes, "img_bytes": img_bytes, "img_files": img_files,
            "total_bytes": db_bytes + img_bytes,
            "tables": tables, "qpf_tmfc": len(tmfcs),
            "retention": cfg()}


def cleanup(obs_days: int | None = None, now: datetime | None = None,
            vacuum: bool = True) -> dict:
    """보관 기간이 지난 것을 지운다. 지운 줄 수와 되찾은 바이트를 돌려준다.

    되돌릴 수 없다 — 그래서 기본값이 30일이고, 하루 미만으로는 못 줄인다.
    """
    now = now or datetime.now()
    c = cfg()
    days = int(obs_days if obs_days is not None else c["obs_days"])
    before = usage()

    removed: dict[str, int] = {}
    if days > 0:
        cut = (now - timedelta(days=max(1, days))).strftime("%Y-%m-%d %H:%M")
        with db.tx() as con:
            for t, col in _AGED:
                try:
                    cur = con.execute(f"DELETE FROM {t} WHERE {col} < ?", (cut,))
                except Exception as e:               # noqa: BLE001
                    log.warning("%s 정리 실패: %s", t, e)
                    continue
                if cur.rowcount:
                    removed[t] = cur.rowcount
            # 예측은 발표시각이 'YYYYMMDDHHMI' 라 형식이 다르다
            cur = con.execute("DELETE FROM fcst_rn1 WHERE tmfc < ?",
                              ((now - timedelta(days=max(1, days))).strftime("%Y%m%d%H%M"),))
            if cur.rowcount:
                removed["fcst_rn1"] = cur.rowcount

    ld = int(c.get("log_days", 30))
    if ld > 0:
        with db.tx() as con:
            cur = con.execute("DELETE FROM snapshot WHERE fetched_at < ?",
                              ((now - timedelta(days=max(1, ld))).strftime("%Y-%m-%d %H:%M"),))
            if cur.rowcount:
                removed["snapshot"] = cur.rowcount

    # 예측 이미지는 qpf 설정(발표분 수)이 주인이다. 여기서는 그 규칙을 한 번 더 돌린다 —
    # DB 에는 없는데 폴더만 남은 고아 폴더를 같이 치운다.
    from .collectors import qpf
    qpf._prune(int(qpf.cfg().get("keep", 3)))
    with db.tx() as con:
        alive = {r["tmfc"] for r in con.execute("SELECT DISTINCT tmfc FROM qpf_frame")}
    orphan = 0
    d = CACHE / "qpf"
    if d.exists():
        for sub in d.iterdir():
            if sub.is_dir() and sub.name not in alive:
                for f in sub.iterdir():
                    f.unlink()
                sub.rmdir()
                orphan += 1

    if vacuum:
        # ⚠️ VACUUM 은 트랜잭션 안에서 못 돈다. tx() 를 쓰면 안 된다.
        con = db.connect()
        try:
            con.execute("VACUUM")
        finally:
            con.close()

    after = usage()
    return {"removed": removed, "orphan_dirs": orphan,
            "freed_bytes": max(0, before["total_bytes"] - after["total_bytes"]),
            "before": before["total_bytes"], "after": after["total_bytes"],
            "usage": after}

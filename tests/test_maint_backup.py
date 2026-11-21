"""A5 — 새벽마다 DB 한 벌(sqlite backup), 최근 둘만 남긴다."""
from datetime import datetime


def test_backup_keeps_two(tdb):
    from app import maint
    with tdb.tx() as con:
        con.execute("INSERT INTO decision(at, sigun, act) VALUES('2026-11-18T00:00:00','창원','메모')")
    for d in (16, 17, 18):
        maint.backup(datetime(2026, 11, d, 3, 0))
    files = sorted(p.name for p in (tdb.DB_PATH.parent / "backup").glob("*.db"))
    assert files == ["gnweather-20261117.db", "gnweather-20261118.db"]
    import sqlite3
    c = sqlite3.connect(tdb.DB_PATH.parent / "backup" / files[-1])
    assert c.execute("SELECT COUNT(*) FROM decision").fetchone()[0] == 1
    c.close()

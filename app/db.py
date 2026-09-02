"""SQLite 저장소.

핵심은 quality 열이다. rn_hr1=0(무강수) / NULL(결측) / 'fetch_failed'(조회 실패)를
한 열로 구분한다. 이게 없으면 화면에서 셋을 갈라 그릴 수 없고, 감시기가 실패를
'비 안 옴'으로 읽어 헛알림을 낸다(pitfalls ★1).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Any, Iterator

from .config import DB_PATH

SCHEMA = """
PRAGMA journal_mode=WAL;

-- 정시 관측. 기간 누적·다우지점 산출의 유일한 출처.
CREATE TABLE IF NOT EXISTS obs_hourly (
  stn        TEXT NOT NULL,
  tm         TEXT NOT NULL,           -- 'YYYY-MM-DD HH:00' KST 정시
  rn_hr1     REAL,                    -- 그 시각까지 1시간 강수량. NULL 허용
  rn_day     REAL,                    -- 당일 누적(00시 값 = 전날 총량)
  ta         REAL,
  quality    TEXT NOT NULL,           -- 'ok' | 'missing' | 'fetch_failed'
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (stn, tm)
);
CREATE INDEX IF NOT EXISTS idx_obs_tm ON obs_hourly(tm);

-- 정시 이후 구간 보강(매분자료). 정시 자료를 덮어쓰지 않는다.
CREATE TABLE IF NOT EXISTS obs_minute (
  stn TEXT NOT NULL, tm TEXT NOT NULL,   -- 'YYYY-MM-DD HH:MM'
  rn_60m REAL, rn_day REAL,
  quality TEXT NOT NULL, fetched_at TEXT NOT NULL,
  PRIMARY KEY (stn, tm)
);
CREATE INDEX IF NOT EXISTS idx_min_tm ON obs_minute(tm);

-- 초단기예측 RN1. 발표(tmfc)와 대상(tmef)이 둘 다 키다.
-- ⚠️ RN1은 선행 1시간 누적이라 같은 tmfc 안에서 tmef가 달라도 값이 겹칠 수 있다.
--    구간마다 한 번씩만 저장한다.
CREATE TABLE IF NOT EXISTS fcst_rn1 (
  tmfc TEXT NOT NULL,                  -- 'YYYYMMDDHHMM'
  tmef TEXT NOT NULL,
  sigun TEXT NOT NULL,
  emd   TEXT NOT NULL,
  rn1   REAL NOT NULL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (tmfc, tmef, sigun, emd)
);
CREATE INDEX IF NOT EXISTS idx_fcst ON fcst_rn1(tmfc, tmef);

-- 자료 스냅샷(특보처럼 통째로 저장하는 것). payload는 정규화된 JSON.
CREATE TABLE IF NOT EXISTS snapshot (
  kind       TEXT NOT NULL,            -- 'alerts'
  base_time  TEXT NOT NULL,
  fetched_at TEXT NOT NULL,
  payload    TEXT NOT NULL,
  PRIMARY KEY (kind, base_time)
);

-- 수집 이력. 화면의 '수집 14:20'과 실패 표시가 여기서 나온다.
CREATE TABLE IF NOT EXISTS collect_log (
  kind       TEXT PRIMARY KEY,         -- 'rain' | 'forecast' | 'alerts' | 'qpf'
  ok_at      TEXT,                     -- 마지막 성공
  tried_at   TEXT,                     -- 마지막 시도
  ok         INTEGER NOT NULL DEFAULT 0,
  detail     TEXT
);

-- 예측 분포 이미지. 파일은 data/cache 에 두고 여기에는 목록만.
CREATE TABLE IF NOT EXISTS qpf_frame (
  tmfc TEXT NOT NULL, ef INTEGER NOT NULL,
  path TEXT NOT NULL, bytes INTEGER NOT NULL, fetched_at TEXT NOT NULL,
  PRIMARY KEY (tmfc, ef)
);
"""


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


@contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    con = connect()
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tx() as con:
        con.executescript(SCHEMA)


def log_collect(kind: str, ok: bool, at: str, detail: str = "") -> None:
    """성공만 ok_at 을 옮긴다 — 실패해도 마지막 정상 시각은 남아 있어야 한다."""
    with tx() as con:
        con.execute(
            """INSERT INTO collect_log(kind, ok_at, tried_at, ok, detail)
               VALUES(?, ?, ?, ?, ?)
               ON CONFLICT(kind) DO UPDATE SET
                 tried_at=excluded.tried_at, ok=excluded.ok, detail=excluded.detail,
                 ok_at=CASE WHEN excluded.ok=1 THEN excluded.ok_at ELSE collect_log.ok_at END""",
            (kind, at if ok else None, at, 1 if ok else 0, detail[:300]),
        )


def put_snapshot(kind: str, base_time: str, fetched_at: str, payload: Any) -> None:
    with tx() as con:
        con.execute(
            "INSERT OR REPLACE INTO snapshot(kind, base_time, fetched_at, payload) VALUES(?,?,?,?)",
            (kind, base_time, fetched_at, json.dumps(payload, ensure_ascii=False)),
        )


def latest_snapshot(kind: str) -> dict | None:
    with tx() as con:
        r = con.execute(
            "SELECT base_time, fetched_at, payload FROM snapshot WHERE kind=? ORDER BY base_time DESC LIMIT 1",
            (kind,),
        ).fetchone()
    if not r:
        return None
    return {"base_time": r["base_time"], "fetched_at": r["fetched_at"], "data": json.loads(r["payload"])}

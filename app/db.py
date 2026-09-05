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

-- 스방(경남 스마트 통합 방재시스템) 시군별 **평균** 강수량.
-- ⚠️ 기상청 대표지점 값(obs_hourly)과 **뜻이 다르다** — 관측망이 달라 값도 다르다.
--    그래서 같은 표에 섞지 않고 따로 쌓는다. 화면에서도 출처를 밝혀야 한다.
-- 스방이 주는 건 '기간 누적'이라 기간(fr~to, hour)을 같이 남긴다.
CREATE TABLE IF NOT EXISTS bangjae_rain (
  tm         TEXT NOT NULL,           -- 'YYYY-MM-DD HH:MM' **자료가 담고 있는** 시각
  sigun      TEXT NOT NULL,           -- '창원시' 꼴(스방 표기 그대로)
  mm         REAL NOT NULL,           -- 그 기간 시군 평균 강수량
  daw_name   TEXT,                    -- 그 시군 다우지점 이름(비 안 오면 NULL)
  daw_mm     REAL,                    -- 다우지점 강수량
  fr         TEXT NOT NULL,           -- 기간 시작 'YYYYMMDD'
  to_date    TEXT NOT NULL,           -- 기간 끝
  hour       INTEGER NOT NULL,        -- 조회에 쓴 toTime(0~23)
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (tm, sigun)
);
CREATE INDEX IF NOT EXISTS idx_bj_tm ON bangjae_rain(tm);

-- 자료 스냅샷(특보처럼 통째로 저장하는 것). payload는 정규화된 JSON.
-- 스방 지점별 **시간강우량**(dt096). 기상청 obs_hourly 와 나란히 놓고 쓴다.
-- ⚠️ tm 은 **스방 시각 그대로**다. 스방의 'H시'는 H:00~H:59(앞으로 한 시간),
--    기상청의 'H시'는 (H-1):00~H:00(뒤로 한 시간)이라 **한 칸 어긋난다.**
--    맞춰 끼우는 일은 읽을 때(queries) 한다 — 여기서 미리 밀어 두면
--    나중에 원본이 뭐였는지 알 수 없게 된다.
CREATE TABLE IF NOT EXISTS bangjae_hourly (
  tm         TEXT NOT NULL,           -- 'YYYY-MM-DD HH:00' (스방 시각)
  stn        TEXT NOT NULL,           -- 스방 장치코드 lnk_id. 기상청 지점은 그 지점번호가 그대로 온다
  name       TEXT NOT NULL,
  sigun      TEXT NOT NULL,           -- 관제순 짧은 이름('창원')으로 맞춰 넣는다
  mm         REAL,                    -- 결측은 NULL. 무강수 0.0 과 다르다
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (tm, stn)
);
CREATE INDEX IF NOT EXISTS idx_bjh_tm ON bangjae_hourly(tm);

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

-- 설정. 벽면 화면이라 브라우저가 아니라 서버에 둔다 — 어느 화면에서 바꿔도 같이 간다.
CREATE TABLE IF NOT EXISTS setting (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

-- 발표 감지 이력. 실제 지연을 쌓아 두면 감시 구간을 추측이 아니라 실측으로 잡을 수 있다.
CREATE TABLE IF NOT EXISTS qpf_publish (
  tmfc TEXT PRIMARY KEY,
  detected_at TEXT NOT NULL,
  delay_min REAL NOT NULL
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


# 이미 만들어진 표에 뒤늦게 붙인 칸. CREATE TABLE IF NOT EXISTS 로는 안 늘어난다.
# (칸, 형) — 없으면 ALTER 로 붙인다. 있으면 조용히 넘어간다.
_ADDED_COLUMNS = {
    "bangjae_rain": [("daw_name", "TEXT"), ("daw_mm", "REAL")],
    # 15분 강수량 — '지금 어디에 쏟아지고 있나'는 이 값이 제일 빨리 말해 준다.
    # 60분치는 이미 지나간 한 시간을 담고 있어 한 박자 늦다.
    "obs_minute": [("rn_15m", "REAL")],
}


def init() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with tx() as con:
        con.executescript(SCHEMA)
        for table, cols in _ADDED_COLUMNS.items():
            have = {r[1] for r in con.execute(f"PRAGMA table_info({table})")}
            for name, typ in cols:
                if name not in have:
                    con.execute(f"ALTER TABLE {table} ADD COLUMN {name} {typ}")


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


def get_setting(key: str, default):
    with tx() as con:
        r = con.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
    if not r:
        return default
    try:
        v = json.loads(r["value"])
    except json.JSONDecodeError:
        return default
    # 저장된 것이 dict면 기본값 위에 덮어쓴다 — 새 항목이 생겨도 옛 설정이 막지 않는다
    if isinstance(default, dict) and isinstance(v, dict):
        return {**default, **v}
    return v


def put_setting(key: str, value) -> None:
    with tx() as con:
        con.execute("INSERT OR REPLACE INTO setting(key, value) VALUES(?,?)",
                    (key, json.dumps(value, ensure_ascii=False)))


def note_publish(tmfc: str, detected_at: str, delay_min: float) -> None:
    with tx() as con:
        con.execute("INSERT OR IGNORE INTO qpf_publish(tmfc, detected_at, delay_min) VALUES(?,?,?)",
                    (tmfc, detected_at, delay_min))


def publish_stats(limit: int = 60) -> dict:
    """최근 발표 지연 통계. 감시 구간을 실측으로 좁히는 근거가 된다."""
    with tx() as con:
        rows = [r["delay_min"] for r in con.execute(
            "SELECT delay_min FROM qpf_publish ORDER BY tmfc DESC LIMIT ?", (limit,))]
    if not rows:
        return {"n": 0}
    rows.sort()
    return {"n": len(rows), "min": rows[0], "max": rows[-1],
            "p50": rows[len(rows) // 2], "p90": rows[int(len(rows) * 0.9)]}

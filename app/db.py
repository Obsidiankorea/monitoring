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

-- 단기예보 격자(nph-dfs_shrt_grd). 권역·시군 예보 판의 출처.
-- 격자 칸(x, y)마다 한 줄 — 권역을 어떻게 묶든 읽을 때 다시 모을 수 있게 칸째로 둔다.
-- var: 지금은 'PCP'(1시간 강수량)만 받는다. 요소가 늘어도 표를 안 바꾸게 칸을 둔다. val NULL = 결측.
CREATE TABLE IF NOT EXISTS fcst_short (
  tmfc TEXT NOT NULL,                  -- 'YYYYMMDDHH' 발표
  tmef TEXT NOT NULL,                  -- 'YYYYMMDDHH' 대상
  var  TEXT NOT NULL,
  x INTEGER NOT NULL, y INTEGER NOT NULL,
  val REAL,
  fetched_at TEXT NOT NULL,
  PRIMARY KEY (tmfc, var, tmef, x, y)
);
-- 발표분을 끝까지 다 받았는가. 덜 받은 발표분은 다음 주기에 이어 받는다.
CREATE TABLE IF NOT EXISTS fcst_short_run (
  tmfc TEXT PRIMARY KEY,
  complete INTEGER NOT NULL,
  fetched_at TEXT NOT NULL
);

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

-- 기상청 원문 보관(app/kma.py RAW_PATHS) — 매분 관측 · 초단기 격자를 받은 그대로(zlib), 30시간.
-- 재난상황보고서 서버가 같은 요청을 기상청 대신 여기서 받는다(/api/kma/raw). key = 경로 + 정리한 인자(raw_key)
CREATE TABLE IF NOT EXISTS kma_raw (
  key TEXT PRIMARY KEY, at TEXT NOT NULL, ctype TEXT NOT NULL DEFAULT '', body BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_kma_raw_at ON kma_raw(at);
-- 특보 원자료 채워 넣기(collectors/alerts.backfill_raw) — 1분마다 두기 전 시각을 10분 간격으로. 그 시각에만 답한다(사이 분은 기상청)
CREATE TABLE IF NOT EXISTS alert_raw_bf (at TEXT PRIMARY KEY, body TEXT NOT NULL);

-- 공지 · 요청 게시판(app/posts.py) — kind notice 공지(관리자) · request 요청(누구나). 지우지 않고 gone 으로 숨긴다
CREATE TABLE IF NOT EXISTS post (
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '',
  author TEXT NOT NULL DEFAULT '', created TEXT NOT NULL, updated TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'open', reply TEXT NOT NULL DEFAULT '', popup INTEGER NOT NULL DEFAULT 0, gone INTEGER NOT NULL DEFAULT 0
);

-- 특보 원자료(wrn_now_data JSON 행 목록) — 바뀔 때만 한 줄. 재난상황보고서 서버가 기상청 대신 읽는다(/api/alerts/raw)
CREATE TABLE IF NOT EXISTS alert_raw (
  at   TEXT PRIMARY KEY,                -- 'YYYY-MM-DD HH:MM' 이 내용을 처음 받은 때
  body TEXT NOT NULL
);

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

-- 상황판단 모드의 판단 기록 — 누른 결정을 그 시각 수치와 함께(판례가 묻는 '정보를 안 시점 · 한 조치'). 서버 공유
CREATE TABLE IF NOT EXISTS decision (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  at     TEXT NOT NULL,                -- 누른 시각
  sigun  TEXT NOT NULL,
  emd    TEXT,
  fam    TEXT,                         -- 산사태 · 하천 · 지하공간
  stage  TEXT,                         -- 통제 · 사전대피 · 긴급대피
  act    TEXT NOT NULL,                -- 통제 지시 · 사전대피 권고 · 대피명령 요청 · 보류 · 메모
  pct    INTEGER,                      -- 그때 기준 도달률
  eta    TEXT,                         -- 그때 도달 예상 시각
  note   TEXT
);

-- 호우 사건 묶음(app/events.py) — 시작~끝 · 걸린 특보. end 가 비면 진행 중, last 는 마지막으로 특보나 기준 근접이 있던 때
CREATE TABLE IF NOT EXISTS event (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  start  TEXT NOT NULL,
  end    TEXT,
  last   TEXT NOT NULL,
  alerts TEXT NOT NULL DEFAULT '[]'
);

-- 단계가 바뀐 이력 — 처음 그 단계에 이르렀거나(near) 충족으로 오른(met) 때만 한 줄
CREATE TABLE IF NOT EXISTS stage_log (
  id     INTEGER PRIMARY KEY AUTOINCREMENT,
  event  INTEGER NOT NULL,
  at     TEXT NOT NULL,
  sigun  TEXT NOT NULL,
  emd    TEXT,
  fam    TEXT,
  stage  TEXT,
  st     TEXT NOT NULL,                -- near · met
  rule   TEXT,
  pct    INTEGER
);
CREATE INDEX IF NOT EXISTS idx_stage_log_event ON stage_log(event);

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

-- 현장 회신(app/reply.py). 지구마다 변하지 않는 링크(token) 하나 — 담당자가 바뀌어도 링크는 그대로 넘겨받는다.
CREATE TABLE IF NOT EXISTS duty_link (
  rid TEXT PRIMARY KEY, token TEXT NOT NULL UNIQUE,
  sigun TEXT NOT NULL, name TEXT NOT NULL, addr TEXT NOT NULL    -- '창원시' · 지구 이름 · 시군 읍면동 리
);
-- 링크 페이지에서 스스로 등록한 담당자. until 이 비어 있으면 지금 담당(지구마다 둘까지), 채워지면 지난 담당.
CREATE TABLE IF NOT EXISTS duty_person (
  id INTEGER PRIMARY KEY, rid TEXT NOT NULL,
  rank TEXT NOT NULL, name TEXT NOT NULL, tel TEXT NOT NULL,
  since TEXT NOT NULL, until TEXT
);
CREATE INDEX IF NOT EXISTS idx_duty_person ON duty_person(rid, until);
-- 진행 기록(지우지 않고 쌓는다) — kind: ask 상황실 요청 · reply 현장 회신 · on 담당 등록 · off 담당에서 빠짐
CREATE TABLE IF NOT EXISTS duty_log (
  id INTEGER PRIMARY KEY, rid TEXT NOT NULL, at TEXT NOT NULL, kind TEXT NOT NULL,
  who TEXT NOT NULL, action TEXT, more TEXT, memo TEXT NOT NULL, photo TEXT
);
CREATE INDEX IF NOT EXISTS idx_duty_log ON duty_log(rid, id);
-- 산림청 산사태정보시스템(app/sansatai.py). 실황 · 예측 — 읍면동 묶음 한 줄(sta = 산림청 묶음 번호). 지우지 않고 쌓는다(하루 수십 줄, 비 올 때만)
CREATE TABLE IF NOT EXISTS sansatai_pred (
  anal TEXT NOT NULL, kind TEXT NOT NULL, sigun TEXT NOT NULL, gu TEXT, sta TEXT NOT NULL,
  lv INTEGER NOT NULL, emd TEXT, emd_cd TEXT, fetched_at TEXT,
  PRIMARY KEY (anal, kind, sta)
);
CREATE INDEX IF NOT EXISTS idx_sst_pred_sg ON sansatai_pred(sigun, anal);
-- 강우반영 산사태위험도 — 분석 시각마다 경남 · 시군 등급별 500m 칸 수(JSON [1등급, … 5등급])
CREATE TABLE IF NOT EXISTS sansatai_risk (
  anal TEXT PRIMARY KEY, gn TEXT NOT NULL, sigun TEXT NOT NULL, fetched_at TEXT
);
-- 로그인(app/auth.py) — 비밀번호는 scrypt 해시, 접속은 쿠키의 sha256 만
CREATE TABLE IF NOT EXISTS app_user (
  id INTEGER PRIMARY KEY, login TEXT UNIQUE NOT NULL, name TEXT NOT NULL DEFAULT '',
  role TEXT NOT NULL CHECK (role IN ('admin','do','sigun')), sigun TEXT,
  pw TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, created TEXT, last_login TEXT
);
CREATE TABLE IF NOT EXISTS app_session (
  token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, created TEXT, expires TEXT, ip TEXT
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
    "obs_minute": [("rn_15m", "REAL"), ("wss", "REAL")],
    # 겨울 화면(app/cold.py) — 바람(10분 평균) · 습도. 실효습도는 정시 습도로 날마다 평균을 낸다
    "obs_hourly": [("ws", "REAL"), ("wd", "REAL"), ("hm", "REAL")],
    # 판단 기록 — 누른 사람(로그인 이름 · 역할), 지우기는 표시만(gone = '시각 · 누가'). AI 쪽(aireport)에는 who 를 넘기지 않는다
    "decision": [("who", "TEXT"), ("gone", "TEXT")],
    # 계정 신청 — 로그인 화면에서 신청하면 pending=1 · active=0, 관리자가 승인하면 pending=0 · active=1
    "app_user": [("pending", "INTEGER NOT NULL DEFAULT 0")],
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


def put_alert_raw(at: str, body: str) -> bool:
    """특보 원자료 — 앞의 것과 같으면 두지 않는다(바뀔 때만). 둔 것이면 True.
    shortcut: 지우지 않는다 — 하루 몇 줄이라 작다, 커지면 maint 에서 40일 넘은 것 지우기."""
    with tx() as con:
        r = con.execute("SELECT body FROM alert_raw ORDER BY at DESC LIMIT 1").fetchone()
        if r and r["body"] == body:
            return False
        con.execute("INSERT OR REPLACE INTO alert_raw(at, body) VALUES(?,?)", (at, body))
        return True


def put_kma_raw(key: str, ctype: str, body: bytes) -> None:
    """기상청 원문 하나를 둔다(zlib). 30시간 넘은 것은 둘 때 함께 지운다(한 시간에 한 번쯤)."""
    import zlib
    from datetime import datetime, timedelta
    now = datetime.now()
    with tx() as con:
        con.execute("INSERT OR REPLACE INTO kma_raw(key, at, ctype, body) VALUES(?,?,?,?)",
                    (key, now.strftime("%Y-%m-%d %H:%M"), ctype, zlib.compress(body, 6)))
        if now.minute == 7:
            con.execute("DELETE FROM kma_raw WHERE at < ?", ((now - timedelta(hours=30)).strftime("%Y-%m-%d %H:%M"),))


def get_kma_raw(key: str) -> tuple[str, bytes] | None:
    import zlib
    with tx() as con:
        r = con.execute("SELECT ctype, body FROM kma_raw WHERE key=?", (key,)).fetchone()
    return (r["ctype"], zlib.decompress(r["body"])) if r else None


def put_alert_raw_at(at: str, body: str) -> None:
    """지난 시각의 특보 원자료(채워 넣기) — alert_raw_bf 에 그 시각 그대로. 그 시각을 물을 때만 쓴다."""
    with tx() as con:
        con.execute("INSERT OR REPLACE INTO alert_raw_bf(at, body) VALUES(?,?)", (at, body))


def alert_raw_bf_has(at: str) -> bool:
    with tx() as con:
        return con.execute("SELECT 1 FROM alert_raw_bf WHERE at=?", (at,)).fetchone() is not None


def alert_raw_first() -> str | None:
    with tx() as con:
        r = con.execute("SELECT MIN(at) AS a FROM alert_raw").fetchone()
    return r["a"] if r else None


def alert_raw_at(t) -> tuple[str, str] | None:
    """그 시각(datetime) 특보 원자료 (받은 때, 본문). 그 시각 3분 안에 특보를 받은 기록이 없거나
    원자료를 두기 시작하기 전이면 None — 부르는 쪽이 기상청에 묻는다."""
    from datetime import timedelta
    hi, lo = t.strftime("%Y-%m-%d %H:%M"), (t - timedelta(minutes=3)).strftime("%Y-%m-%d %H:%M")
    first = alert_raw_first()
    if not first or hi < first:                      # 1분마다 두기 전 — 채워 넣은 10분 시각과 꼭 같을 때만
        with tx() as con:
            r = con.execute("SELECT at, body FROM alert_raw_bf WHERE at=?", (hi,)).fetchone()
        return (r["at"], r["body"]) if r else None
    with tx() as con:
        if not con.execute("SELECT 1 FROM snapshot WHERE kind='alerts' AND base_time BETWEEN ? AND ? LIMIT 1", (lo, hi)).fetchone():
            return None
        r = con.execute("SELECT at, body FROM alert_raw WHERE at<=? ORDER BY at DESC LIMIT 1", (hi,)).fetchone()
    return (r["at"], r["body"]) if r else None


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

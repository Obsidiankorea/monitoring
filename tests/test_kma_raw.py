"""기상청 원문 보관 — 보고서 서버와 같은 열쇠(인증키 · disp=0 · help=0 빼고 이름순) · /api/kma/raw · 특보 채워 넣기는 그 10분 시각에만."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import kma, main

MIN = "/api/typ01/cgi-bin/url/nph-aws2_min"


def test_key_matches_report_server():
    ours = kma.raw_key(MIN, {"tm2": "202611201930", "stn": "0"})
    theirs = kma.raw_key(MIN, [("tm2", "202611201930"), ("stn", "0"), ("disp", "0"), ("help", "0"), ("authKey", "x")])
    assert ours == theirs == MIN + "?stn=0&tm2=202611201930"
    assert not kma._has_rows(b"#START7777\n# head\n#7777END") and kma._has_rows(b"#x\n202611201930 90 1.0\n")


def test_raw_api(tdb):
    c = TestClient(main.app)
    key = kma.raw_key(MIN, {"tm2": "202611201930", "stn": "0"})
    tdb.put_kma_raw(key, "text/plain; charset=euc-kr", b"202611201930 90 1.0\n")
    r = c.get("/api/kma/raw", params={"path": MIN, "q": key.split("?", 1)[1]})
    assert r.status_code == 200 and r.content == b"202611201930 90 1.0\n"
    assert c.get("/api/kma/raw", params={"path": MIN, "q": "stn=0&tm2=202611201931"}).status_code == 404
    assert c.get("/api/kma/raw", params={"path": "/api/typ01/url/awsh.php", "q": ""}).status_code == 404


def test_alert_backfill_exact_minutes_only(tdb):
    tdb.put_alert_raw("2026-11-20 10:05", "[]")                           # 1분마다 두기 시작한 때
    tdb.put_alert_raw_at("2026-11-19 09:10", '[{"x": 1}]')
    with tdb.tx() as con:                                                 # 그 시각 특보 수집 기록(스냅숏)
        for at in ("2026-11-19 09:10", "2026-11-19 09:13", "2026-11-20 10:06"):
            con.execute("INSERT OR REPLACE INTO snapshot(kind, base_time, fetched_at, payload) VALUES('alerts', ?, ?, '{}')", (at, at))
    assert tdb.alert_raw_at(datetime(2026, 11, 19, 9, 10))[1] == '[{"x": 1}]'
    assert tdb.alert_raw_at(datetime(2026, 11, 19, 9, 13)) is None       # 사이 분은 기상청에(해제 시각을 분 단위로 찾는다)
    assert tdb.alert_raw_at(datetime(2026, 11, 20, 10, 6))[1] == "[]"     # 1분마다 둔 뒤는 그대로


def test_backfill_newest_first(tdb, monkeypatch):
    """채워 넣기는 최근 시각부터 · 이미 채운 시각은 건너뛴다 · 1분마다 둔 뒤 시각은 묻지 않는다."""
    import asyncio
    from app.collectors import alerts
    asked = []

    async def fake(path, params):
        asked.append(params["tm"])
        return b"[]"
    monkeypatch.setattr(alerts, "fetch_bytes", fake)
    from datetime import datetime as dt, timedelta
    first = (dt.now() - timedelta(hours=1)).replace(second=0, microsecond=0)
    tdb.put_alert_raw(first.strftime("%Y-%m-%d %H:%M"), "[]")
    n = asyncio.run(alerts.backfill_raw(hours=2, workers=2))
    assert n == len(asked) >= 5 and asked[0] == max(asked) and asked[-1] == min(asked)      # 최근 것부터
    assert all(a < first.strftime("%Y%m%d%H%M") for a in asked)
    asked.clear()
    assert asyncio.run(alerts.backfill_raw(hours=2, workers=2)) == 0 and asked == []


def test_pass_api(tdb, monkeypatch):
    """/api/kma/pass — 이 서버 키로 대신 묻기 · authKey 버림 · 1분 캐시 · 기상청 실패는 502 + X-GN-Kma-Fail · 경로 제한."""
    asked = []

    async def fake(path, params):
        asked.append((path, params))
        if params.get("stn") == "bad":
            raise kma.KmaError("실패")
        return "image/png", b"PNG"
    monkeypatch.setattr(kma, "fetch_resp", fake)
    kma._pass_cache.clear()
    c = TestClient(main.app)
    p = "/api/typ01/cgi-bin/url/nph-wrn7"
    r = c.get("/api/kma/pass", params={"path": p, "stn": "1", "authKey": "x"})
    assert r.status_code == 200 and r.content == b"PNG" and r.headers["content-type"] == "image/png"
    assert asked == [(p, {"stn": "1"})]
    c.get("/api/kma/pass", params={"path": p, "stn": "1"})
    assert len(asked) == 1                                                  # 1분 캐시
    r = c.get("/api/kma/pass", params={"path": p, "stn": "bad"})
    assert r.status_code == 502 and r.headers.get("X-GN-Kma-Fail") == "1"
    assert c.get("/api/kma/pass", params={"path": "/api/typ01/../x"}).status_code == 400
    assert c.get("/api/kma/pass", params={"path": "/admin"}).status_code == 400

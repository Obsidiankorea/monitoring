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

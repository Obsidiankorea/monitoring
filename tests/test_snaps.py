"""시연(스냅숏) — 지금을 굳히기 · 목록 · 지우기 · 시연 서버로 띄우기."""
import importlib
import json
import sqlite3
import time
from datetime import datetime

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import config, snaps

T = datetime(2026, 10, 19, 0, 24)
ALERTS = {"groups": [{"lv": "watch", "name": "호우주의보", "sea": False, "tmfc": "23:05", "count": 2,
                      "unit": "개시군", "regions": ["남해군", "고성군"], "siguns": ["고성", "남해"]}], "pending": []}


@pytest.fixture
def live(tmp_path, monkeypatch):
    """쌓인 자료 흉내 — T 앞뒤 관측 · 초단기 발표 셋 · 격자 · 설정. 진짜 DB · 캐시는 건드리지 않는다."""
    from app import db, gridstore
    st = tmp_path / "live"
    monkeypatch.setattr(db, "DB_PATH", st / "gnweather.db")
    monkeypatch.setattr(config, "CACHE", st / "cache")
    monkeypatch.setattr(config, "SNAPS", tmp_path / "snaps")
    monkeypatch.setattr(gridstore, "ROOT", st / "cache" / "grid")
    db.init()
    with db.tx() as c:
        for tm in ("2026-10-18 23:00", "2026-10-19 00:00", "2026-10-19 01:00"):      # 01시는 T 뒤 — 버린다
            c.execute("INSERT INTO obs_hourly VALUES('155', ?, 12.5, 40, 18, 'ok', ?)", (tm, tm))
        for tmfc in ("202610182350", "202610190000", "202610190010", "202610190030"):  # 0030 은 T 뒤
            c.execute("INSERT INTO fcst_rn1 VALUES(?, '202610190100', '고성', '고성읍', 10, ?)", (tmfc, tmfc))
        c.execute("INSERT INTO snapshot VALUES('alerts', '2026-10-19 00:20', '2026-10-19 00:20', ?)",
                  (json.dumps({"groups": [], "pending": []}),))
    db.put_setting("map", {"layer": "vsrt", "acc_hours": 12, "acc_from": "hours"})
    for run in ("202610190000", "202610190010", "202610190030"):
        gridstore.save("vsrt", f"{run}_202610190100", np.zeros(gridstore.shape("dfs")))
    for k in ("202610190000", "202610190010"):
        gridstore.save("obs60", k, np.zeros(gridstore.shape("hr")))
    monkeypatch.setattr(snaps, "alerts_at", lambda now: ALERTS)                    # 기상청 대신
    return st


def test_make_cuts_at_that_moment(live, tmp_path):
    m = snaps.make(now=T, acc={"from": "hours", "hours": 6})
    assert m["name"] == "snap-20261019-0024" and m["now"] == "202610190024"
    assert m["title"] == "10.19. 00:24 · 호우주의보(고성·남해)" and m["alerts_src"] == "kma"
    assert m["acc"] == {"from": "hours", "hours": 6} and m["kept"]["fcst_rn1"] == ["202610190000", "202610190010"]
    assert m["files"]["vsrt"] == 2 and "예측 분포 그림 없음" in m["warn"]
    c = sqlite3.connect(tmp_path / "snaps" / m["name"] / "state" / "gnweather.db")
    assert [r[0] for r in c.execute("SELECT tm FROM obs_hourly ORDER BY tm")] == ["2026-10-18 23:00", "2026-10-19 00:00"]
    al = json.loads(c.execute("SELECT payload FROM snapshot WHERE kind='alerts'").fetchone()[0])
    assert al["groups"][0]["siguns"] == ["고성", "남해"]                          # 그 시각 특보로 바꿔 넣었다
    assert json.loads(c.execute("SELECT value FROM setting WHERE key='map'").fetchone()[0])["acc_hours"] == 6
    c.close()
    assert sqlite3.connect(live / "gnweather.db").execute("SELECT COUNT(*) FROM obs_hourly").fetchone()[0] == 3  # 원본 그대로
    with pytest.raises(FileExistsError):
        snaps.make(now=T)
    assert not list((tmp_path / "snaps").glob(".tmp-*"))


def test_list_and_delete(live):
    snaps.make(now=T, title="밤비")
    snaps.make(now=datetime(2026, 10, 19, 0, 10), alerts="db")
    ls = snaps.list_all()
    assert [x["name"] for x in ls] == ["snap-20261019-0024", "snap-20261019-0010"]   # 새 것부터
    assert ls[0]["title"] == "밤비" and ls[1]["alerts"] == [] and ls[1]["acc"] == {"from": "hours", "hours": 12}
    snaps.delete("snap-20261019-0010")
    assert [x["name"] for x in snaps.list_all()] == ["snap-20261019-0024"]
    for bad in ("../x", ".tmp-a", ""):
        with pytest.raises(ValueError):
            snaps.delete(bad)
    with pytest.raises(FileNotFoundError):
        snaps.delete("nope")


def test_api_save_then_delete(live, monkeypatch):
    from app import clock, main
    monkeypatch.setattr(clock, "now", lambda: T)
    monkeypatch.setattr(snaps, "JOB", None)
    c = TestClient(main.app)
    r = c.post("/api/snaps", json={"title": "", "acc": {"from": "today"}})
    assert r.status_code == 200 and r.json()["name"] == "snap-20261019-0024"
    for _ in range(100):
        j = c.get("/api/snaps").json()
        if j["job"]["done"]:
            break
        time.sleep(0.05)
    assert j["job"]["error"] is None and [x["name"] for x in j["snaps"]] == ["snap-20261019-0024"]
    assert j["snaps"][0]["acc"]["from"] == "today" and j["demo"] is False
    assert c.post("/api/snaps", json={}).status_code == 409                      # 같은 시각이 이미 있다
    assert c.post("/api/snaps", json={"acc": {"from": "hours", "hours": 5}}).status_code == 400
    assert c.get("/snap/snap-20261019-0024").status_code == 404                  # 실황 서버는 갈아 타지 않는다
    assert c.delete("/api/snaps/snap-20261019-0024").json()["ok"]
    assert c.get("/api/snaps").json()["snaps"] == []
    assert c.delete("/api/snaps/snap-20261019-0024").status_code == 404


def test_demo_server_reads_store(live, tmp_path, monkeypatch):
    """시연 서버 — 굳힌 것을 사본으로 떠서 쓰고, 시계를 멈추고, 수집하지 않는다. 이름이 없으면 가장 새 것."""
    snaps.make(now=datetime(2026, 10, 19, 0, 10), alerts="db")
    snaps.make(now=T)
    monkeypatch.setenv("GN_SNAPS", str(tmp_path / "snaps"))
    monkeypatch.setenv("GN_SNAP_STATE", str(tmp_path / "run"))
    monkeypatch.setenv("GN_DEMO", "1")
    monkeypatch.delenv("GN_SNAP", raising=False)
    monkeypatch.delenv("GN_NOW", raising=False)
    from app import clock
    try:
        importlib.reload(config)
        importlib.reload(clock)
        assert config.DEMO and config.SNAP == "snap-20261019-0024"
        assert config.DB_PATH == tmp_path / "run" / "gnweather.db" and config.DB_PATH.exists()
        assert clock.now() == T and config.SNAP_META["alerts"] == ["호우주의보(고성·남해)"]
        monkeypatch.setenv("GN_SNAP", "snap-20261019-0010")
        importlib.reload(config)
        assert config.SNAP == "snap-20261019-0010"
    finally:
        for k in ("GN_SNAPS", "GN_SNAP_STATE", "GN_DEMO", "GN_SNAP", "GN_NOW", "NO_COLLECT"):
            monkeypatch.delenv(k, raising=False)
        importlib.reload(config)
        importlib.reload(clock)

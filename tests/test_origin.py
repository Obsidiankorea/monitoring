"""자료 받는 곳 — 이 PC(수집) / 서버(언레이드). 서버면 /api/… 를 넘기고, 받는 곳·업데이트·저장공간은 이 PC."""
import httpx
import pytest
from fastapi.testclient import TestClient

from app import origin


def test_should_proxy_keeps_local_things():
    assert origin.should_proxy("/api/alerts") and origin.should_proxy("/api/grid/emdday")
    assert origin.should_proxy("/api/settings/map") and origin.should_proxy("/api/refresh/rain")
    for p in ("/api/origin", "/api/origin/test", "/api/update", "/api/update/pull",
              "/api/storage", "/api/storage/cleanup", "/api/settings/retention", "/", "/map.html"):
        assert not origin.should_proxy(p), p


def test_check_url():
    assert origin.check_url(" http://100.106.116.92:8000/map.html?x=1 ") == "http://100.106.116.92:8000"
    assert origin.check_url("https://tower") == "https://tower"
    for bad in ("", "tower:8000", "ftp://tower", "http://"):
        with pytest.raises(ValueError):
            origin.check_url(bad)


def test_put_and_default(tdb):
    assert origin.cfg()["mode"] == "local" and origin.remote() is None      # 기본은 예전과 같다(이 PC 수집)
    c = origin.put({"mode": "server", "url": "http://10.0.0.5:8000/"})
    assert c == {"mode": "server", "url": "http://10.0.0.5:8000"} and origin.remote() == "http://10.0.0.5:8000"
    with pytest.raises(ValueError):
        origin.put({"mode": "cloud"})
    assert origin.put({"mode": "local"})["url"] == "http://10.0.0.5:8000"  # 주소는 남는다
    assert origin.remote() is None


def test_middleware_forwards_to_server(tdb, monkeypatch):
    from app import main
    seen = []

    def handler(req: httpx.Request):
        seen.append((req.method, req.url.path, req.url.query.decode(), req.content))
        if req.url.path == "/api/alerts":
            return httpx.Response(200, json={"from": "server"})
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(origin, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    origin.put({"mode": "server", "url": "http://srv:8000"})
    c = TestClient(main.app)                                   # with 없이 — 수집기(lifespan)는 안 띄운다
    assert c.get("/api/alerts").json() == {"from": "server"}
    c.put("/api/settings/map", json={"layer": "obs60"})
    assert seen[-1][:2] == ("PUT", "/api/settings/map") and b"obs60" in seen[-1][3]
    c.get("/api/grid/emd?sigun=%ED%95%A8%EC%96%91&layer=obs60")
    assert seen[-1][1] == "/api/grid/emd" and "sigun=" in seen[-1][2]
    n = len(seen)
    o = c.get("/api/origin").json()                            # 받는 곳 설정은 이 PC 가 답한다
    assert o["mode"] == "server" and len(seen) == n


def test_server_unreachable_is_502(tdb, monkeypatch):
    from app import main

    def handler(req):
        raise httpx.ConnectError("refused", request=req)

    monkeypatch.setattr(origin, "_client", httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    origin.put({"mode": "server", "url": "http://srv:8000"})
    r = TestClient(main.app).get("/api/alerts")
    assert r.status_code == 502 and "닿지 않는다" in r.json()["detail"]


def test_server_update_asks_by_file(tmp_path, monkeypatch):
    """서버 갱신 — 컨테이너는 state/update 에 부탁 파일만 둔다(언레이드 updater.sh 가 집어 간다)."""
    import json as _j
    from app import config, main, serverupdate
    monkeypatch.setattr(config, "STATE", tmp_path)
    c = TestClient(main.app)
    assert c.get("/api/server-update").json()["available"] is False        # 장치가 없으면(PC) 칸을 숨긴다
    assert c.post("/api/server-update", json={"action": "deploy"}).status_code == 404
    (tmp_path / "update").mkdir()
    (tmp_path / "update" / "status.json").write_text(_j.dumps({"running": "abc1234", "remote": "def5678", "behind": 2,
                                                               "commits": [], "deploying": False, "last": None}), "utf-8")
    j = c.get("/api/server-update").json()
    assert j["available"] and j["behind"] == 2 and j["requested"] is False and j["updater_stale"] is False
    assert c.post("/api/server-update", json={"action": "deploy"}).json()["requested"] is True
    assert (tmp_path / "update" / "request").exists()
    assert c.post("/api/server-update", json={"action": "check"}).json()["checking"] is True
    assert c.post("/api/server-update", json={"action": "rm"}).status_code == 400
    assert serverupdate.STALE_S == 300

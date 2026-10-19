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

"""자료 받는 곳 '서버 + 이 PC 스방'(mix) — 읽기만 서버로, 스방 · 설정 · 보고서 · 쓰기는 이 PC."""
from app import origin


def _mix(monkeypatch, mode="mix"):
    monkeypatch.setattr(origin, "cfg", lambda: {"mode": mode, "url": "https://gisang.day"})


def test_mix_읽기는_서버로(monkeypatch):
    _mix(monkeypatch)
    assert origin.remote() == "https://gisang.day"
    assert origin.should_proxy("/api/alerts", "GET")
    assert origin.should_proxy("/api/rain", "GET", "hours=24")


def test_mix_스방_설정_보고서는_이_PC(monkeypatch):
    _mix(monkeypatch)
    assert not origin.should_proxy("/api/bangjae", "GET")
    assert not origin.should_proxy("/api/rain", "GET", "hours=24&src=bangjae")
    assert not origin.should_proxy("/api/settings/layers", "GET")
    assert not origin.should_proxy("/api/reports/run", "POST")
    assert not origin.should_proxy("/api/reports", "GET")


def test_mix_쓰기는_서버로_보내지_않는다(monkeypatch):
    _mix(monkeypatch)
    for m in ("POST", "PUT", "DELETE", "PATCH"):
        assert not origin.should_proxy("/api/alerts", m)


def test_server_모드는_예전_그대로(monkeypatch):
    _mix(monkeypatch, "server")
    assert origin.should_proxy("/api/bangjae", "GET")
    assert origin.should_proxy("/api/settings/layers", "PUT")
    assert not origin.should_proxy("/api/origin", "GET")


def test_local_은_넘기지_않는다(monkeypatch):
    _mix(monkeypatch, "local")
    assert origin.remote() is None

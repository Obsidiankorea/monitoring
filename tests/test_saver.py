"""API 절약 모드 — 수집 주기를 n분 이상으로 늦춘다(긴 주기는 그대로, 특보는 따로)."""
from app import db, main


def test_saver_off_keeps_base(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "get_setting", lambda k, d=None: d)
    assert main.intervals() == main.base_intervals()


def test_saver_on_raises_short_only(monkeypatch):
    st = {"api_saver": {"on": True, "min": 5, "alerts": False}}
    monkeypatch.setattr(db, "get_setting", lambda k, d=None: st.get(k, d))
    iv = main.intervals()
    assert iv["alerts"] == 60                      # 특보는 그대로
    assert iv["minute"] == 300 and iv["qpf"] == 300  # 1분짜리는 5분
    assert iv["rain"] == 600                       # 10분짜리는 그대로
    st["api_saver"]["alerts"] = True
    assert main.intervals()["alerts"] == 300
    st["api_saver"]["min"] = 15
    assert main.intervals()["rain"] == 900

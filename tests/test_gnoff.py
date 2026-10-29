from app import db, sites


def test_gn_off_marks_all_gn_keys(monkeypatch):
    """map.gn_off 를 켜면 경남 AWS('gn:' 열쇠)는 전부 비활성, 기상청 지점번호는 그대로, 한 곳씩 끈 것은 따로 유지."""
    cfg = {"aws_off": [{"id": "108"}], "gn_off": False}
    monkeypatch.setattr(db, "get_setting", lambda k, d: cfg if k == "map" else d)
    off = sites.off_keys()
    assert "108" in off and "gn:창원:북면" not in off and sites.gn_off() is False
    cfg["gn_off"] = True
    off = sites.off_keys()
    assert "gn:창원:북면" in off and "108" in off and "159" not in off and off and sites.gn_off() is True

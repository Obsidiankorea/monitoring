import pytest

from app import apikeys, config


@pytest.fixture
def keys(tmp_path, monkeypatch):
    f = tmp_path / "api_keys.txt"
    f.write_text("# 주석\nORG_API_KEY=abc\nOTHER=keepme\n", "utf-8")
    monkeypatch.setattr(apikeys, "FILE", f)
    monkeypatch.setattr(config, "KEYS", {"ORG_API_KEY": "abc"})
    monkeypatch.setattr(config, "ORG_API_KEY", "abc")
    return f


def test_save_adds_replaces_and_deletes_keeping_other_lines(keys):
    apikeys.save("LAW_OC", "myid")
    apikeys.save("ORG_API_KEY", "newkey1234567")
    t = keys.read_text("utf-8")
    assert "LAW_OC=myid" in t and "ORG_API_KEY=newkey1234567" in t and "ORG_API_KEY=abc" not in t
    assert "# 주석" in t and "OTHER=keepme" in t
    assert config.KEYS["LAW_OC"] == "myid" and config.ORG_API_KEY == "newkey1234567"
    apikeys.save("LAW_OC", "")
    assert "LAW_OC" not in keys.read_text("utf-8") and "LAW_OC" not in config.KEYS


def test_save_rejects_unknown_names_and_bad_values(keys):
    with pytest.raises(ValueError):
        apikeys.save("OTHER", "x")                       # 목록에 없는 이름
    with pytest.raises(ValueError):
        apikeys.save("LAW_OC", "a\nORG_API_KEY=evil")    # 줄바꿈으로 다른 키를 심는 것


def test_status_never_returns_the_value(keys):
    apikeys.save("DATA_GO_KR_KEY", "abcdefghij1234")
    st = {k["name"]: k for k in apikeys.status()}
    assert st["DATA_GO_KR_KEY"]["set"] and st["DATA_GO_KR_KEY"]["tail"] == "1234" and "abcdefghij" not in str(st)
    assert not st["LAW_OC"]["set"]

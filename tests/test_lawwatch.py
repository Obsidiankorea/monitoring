from datetime import datetime

import pytest

from app import lawwatch as lw


def _row(name, serial, enforce, kind="일부개정", promul="20260121"):
    return {"법령명한글": name, "법령일련번호": serial, "시행일자": enforce, "공포일자": promul, "제개정구분명": kind}


@pytest.fixture
def env(tmp_path, monkeypatch):
    store, data = {}, {"cur": {}, "pend": {}}
    monkeypatch.setattr(lw.db, "get_setting", lambda k, d: store.get(k, d))
    monkeypatch.setattr(lw.db, "put_setting", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(lw, "OUT", tmp_path / "proposals")
    monkeypatch.setattr(lw, "watch_list", lambda: [{"name": "자연재해대책법", "aliases": ["자대법"]}])
    monkeypatch.setattr(lw, "_cites", lambda name, al: ["통제·대피 기준", "용어집"])
    monkeypatch.setattr(lw, "_fetch", lambda w, nw: data["cur" if nw == 3 else "pend"].get(w["name"], []))
    return store, data


def test_rows_finds_items_whatever_the_nesting():
    one = {"LawSearch": {"law": _row("a", "1", "2")}}
    many = {"LawSearch": {"law": [_row("a", "1", "2"), _row("b", "3", "4")]}}
    assert [r["법령명한글"] for r in lw._rows(one, "법령명한글")] == ["a"]
    assert [r["법령명한글"] for r in lw._rows(many, "법령명한글")] == ["a", "b"]
    assert lw._rows({"LawSearch": {"law": []}}, "법령명한글") == []


def test_first_run_only_remembers_then_change_writes_proposal(env):
    store, data = env
    data["cur"]["자연재해대책법"] = [_row("자연재해대책법", "100", "20260722")]
    r = lw.check(datetime(2026, 10, 31))
    assert r["first"] is True and r["changed"] == [] and not (lw.OUT.exists() and list(lw.OUT.glob("*.md")))
    assert store["law_state"]["자연재해대책법"]["serial"] == "100"

    r = lw.check(datetime(2026, 11, 1))                       # 그대로면 조용하다
    assert r["changed"] == [] and r["first"] is False

    data["cur"]["자연재해대책법"] = [_row("자연재해대책법", "101", "20270101", "타법개정")]
    r = lw.check(datetime(2026, 11, 2))
    assert r["changed"][0][0] == "자연재해대책법" and "시행일 20260722 → 20270101" in r["changed"][0][1][0]
    f = lw.OUT / "2026-11-02-자연재해대책법.md"
    t = f.read_text("utf-8")
    assert "status: 검토대기" in t and "[[통제·대피 기준]]" in t and "law.go.kr/법령/" in t


def test_new_pending_enactment_is_flagged_once(env):
    store, data = env
    data["cur"]["자연재해대책법"] = [_row("자연재해대책법", "100", "20260722")]
    lw.check(datetime(2026, 10, 31))
    data["pend"]["자연재해대책법"] = [_row("자연재해대책법", "200", "20270301", "일부개정")]
    r = lw.check(datetime(2026, 11, 1))
    assert "시행예정 개정 공포 — 시행일 20270301" in r["changed"][0][1][0]
    assert lw.check(datetime(2026, 11, 2))["changed"] == []   # 같은 시행예정은 다시 알리지 않는다


def test_unknown_law_and_api_errors_make_no_proposal(env, monkeypatch):
    store, data = env
    r = lw.check(datetime(2026, 10, 31))                      # 목록에 없는 법령명
    assert r["changed"] == [] and "법제처 목록에 없다" in r["errors"][0]

    def boom(name, nw):
        raise RuntimeError(f"{name}: 사용자 정보 검증에 실패하였습니다")
    monkeypatch.setattr(lw, "_fetch", boom)
    r = lw.check(datetime(2026, 11, 1))
    assert r["changed"] == [] and "검증에 실패" in r["errors"][0]
    assert not (lw.OUT.exists() and list(lw.OUT.glob("*.md")))


def test_watch_file_is_valid_and_names_unique():
    names = [w["name"] for w in lw.watch_list()]
    assert len(names) == len(set(names)) and "재난 및 안전관리 기본법" in names


def test_admrul_and_ordin_use_their_own_fields_and_state_keys(monkeypatch):
    store = {}
    monkeypatch.setattr(lw.db, "get_setting", lambda k, d: store.get(k, d))
    monkeypatch.setattr(lw.db, "put_setting", lambda k, v: store.__setitem__(k, v))
    monkeypatch.setattr(lw, "watch_list", lambda: [{"name": "재난문자방송 기준 및 운영규정", "target": "admrul"},
                                                  {"name": "거제시 재난 대피에 관한 조례", "target": "ordin", "org": "거제시"}])
    got = {"admrul": [{"행정규칙명": "재난문자방송 기준 및 운영규정", "행정규칙일련번호": "9", "시행일자": "20260204", "발령일자": "20260204", "제개정구분명": "일부개정"}],
           "ordin": [{"자치법규명": "거제시 재난 대피에 관한 조례", "자치법규일련번호": "7", "시행일자": "20260923", "공포일자": "20260923",
                      "제개정구분명": "일부개정", "지자체기관명": "경상남도 거제시"}]}
    calls = []

    class R:
        def __init__(self, t): self.t = t
        def raise_for_status(self): pass
        def json(self): return {"X": {"law": got[self.t]}}

    def fake_get(url, params, **kw):
        calls.append(params)
        return R(params["target"])

    monkeypatch.setattr(lw.config, "KEYS", {"LAW_OC": "k"})
    monkeypatch.setattr(lw.httpx, "get", fake_get)
    r = lw.check(datetime(2026, 10, 31))
    assert r["errors"] == [] and r["first"] is True
    assert set(store["law_state"]) == {"admrul:재난문자방송 기준 및 운영규정", "ordin:거제시 재난 대피에 관한 조례"}
    assert store["law_state"]["ordin:거제시 재난 대피에 관한 조례"]["serial"] == "7"
    assert len(calls) == 2 and "nw" not in calls[0] and calls[1]["nw"] == 3        # 행정규칙은 nw 없이, 자치법규는 현행(3)만

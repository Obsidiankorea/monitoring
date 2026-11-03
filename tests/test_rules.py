"""위키 판정값(data/판정값.csv) · 블록 문단 — 위키를 고치면 판정이 바뀌고, 못 읽으면 기본값으로 계속한다."""
from app import ai, aireport

HEAD = "항목,값,단위,뜻,근거 문서,원문\n"


def _vault(tmp_path, monkeypatch, csv: str | None):
    (tmp_path / "data").mkdir()
    if csv is not None:
        (tmp_path / "data" / "판정값.csv").write_text("﻿" + HEAD + csv, "utf-8")
    monkeypatch.setattr(ai, "wiki", lambda: tmp_path)
    ai._RULES.clear()
    aireport.reset_cache()
    return tmp_path


def _groups(a, w):
    return [{"name": "호우주의보", "siguns": [f"a{i}" for i in range(a)]},
            {"name": "호우경보", "siguns": [f"w{i}" for i in range(w)]}]


def test_stage_follows_wiki_value(tmp_path, monkeypatch):
    _vault(tmp_path, monkeypatch, "비상1단계_호우주의보_시군,5,개 시군,,,\n")
    assert ai._stage(_groups(4, 0))["stage"] == "초기대응"          # 기본 4 였으면 비상 1단계
    assert ai._stage(_groups(5, 0))["stage"] == "비상 1단계"
    assert ai._stage(_groups(0, 3))["stage"] == "비상 2단계"          # 없는 줄은 기본값(3)
    assert "비상1단계_호우주의보_시군" not in " ".join(ai.rules()["err"])
    assert ai.is_cbs(72, 0) and not ai.is_cbs(50, 89) and ai.is_relay(0, 100)


def test_bad_or_missing_csv_falls_back_with_warning(tmp_path, monkeypatch):
    _vault(tmp_path, monkeypatch, None)
    assert ai.rules()["v"] == ai.RULE_DEFAULT and ai.rules()["err"]
    assert any("판정값을 못 읽었다" in x for x in aireport._refs([]))
    (tmp_path / "data" / "판정값.csv").write_text(HEAD + "비상1단계_호우주의보_시군,1,,,,\n상황전파_1시간,스물,,,,\n", "utf-8")
    r = ai.rules()                                                  # mtime 이 바뀌어 다시 읽는다
    assert r["v"] == ai.RULE_DEFAULT                                 # 1 은 초기대응을 없앤다 → 전부 기본값
    assert any("스물" in e for e in r["err"])


def test_block_reads_paragraph_and_falls_back(tmp_path, monkeypatch):
    v = _vault(tmp_path, monkeypatch, "")
    (v / "매뉴얼.md").write_text("# 매뉴얼\n\n두 경우 모두 **유선**으로 전파한다. ^전파\n\n> 2. 섬은 **제외**한다. ^제외\n", "utf-8")
    assert aireport.block("매뉴얼#^전파", "옛") == "두 경우 모두 유선으로 전파한다."
    assert aireport.block("매뉴얼#^제외", "옛") == "섬은 제외한다."
    assert aireport.block("매뉴얼#^없음", "옛") == "옛"
    assert any("[[매뉴얼#^없음]]" in x for x in aireport._refs([]))

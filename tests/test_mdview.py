"""문서 보기 — 보이는 폴더만(docs/api 와 경로 장난은 막는다) · HTML 은 걸러 낸다 · 목록 · 표 · 콜아웃 · 위키링크."""
from app import mdview


def test_only_listed_docs():
    paths = {x["path"] for x in mdview.listing()}
    assert "00-대시보드-로드맵.md" in paths and "재난온톨로지/00-로드맵.md" in paths
    assert not any(p.startswith("api/") for p in paths)
    assert mdview.view("api/kma-apihub.md") is None and mdview.view("../config/api_keys.txt") is None


def test_render():
    h = mdview.render("# 제목\n\n- a\n  - b\n- c\n\n| x | y |\n|---|---|\n| 1 | **2** |\n\n> [!warning] 조심\n> 내용\n\n<script>alert(1)</script> [[있다|별칭]] [[없다]]",
                      {"있다": "재난온톨로지/있다.md"})
    assert "<h2>제목</h2>" in h and "<ul><li>a<ul><li>b</li></ul></li><li>c</li></ul>" in h
    assert "<td><b>2</b></td>" in h and 'class="co warning"' in h and "조심" in h
    assert "<script>" not in h and 'href="#doc=재난온톨로지/있다.md"' in h and 'class="wk"' in h

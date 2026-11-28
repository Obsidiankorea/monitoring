import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("sansatai_dump", Path(__file__).parent.parent / "tools" / "sansatai_dump.py")
sd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sd)


def test_shelter_counts_by_address_sigun():
    sh = [
        {"evctnPlaceNm": "가", "evctnshlLotnoAddr": "경상남도 진주시 a", "evctnPlaceMnagnNm": "경상남도 진주시"},
        {"evctnPlaceNm": "나", "evctnshlLotnoAddr": "경상남도 진주시 b", "evctnPlaceMnagnNm": "진주시"},
        {"evctnPlaceNm": "다", "evctnshlLotnoAddr": None, "evctnshlRoadNmAddr": "경상남도 함양군 c", "evctnPlaceMnagnNm": "함양국유림관리소"},
        {"evctnPlaceNm": "라", "evctnshlLotnoAddr": "경상북도 상주시 d"},
    ]
    md = sd.md_shelter({"대피소": {"shelterList": sh}}, "2026-11-28 00:00")
    assert "## 시도별 (4곳)" in md and "| 경상남도 | 3 |" in md
    assert "| 진주시 | 2 |" in md and "| 함양군 | 1 |" in md
    assert "상주시" not in md.split("## 경남 목록")[1]


def test_now_empty_lists():
    md = sd.md_now({}, "2026-11-28 00:00")
    assert md.count("_지금 없음_") == 5

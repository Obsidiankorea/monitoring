"""기상특보 응답 읽기 — JSON(disp=1, 2026.10~) · 콤마 글(euc-kr) 둘 다. 모양이 낯설면 '특보 없음'이 아니라 실패."""
import json
from datetime import datetime

import pytest

from app.collectors import alerts
from app.kma import KmaError

NOW = datetime(2026, 10, 19, 0, 10)
ROWS = [  # 2026.10.19 00:04 실제 응답에서 추린 것
    ("S1131000", "동해남부앞바다", "S1131100", "울산앞바다", "202610182000", "202610182100", "풍랑", "주의", "발표", "19일 새벽(03시~06시),"),
    ("L1080000", "경상남도", "L1082400", "남해군", "202610182350", "202610182350", "호우", "주의", "발표", ""),
    ("L1080000", "경상남도", "L1082300", "고성군", "202610182305", "202610182305", "호우", "주의", "발표", ""),
    ("L1050000", "전라남도", "L1051000", "여수시", "202610182305", "202610182305", "호우", "주의", "발표", ""),
]


def _json() -> bytes:
    return json.dumps([dict(zip(alerts.KEYS, r)) for r in ROWS], ensure_ascii=False, indent=4).encode("utf-8")


def _text() -> bytes:
    body = "\n".join(", ".join(r) + "=" for r in ROWS)
    return f"#START7777\n#  특보현황 조회\n{body}\n#7777END\n".encode("euc-kr")


@pytest.mark.parametrize("raw", [_json(), _text()], ids=["json", "text"])
def test_reads_both_shapes(raw):
    d = alerts.normalize(raw, NOW)
    assert [(g["name"], g["siguns"]) for g in d["groups"]] == [("호우주의보", ["고성", "남해"])]
    assert d["groups"][0]["tmfc"] == "23:05" and d["groups"][0]["count"] == 2


def test_empty_is_no_alerts():
    for raw in (b"[]", b"#START7777\n# header only\n#7777END\n"):
        assert alerts.normalize(raw, NOW) == {"groups": [], "pending": []}


def test_unfamiliar_shape_fails_not_empty():
    """모양이 바뀌었는데 '특보 없음'으로 넘기면 호우주의보를 통째로 못 본다(09.30~10.19 실제로 그랬다)"""
    for raw in (b'{"result": "ok"}', json.dumps([{"a": 1}]).encode(), "알 수 없는 응답 본문".encode("euc-kr")):
        with pytest.raises(KmaError):
            alerts.normalize(raw, NOW)


def test_sea_only_gyeongnam_and_never_a_sigun():
    """남해서부(전남 쪽) 먼바다는 '남해'(군)로 시작해도 경남이 아니다 — 남해군 특보처럼 그려졌다(2026-10-23).
    경남 바다(남해동부 먼바다 · 거제 · 경남 앞바다)만 바다 특보로, 시군에는 붙이지 않는다. 세분화 군은 'OO군' 그대로일 때만."""
    rows = [
        ("S1320000", "남해서부먼바다", "S1321000", "남해서부서쪽먼바다", "202610230600", "202610230600", "풍랑", "주의", "발표", ""),
        ("S1320000", "남해서부먼바다", "S1322000", "남해서부동쪽먼바다", "202610230600", "202610230600", "풍랑", "주의", "발표", ""),
        ("S1330000", "남해동부먼바다", "S1331000", "남해동부동쪽안쪽먼바다", "202610230600", "202610230600", "풍랑", "주의", "발표", ""),
        ("S1131000", "남해동부앞바다", "S1131200", "거제시동부앞바다", "202610230600", "202610230600", "풍랑", "주의", "발표", ""),
        ("S1131000", "남해동부앞바다", "S1131100", "부산앞바다", "202610230600", "202610230600", "풍랑", "주의", "발표", ""),
        ("L1050000", "남해군", "L1051000", "남해동부", "202610230600", "202610230600", "강풍", "주의", "발표", ""),
        ("L1080000", "합천군", "L1082800", "합천남부", "202610230600", "202610230600", "호우", "주의", "발표", ""),
    ]
    raw = json.dumps([dict(zip(alerts.KEYS, r)) for r in rows], ensure_ascii=False).encode("utf-8")
    d = alerts.normalize(raw, datetime(2026, 10, 23, 7, 0))
    by = {(g["name"], g["sea"]): g for g in d["groups"]}
    sea = by[("풍랑주의보", True)]
    assert sea["regions"] == ["남해동부동쪽안쪽먼바다", "거제시동부앞바다"] and sea["siguns"] == []
    assert ("풍랑주의보", False) not in by                                   # 남해서부 → 남해군 이 아니다
    assert by[("호우주의보", False)]["siguns"] == ["합천"]
    assert ("강풍주의보", False) not in by                                   # 상위구역 '남해군' 은 세분화 군이 아니다


def test_preliminary_typhoon_with_day():
    """예비특보 — 태풍처럼 하루 이틀 앞이면 날짜를 붙인다. 레벨 칸 · 이름에 '예비'가 와도 예비로(발효 중으로 세지 않는다).
    바다 구역 예비는 시군에 붙이지 않고 바다로 표시."""
    rows = [
        ("L1080000", "경상남도", "L1082100", "창원시", "202610241100", "202610251158", "태풍", "", "예비", ""),
        ("S1330000", "남해동부먼바다", "S1331000", "남해동부안쪽먼바다", "202610241100", "202610250559", "태풍", "예비", "발표", ""),
        ("L1080000", "경상남도", "L1082200", "거제시", "202610241100", "202610251200", "태풍예비", "", "발표", ""),
        ("L1050000", "전라남도", "L1051000", "여수시", "202610241100", "202610251158", "태풍", "", "예비", ""),
    ]
    raw = json.dumps([dict(zip(alerts.KEYS, r)) for r in rows], ensure_ascii=False).encode("utf-8")
    d = alerts.normalize(raw, datetime(2026, 10, 24, 11, 30))
    assert d["groups"] == []                                                  # 발효 중으로 세지 않는다
    pre = [(p["name"], p["sigun"], p["sea"], p["when"]) for p in d["pending"]]
    assert pre == [("태풍", "창원", False, "25일 오전(06~12시)"), ("태풍", None, True, "25일 새벽(03~06시)"),
                   ("태풍", "거제", False, "25일 12시")]


def test_subzone_with_gun_and_control_order():
    """세부구역이 '하동군북부'처럼 군을 붙여 와도 그 시군으로(10-27 — 시군을 못 찾아 날것으로 보였다).
    육상 구역은 관제순(창원 · 진주 … 합천), 발효 예정도 시군을 붙인다."""
    rows = [
        ("L1080000", "경상남도", "L1082600", "밀양시", "202610271600", "202610272100", "한파", "주의", "발표", ""),
        ("L1080000", "하동군", "L1083010", "하동군북부", "202610271600", "202610272100", "한파", "주의", "발표", ""),
        ("L1080000", "산청군", "L1083110", "산청군서남부", "202610271600", "202610271600", "한파", "주의", "발표", ""),
        ("L1080000", "경상남도", "L1082200", "진주시", "202610271600", "202610271600", "한파", "주의", "발표", ""),
        ("L1080000", "합천군", "L1082810", "합천군서북부", "202610271600", "202610271600", "한파", "주의", "발표", ""),
    ]
    raw = json.dumps([dict(zip(alerts.KEYS, r)) for r in rows], ensure_ascii=False).encode("utf-8")
    d = alerts.normalize(raw, datetime(2026, 10, 27, 17, 0))
    g = d["groups"][0]
    assert g["siguns"] == ["진주", "산청", "합천"] and g["regions"] == ["진주시", "산청군서남부", "합천군서북부"]
    assert [(p["reg"], p["sigun"]) for p in d["pending"]] == [("밀양시", "밀양"), ("하동군북부", "하동")]
    from app.domain.regions import sub_of
    assert sub_of("하동군북부") == "북" and sub_of("합천서북부") == "서북"

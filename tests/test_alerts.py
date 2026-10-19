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

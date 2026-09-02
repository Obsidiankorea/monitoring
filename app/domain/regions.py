"""경남 도메인 규칙. 기상청 API를 모른다 — 순수 함수로 둔다."""
from __future__ import annotations

import json
from functools import lru_cache

from ..config import DATA

# 관제순. 행정코드순도 가나다순도 아니다. 표·목록은 항상 이 순서.
ORDER = ["창원", "진주", "통영", "사천", "김해", "밀양", "거제", "양산",
         "의령", "함안", "창녕", "고성", "남해", "하동", "산청", "함양", "거창", "합천"]

# 시군 대표지점(stn). 기상청 API에 stn으로 그대로 넣는다.
REP_STN = {"창원": "155", "진주": "192", "통영": "162", "사천": "917", "김해": "253",
           "밀양": "288", "거제": "294", "양산": "257", "의령": "263", "함안": "920",
           "창녕": "919", "고성": "918", "남해": "295", "하동": "932", "산청": "289",
           "함양": "264", "거창": "284", "합천": "285"}

# 특보구역이 나뉜 군. API에서 이들은 상위구역(REG_UP_KO)이 '경상남도'가 아니라 'OO군'이다.
SUBZONES = {
    "합천": {"합천서북부": "서북", "합천중부": "중", "합천남부": "남"},
    "산청": {"산청북부": "북", "산청서남부": "서남", "산청동남부": "동남"},
    "함양": {"함양중부": "중", "함양서북부": "서북"},
    "거창": {"거창북부": "북", "거창남부": "남"},
    "하동": {"하동북부": "북", "하동남부": "남"},
}

# ⚠️ 경남 고성은 세분화되지 않아 상위구역이 항상 '경상남도'다.
#    상위구역이 '고성군'인 것은 강원 고성이다.
NO_SPLIT_SIGUN = {"고성"}

SEA_PARENTS = {"남해동부전해상", "남해동부앞바다"}
SEA_EXCLUDE = ("부산", "전남")


@lru_cache(maxsize=1)
def stations() -> list[dict]:
    """경남 AWS 56지점."""
    return json.loads((DATA / "aws_stations.json").read_text(encoding="utf-8"))["stations"]


@lru_cache(maxsize=1)
def by_sigun() -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {s: [] for s in ORDER}
    for st in stations():
        out.setdefault(st["sigun"], []).append(st)
    return out


@lru_cache(maxsize=1)
def grids() -> dict:
    """읍면동 ↔ 격자 XY. 인덱스 = (Y-1)*width + (X-1)."""
    return json.loads((DATA / "gyeongnam_grids.json").read_text(encoding="utf-8"))


def in_gyeongnam(reg_up: str, reg: str) -> bool:
    """특보 행이 경남 것인지 — 육상 미세분 / 육상 세분화 / 해상."""
    if reg_up == "경상남도":
        return True
    if reg_up in SEA_PARENTS:
        return not any(x in reg for x in SEA_EXCLUDE)
    for sig in ORDER:
        if sig in NO_SPLIT_SIGUN:
            continue                      # 강원 고성이 새어 들어오는 것을 막는다
        if reg_up.startswith(sig):
            return True
    return False


def sigun_of(reg: str) -> str | None:
    """구역명에서 시군을 찾는다. '합천중부' → '합천'."""
    for sig, subs in SUBZONES.items():
        if reg in subs:
            return sig
    return reg if reg in ORDER else (reg[:-1] if reg[:-1] in ORDER else None)


def sub_of(reg: str) -> str:
    """세부구역 접미사. '합천중부' → '중'."""
    for subs in SUBZONES.values():
        if reg in subs:
            return subs[reg]
    return ""


def split_level(atype: str) -> tuple[str, str]:
    """특보명에서 레벨을 뗀다.

    ⚠️ '중대경보'를 가장 먼저 떼야 한다. 안 그러면 '폭염중대경보'가
       '폭염중대'로 파싱돼 통째로 누락된다(pitfalls ★4).
    """
    for lvl in ("중대경보", "경보", "주의보", "주의"):
        if atype.endswith(lvl):
            return atype[: -len(lvl)], lvl
    return atype, ""


# 예비특보의 TM_EF는 시각이 아니라 시간대 코드다. 분이 58/59인 값만 코드다.
PRE_SLOTS = {
    "0259": "새벽(00~03시)", "0559": "새벽(03~06시)", "0859": "아침(06~09시)",
    "1159": "오전(09~12시)", "1459": "낮(12~15시)", "1759": "늦은 오후(15~18시)",
    "2059": "저녁(18~21시)", "2359": "밤(21~24시)",
    "0558": "새벽(00~06시)", "1158": "오전(06~12시)",
    "1458": "오후(12~18시)", "1758": "오후(12~18시)", "2358": "밤(18~24시)",
}


def pre_slot(tm_ef: str) -> str | None:
    return PRE_SLOTS.get(tm_ef[-4:]) if len(tm_ef) >= 4 else None

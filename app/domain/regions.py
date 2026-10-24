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
# 경남 바다가 아닌 것 — 부산 · 전남 앞바다, 남해**서부** 먼바다(전남 쪽). ⚠️ '남해서부…'는 '남해'(군)로 시작해
# 시군 이름 앞머리 맞추기에 걸려 남해군 특보처럼 그려졌다(2026-10-23 남해서부서쪽 · 동쪽먼바다 풍랑주의보)
SEA_EXCLUDE = ("부산", "전남", "남해서부")
# 경남 바다라고 볼 이름 — 남해동부 먼바다(동쪽 · 서쪽 · 안쪽 · 바깥)는 SEA_PARENTS 나 '남해동부'로, 앞바다는 이 말로
GN_SEA_KEYS = ("거제", "경남", "통영")


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


def is_sea(reg_up: str, reg: str) -> bool:
    """바다 특보 구역인가 — 이름으로 가른다('…앞바다' · '…먼바다' · '…전해상'). 상위구역 목록만 보면 새 구역을 놓친다."""
    return reg_up in SEA_PARENTS or "바다" in reg or "해상" in reg or "바다" in reg_up or "해상" in reg_up


def in_gyeongnam(reg_up: str, reg: str) -> bool:
    """특보 행이 경남 것인지 — 육상 미세분 / 육상 세분화 / 해상.

    바다는 경남 바다만 — 남해동부 먼바다 · 경남 앞바다(거제시동부 · 경남중부남해 · 경남서부남해 …). 부산 · 전남 · 남해서부는 뺀다.
    세분화된 군(합천 · 산청 · 함양 · 거창 · 하동)은 상위구역이 'OO군' 그대로일 때만.
    ⚠️ 예전에는 상위구역이 시군 이름으로 **시작**하기만 하면 경남으로 쳤다 — '남해서부먼바다'가 '남해'로 걸렸다."""
    if is_sea(reg_up, reg):
        if any(x in reg or x in reg_up for x in SEA_EXCLUDE):
            return False
        return reg_up in SEA_PARENTS or reg.startswith("남해동부") or any(k in reg for k in GN_SEA_KEYS)
    if reg_up == "경상남도":
        return True
    # 강원 고성(상위구역 '고성군')은 SUBZONES 에 없어 새어 들지 않는다(경남 고성은 늘 '경상남도')
    return reg_up.removesuffix("군") in SUBZONES


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


def pre_when(tm_ef: str) -> str:
    """예비특보 발효 예상 — '25일 새벽(03~06시)'. 시간대 코드가 아니면 '25일 12시', 모르면 그대로.
    ⚠️ 예전에는 시간대만 적어(새벽(03~06시)) 오늘인지 내일인지 몰랐다 — 태풍 예비특보는 하루 이틀 앞을 말한다."""
    t = (tm_ef or "").strip()
    if len(t) == 12 and t.isdigit():
        day = f"{int(t[6:8])}일"
        slot = pre_slot(t)
        return f"{day} {slot}" if slot else f"{day} {int(t[8:10])}시"
    return pre_slot(t) or t


# 기상청 예보 문구의 권역. 단기예보 통보문·예상강수량이 이 이름으로 나온다.
# (화면 이름, 시군들, 묶음, 상위 권역) — 묶음이 바뀌는 자리에 화면이 구분선을 긋는다.
# ⚠️ 경남서부내륙이 **위**, 북서내륙·남서내륙이 그 **아래**다. 기상청은 둘을 나눠
#    말할 때도, 합쳐 말할 때도 있어서 셋 다 두되 상하로 그린다.
# ⚠️ 경남중부남해안은 창원 하나뿐이라 '창원'으로 적는다 — 권역 이름이 더 길 뿐
#    가리키는 곳은 같다.
ZONES = [
    ("경남서부내륙",  ["함양", "거창", "합천", "진주", "하동", "산청"],  "서부내륙", None),
    ("북서내륙",      ["함양", "거창", "합천"],                        "서부내륙", "경남서부내륙"),
    ("남서내륙",      ["진주", "하동", "산청"],                        "서부내륙", "경남서부내륙"),
    ("경남중부내륙",  ["밀양", "의령", "함안", "창녕"],                 "중동부내륙", None),
    ("경남동부내륙",  ["김해", "양산"],                                "중동부내륙", None),
    ("창원",          ["창원"],                                       "남해안", None),
    ("경남서부남해안", ["통영", "사천", "거제", "고성", "남해"],          "남해안", None),
]

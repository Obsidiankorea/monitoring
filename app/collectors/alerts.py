"""기상특보 수집 — wrn_now_data.php.

⚠️ 응답 인코딩은 euc-kr.
⚠️ 레벨은 '경보'/'주의'다. '주의보'로 매칭하면 표가 통째로 빈다.
⚠️ 예비특보(CMD='예비')가 같은 응답에 섞여 온다. TM_EF는 시각이 아니라 시간대 코드다.
⚠️ 아직 발효 전인 특보도 함께 온다 — 집계에는 TM_EF <= 기준시각만 넣는다.
⚠️ 조회 실패를 '특보 없음'으로 처리하면 전부해제→전부신규 헛알림이 난다(pitfalls ★1).
"""
from __future__ import annotations

import logging
from datetime import datetime

from .. import db
from ..domain.regions import ORDER, in_gyeongnam, pre_slot, sigun_of, split_level
from ..kma import KmaError, fetch_text

log = logging.getLogger("collect.alerts")

# 컬럼 인덱스 — 실측으로 확인한 자리
I_REG_UP, I_REG, I_TM_FC, I_TM_EF, I_WRN, I_LVL, I_CMD = 1, 3, 4, 5, 6, 7, 8


def _rows(text: str) -> list[list[str]]:
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        # 행은 콤마로 나뉜다. 공백만 있는 형태도 있어 둘 다 받는다.
        parts = [c.strip() for c in (line.split(",") if "," in line else line.split())]
        if len(parts) > I_CMD:
            out.append(parts)
    return out


def normalize(text: str, now: datetime) -> dict:
    """행 → 화면이 바로 쓸 모양. 집계는 시군 수로만 센다."""
    groups: dict[tuple[str, str], dict] = {}
    pending: list[dict] = []
    stamp = now.strftime("%Y%m%d%H%M")

    for p in _rows(text):
        reg_up, reg = p[I_REG_UP], p[I_REG]
        if not in_gyeongnam(reg_up, reg):
            continue

        cmd = p[I_CMD]
        if cmd == "해제":
            continue

        name, lvl = split_level(p[I_WRN] + p[I_LVL])
        sea = reg_up in {"남해동부전해상", "남해동부앞바다"}
        # 화면 표기는 '주의보'로 통일한다. API가 주는 문자열은 '주의'다.
        disp_lvl = {"주의": "주의보"}.get(p[I_LVL], p[I_LVL])

        if cmd == "예비":
            pending.append({"kind": "pre", "name": p[I_WRN], "reg": reg,
                            "sigun": sigun_of(reg), "tmfc": p[I_TM_FC],
                            "when": pre_slot(p[I_TM_EF]) or p[I_TM_EF]})
            continue

        # 아직 발효 전인 것은 집계에서 빼고 따로 적는다
        if p[I_TM_EF] > stamp:
            pending.append({"kind": "later", "name": p[I_WRN] + disp_lvl, "reg": reg,
                            "sigun": sigun_of(reg), "tmef": p[I_TM_EF]})
            continue

        key = (p[I_WRN] + disp_lvl, "sea" if sea else "land")
        g = groups.setdefault(key, {"name": key[0], "sea": sea, "tmfc": p[I_TM_FC],
                                    "regions": [], "siguns": []})
        g["regions"].append(reg)
        g["tmfc"] = min(g["tmfc"], p[I_TM_FC])
        sig = sigun_of(reg)
        if sig and sig not in g["siguns"]:
            g["siguns"].append(sig)

    def lv_of(name: str) -> str:
        if "중대경보" in name:
            return "severe"
        return "warn" if name.endswith("경보") else "watch"

    out = []
    for g in groups.values():
        g["siguns"].sort(key=lambda s: ORDER.index(s) if s in ORDER else 99)
        out.append({
            "lv": lv_of(g["name"]), "name": g["name"], "sea": g["sea"],
            "tmfc": g["tmfc"][8:10] + ":" + g["tmfc"][10:12] if len(g["tmfc"]) >= 12 else g["tmfc"],
            # 해상은 시군 개념이 없어 개소로 셀 수밖에 없다
            "count": len(g["regions"]) if g["sea"] else len(g["siguns"]),
            "unit": "개소" if g["sea"] else "개시군",
            "regions": g["regions"], "siguns": g["siguns"],
        })

    order = {"severe": 0, "warn": 1, "watch": 2}
    out.sort(key=lambda a: (order.get(a["lv"], 3), a["sea"], -a["count"]))
    return {"groups": out, "pending": pending}


async def collect(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    at = now.strftime("%Y-%m-%d %H:%M")
    try:
        # tm 을 비우면 '현재 발효 중'. 특보는 예외 없이 실행 시점 최신으로 조회한다.
        text = await fetch_text("/api/typ01/url/wrn_now_data.php",
                                {"fe": "f", "tm": "", "disp": "1", "help": "0"})
    except KmaError as e:
        db.log_collect("alerts", False, at, str(e))
        raise

    data = normalize(text, now)
    db.put_snapshot("alerts", at, at, data)
    db.log_collect("alerts", True, at, f"{len(data['groups'])}종")
    return data

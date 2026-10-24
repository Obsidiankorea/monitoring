"""기상특보 수집 — wrn_now_data.php.

⚠️ 응답 모양이 둘이다. disp=1 은 2026.10 무렵부터 **JSON(UTF-8)** 으로 온다 — 예전엔 콤마 글(euc-kr)이었다.
   글로 읽으면 행이 0개라 '특보 없음'이 된다(09.30~10.19 내내 호우주의보를 못 봤다). 둘 다 읽고,
   읽은 행이 없는데 본문에 자료가 있으면 실패로 올린다 — 모양이 또 바뀌어도 '특보 없음'으로 숨지 않게.
⚠️ 레벨은 '경보'/'주의'다. '주의보'로 매칭하면 표가 통째로 빈다.
⚠️ 예비특보(CMD='예비')가 같은 응답에 섞여 온다. TM_EF는 시각이 아니라 시간대 코드다.
   태풍 예비특보처럼 하루 이틀 앞을 말하기도 해 **날짜를 붙여** 적는다('25일 새벽(03~06시)'). 레벨 칸이나
   특보 이름에 '예비'가 붙어 와도 예비로 읽는다 — 발효 중인 '태풍예비' 특보로 잘못 세지 않게(10-24).
⚠️ 아직 발효 전인 특보도 함께 온다 — 집계에는 TM_EF <= 기준시각만 넣는다.
⚠️ 조회 실패를 '특보 없음'으로 처리하면 전부해제→전부신규 헛알림이 난다(pitfalls ★1).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime

from .. import db
from ..domain.regions import ORDER, in_gyeongnam, is_sea, pre_when, sigun_of, split_level
from ..kma import KmaError, fetch_bytes

log = logging.getLogger("collect.alerts")

# 컬럼 인덱스 — 실측으로 확인한 자리(JSON 은 같은 차례의 키로 온다)
I_REG_UP, I_REG, I_TM_FC, I_TM_EF, I_WRN, I_LVL, I_CMD = 1, 3, 4, 5, 6, 7, 8
KEYS = ("REG_UP", "REG_UP_KO", "REG_ID", "REG_KO", "TM_FC", "TM_EF", "WRN", "LVL", "CMD", "ED_TM")


def parse(raw: bytes | str) -> list[list[str]]:
    """응답 → 행(글자 칸 목록). JSON(UTF-8) · 콤마/공백 글(euc-kr) 둘 다.
    읽은 행이 없는데 본문에 자료 줄이 있으면 KmaError — 모양이 낯선 것을 '특보 없음'으로 넘기지 않는다."""
    if isinstance(raw, bytes):
        head = raw.lstrip()[:1]
        raw = raw.decode("utf-8" if head in (b"[", b"{") else "euc-kr", errors="replace")
    t = raw.strip()
    if t[:1] in ("[", "{"):
        try:
            j = json.loads(t)
        except ValueError as e:
            raise KmaError(f"특보 JSON 을 못 읽었다: {e}") from e
        if isinstance(j, dict):                       # {"data": [...]} 처럼 감싸 올 때
            j = next((v for v in j.values() if isinstance(v, list)), None)
        if not isinstance(j, list):
            raise KmaError("특보 JSON 모양이 낯설다(목록이 아니다)")
        rows = [[str(x.get(k) or "").strip() for k in KEYS] for x in j if isinstance(x, dict)]
        if len(rows) != len(j) or any(not r[I_WRN] for r in rows):
            raise KmaError("특보 JSON 키가 낯설다(REG_UP_KO · WRN …)")
        return rows
    rows = _rows(t)
    if not rows and any(ln.strip() and not ln.strip().startswith("#") for ln in t.splitlines()):
        raise KmaError(f"특보 응답 모양이 낯설다: {t[:80]!r}")
    return rows


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


def normalize(raw: bytes | str, now: datetime) -> dict:
    """응답 → 화면이 바로 쓸 모양. 집계는 시군 수로만 센다."""
    groups: dict[tuple[str, str], dict] = {}
    pending: list[dict] = []
    stamp = now.strftime("%Y%m%d%H%M")

    for p in parse(raw):
        reg_up, reg = p[I_REG_UP], p[I_REG]
        if not in_gyeongnam(reg_up, reg):
            continue

        cmd = p[I_CMD]
        if cmd == "해제":
            continue

        name, lvl = split_level(p[I_WRN] + p[I_LVL])
        sea = is_sea(reg_up, reg)          # 이름으로 — 바다 구역은 시군에 붙이지 않는다
        # 화면 표기는 '주의보'로 통일한다. API가 주는 문자열은 '주의'다.
        disp_lvl = {"주의": "주의보"}.get(p[I_LVL], p[I_LVL])

        if cmd == "예비" or p[I_LVL] == "예비" or p[I_WRN].endswith("예비"):
            pending.append({"kind": "pre", "name": p[I_WRN].removesuffix("예비"), "reg": reg, "sea": sea,
                            "sigun": None if sea else sigun_of(reg), "tmfc": p[I_TM_FC],
                            "when": pre_when(p[I_TM_EF])})
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
        sig = None if sea else sigun_of(reg)
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
        raw = await fetch_bytes("/api/typ01/url/wrn_now_data.php",
                                {"fe": "f", "tm": "", "disp": "1", "help": "0"})
        data = normalize(raw, now)
    except KmaError as e:
        db.log_collect("alerts", False, at, str(e))
        raise

    db.put_snapshot("alerts", at, at, data)
    db.log_collect("alerts", True, at, f"{len(data['groups'])}종")
    return data

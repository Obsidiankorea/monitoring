"""지하차도 침수 위험 경보 — 국가교통정보센터 재난상황정보(openapi.its.go.kr), 범례 '하천 · 댐'에 목록으로.

호출이 월 1000건으로 묶여 있어 경남에 호우특보가 있을 때만 15분마다 부른다(평시 0건). 이 경보는 호우경보에서 만들어지므로 평시에 받을 것이 없다.
⚠️ 실제 응답은 기술기준과 다르다(2026-07~08 192건 확인) — body.items · 침수 건은 좌표 · 도로명 · 지하차도 이름이 비었고, 좌표가 없어 영역 조건에도 안 걸러져 전국이 온다.
   그래서 지도에 찍지 못하고, 지역 이름과 링크 번호 앞 두 자리(38 = 경남, 진주 · 밀양 표본으로 확인)로만 가른다.
⚠️ 해제되어도 endDate 가 '-' 로 남는 건이 있다 — 어제 · 오늘 발생한 것만 보고, 호우특보가 끝나면 비운다. 키는 NAS 서버에만 둔다(같은 키로 두 곳이 부르면 한도가 두 배로 줄어든다).
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta

import httpx

from . import config, db, queries

log = logging.getLogger("its")

URL = "https://openapi.its.go.kr:9443/disasterInfo"
STOP_AT = 950                                              # 월 1000건 — 시험 호출 몫을 남기고 멈춘다
SIGUN = re.compile("창원|마산|진해|진주|통영|사천|김해|밀양|거제|양산|의령|함안|창녕|고성|남해|하동|산청|함양|거창|합천")

_LIVE: dict = {"at": None, "err": None, "rows": []}


def _key() -> str:
    return config.KEYS.get("ITS_KEY", "")


def hoou() -> bool:
    """경남에 호우특보가 발효 중인가."""
    return any(g["name"].startswith("호우") for g in queries.alerts()["data"]["groups"])


def calls(now: datetime) -> int:
    d = db.get_setting("its_calls", {}) or {}
    return d.get("n", 0) if d.get("ym") == f"{now:%Y%m}" else 0


def parse(j: dict, now: datetime) -> list[dict]:
    """응답 → 지금 걸린 경남 침수 위험 경보. 범람 건도 같은 모양일 것으로 보고 받는다(2026 여름 0건, 실물 미확인)."""
    out = []
    for x in ((j.get("body") or {}).get("items") or []):
        name = re.sub(r"^.*\]|호우경보", "", x.get("socName") or "").strip()
        links = [k for k in (x.get("linkId") or "").split(",") if k]
        end = x.get("endDate") or "-"
        # shortcut: 강원 고성도 지역 이름에 걸린다, 호우특보 시군과 맞출 일이 생기면 그때 좁힌다
        gn = SIGUN.search(name) or any(k.startswith("38") for k in links)
        if x.get("eventType") in ("D03", "D04") and gn and (end == "-" or end[:12] > f"{now:%Y%m%d%H%M}"):
            out.append({"name": name or "지역 이름 없음", "type": x["eventType"], "at": (x.get("startDate") or "")[:12], "links": len(links)})
    return sorted(out, key=lambda r: r["at"], reverse=True)


async def run() -> None:
    """스케줄러가 15분마다 부른다 — 호우특보가 없으면 부르지 않는다."""
    now = datetime.now()
    if config.DEMO or not _key():
        return
    if not hoou():
        _LIVE.update(rows=[], err=None)
        return
    n = calls(now)
    if n >= STOP_AT:
        _LIVE["err"] = f"이번 달 {n}건 — 다음 달까지 멈춤"
        return
    db.put_setting("its_calls", {"ym": f"{now:%Y%m}", "n": n + 1})   # 실패한 호출도 한도에 든다
    try:
        async with httpx.AsyncClient(timeout=30, verify=config.VERIFY_SSL) as cli:
            r = await cli.get(URL, params={"apiKey": _key(), "category": "D", "eventType": "D03,D04", "getType": "json",
                                           "startDate": f"{now - timedelta(days=1):%Y%m%d}", "endDate": f"{now:%Y%m%d}"})
            r.raise_for_status()
            j = r.json()
        if (j.get("header") or {}).get("resultCode") != 0:
            raise RuntimeError(str((j.get("header") or {}).get("resultMsg")))
        _LIVE.update(at=now.isoformat(timespec="seconds"), err=None, rows=parse(j, now))
    except Exception as e:                                    # noqa: BLE001
        _LIVE["err"] = str(e)[:160].replace(_key(), "***")
        log.warning("재난상황정보 수집 실패: %s", _LIVE["err"])


def status() -> dict:
    return {"on": bool(_key()) or bool(_LIVE["rows"]), "active": hoou(), "calls": calls(datetime.now()), **_LIVE}

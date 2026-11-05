"""인명피해 우려지역 지구 → 좌표(메모리 POS). 순서: 사람이 적은 좌표 > 연속지적도로 찾은 좌표 > 브이월드(나머지만).

① 위키 data/지구좌표_수동.csv(지역ID,위도,경도) — 사람이 적은 것, 저장 가능.
② 위키 data/지구좌표.csv — tools/build_parcels.py 가 연속지적도(공개 자료)로 만든 것, 저장 가능. 외부 서비스 없이 켜자마자 다 있다.
③ 둘 다 없는 지구만 브이월드 지오코더(VWORLD_KEY 가 있을 때). ⚠️ 약관: 응답은 저장 금지 → 메모리에만, 켤 때마다 다시.
좌표가 없는 지구는 읍면동 기준으로 계산한다.
"""
from __future__ import annotations

import asyncio
import csv
import logging
from datetime import datetime

import httpx

from . import ai, config

log = logging.getLogger(__name__)
URL = "https://api.vworld.kr/req/address"
GU = {"의창구", "성산구", "마산합포구", "마산회원구", "진해구"}   # 창원은 지구명 칸에 구가 들어 있다('횡천지구' 같은 지구 이름과 구별)

POS: dict[str, tuple[float, float]] = {}    # 지역ID → (위도, 경도) — 메모리에만
APPROX: set[str] = set()                     # 리 · 읍면동 가운데로 찍은 근사 — 지도에만, 판정(지구 자리 비)에는 안 쓴다
FAIL: dict[str, str] = {}                    # 지역ID → 못 찾은 이유
STATE = {"state": "대기", "total": 0, "done": 0, "found": 0, "manual": 0, "at": None, "err": ""}


def address(w: dict) -> str:
    """경상남도 + 시군 + (창원 구) + 읍면동 + 리 + 지번. 빈칸 표시 '–' 와 '번지' 는 뺀다."""
    gu = (w.get("지구명") or "").strip()
    parts = ["경상남도", w.get("시군", ""), gu if gu in GU else "", w.get("읍면동", ""), w.get("리", ""),
             (w.get("지번") or "").replace("번지", "")]
    return " ".join(p.strip() for p in parts if p and p.strip() not in ("", "–", "-"))


def parse(j: dict) -> tuple[float, float] | str:
    """브이월드 응답 → (위도, 경도) 또는 못 찾은 이유."""
    r = j.get("response") or {}
    if r.get("status") != "OK":
        return (r.get("error") or {}).get("text") or r.get("status") or "응답 이상"
    p = (r.get("result") or {}).get("point") or {}
    try:
        lat, lon = float(p["y"]), float(p["x"])
    except (KeyError, TypeError, ValueError):
        return "좌표 없음"
    if not (34.4 < lat < 35.95 and 127.5 < lon < 129.5):          # 경남 밖이면 엉뚱한 곳을 찍은 것
        return f"경남 밖({lat:.3f},{lon:.3f})"
    return lat, lon


def _key_error(why: str) -> bool:
    return any(s in why for s in ("인증키", "KEY", "제한량"))


async def ask(cli: httpx.AsyncClient, key: str, addr: str) -> tuple[float, float] | str:
    """지번(PARCEL)으로 먼저, 못 찾으면 도로명(ROAD)으로 — 지번 칸에 도로명이 든 지구가 있다."""
    why = ""
    for kind in ("PARCEL", "ROAD"):
        q = {"service": "address", "request": "getcoord", "version": "2.0", "crs": "epsg:4326", "address": addr,
             "refine": "true", "simple": "false", "format": "json", "type": kind, "key": key}
        for n in range(4):                                          # 브이월드가 한꺼번에 받으면 연결을 끊는다 — 쉬었다 다시
            try:
                r = parse((await cli.get(URL, params=q)).json())
                break
            except Exception as e:                                  # noqa: BLE001 — 한 곳 실패가 전체를 멈추지 않게
                r = f"요청 실패 {type(e).__name__}"
                await asyncio.sleep(1.5 * 2 ** n)
        if isinstance(r, tuple):
            return r
        why = why or r
        if _key_error(r):                                           # 키 · 한도 문제면 도로명으로 다시 물어도 같다
            break
    return why


def _manual(name: str = "지구좌표_수동.csv") -> dict[str, tuple[float, float]]:
    out = {}
    try:
        with open(ai.wiki() / "data" / name, encoding="utf-8-sig", newline="") as f:
            for w in csv.DictReader(f):
                try:
                    out[w["지역ID"].strip()] = (float(w["위도"]), float(w["경도"]))
                except (KeyError, ValueError, AttributeError):
                    continue
    except OSError:
        pass
    return out


def _approx() -> set[str]:
    try:
        with open(ai.wiki() / "data" / "지구좌표.csv", encoding="utf-8-sig", newline="") as f:
            return {w["지역ID"] for w in csv.DictReader(f) if (w.get("방법") or "").endswith("중심")}
    except OSError:
        return set()


def exact() -> dict[str, tuple[float, float]]:
    """판정에 쓸 좌표 — 근사(리 · 읍면동 가운데)는 뺀다. 한 점으로 비를 보면 읍면동 최대 칸보다 덜 잡을 수 있다."""
    return {k: v for k, v in POS.items() if k not in APPROX}


def _rows() -> list[dict]:
    try:
        with open(ai.wiki() / "data" / "인명피해 우려지역.csv", encoding="utf-8-sig", newline="") as f:
            return [w for w in csv.DictReader(f) if w.get("지역ID")]
    except OSError:
        return []


async def run() -> None:
    """한 번 돈다 — 서버가 켜질 때. 이미 도는 중이면 그냥 돌아간다."""
    if STATE["state"] == "받는 중":
        return
    key = config.KEYS.get("VWORLD_KEY", "")
    rows = _rows()
    man = {**_manual("지구좌표.csv"), **_manual()}                  # 지적도 위에 사람이 적은 것
    APPROX.clear()
    APPROX.update(_approx() - set(_manual()))
    POS.update(man)
    STATE.update(state="받는 중", total=len(rows), done=0, found=len(POS), manual=len(man), err="", at=None)
    if all(w["지역ID"] in man and w["지역ID"] not in APPROX for w in rows):
        STATE.update(state="끝", done=len(rows), at=datetime.now().isoformat(timespec="seconds"))
        return
    if not key:
        STATE.update(state="키 없음", done=len(rows), err=f"좌표 없는 {len(rows) - len(man)}곳 · 근사 {len(APPROX)}곳은 읍면동 기준(VWORLD_KEY 없음)")
        return
    sem = asyncio.Semaphore(2)                                      # 5개씩이면 절반이 끊겼다(2026-11 시험)

    async def one(cli: httpx.AsyncClient, w: dict) -> None:
        rid = w["지역ID"]
        if (rid not in man or rid in APPROX) and not STATE["err"]:      # 근사(리 · 읍면동 가운데)는 브이월드로 정확한 점을 찾아 본다
            async with sem:
                r = await ask(cli, key, address(w))
                await asyncio.sleep(0.1)
            if isinstance(r, tuple):
                POS[rid] = r
                APPROX.discard(rid)
                FAIL.pop(rid, None)
            else:
                FAIL[rid] = r
                if _key_error(r):
                    STATE["err"] = r                                # 남은 곳은 묻지 않는다
        STATE["done"] += 1
        STATE["found"] = len(POS)

    async with httpx.AsyncClient(timeout=15, verify=config.VERIFY_SSL) as cli:
        await asyncio.gather(*(one(cli, w) for w in rows))
    STATE.update(state="오류" if STATE["err"] else "끝", at=datetime.now().isoformat(timespec="seconds"))
    log.info("지구 좌표 %d/%d곳(수동 %d) — 못 찾음 %d%s", len(POS), len(rows), len(man), len(FAIL),
             f" · {STATE['err']}" if STATE["err"] else "")


def status() -> dict:
    """화면용 — 좌표 값은 지구 자료(districts)로 주고, 여기는 진행 상황과 못 찾은 이유 묶음만."""
    why: dict[str, int] = {}
    for v in FAIL.values():
        why[v] = why.get(v, 0) + 1
    return {**STATE, "fail": len(FAIL), "why": dict(sorted(why.items(), key=lambda x: -x[1])[:5])}

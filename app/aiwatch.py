"""AI 기준 근접 알림 — 사람이 팝업을 열지 않아도, 위키 기준(통제 · 사전대피 · 긴급대피)에 가까워지거나 닿으면 텔레그램으로 알린다.

켜고 끄는 것은 설정(지도 › AI 알림 · DB ai_alert). **기본은 끔**이고, 켜는 서버(서버 한 곳)에서만 켠다 — PC 와 서버를 둘 다 켜면 같은 알림이 두 번 간다.
5분마다 aireport 가 쓰는 같은 판정(app/ai.py ladders)을 읽어서, **새로 생겼거나 한 단계 올라간 것**만 보낸다(같은 상태는 다시 보내지 않는다).
  · 사전대피 · 긴급대피: 근접(70%↑) 또는 충족  · 통제: 충족  · 비상단계가 오르면 그것도
⚠️ 토큰 · 채팅 번호는 config/api_keys.txt(TELEGRAM_BOT_TOKEN · TELEGRAM_CHAT_ID)에서만. 오류 글에서 토큰은 지운다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime

import httpx

from . import ai, aireport, config, db

log = logging.getLogger("aiwatch")

RANK = {"near": 1, "met": 2}
KEEP_S = 3600            # 이만큼 안 보이던 것은 상태에서 지운다(다시 생기면 새로 알린다)
MAX_LINES = 10          # 문자 한 통에 읍면동 줄 몇 개까지
STAGE_RANK = {"긴급대피": 3, "사전대피": 2, "통제": 1}


def cfg() -> dict:
    return {"on": False, **(db.get_setting("ai_alert", {}) or {})}


def ready() -> bool:
    return bool(config.KEYS.get("TELEGRAM_BOT_TOKEN") and config.KEYS.get("TELEGRAM_CHAT_ID"))


def _mask(text: object) -> str:
    t = str(text)
    tok = config.KEYS.get("TELEGRAM_BOT_TOKEN") or ""
    return t.replace(tok, "***") if tok else t


async def send(text: str) -> None:
    tok, chat = config.KEYS["TELEGRAM_BOT_TOKEN"], config.KEYS["TELEGRAM_CHAT_ID"]
    async with httpx.AsyncClient(timeout=15, verify=config.VERIFY_SSL) as c:
        r = await c.post(f"https://api.telegram.org/bot{tok}/sendMessage", json={"chat_id": chat, "text": text[:3800]})
        if r.status_code != 200:
            raise RuntimeError(f"텔레그램 {r.status_code}")


def _scan(base: str) -> dict[str, tuple[str, tuple]]:
    """지금 알릴 만한 것 — {열쇠: (상태, (시군, 읍면동, 유형, 단계, 기준))}. 비상단계는 시군 자리에 '도'."""
    o = aireport.overview(base)
    out: dict[str, tuple[str, str]] = {}
    if o["stage"]:
        out[f"stage|{o['stage']['stage']}"] = ("met", ("도", o["stage"]["stage"], "비상단계", "", o["stage"]["why"]))
    focus = [r["sigun"] for r in o["rows"]
             if r["relay"] or r["cbs"] or r["alerts"] or (r["fc_sum"] or 0) >= 30 or (r["fc_peak"] or 0) >= 20][:8]
    for sg in focus:
        s = aireport.situation(sg, base)
        for e in s["emd"]:
            for fam, cs in e["ladders"].items():
                for c in cs:
                    ok = c["st"] == "met" or (c["st"] == "near" and c["stage"] != "통제")
                    if not ok:
                        continue
                    k = f"{sg}|{e['emd']}|{fam}|{c['stage']}|{c['rule']}"
                    out[k] = (c["st"], (sg, e["emd"], fam, c["stage"], c["rule"]))
    return out


_SNAP: dict = {"t": 0.0, "v": None}
SNAP_TTL = 120          # 화면이 몇 초마다 물어도 이만큼은 같은 판정을 돌려 준다(훑는 데 수 초)


def snapshot(base: str) -> dict:
    """화면용 — 지금 기준에 가까워졌거나 닿은 곳(텔레그램 켜고 끄는 것과 무관). 시군별로 묶어 센 것 먼저."""
    now_t = time.time()
    if _SNAP["v"] is not None and now_t - _SNAP["t"] < SNAP_TTL:
        return _SNAP["v"]
    found = _scan(base)
    items = [{"sigun": x[0], "emd": x[1], "fam": x[2], "stage": x[3], "rule": x[4], "st": st}
             for st, x in found.values()]
    stage = next((i for i in items if i["fam"] == "비상단계"), None)
    items = [i for i in items if i["fam"] != "비상단계"]
    items.sort(key=lambda i: (-STAGE_RANK.get(i["stage"], 0), -RANK.get(i["st"], 0), i["sigun"], i["emd"]))
    sg: dict[str, dict] = {}
    for i in items:
        d = sg.setdefault(i["sigun"], {"met": 0, "near": 0, "top": 0})
        d[i["st"]] += 1
        d["top"] = max(d["top"], STAGE_RANK.get(i["stage"], 0) * 10 + RANK[i["st"]])
    out = {"at": datetime.now().strftime("%m.%d %H:%M"), "n": len(items), "stage": stage["emd"] if stage else None,
           "sigun": sg, "items": items}
    _SNAP.update(t=now_t, v=out)
    return out


def _diff(now: dict, state: dict, ts: float) -> tuple[list, dict]:
    """새로 생겼거나 상태가 올라간 것만 골라 낸다. 상태는 보이는 것만 남기고 KEEP_S 지난 것은 지운다."""
    new = [(st, x) for k, (st, x) in now.items()
           if k not in state or RANK.get(st, 0) > RANK.get(state[k][0], 0)]
    keep = {k: v for k, v in state.items() if k not in now and ts - v[1] < KEEP_S}
    keep.update({k: [st, ts] for k, (st, _) in now.items()})
    return new, keep


def _msg(new: list, tm: str) -> str:
    """읍면동마다 한 줄 — 같은 읍면동의 여러 기준은 단계가 센 것부터 묶는다."""
    stage = [x for st, x in new if x[2] == "비상단계"]
    by: dict[tuple, dict] = {}
    for st, (sg, emd, fam, stg, rule) in new:
        if fam == "비상단계":
            continue
        d = by.setdefault((sg, emd), {})
        k = (fam, stg)
        d[k] = max(d.get(k, 0), 2 if st == "met" else 1)
    ranked = sorted(by.items(), key=lambda kv: -max(STAGE_RANK[k[1]] * 10 + v for k, v in kv[1].items()))
    lines = [f"도 비상단계 기준 {x[1]} — {x[4]}" for x in stage]
    for (sg, emd), d in ranked[:MAX_LINES]:
        parts = [f"{fam} {stg} {'충족' if v == 2 else '근접'}" for (fam, stg), v in sorted(d.items(), key=lambda kv: -(STAGE_RANK[kv[0][1]] * 10 + kv[1]))]
        lines.append(f"{sg} {emd} — " + " · ".join(parts[:3]))
    more = len(ranked) - MAX_LINES
    head = f"⚠️ 경남 AI 상황판단 — {tm} 기준에 가까워졌거나 닿은 곳 {len(ranked)}곳" + (f" · {stage[0][1]} 진입" if stage else "")
    return "\n".join([head, *[f"• {x}" for x in lines], *([f"… 외 {more}곳"] if more > 0 else []), "",
                      "지도에서 I 키(AI 상황판단)로 대상 지구 · 대피장소를 본다. 판단 · 대피명령은 권한자(시장 · 군수) — 기준과의 대조일 뿐이다."])


async def run() -> dict:
    if config.DEMO or not cfg()["on"]:
        return {"skipped": "꺼 둠"}
    if not ready():
        return {"skipped": "텔레그램 키 없음"}
    base = f"http://127.0.0.1:{os.environ.get('PORT', '8000')}"
    at = datetime.now().strftime("%m.%d %H:%M")
    try:
        now = await asyncio.to_thread(_scan, base)
        new, state = _diff(now, db.get_setting("ai_alert_state", {}) or {}, time.time())
        if new:
            await send(_msg(new, at))
        db.put_setting("ai_alert_state", state)             # 보낸 뒤에 기억 — 보내다 실패하면 다음에 다시 시도
        db.put_setting("ai_alert_last", {"at": at, "sent": len(new), "seen": len(now), "err": ""})
        return {"sent": len(new), "seen": len(now)}
    except Exception as e:                                  # noqa: BLE001
        err = _mask(e)[:200]
        log.warning("AI 알림 실패: %s", err)
        db.put_setting("ai_alert_last", {"at": at, "sent": 0, "seen": 0, "err": err})
        return {"error": err}


def status() -> dict:
    return {**cfg(), "ready": ready(), "last": db.get_setting("ai_alert_last", {}) or {}, "every_s": 300}

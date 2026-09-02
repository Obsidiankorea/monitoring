"""FastAPI 진입점 — 수집기(스케줄러)와 웹을 한 프로세스에 둔다.

핵심 원칙: 화면을 열 때 기상청을 부르지 않는다.
수집기가 주기적으로 받아 DB에 넣고, 웹은 저장된 것을 읽기만 한다.
그래야 접속자가 몇이든 기상청 호출은 한 번이고, API가 죽어도 마지막 정상
자료가 화면에 남는다.
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, queries
from .collectors import alerts, forecast, qpf, rain
from .config import CACHE, INTERVALS, POLL_DEFAULT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
# ⚠️ httpx는 요청 URL을 통째로 찍는다 — authKey가 로그 파일에 그대로 남는다.
logging.getLogger("httpx").setLevel(logging.WARNING)
log = logging.getLogger("main")

STATIC = Path(__file__).parent / "web" / "static"

COLLECTORS = {"rain": rain.collect, "forecast": forecast.collect,
              "alerts": alerts.collect, "qpf": qpf.collect}

# 한 자료를 두 번 동시에 받지 않게 — 주기가 겹치거나 수동 조회가 끼어들 수 있다
_locks = {k: asyncio.Lock() for k in COLLECTORS}


async def run_one(kind: str, force: bool = False) -> dict:
    if kind not in COLLECTORS:
        raise HTTPException(404, f"모르는 수집기: {kind}")
    async with _locks[kind]:
        try:
            fn = COLLECTORS[kind]
            # 수동 조회는 감시 구간을 무시하고 실제로 다녀온다
            res = await (fn(force=True) if force and kind == "qpf" else fn())
            return {"ok": True, "kind": kind, "result": res}
        except Exception as e:                       # noqa: BLE001
            log.warning("%s 수집 실패: %s", kind, e)
            db.log_collect(kind, False, datetime.now().strftime("%Y-%m-%d %H:%M"), str(e))
            return {"ok": False, "kind": kind, "error": str(e)}


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    sched = AsyncIOScheduler(timezone="Asia/Seoul")   # 시각은 전부 KST. UTC로 바꾸지 않는다.
    for kind, sec in INTERVALS.items():
        sched.add_job(run_one, "interval", seconds=sec, args=[kind],
                      id=kind, max_instances=1, coalesce=True)
    sched.start()
    # 뜨자마자 한 번씩 받아 둔다 — 빈 화면으로 시작하지 않게
    for kind in COLLECTORS:
        asyncio.create_task(run_one(kind))
    log.info("수집기 시작: %s", INTERVALS)
    try:
        yield
    finally:
        sched.shutdown(wait=False)


app = FastAPI(title="경남 기상 대시보드", lifespan=lifespan)


@app.get("/api/rain")
async def api_rain(hours: int = Query(12, ge=1, le=72)):
    return queries.rain(hours)


@app.get("/api/forecast")
async def api_forecast(hours: int = Query(6, ge=1, le=6)):
    return queries.forecast(hours)


@app.get("/api/alerts")
async def api_alerts():
    return queries.alerts()


@app.get("/api/qpf")
async def api_qpf():
    return queries.qpf_frames()


@app.get("/api/qpf/{tmfc}/{ef}.png")
async def api_qpf_frame(tmfc: str, ef: int):
    p = CACHE / "qpf" / tmfc / f"{ef:03d}.png"
    if not p.exists():
        raise HTTPException(404, "없는 프레임")
    # 프레임은 한 번 만들어지면 바뀌지 않는다 — 오래 캐시해도 된다
    return FileResponse(p, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/status")
async def api_status():
    return {"collect": queries.status(), "poll": POLL_DEFAULT, "intervals": INTERVALS,
            "qpf": qpf.cfg(), "publish": db.publish_stats()}


@app.get("/api/settings")
async def api_settings_get():
    """설정은 서버에 둔다 — 벽면 화면이라 어느 브라우저에서 바꿔도 같이 가야 한다."""
    c = qpf.cfg()
    return {"qpf": c, "frames": len(qpf.frame_efs(c)),
            "publish": db.publish_stats(), "intervals": INTERVALS}


@app.put("/api/settings/qpf")
async def api_settings_qpf(body: dict):
    cur = qpf.cfg()
    allowed = {"step": (10, 20, 30), "ahead": (180, 240, 360),
               "size": (600, 900, 1200, 1800), "keep": tuple(range(1, 7))}
    for k, ok in allowed.items():
        if k in body:
            try:
                v = int(body[k])
            except (TypeError, ValueError):
                raise HTTPException(400, f"{k}: 숫자가 아니다")
            if v not in ok:
                raise HTTPException(400, f"{k}: {ok} 중 하나여야 한다")
            cur[k] = v
    for k in ("watch_from", "watch_to"):
        if k in body:
            cur[k] = max(0, min(10, int(body[k])))
    if cur["watch_from"] >= cur["watch_to"]:
        raise HTTPException(400, "감시 시작이 끝보다 늦다")
    db.put_setting("qpf", cur)
    return {"qpf": cur, "frames": len(qpf.frame_efs(cur))}


@app.post("/api/refresh/{kind}")
async def api_refresh(kind: str, force: bool = False):
    """수동 조회. ⚠️ 주기와 무관하게 실제로 다녀온다.

    내부 주기 함수를 그냥 부르면 '이미 처리함' 분기로 빠져 아무 일도
    일어나지 않는다(pitfalls ★3). 여기서는 항상 수집기를 직접 부른다.
    """
    return await run_one(kind, force=force)


if STATIC.exists():
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


if __name__ == "__main__":
    # 포트는 PORT 환경변수를 따른다 — 없으면 8000.
    # 하드코딩하면 이미 쓰는 포트와 부딪힌다.
    import os

    import uvicorn

    uvicorn.run("app.main:app", host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))

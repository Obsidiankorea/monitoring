"""FastAPI 진입점 — 수집기(스케줄러)와 웹을 한 프로세스에 둔다.

핵심 원칙: 화면을 열 때 기상청을 부르지 않는다.
수집기가 주기적으로 받아 DB에 넣고, 웹은 저장된 것을 읽기만 한다.
그래야 접속자가 몇이든 기상청 호출은 한 번이고, API가 죽어도 마지막 정상
자료가 화면에 남는다.
"""
from __future__ import annotations

import asyncio
import gzip
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import db, demo, gridcase, gridstore, gridview, maint, queries, update
from .collectors import alerts, bangjae_rain, forecast, grid_rain, qpf, rain, shortfc
from .config import CACHE, INTERVALS, POLL_DEFAULT

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
# ⚠️ httpx는 요청 URL을 통째로 찍는다 — authKey가 로그 파일에 그대로 남는다.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("collect.qpf").setLevel(logging.DEBUG)
log = logging.getLogger("main")

STATIC = Path(__file__).parent / "web" / "static"

#: 이 코드로 끝나면 실행 스크립트가 다시 띄운다. 다른 코드면 그냥 끝난다.
RESTART_CODE = 42

COLLECTORS = {"rain": rain.collect, "forecast": forecast.collect,
              "alerts": alerts.collect, "qpf": qpf.collect,
              # 스방은 기상청과 **다른 서버**라 따로 돈다(계정 없으면 조용히 건너뜀)
              "bangjae": bangjae_rain.collect,
              # 단기예보 격자 — 권역·시군 예보 판. 받은 발표분은 다시 부르지 않는다.
              "short": shortfc.collect,
              # 경남 지도 — 500m 격자(15분·60분·일)와 실황 5km. 경남 bbox 만 잘라 둔다.
              "grid": grid_rain.collect, "odam": grid_rain.collect_odam}

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


async def _nightly() -> None:
    if not maint.cfg().get("auto", True):
        return
    res = await asyncio.to_thread(maint.cleanup)
    log.info("정리: %s · %.1fMB 회수", res["removed"], res["freed_bytes"] / 1048576)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    if os.environ.get("NO_COLLECT") == "1":
        # 화면만 띄운다(개발용). ⚠️ 같은 PC 에서 수집기가 둘 돌면 기상청 호출이 두 배가 된다.
        log.info("수집기 끔(NO_COLLECT) — 저장된 자료만 보여 준다")
        app.state.sched = None
        yield
        return
    sched = AsyncIOScheduler(timezone="Asia/Seoul")   # 시각은 전부 KST. UTC로 바꾸지 않는다.
    app.state.sched = sched
    for kind, sec in db.get_setting("intervals", INTERVALS).items():
        sched.add_job(run_one, "interval", seconds=sec, args=[kind],
                      id=kind, max_instances=1, coalesce=True)
    # 하루 한 번 묵은 자료 치우기 — 안 하면 DB 와 이미지 캐시가 계속 자란다
    sched.add_job(_nightly, "cron", hour=4, minute=20, id="maint",
                  max_instances=1, coalesce=True)
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
async def api_rain(hours: int = Query(12, ge=1, le=72),
                   src: str = Query("kma", pattern="^(kma|bangjae)$")):
    """지점별 강수량. `src=bangjae` 면 스방 265개소.

    화면이 더 긴 구간을 고르면 그만큼 과거를 채운다.
    ⚠️ 그 전에는 26시간 앞이 영원히 비어 있었다 — '2일'을 골라도 그래프 왼쪽이
       통째로 빈 채였다. 여기서 깊이를 올리고 곧바로 한 번 받아 온다.
    """
    grew = rain.want_depth(hours)
    out = queries.rain(hours, src=src)
    # 빈 시각이 있으면 지금 채운다. 이미 받는 중이면 겹쳐 부르지 않는다.
    kind = "bangjae" if src == "bangjae" else "rain"
    if (grew or out.get("missing")) and not _locks[kind].locked():
        asyncio.create_task(run_one(kind))
        out["filling"] = True
    return out


@app.get("/api/forecast")
async def api_forecast(hours: int = Query(6, ge=1, le=6), sigun: str | None = None):
    """`sigun=` 이면 그 시군 읍면동 전부(emd_sigun)를 더 준다 — 지도 판 시군 상세."""
    return queries.forecast(hours, sigun=sigun)


@app.get("/api/short")
async def api_short():
    """단기예보 — 권역·시군별 예상강수량 격자 분포(오늘·내일·모레)."""
    return queries.short()


@app.get("/api/minute")
async def api_minute(n: int = Query(8, ge=1, le=20)):
    """지금 가장 세게 오는 곳 — 15분·60분 강수량 상위. 기상청 매분자료만 쓴다."""
    return queries.minute_top(n)


@app.get("/api/alerts")
async def api_alerts():
    return queries.alerts()


@app.get("/api/qpf")
async def api_qpf():
    return queries.qpf_frames()


@app.get("/api/qpf/legend")
async def api_qpf_legend():
    """예측 분포 범례 — 색은 기상청 원본 그림에서 그대로 뽑은 것이다."""
    lg = qpf.legend()
    if not lg:
        raise HTTPException(404, "아직 범례를 뽑지 못했다")
    return lg


@app.get("/api/qpf/{tmfc}/{ef}.png")
async def api_qpf_frame(tmfc: str, ef: int):
    p = CACHE / "qpf" / tmfc / f"{ef:03d}.png"
    if not p.exists():
        raise HTTPException(404, "없는 프레임")
    # 프레임은 한 번 만들어지면 바뀌지 않는다 — 오래 캐시해도 된다
    return FileResponse(p, media_type="image/png",
                        headers={"Cache-Control": "public, max-age=86400"})


@app.get("/api/grid/meta")
async def api_grid_meta():
    """경남 지도 — 층마다 격자·기준시각·지연 여부, 격자 틀, 지도 설정."""
    return await asyncio.to_thread(gridview.meta)


@app.get("/api/grid/flow")
async def api_grid_flow(hours: int = Query(6, ge=1, le=24), step: int = Query(10),
                        test: bool = False, case: str | None = None):
    """재생 흐름 — 지난 hours 시간 실측(60분, step 분 간격) → 초단기 +1~6h.
    지도 재생과 오른쪽 타임라인이 같은 프레임 목록·같은 시군 값을 쓴다.
    `case=` 면 재현 사례의 처음부터 끝까지(매시, 예측 없음)."""
    if case:
        try:
            return await asyncio.to_thread(gridcase.flow, case)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e
    if step not in (10, 20, 30, 60):
        raise HTTPException(400, "step 은 10·20·30·60")
    return await asyncio.to_thread(gridview.flow, hours, step, None, test)


@app.get("/api/grid/cases")
async def api_grid_cases():
    """재현 사례 목록(data/demo/map/*) — 지난 호우를 격자 그대로 굳혀 둔 것."""
    return {"cases": gridcase.listing()}


@app.get("/api/grid/case/{slug}")
async def api_grid_case(slug: str):
    """사례 meta — 시군별 1시간·3시간·12시간·누적 최대(+읍면동), 산출 호우특보, 확인한 관측소 값."""
    try:
        return gridcase.meta(slug)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/grid/sigun")
async def api_grid_sigun(layer: str, tm: str | None = None, test: bool = False,
                         case: str | None = None):
    """시군별 최대(+그 칸의 읍면동)·평균. 결측 칸은 평균에서 뺀다."""
    try:
        return await asyncio.to_thread(gridview.sigun, layer, tm, test, case)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/grid/stations")
async def api_grid_stations(layer: str, tm: str | None = None, test: bool = False,
                            case: str | None = None):
    """관측소(경남 AWS) — 위치와 **격자와 같은 시각**의 실측값. 예측 층이면 위치만(status 'forecast').
    행마다 q = ok | missing(기상청 결측) | none(그 시각 값을 못 받음) | part(사례 누적, 일부 결측 — 하한)."""
    try:
        return await asyncio.to_thread(gridview.stations, layer, tm, test, case)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/grid/acctable")
async def api_grid_acctable(hours: int = Query(12, ge=1, le=48), sigun: str | None = None,
                       test: bool = False, case: str | None = None, tm: str | None = None):
    """격자 누적 — 시군 줄(누적 최대 칸·읍면동·그 칸의 매시 값), `sigun=` 이면 그 시군 읍면동 줄.
    `case=` 면 재현 사례 처음부터 tm 까지. 받지 못한 정시가 있으면 missing 시간 수(합은 하한)."""
    try:
        if case:
            return await asyncio.to_thread(gridcase.acc_rows, case, tm, sigun)
        return await asyncio.to_thread(gridview.acc, hours, sigun, None, test)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


# 경계·칸 지도(tools/build_geo.py 가 만든 것)와 관측소 위치(tools/build_stations.py).
# 바뀔 일이 드물지만 저장소 갱신 뒤 새로고침 한 번에 따라오게 하루만 캐시한다.
_GEO_FILES = {"gyeongnam.topo.json": "application/json", "grids.json": "application/json",
              "stations.json": "application/json",
              "mask_sigun.u8.gz": None, "mask_emd.u16.gz": None}


@app.get("/api/grid/geo/{name}")
async def api_grid_geo(name: str):
    if name not in _GEO_FILES:
        raise HTTPException(404, "없는 파일")
    p = gridstore.GEO / name
    if _GEO_FILES[name]:
        return FileResponse(p, media_type=_GEO_FILES[name],
                            headers={"Cache-Control": "public, max-age=86400"})
    # .gz 는 풀어서 쓰라고 Content-Encoding 으로 준다 — 브라우저가 알아서 푼다
    return Response(p.read_bytes(), media_type="application/octet-stream",
                    headers={"Content-Encoding": "gzip",
                             "Cache-Control": "public, max-age=86400"})


@app.get("/api/grid/{layer}")
async def api_grid(layer: str, tm: str | None = None, test: bool = False,
                   case: str | None = None):
    """한 층의 격자 — 0.1㎜ uint16(65535 = 결측), 행은 남→북, gzip.

    layer = obs15 | obs60 | obsday | odam | vsrt+N(1~6) | shrt_today | shrt_tomorrow
    `test=1` 이면 합성 격자(비 없는 날 화면 점검용).
    `case=사례` 면 재현 사례 — layer = obs60(1시간) | acc(사례 누적).
    """
    def build():
        fr = gridcase.frame(case, layer, tm) if case else gridview.frame(layer, tm, test=test)
        if "arr" in fr:
            body = gzip.compress(gridstore.encode(fr["arr"]), 6)
        else:
            body = gridstore.raw_gz(fr["store"], fr["key"])
        return fr, body

    try:
        fr, body = await asyncio.to_thread(build)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e
    h, w = gridstore.shape(fr["grid"])
    hd = {"Content-Encoding": "gzip", "X-Grid": fr["grid"], "X-Grid-Shape": f"{h},{w}",
          "X-Grid-Tm": fr["tm"], "Cache-Control": "no-cache"}
    for k in ("tmfc", "capped", "from", "case"):
        if k in fr:
            hd[f"X-Grid-{k.capitalize()}"] = str(fr[k])
    if "hours" in fr:
        hd["X-Grid-Hours"] = ",".join(fr["hours"])
    if fr.get("test"):
        hd["X-Grid-Test"] = "1"
    return Response(body, media_type="application/octet-stream", headers=hd)


@app.put("/api/settings/map")
async def api_settings_map(body: dict):
    """지도 판에서 고른 층 — 서버에 둔다(벽면 화면은 어느 브라우저에서 바꿔도 같이 가야 한다)."""
    try:
        return {"map": gridview.put_setting(body)}
    except (LookupError, ValueError) as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/bangjae")
async def api_bangjae():
    """스방 시군별 평균 강수량. 기상청 값과 관측망이 달라 따로 준다."""
    return JSONResponse(queries.bangjae_rain())


@app.get("/api/storage")
async def api_storage():
    """DB·이미지가 얼마나 쌓였는지. 설정창의 '저장공간'이 이걸 그대로 보여 준다."""
    return maint.usage()


@app.post("/api/storage/cleanup")
async def api_storage_cleanup(days: int | None = None):
    """보관 기간이 지난 자료를 지운다. ⚠️ 되돌릴 수 없다."""
    return await asyncio.to_thread(maint.cleanup, days)


@app.put("/api/settings/retention")
async def api_settings_retention(body: dict):
    try:
        return {"retention": maint.put_cfg(body)}
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/demo")
async def api_demo_list():
    return {"cases": demo.listing()}


@app.get("/api/demo/{slug}")
async def api_demo_get(slug: str):
    """담아 둔 사례. 아직 없으면 그 자리에서 받아 만든다."""
    b = demo.load(slug)
    if b is None:
        if slug not in demo.CASES:
            raise HTTPException(404, f"모르는 사례: {slug}")
        try:
            b = await demo.build(slug)
        except Exception as e:                       # noqa: BLE001
            raise HTTPException(503, f"사례를 만들 수 없다: {e}") from e
    return JSONResponse(b)


@app.get("/api/update")
async def api_update(check: bool = True):
    """지금 버전과 원격에 새 것이 있는지. `check=false` 면 원격을 부르지 않는다."""
    return await asyncio.to_thread(update.status, check)


@app.post("/api/update/pull")
async def api_update_pull():
    """GitHub 에서 받아 온다. ⚠️ `--ff-only` — 손댄 파일이 있으면 실패한다."""
    return await asyncio.to_thread(update.pull)


@app.post("/api/update/restart")
async def api_update_restart():
    """스스로 끝난다. 실행 스크립트(run.bat/run.command)가 다시 띄운다.

    ⚠️ 파이썬 코드가 바뀌면 프로세스를 다시 띄워야 반영된다. 화면만 바뀌었으면
       새로고침으로 충분하니 여기까지 오지 않는다.
    ⚠️ 스크립트로 띄우지 않았으면 그냥 꺼진다 — 그래서 화면이 먼저 물어본다.
    """
    async def bye():
        await asyncio.sleep(0.4)          # 응답을 먼저 보내고 끊는다
        log.info("업데이트 반영을 위해 종료한다(코드 %d)", RESTART_CODE)
        os._exit(RESTART_CODE)

    asyncio.create_task(bye())
    return {"ok": True, "code": RESTART_CODE}


@app.get("/api/status")
async def api_status():
    return {"collect": queries.status(), "poll": POLL_DEFAULT,
            "intervals": db.get_setting("intervals", INTERVALS),
            "qpf": qpf.cfg(), "publish": db.publish_stats()}


@app.get("/api/settings")
async def api_settings_get():
    """설정은 서버에 둔다 — 벽면 화면이라 어느 브라우저에서 바꿔도 같이 가야 한다."""
    c = qpf.cfg()
    return {"qpf": c, "frames": len(qpf.frame_efs(c)),
            "publish": db.publish_stats(),
            "intervals": db.get_setting("intervals", INTERVALS)}


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
    db.put_setting("qpf", cur)
    return {"qpf": cur, "frames": len(qpf.frame_efs(cur))}


@app.put("/api/settings/intervals")
async def api_settings_intervals(body: dict):
    """수집 주기. ⚠️ 화면 갱신 주기와 다르다 — 이건 기상청을 실제로 부르는 간격이다."""
    cur = db.get_setting("intervals", INTERVALS)
    for k in COLLECTORS:
        if k in body:
            sec = max(30, min(3600, int(body[k])))
            cur[k] = sec
            job = app.state.sched.get_job(k) if app.state.sched else None
            if job:
                job.reschedule("interval", seconds=sec)
    db.put_setting("intervals", cur)
    return {"intervals": cur}


@app.post("/api/refresh/{kind}")
async def api_refresh(kind: str, force: bool = False):
    """수동 조회. ⚠️ 주기와 무관하게 실제로 다녀온다.

    내부 주기 함수를 그냥 부르면 '이미 처리함' 분기로 빠져 아무 일도
    일어나지 않는다(pitfalls ★3). 여기서는 항상 수집기를 직접 부른다.
    """
    return await run_one(kind, force=force)


@app.middleware("http")
async def no_cache_html(request, call_next):
    """화면 파일은 캐시하지 않는다.

    ⚠️ 고친 화면이 안 나온다는 말이 실제로 있었다 — 브라우저가 index.html 을
       메모리 캐시에서 그냥 꺼내 쓰느라 서버까지 오지도 않았다.
       벽면에 걸어 두고 몇 주씩 안 닫는 화면이라 더 그렇다.
    """
    resp = await call_next(request)
    ct = resp.headers.get("content-type", "")
    if ct.startswith("text/html"):
        resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


if STATIC.exists():
    app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")


if __name__ == "__main__":
    # 포트는 PORT 환경변수를 따른다 — 없으면 8000.
    # 하드코딩하면 이미 쓰는 포트와 부딪힌다.
    #   --no-collect   수집기 없이 화면만(개발용 미리보기). --port N 으로 포트를 준다.
    import sys

    import uvicorn

    argv = sys.argv[1:]
    if "--no-collect" in argv:
        os.environ["NO_COLLECT"] = "1"
    if "--port" in argv:
        os.environ["PORT"] = argv[argv.index("--port") + 1]
    uvicorn.run("app.main:app", host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))

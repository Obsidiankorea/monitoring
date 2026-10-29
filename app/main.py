"""FastAPI 진입점 — 수집기(스케줄러)와 웹을 한 프로세스에 둔다.

핵심 원칙: 화면을 열 때 기상청을 부르지 않는다.
수집기가 주기적으로 받아 DB에 넣고, 웹은 저장된 것을 읽기만 한다.
그래야 접속자가 몇이든 기상청 호출은 한 번이고, API가 죽어도 마지막 정상
자료가 화면에 남는다.
"""
from __future__ import annotations

import asyncio
import json
import gzip
import logging
import os
import sys

# ⚠️ 시연(--snap)은 설정(config)을 읽기 **전에** 정해야 한다 — python -m app.main 은 이 파일을 먼저 돌려
#    config 를 읽어 버리고, uvicorn 이 app.main 을 다시 부를 때는 이미 읽힌 config 를 그대로 쓴다
if __name__ == "__main__" and ("--snap" in sys.argv or "--demo" in sys.argv):
    os.environ["GN_DEMO"] = "1"
    if "--snap" in sys.argv:
        os.environ["GN_SNAP"] = sys.argv[sys.argv.index("--snap") + 1]
    if "--port" not in sys.argv:
        os.environ.setdefault("PORT", "8001")
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException, Query
from fastapi import Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import clock, config, db, demo, gridcase, gridstore, gridview, maint, origin, queries, serverupdate, snaps, update
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
              # 매분자료만 1분마다 — 지도 AWS 층 '지금' 칸과 지금 오는 비(정시 자료는 rain 이 10분마다)
              "minute": rain.collect_minute,
              "alerts": alerts.collect, "qpf": qpf.collect,
              # 스방은 기상청과 **다른 서버**라 따로 돈다(계정 없으면 조용히 건너뜀)
              "bangjae": bangjae_rain.collect,
              # 단기예보 격자 — 권역·시군 예보 판. 받은 발표분은 다시 부르지 않는다.
              "short": shortfc.collect,
              # 경남 지도 — 500m 격자(15분·60분·일)와 실황 5km. 경남 bbox 만 잘라 둔다.
              "grid": grid_rain.collect, "odam": grid_rain.collect_odam}

def intervals() -> dict:
    """수집 주기 — 저장한 것 위에 기본값을 깐다. 저장한 뒤에 생긴 수집기(minute 등)도 기본 주기로 돈다.
    ⚠️ 저장한 것만 읽으면 새 수집기가 영영 예약되지 않는다."""
    return {**INTERVALS, **db.get_setting("intervals", INTERVALS)}


# 한 자료를 두 번 동시에 받지 않게 — 주기가 겹치거나 수동 조회가 끼어들 수 있다
_locks = {k: asyncio.Lock() for k in COLLECTORS}


async def run_one(kind: str, force: bool = False) -> dict:
    if kind not in COLLECTORS:
        raise HTTPException(404, f"모르는 수집기: {kind}")
    if config.DEMO:
        # 시연 — 기상청을 부르지 않는다(굳힌 시각 뒤 자료가 끼면 '가장 새 것'이 바뀐다). 수동 조회·과거 메우기도
        return {"ok": False, "kind": kind, "error": "시연 — 수집하지 않는다"}
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
    if config.DEMO and config.SNAP:
        snaps.add_bangjae(config.DB_PATH, config.SNAP)   # 서버 시연에 없는 경남 AWS(내부망에서 받아 둔 것)
    if os.environ.get("NO_COLLECT") == "1":
        # 화면만 띄운다(개발용). ⚠️ 같은 PC 에서 수집기가 둘 돌면 기상청 호출이 두 배가 된다.
        log.info("수집기 끔(NO_COLLECT) — 저장된 자료만 보여 준다")
        app.state.sched = None
        yield
        return
    sched = AsyncIOScheduler(timezone="Asia/Seoul")   # 시각은 전부 KST. UTC로 바꾸지 않는다.
    app.state.sched = sched
    # 수집기 골라 끄기 — SKIP_COLLECT=bangjae 처럼(쉼표). 언레이드(집)에서는 스방(내부망)에 닿지 않아 실패만 쌓인다
    skip = {x.strip() for x in os.environ.get("SKIP_COLLECT", "").split(",") if x.strip()}
    app.state.skip = skip
    if skip:
        log.info("수집기 끔(SKIP_COLLECT): %s", ", ".join(sorted(skip)))
    for kind, sec in intervals().items():
        if kind in skip or kind not in COLLECTORS:
            continue
        sched.add_job(run_one, "interval", seconds=sec, args=[kind],
                      id=kind, max_instances=1, coalesce=True)
    # 하루 한 번 묵은 자료 치우기 — 안 하면 DB 와 이미지 캐시가 계속 자란다
    sched.add_job(_nightly, "cron", hour=4, minute=20, id="maint",
                  max_instances=1, coalesce=True)
    sched.start()
    if origin.remote():
        # 설정 '서버에서 받기' — 이 PC 는 수집하지 않는다(같은 키로 호출이 두 배가 되지 않게)
        sched.pause()
        log.info("자료는 서버(%s)에서 받는다 — 이 PC 수집기 멈춤", origin.remote())
    else:
        # 뜨자마자 한 번씩 받아 둔다 — 빈 화면으로 시작하지 않게
        for kind in COLLECTORS:
            if kind not in skip:
                asyncio.create_task(run_one(kind))
        log.info("수집기 시작: %s", INTERVALS)
    try:
        yield
    finally:
        sched.shutdown(wait=False)


app = FastAPI(title="경남 기상 대시보드", lifespan=lifespan)


@app.get("/api/rain")
async def api_rain(hours: int = Query(12, ge=1, le=gridview.ACC_SPAN_MAX),
                   src: str = Query("kma", pattern="^(kma|bangjae)$"), tail: bool = True):
    """지점별 강수량. `src=bangjae` 면 스방 265개소. `tail=0` 이면 정시까지만(마지막 '정시 뒤 지금까지' 칸을 붙이지 않는다 —
    지도 판에서 AWS 실시간 감시를 끈 동안 위 카드가 지도와 같은 정시를 보이게).

    화면이 더 긴 구간을 고르면 그만큼 과거를 채운다.
    ⚠️ 그 전에는 26시간 앞이 영원히 비어 있었다 — '2일'을 골라도 그래프 왼쪽이
       통째로 빈 채였다. 여기서 깊이를 올리고 곧바로 한 번 받아 온다.
    """
    grew = rain.want_depth(hours)
    out = queries.rain(hours, src=src, tail=tail)
    # 빈 시각이 있으면 지금 채운다. 이미 받는 중이면 겹쳐 부르지 않는다.
    kind = "bangjae" if src == "bangjae" else "rain"
    if (grew or out.get("missing")) and not _locks[kind].locked() and not config.DEMO:
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
                        test: bool = False, case: str | None = None,
                        src: str = Query("grid", pattern="^(grid|aws)$")):
    """재생 흐름 — 지난 hours 시간 실측(60분, step 분 간격) → 초단기 +1~6h.
    지도 재생과 오른쪽 타임라인이 같은 프레임 목록·같은 시군 값을 쓴다.
    `src=aws` 면 실측이 AWS 1시간 면(정시마다 — step 은 쓰지 않는다).
    `case=` 면 재현 사례의 처음부터 끝까지(매시, 예측 없음)."""
    if case:
        try:
            return await asyncio.to_thread(gridcase.flow, case)
        except LookupError as e:
            raise HTTPException(404, str(e)) from e
    if step not in (10, 20, 30, 60):
        raise HTTPException(400, "step 은 10·20·30·60")
    try:
        return await asyncio.to_thread(gridview.flow, hours, step, None, test, src)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


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


_SINCE = r"^(today|yesterday|hours|\d{8}|\d{10})$"   # 누적(acc) 층의 구간 — 강수 누적 카드와 같은 말(YYYYMMDD = 그날 0시부터, YYYYMMDDHH = 그 시각부터)


@app.get("/api/grid/sigun")
async def api_grid_sigun(layer: str, tm: str | None = None, test: bool = False,
                         case: str | None = None, hours: int | None = Query(None, ge=1, le=gridview.ACC_SPAN_MAX),
                         since: str | None = Query(None, pattern=_SINCE)):
    """시군별 최대(+그 칸의 읍면동)·평균. 결측 칸은 평균에서 뺀다."""
    try:
        return await asyncio.to_thread(gridview.sigun, layer, tm, test, case, hours, since)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/grid/stations")
async def api_grid_stations(layer: str, tm: str | None = None, test: bool = False,
                            case: str | None = None, hours: int | None = Query(None, ge=1, le=gridview.ACC_SPAN_MAX),
                            since: str | None = Query(None, pattern=_SINCE)):
    """관측소(경남 AWS) — 위치와 **격자와 같은 시각**의 실측값. 예측 층이면 위치만(status 'forecast').
    행마다 q = ok | missing(기상청 결측) | none(그 시각 값을 못 받음) | part(사례 누적, 일부 결측 — 하한)."""
    try:
        return await asyncio.to_thread(gridview.stations, layer, tm, test, case, hours, since)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/grid/acctable")
async def api_grid_acctable(hours: int = Query(12, ge=1, le=gridview.ACC_SPAN_MAX), sigun: str | None = None,
                       test: bool = False, case: str | None = None, tm: str | None = None,
                       since: str | None = Query(None, pattern=r"^(today|yesterday|\d{8}|\d{10})$")):
    """격자 누적 — 시군 줄(누적 최대 칸·읍면동·그 칸의 매시 값), `sigun=` 이면 그 시군 읍면동 줄.
    `case=` 면 재현 사례 처음부터 tm 까지. 받지 못한 정시가 있으면 missing 시간 수(합은 하한)."""
    try:
        if case:
            return await asyncio.to_thread(gridcase.acc_rows, case, tm, sigun)
        return await asyncio.to_thread(gridview.acc, hours, sigun, None, test, since)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/grid/emd")
async def api_grid_emd(sigun: str, layer: str = "obs60", tm: str | None = None, test: bool = False,
                       case: str | None = None, hours: int = Query(1, ge=1, le=12)):
    """고른 시군(쉼표로 여럿)의 **읍면동마다** 그 층 최대와 그 칸. 사례면 hours 시간 합."""
    try:
        return await asyncio.to_thread(gridview.emd, sigun, layer, tm, test, case, hours)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/grid/emdday")
async def api_grid_emdday(layer: str, sigun: str | None = None, test: bool = False):
    """단기 오늘·내일 — 읍면동마다 그날 합 · 6시간 구간 합 최대(합 큰 순). sigun 이 없으면 경남 전부."""
    try:
        return await asyncio.to_thread(gridview.emd_day, layer, sigun, test)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


@app.get("/api/grid/testrain")
async def api_grid_testrain(hours: int = Query(12, ge=1, le=48)):
    """테스트 — /api/rain 과 같은 모양의 합성 지점(기상청 자리 + 스방 흉내, 위치는 읍면동 짐작). 실제 자료가 아니다."""
    return await asyncio.to_thread(gridview.test_rain, hours)


# 경계·칸 지도(tools/build_geo.py 가 만든 것)와 관측소 위치(tools/build_stations.py).
# 바뀔 일이 드물지만 저장소 갱신 뒤 새로고침 한 번에 따라오게 하루만 캐시한다.
_GEO_FILES = {"gyeongnam.topo.json": "application/json", "grids.json": "application/json",
              "stations.json": "application/json", "emd.topo.json": "application/json",
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
                   case: str | None = None, hours: int | None = Query(None, ge=1, le=gridview.ACC_SPAN_MAX),
                   since: str | None = Query(None, pattern=_SINCE)):
    """한 층의 격자 — 0.1㎜ uint16(65535 = 결측), 행은 남→북, gzip.

    layer = obs15 | obs60 | obsday | acc | aws | aws60 | odam | vsrt+N(1~6) | shrt_today | shrt_tomorrow
    aws60(AWS 1시간)은 tm = 정시(YYYYMMDDHH00) 또는 매분 시각(그 분의 직전 60분, 기상청만) — 없으면 '지금'
    (마지막 정시 뒤 매분자료가 있으면 그 분, 없으면 관측소 값이 든 가장 최근 정시). aws(AWS 누적)도 '지금' 칸까지 잇는다.
    '지금' 칸이면 X-Grid-Live = 그 매분 시각.
    acc(누적)는 hours · since(today|yesterday|hours) 구간 — 없으면 지도 설정(강수 누적 카드와 같은 구간).
    `test=1` 이면 합성 격자(비 없는 날 화면 점검용).
    `case=사례` 면 재현 사례 — layer = obs60(1시간) | acc(사례 누적).
    """
    def build():
        fr = gridcase.frame(case, layer, tm) if case else gridview.frame(layer, tm, test=test, hours=hours,
                                                                         since=since)
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
    for k in ("tmfc", "capped", "from", "case", "n", "live"):
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


@app.get("/api/server-update")
async def api_server_update():
    """서버(언레이드) 갱신 상태 — 지금 판 · GitHub 최신 · 밀린 커밋 · 마지막 갱신(app/serverupdate.py).
    PC 가 서버에서 받는 중이면 서버로 넘어간다(LOCAL_ONLY 가 아니다) — PC 화면에서도 서버를 갱신한다."""
    return await asyncio.to_thread(serverupdate.status)


@app.post("/api/server-update")
async def api_server_update_ask(body: dict | None = None, request: Request = None):
    """action = deploy(갱신 부탁) | check(GitHub 다시 확인). 1분 안에 언레이드 예약 작업이 집어 간다."""
    if config.DEMO:
        raise HTTPException(403, "시연 화면에서는 갱신하지 않는다 — 실황(:8000)에서")
    action = str((body or {}).get("action") or "deploy")
    who = request.client.host if request and request.client else ""
    try:
        return await asyncio.to_thread(serverupdate.ask, action, who)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError as e:
        raise HTTPException(404, str(e))


@app.get("/api/ai/situation")
async def api_ai_situation(sigun: str, base: str | None = None):
    """AI 상황판단 — 시군 하나의 지금 수치(이 서버 API)와 LLM 위키 기준(산사태 지구 대피기준까지 %)을 맞대 놓는다.
    판단하지 않는다(app/ai.py). base 를 주면 그 대시보드 서버의 자료로(시험용 — 예: NAS)."""
    from . import ai
    me = base or f"http://127.0.0.1:{os.environ.get('PORT', '8000')}"
    try:
        s = await asyncio.to_thread(ai.situation, sigun, me)
    except FileNotFoundError as e:
        raise HTTPException(503, f"LLM 위키를 못 찾았다(GN_WIKI): {e}")
    s["brief"] = ai.brief(s)
    return s


@app.get("/api/ai/emdwin")
async def api_grid_emdwin():
    """경남 읍면동마다 1 · 3 · 12 · 24 · 48시간 누적 · 15분 최대 칸(격자 500m) — 한 번에. AI 상황판단 · Hermes 도구용."""
    try:
        return await asyncio.to_thread(gridview.emd_windows)
    except LookupError as e:
        raise HTTPException(404, str(e)) from e


def _ai_base(base: str | None) -> str:
    return base or f"http://127.0.0.1:{os.environ.get('PORT', '8000')}"


@app.get("/api/ai/report")
async def api_ai_report(sigun: str | None = None, base: str | None = None, mode: str = "all"):
    """AI 상황판단 보고 — 시군이 없으면 경남 전체. 상황 · 중요한 점 · 할 일 · 살펴볼 곳 · 다음 확인 · 참고(책자 쪽수).
    규칙으로 만든다(LLM 없이). 예상 질문 목록을 같이 준다(app/aireport.py)."""
    from . import aireport, llm
    try:
        r = await asyncio.to_thread(aireport.report, _ai_base(base), sigun or None, mode)
    except FileNotFoundError as e:
        raise HTTPException(503, f"LLM 위키를 못 찾았다(GN_WIKI): {e}")
    r["llm"] = llm.mode()
    r["modes"] = [{"id": k, "label": v} for k, v in aireport.MODES]
    r.setdefault("mode", "all")
    return r


@app.post("/api/ai/ask")
async def api_ai_ask(body: dict):
    """예상 질문(q = id) 은 규칙으로, 자유 질문(text) 은 LLM(GN_AI)으로 답한다."""
    from . import aireport
    sigun = body.get("sigun") or None
    if body.get("q"):
        return await asyncio.to_thread(aireport.answer, _ai_base(body.get("base")), str(body["q"]), sigun)
    text = str(body.get("text") or "").strip()[:500]
    if not text:
        raise HTTPException(400, "q 또는 text")
    return await asyncio.to_thread(aireport.ask_free, _ai_base(body.get("base")), text, sigun)


@app.get("/api/aws/match")
async def api_aws_match():
    """경남 AWS(스방) 지점마다 경남 AWS 목록과 짝지어졌나 — 위치 출처(kma · aws · emd 임시 · none). 내부망 점검용."""
    return await asyncio.to_thread(queries.aws_match)


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
            "intervals": intervals(),
            "qpf": qpf.cfg(), "publish": db.publish_stats()}


@app.get("/api/settings")
async def api_settings_get():
    """설정은 서버에 둔다 — 벽면 화면이라 어느 브라우저에서 바꿔도 같이 가야 한다."""
    c = qpf.cfg()
    return {"qpf": c, "frames": len(qpf.frame_efs(c)),
            "publish": db.publish_stats(),
            "intervals": intervals()}


@app.put("/api/settings/qpf")
async def api_settings_qpf(body: dict):
    cur = qpf.cfg()
    allowed = {"step": (10, 20, 30), "ahead": (180, 240, 300, 360),
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
    cur = intervals()
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


# ── 시연(스냅숏) — 시계와 목록 ─────────────────────────────────────────────
@app.get("/api/clock.js")
async def api_clock_js():
    """화면이 맨 먼저 읽는 작은 스크립트 — 시연이면 멈춘 시각(ms)과 그 시연, 실황이면 null."""
    snap = None
    if config.SNAP_META:
        m = config.SNAP_META
        snap = {k: m.get(k) for k in ("name", "title", "now", "note", "alerts", "fake")}
        snap["acc"] = m.get("acc") or ({"from": "hours", "hours": m["hours"]} if m.get("hours") else None)
    body = f"window.GN_NOW={json.dumps(clock.epoch_ms())};window.GN_SNAP={json.dumps(snap, ensure_ascii=False)};"
    return Response(body, media_type="application/javascript", headers={"Cache-Control": "no-store"})


@app.get("/api/snaps")
async def api_snaps():
    """굳혀 둔 시연 목록(app/snaps.py, 새 것부터) · 지금 굳히는 중인 것(job) · 이 서버가 시연 서버인가(demo)."""
    return {"snaps": await asyncio.to_thread(snaps.list_all), "this": config.SNAP,
            "demo": config.DEMO, "job": snaps.JOB}


@app.post("/api/snaps")
async def api_snaps_make(body: dict | None = None):
    """지금을 굳힌다(뒤에서) — 화면은 /api/snaps 의 job 이 끝날 때까지 본다.
    body: title · note · acc {from: hours|today|yesterday, hours} · overwrite"""
    if config.DEMO:
        raise HTTPException(403, "시연 화면에서는 저장하지 않는다 — 실황(:8000)에서 저장한다")
    b = body or {}
    acc = b.get("acc")
    if acc is not None:
        if not isinstance(acc, dict) or acc.get("from", "hours") not in ("hours", "today", "yesterday")                 or int(acc.get("hours") or 12) not in (3, 6, 12, 24, 48):
            raise HTTPException(400, "acc 는 {from: hours|today|yesterday, hours: 3·6·12·24·48}")
    try:
        job = snaps.start(title=str(b.get("title") or ""), note=str(b.get("note") or ""), acc=acc,
                          overwrite=bool(b.get("overwrite")))
    except FileExistsError as e:
        raise HTTPException(409, f"같은 시각 시연이 이미 있다({e})")
    except (RuntimeError, ValueError) as e:
        raise HTTPException(409, str(e))
    return job


@app.delete("/api/snaps/{name}")
async def api_snaps_delete(name: str):
    """굳힌 것을 지운다 — 서버 폴더째(되돌릴 수 없다). 지금 띄워 보는 중인 시연 서버는 제 사본으로 계속 돈다."""
    if config.DEMO:
        raise HTTPException(403, "시연 화면에서는 지우지 않는다 — 실황(:8000)에서 지운다")
    try:
        await asyncio.to_thread(snaps.delete, name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except FileNotFoundError:
        raise HTTPException(404, f"그런 시연이 없다({name})")
    return {"ok": True, "name": name}


def _reexec(name: str) -> None:
    """시연 서버를 그 시연으로 다시 띄운다 — 같은 프로세스 자리에서(도커 PID 1 그대로). 설정은 config 가 읽을 때 정해서
    도는 중에는 못 바꾼다. ⚠️ 윈도에는 exec 이 없어 새로 띄우고 나간다(PC 시험용)."""
    os.environ["GN_SNAP"] = name
    argv = list(getattr(sys, "orig_argv", [sys.executable, "-m", "app.main"]))[1:]
    if "--snap" in argv:
        argv[argv.index("--snap") + 1] = name
    log.info("시연 서버를 %s 로 다시 띄운다", name)
    if os.name == "nt":
        import subprocess
        subprocess.Popen([sys.executable, *argv])
        os._exit(0)
    os.execv(sys.executable, [sys.executable, *argv])


_SWITCH = """<!doctype html><meta charset="utf-8"><title>시연 여는 중</title>
<style>body{{margin:0;height:100vh;display:grid;place-items:center;background:#0f141b;color:#cfd8e3;font:15px system-ui,sans-serif}}
b{{color:#fff}}small{{display:block;margin-top:8px;color:#7d8a99}}</style>
<div><b>시연 «{title}»</b> 을 여는 중…<small>시연 서버를 그 시각 자료로 다시 띄운다(몇 초)</small></div>
<script>
const want = {name}, to = {to};
async function poll() {{
  try {{ const j = await (await fetch("/api/snaps", {{cache: "no-store"}})).json();
         if (j.this === want) return location.replace(to); }} catch (e) {{}}
  setTimeout(poll, 700);
}}
setTimeout(poll, 1200);
</script>"""


@app.get("/snap/{name}")
async def snap_open(name: str, to: str = "/"):
    """시연 서버(:8001)에서 그 시연으로 연다 — 지금 띄운 것이 다르면 갈아 탄다(다시 띄우는 동안 기다림 화면)."""
    if not to.startswith("/") or to.startswith("//"):
        to = "/"
    if not config.DEMO:
        raise HTTPException(404, "시연 서버(:8001)에서 연다")
    try:
        snaps.check_name(name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if config.SNAP == name:
        return RedirectResponse(to, status_code=302)
    meta = config.SNAPS / name / "meta.json"
    if not meta.exists():
        raise HTTPException(404, f"그런 시연이 없다({name})")
    title = json.loads(meta.read_text("utf-8")).get("title") or name
    asyncio.get_running_loop().call_later(0.6, _reexec, name)
    import html
    return HTMLResponse(_SWITCH.format(title=html.escape(title), name=json.dumps(name), to=json.dumps(to)),
                        headers={"Cache-Control": "no-store"})


# ── 자료를 어디서 받나(이 PC / 서버) — app/origin.py ────────────────────────────
def _collecting() -> bool:
    sch = getattr(app.state, "sched", None)
    return bool(sch) and sch.running and sch.state == 1          # 1 = STATE_RUNNING(멈춤 2)


@app.get("/api/origin")
async def api_origin_get():
    return {**origin.cfg(), "collecting": _collecting()}


@app.put("/api/origin")
async def api_origin_put(body: dict):
    """받는 곳 바꾸기 — 서버면 이 PC 수집기를 멈추고, 이 PC 면 다시 돌려 곧바로 한 번씩 받는다."""
    try:
        c = origin.put(body)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    sch = getattr(app.state, "sched", None)
    if sch and sch.running:
        if c["mode"] == "server" and sch.state == 1:
            sch.pause()
            log.info("자료는 서버(%s)에서 받는다 — 이 PC 수집기 멈춤", c["url"])
        elif c["mode"] == "local" and sch.state == 2:
            sch.resume()
            for kind in COLLECTORS:
                if kind not in getattr(app.state, "skip", set()):
                    asyncio.create_task(run_one(kind))
            log.info("이 PC 에서 다시 수집한다")
    return {**c, "collecting": _collecting()}


@app.post("/api/origin/test")
async def api_origin_test(body: dict):
    """그 주소에 대시보드 서버가 있나(받는 곳을 바꾸기 전에 눌러 본다)."""
    try:
        return await origin.test(str(body.get("url") or origin.cfg()["url"]))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.middleware("http")
async def from_server(request: Request, call_next):
    """'서버에서 받기'면 화면이 부르는 /api/… 를 서버로 넘긴다(받는 곳 설정·업데이트·저장공간은 이 PC)."""
    base = origin.remote()
    if not base or not origin.should_proxy(request.url.path):
        return await call_next(request)
    body = await request.body() if request.method in ("POST", "PUT", "PATCH", "DELETE") else b""
    code, content, head = await origin.forward(base, request.method, request.url.path,
                                               request.url.query, body, request.headers.get("content-type"))
    return Response(content=content, status_code=code, headers=head)


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
    if "--ai" in argv:                        # AI 상황판단 자유 질문 — claude-cli(이 PC 시험) | openai(Hermes 등)
        os.environ["GN_AI"] = argv[argv.index("--ai") + 1]
    if "--snap" in argv or "--demo" in argv:   # 시연 서버 — 굳혀 둔 그 시각 자료로(수집 안 함). 기본 포트 8001
        os.environ["GN_DEMO"] = "1"
        if "--snap" in argv:
            os.environ["GN_SNAP"] = argv[argv.index("--snap") + 1]
        os.environ.setdefault("PORT", "8001")
    uvicorn.run("app.main:app", host=os.environ.get("HOST", "127.0.0.1"),
                port=int(os.environ.get("PORT", "8000")))

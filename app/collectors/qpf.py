"""예측 분포 이미지 수집 — nph-qpf_ana_img (융합 qpf=B).

장수는 설정으로 정한다. 간격 10분·6시간이면 36장, 20분·3시간이면 9장.
발표는 10분마다 나오므로 이 숫자가 곧 10분당 호출 수다.

발표가 났는지 먼저 1분 간격으로 확인하고, 난 뒤에만 내려받는다.
못 났는데 36장을 부르면 전부 헛수고이고, 늦게 부르면 그만큼 화면이 늦는다.

⚠️ 이 API는 지역 크롭을 안 해 준다. stn·zoom_*·lon/lat을 줘도 전국 이미지를 준다.
   전국을 받아 PIL로 직접 잘라야 한다.
⚠️ 크롭 박스는 소스마다 다르다(QPF 835×820, 초단기 분포도 901×1551).
   하나로 쓰면 엉뚱한 데가 잘린다 — 소스별로 따로 둔다.
⚠️ 36장을 한꺼번에 요청하면 중간이 통째로 실패한다(실측: ef 190~240 누락).
   순차로 받고 실패는 한 번 더 시도한다.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from io import BytesIO

from .. import db
from ..config import CACHE, QPF
from ..kma import KmaError, fetch_bytes

log = logging.getLogger("collect.qpf")

KEEP_DEFAULT = 3
SCAN_BACK = 9          # 가진 것이 없을 때 거슬러 훑을 슬롯 수(90분)

# size=1800 응답(1835×1820) 기준 경남 광역 박스.
# ⚠️ 크롭 박스는 소스마다 다르다(QPF 835×820, 초단기 분포도 901×1551).
#    하나로 쓰면 엉뚱한 데가 잘린다 — 소스별로 따로 둔다.
CROP = (660, 560, 660 + 950, 560 + 800)

# ── 범례 ──────────────────────────────────────────────────────────────
# 원본 그림 오른쪽 끝에 세로 색 띠가 있다(legend=1 로 받는다). 경남만 잘라 내면
# 그 띠가 통째로 날아가므로, 자르기 전에 색을 뽑아 따로 남긴다.
#
# ⚠️ 색을 흉내 내지 않는다. 기상청 QPF 색계는 우리 청색 램프와 전혀 달라서
#    비슷하게 칠하면 거짓말이 된다. 원본에서 그대로 뽑는다.
# ⚠️ 경계값은 원본 범례에 **찍힌 대로** 옮겨 적었다. 그림 속 글자라 뽑아낼 수가
#    없다. 앞의 0.1 이 두 번 나오는 것도 기상청 범례가 그렇게 찍는다 —
#    우리 오타가 아니다. 그래서 화면에는 눈금을 띄엄띄엄만 적는다.
LEGEND_X = 1803        # 색 띠가 지나는 세로줄(size=1800 응답 기준)
LEGEND_BOUNDS = [0.1, 0.1, 0.5, 1, 2, 3, 4, 5, 6, 7, 8, 9,
                 10, 15, 20, 25, 30, 40, 50, 60, 70, 80, 90, 110]


def _legend(im) -> dict | None:
    """세로 색 띠에서 단계별 색을 뽑는다. 약한 쪽이 아래이므로 뒤집어 담는다."""
    if im.width <= LEGEND_X:
        return None
    px = im.convert("RGB").load()
    x = LEGEND_X
    # 같은 색이 이어지는 구간을 센다. 흰 배경과 테두리는 버린다.
    runs, prev = [], None
    for y in range(im.height):
        c = px[x, y]
        if prev is not None and c == prev[0]:
            prev[1] += 1
        else:
            prev = [c, 1]
            runs.append(prev)
    bands = [r for r in runs if r[1] >= 20]
    if len(bands) < len(LEGEND_BOUNDS):
        return None                       # 띠를 못 찾았다 — 조용히 접는다
    # 위가 센 값이다. 아래(약함)부터 담되 맨 아래 흰 칸(무강수)은 뺀다.
    cols = [c for c, _ in reversed(bands)]
    white = lambda c: c[0] > 245 and c[1] > 245 and c[2] > 245
    while cols and white(cols[0]):
        cols.pop(0)
    cols = cols[:len(LEGEND_BOUNDS)]
    if len(cols) < len(LEGEND_BOUNDS):
        return None
    return {"colors": ["#%02x%02x%02x" % c for c in cols],
            "bounds": LEGEND_BOUNDS, "unit": "mm/h"}


#: 한 번 뽑으면 바뀌지 않는다. 재시작하면 DB 에서 되살린다.
_legend_cache: dict = {}


def legend() -> dict | None:
    if not _legend_cache.get("colors"):
        saved = db.get_setting("qpf_legend", None)
        if saved:
            _legend_cache.update(saved)
    return dict(_legend_cache) if _legend_cache.get("colors") else None


def cfg() -> dict:
    """설정은 DB가 이긴다 — 화면에서 바꾼 값이 재시작해도 남는다."""
    return db.get_setting("qpf", QPF)


def frame_efs(c: dict) -> list[int]:
    step = max(10, int(c["step"]) // 10 * 10)
    return list(range(step, int(c["ahead"]) + 1, step))


def _slot(now: datetime) -> datetime:
    """발표시각 후보 — 가장 최근 10분 경계. 발표는 10분마다 나온다."""
    t = now.replace(second=0, microsecond=0)
    return t - timedelta(minutes=t.minute % 10)


def _crop(raw: bytes) -> tuple[bytes, bool]:
    """경남만 잘라 낸다. 두 번째 값은 '빈 그림인가'.

    ⚠️ 발표가 났다고 그림이 바로 올라오는 것은 아니다. 막 올라오는 중에는
       완전히 빈 이미지가 온다(실측: 원본 1835×1820이 1,429바이트, 색 1개).
       그걸 저장하면 화면이 하얗게 뜨고, 다음 발표까지 그대로 남는다.
       빈 것은 저장하지 않고 다음 주기에 다시 받는다.
    """
    try:
        from PIL import Image
    except ImportError:
        return raw, False                 # PIL이 없으면 판별도 못 한다
    im = Image.open(BytesIO(raw))
    # 자르기 전에 범례를 챙긴다 — 자르고 나면 색 띠가 없다
    if not _legend_cache.get("colors"):
        try:
            lg = _legend(im)
            if lg:
                _legend_cache.update(lg)
                db.put_setting("qpf_legend", lg)
        except Exception as e:                       # noqa: BLE001
            log.warning("범례를 못 뽑았다: %s", e)
    box = tuple(min(v, s) for v, s in zip(CROP, (im.width, im.height) * 2))
    cut = im.crop(box)
    # 해안선이 그려진 정상 그림은 색이 수십 가지다. 두 가지 이하면 빈 그림이다.
    cols = cut.convert("RGB").getcolors(maxcolors=8)
    blank = cols is not None and len(cols) <= 2
    out = BytesIO()
    cut.save(out, format="PNG", optimize=True)
    return out.getvalue(), blank


async def _one(tmfc: str, ef: int, size: int) -> bytes:
    return await fetch_bytes("/api/typ03/cgi/dfs/nph-qpf_ana_img", {
        "eva": 1, "tm": tmfc, "qpf": "B", "ef": ef,
        "map": "HR", "grid": 2, "legend": 1, "size": size,
        "zoom_level": 0, "zoom_x": "0000000", "zoom_y": "0000000",
        "stn": 108, "x1": 470, "y1": 575,
    })


async def _is_blank_slot(tmfc: str, ef: int, size: int) -> bool:
    """그 발표분의 그림이 준비됐는지 한 장으로 확인한다."""
    _, blank = _crop(await _one(tmfc, ef, size))
    return blank


async def _download(tmfc: str, efs: list[int], c: dict, at: str) -> tuple[int, int, list]:
    """한 발표분을 내려받는다 → (저장, 빈그림, 실패)."""
    outdir = CACHE / "qpf" / tmfc
    outdir.mkdir(parents=True, exist_ok=True)
    with db.tx() as con:
        have = {r["ef"] for r in con.execute("SELECT ef FROM qpf_frame WHERE tmfc=?", (tmfc,))}

    saved, blanks, failed = 0, 0, []
    for ef in efs:
        if ef in have:
            continue
        for attempt in range(2):
            try:
                raw, blank = _crop(await _one(tmfc, ef, c["size"]))
                if blank:
                    blanks += 1
                    break                  # 빈 그림은 저장하지 않는다
                path = outdir / f"{ef:03d}.png"
                path.write_bytes(raw)
                with db.tx() as con:
                    con.execute(
                        "INSERT OR REPLACE INTO qpf_frame(tmfc, ef, path, bytes, fetched_at) VALUES(?,?,?,?,?)",
                        (tmfc, ef, str(path.relative_to(CACHE)), len(raw), at))
                saved += 1
                break
            except KmaError as e:
                # ⚠️ 한꺼번에 던지면 중간이 통째로 실패한다(실측: ef 190~240 누락).
                if attempt:
                    failed.append(f"ef={ef}: {e}")
                else:
                    await asyncio.sleep(0.4)
    return saved, blanks, failed


def _prune(keep: int) -> None:
    """오래된 발표분 정리 — 캐시가 무한히 자라지 않게."""
    with db.tx() as con:
        olds = [r["tmfc"] for r in con.execute(
            "SELECT DISTINCT tmfc FROM qpf_frame ORDER BY tmfc DESC")][keep:]
        for old in olds:
            con.execute("DELETE FROM qpf_frame WHERE tmfc=?", (old,))
            d = CACHE / "qpf" / old
            if d.exists():
                for f in d.iterdir():
                    f.unlink()
                d.rmdir()


def _last_have() -> str | None:
    with db.tx() as con:
        r = con.execute("SELECT MAX(tmfc) t FROM qpf_frame").fetchone()
    return r["t"] if r and r["t"] else None


async def collect(now: datetime | None = None, force: bool = False) -> dict:
    """가진 것보다 새로운 발표분이 올라왔는지 앞으로 훑어 보고, 있으면 최신 것을 받는다.

    ⚠️ 이 API는 지금 시각의 발표분을 바로 주지 않는다. 실측으로 최신 가용분은
       보통 **20~30분 전** 것이다(19:44에 확인한 최신은 19:30). 그래서 현재 슬롯을
       노리고 기다리는 방식은 틀렸다 — 가진 것 다음 슬롯부터 앞으로 훑어
       '빈 그림이 나오기 직전'까지가 올라온 범위다.

    ⚠️ 발표 스탬프는 그림보다 먼저 바뀐다. 그림이 실제로 있는지로만 판정한다.
    """
    now = now or datetime.now()
    at = now.strftime("%Y-%m-%d %H:%M")
    c = cfg()
    efs = frame_efs(c)
    cur = _slot(now)

    last = _last_have()
    if last:
        start = datetime.strptime(last, "%Y%m%d%H%M") + timedelta(minutes=10)
    else:
        start = cur - timedelta(minutes=10 * SCAN_BACK)   # 처음이면 이만큼 거슬러 훑는다

    # 앞으로 훑으며 그림이 있는 마지막 슬롯을 찾는다. 빈 것이 나오면 거기서 멈춘다.
    newest, probes = None, 0
    t = start
    while t <= cur:
        tmfc = t.strftime("%Y%m%d%H%M")
        probes += 1
        try:
            if await _is_blank_slot(tmfc, efs[0], c["size"]):
                break
        except KmaError as e:
            db.log_collect("qpf", False, at, f"확인 실패: {e}")
            return {"tmfc": last, "saved": 0, "error": str(e)}
        newest = tmfc
        t += timedelta(minutes=10)

    if not newest:
        # 새로 올라온 것이 없다. 가진 것을 그대로 쓴다 — 이건 실패가 아니다.
        if last:
            with db.tx() as con:
                have = con.execute("SELECT COUNT(*) n FROM qpf_frame WHERE tmfc=?", (last,)).fetchone()["n"]
            if have >= len(efs):
                return {"tmfc": last, "saved": 0, "skipped": f"새 발표 없음(확인 {probes}회)"}
            newest = last                 # 받다 만 것이 있으면 마저 받는다
        else:
            db.log_collect("qpf", False, at, "받을 수 있는 발표분이 없다")
            return {"tmfc": None, "saved": 0, "skipped": "받을 수 있는 발표분이 없다"}

    lag = (now - datetime.strptime(newest, "%Y%m%d%H%M")).total_seconds() / 60
    saved, blanks, failed = await _download(newest, efs, c, at)
    _prune(int(c.get("keep", KEEP_DEFAULT)))

    if saved:
        db.note_publish(newest, at, round(lag, 1))
        log.info("qpf %s 받음 — %d/%d장 (지금-%.0f분, 확인 %d회)",
                 newest[8:12], saved, len(efs), lag, probes)

    db.log_collect("qpf", saved > 0 or bool(last), at,
                   f"발표 {newest[8:12]} · {saved}/{len(efs)}장 · 지금-{lag:.0f}분"
                   + (f" · 실패 {len(failed)}" if failed else ""))
    return {"tmfc": newest, "saved": saved, "frames": len(efs),
            "lag_min": round(lag, 1), "probes": probes, "failed": failed}

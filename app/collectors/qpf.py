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
import hashlib
import logging
from datetime import datetime, timedelta
from io import BytesIO

from .. import db
from ..config import CACHE, QPF
from ..kma import KmaError, fetch_bytes

log = logging.getLogger("collect.qpf")

KEEP_DEFAULT = 3

# size=1800 응답(1835×1820) 기준 경남 광역 박스.
# ⚠️ 크롭 박스는 소스마다 다르다(QPF 835×820, 초단기 분포도 901×1551).
#    하나로 쓰면 엉뚱한 데가 잘린다 — 소스별로 따로 둔다.
CROP = (660, 560, 660 + 950, 560 + 800)


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


def _stamp(raw: bytes) -> str:
    """이미지 왼쪽 아래에 찍힌 발표시각 표시를 해시한다.

    강수역이 똑같아도 이 글자는 발표마다 달라지므로, 이것으로 판정하면
    무강수 상황에서도 속지 않는다.
    """
    try:
        from PIL import Image
    except ImportError:
        return hashlib.md5(raw).hexdigest()
    im = Image.open(BytesIO(raw))
    return hashlib.md5(im.crop((0, im.height - 22, 240, im.height)).tobytes()).hexdigest()


async def latest_stamp() -> str:
    """지금 올라와 있는 최신 발표분의 표시.

    ⚠️ 아직 안 나온 tm을 주면 API가 최신 발표분으로 바꿔 돌려준다.
       그 성질을 거꾸로 이용한다 — 넉넉히 미래를 요청하면 늘 '최신'이 온다.
       작은 크기(600)로 한 장만 받으므로 확인 비용은 한 번의 호출이다.
    """
    future = (datetime.now() + timedelta(hours=1)).strftime("%Y%m%d%H%M")
    return _stamp(await _one(future, 10, 600))


async def collect(now: datetime | None = None, force: bool = False) -> dict:
    """발표가 났는지 먼저 보고, 난 것만 내려받는다."""
    now = now or datetime.now()
    at = now.strftime("%Y-%m-%d %H:%M")
    c = cfg()
    slot = _slot(now)
    tmfc = slot.strftime("%Y%m%d%H%M")
    efs = frame_efs(c)

    with db.tx() as con:
        have = {r["ef"] for r in con.execute("SELECT ef FROM qpf_frame WHERE tmfc=?", (tmfc,))}
        known = con.execute("SELECT 1 FROM qpf_publish WHERE tmfc=?", (tmfc,)).fetchone()

    # 이미 다 받았으면 아무 것도 하지 않는다
    if have >= set(efs):
        return {"tmfc": tmfc, "saved": 0, "skipped": "완료"}

    # 판정 경로가 보이지 않으면 왜 받았는지/안 받았는지 알 수 없다
    log.debug("qpf %s have=%d/%d known=%s force=%s", tmfc, len(have), len(efs), bool(known), force)

    elapsed = (now - slot).total_seconds() / 60

    if force:
        log.info("qpf %s 수동 조회 — 발표 확인을 건너뛴다", tmfc)

    if not known and not force:
        # 감시 구간 밖에서는 부르지 않는다 — 발표 전에 불러 봐야 헛수고다
        if elapsed < c["watch_from"]:
            return {"tmfc": tmfc, "saved": 0, "skipped": f"대기(+{elapsed:.0f}분)"}
        if elapsed > c["watch_to"]:
            return {"tmfc": tmfc, "saved": 0, "skipped": f"이번 발표는 넘김(+{elapsed:.0f}분)"}
        try:
            now_stamp = await latest_stamp()
        except KmaError as e:
            db.log_collect("qpf", False, at, f"발표 확인 실패: {e}")
            return {"tmfc": tmfc, "saved": 0, "error": str(e)}
        if now_stamp == db.get_setting("qpf_stamp", ""):
            log.debug("qpf %s 미발표 (+%.0f분)", tmfc, elapsed)
            return {"tmfc": tmfc, "saved": 0, "skipped": f"미발표(+{elapsed:.0f}분)"}
        db.put_setting("qpf_stamp", now_stamp)
        db.note_publish(tmfc, at, round(elapsed, 1))
        log.info("발표 %s 확인 (정시+%.0f분) — %d장 내려받는다", tmfc[8:12], elapsed, len(efs))

    outdir = CACHE / "qpf" / tmfc
    outdir.mkdir(parents=True, exist_ok=True)

    saved, failed, blanks = 0, [], 0
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
                #    한 번 쉬고 다시 시도한다.
                if attempt:
                    failed.append(f"ef={ef}: {e}")
                else:
                    await asyncio.sleep(0.4)

    # 오래된 발표분 정리 — 캐시가 무한히 자라지 않게
    with db.tx() as con:
        olds = [r["tmfc"] for r in con.execute(
            "SELECT DISTINCT tmfc FROM qpf_frame ORDER BY tmfc DESC")][int(c.get("keep", KEEP_DEFAULT)):]
        for old in olds:
            con.execute("DELETE FROM qpf_frame WHERE tmfc=?", (old,))
            d = CACHE / "qpf" / old
            if d.exists():
                for f in d.iterdir():
                    f.unlink()
                d.rmdir()

    # 한 장도 못 건졌으면 아직 올라오는 중이다 — 발표를 못 본 것으로 되돌려 다시 시도한다
    if saved == 0 and blanks:
        db.put_setting("qpf_stamp", "")
        with db.tx() as con:
            con.execute("DELETE FROM qpf_publish WHERE tmfc=?", (tmfc,))
        log.info("qpf %s 그림이 아직 비어 있다 — 다음 주기에 다시 받는다", tmfc)
        db.log_collect("qpf", False, at, f"발표 {tmfc[8:12]} · 그림 준비 중")
        return {"tmfc": tmfc, "saved": 0, "skipped": "그림 준비 중"}

    ok = saved > 0 or bool(have)
    db.log_collect("qpf", ok, at, f"발표 {tmfc[8:12]} · {saved}/{len(efs)}장"
                                  + (f" · 빈 그림 {blanks}" if blanks else "")
                                  + (f" · 실패 {len(failed)}" if failed else ""))
    return {"tmfc": tmfc, "saved": saved, "frames": len(efs),
            "blank": blanks, "failed": failed}

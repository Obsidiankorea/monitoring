"""예측 분포 이미지 수집 — nph-qpf_ana_img (융합 qpf=B), 10분 간격 36장.

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
from ..config import CACHE
from ..kma import KmaError, fetch_bytes

log = logging.getLogger("collect.qpf")

SIZE = 1800          # 벽면용. 응답은 1835×1820이 된다.
EF_MAX = 360         # +10 ~ +360분, 10분 간격 36장
KEEP_TMFC = 3        # 최근 발표분 몇 개까지 남길지

# size=1800 응답(1835×1820) 기준 경남 광역 박스. 원본 비율이 바뀌면 여기만 고친다.
CROP = (660, 560, 660 + 950, 560 + 800)


def _slot(now: datetime) -> datetime:
    t = now.replace(second=0, microsecond=0)
    t -= timedelta(minutes=t.minute % 10)
    return t - timedelta(minutes=10)      # 발표 지연 +2~8분


def _crop(raw: bytes) -> bytes:
    try:
        from PIL import Image
    except ImportError:
        return raw                        # PIL이 없으면 전국 그대로 둔다
    im = Image.open(BytesIO(raw))
    box = tuple(min(v, s) for v, s in zip(CROP, (im.width, im.height) * 2))
    out = BytesIO()
    im.crop(box).save(out, format="PNG", optimize=True)
    return out.getvalue()


async def _one(tmfc: str, ef: int) -> bytes:
    return await fetch_bytes("/api/typ03/cgi/dfs/nph-qpf_ana_img", {
        "eva": 1, "tm": tmfc, "qpf": "B", "ef": ef,
        "map": "HR", "grid": 2, "legend": 1, "size": SIZE,
        "zoom_level": 0, "zoom_x": "0000000", "zoom_y": "0000000",
        "stn": 108, "x1": 470, "y1": 575,
    })


async def collect(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    at = now.strftime("%Y-%m-%d %H:%M")
    tmfc = _slot(now).strftime("%Y%m%d%H%M")
    outdir = CACHE / "qpf" / tmfc
    outdir.mkdir(parents=True, exist_ok=True)

    with db.tx() as con:
        have = {r["ef"] for r in con.execute("SELECT ef FROM qpf_frame WHERE tmfc=?", (tmfc,))}

    saved, failed = 0, []
    for ef in range(10, EF_MAX + 1, 10):
        if ef in have:
            continue
        for attempt in range(2):
            try:
                raw = _crop(await _one(tmfc, ef))
                path = outdir / f"{ef:03d}.png"
                path.write_bytes(raw)
                with db.tx() as con:
                    con.execute(
                        "INSERT OR REPLACE INTO qpf_frame(tmfc, ef, path, bytes, fetched_at) VALUES(?,?,?,?,?)",
                        (tmfc, ef, str(path.relative_to(CACHE)), len(raw), at))
                saved += 1
                break
            except KmaError as e:
                if attempt:
                    failed.append(f"ef={ef}: {e}")
                else:
                    await asyncio.sleep(0.4)

    # 오래된 발표분 정리 — 캐시가 무한히 자라지 않게
    with db.tx() as con:
        olds = [r["tmfc"] for r in con.execute(
            "SELECT DISTINCT tmfc FROM qpf_frame ORDER BY tmfc DESC")][KEEP_TMFC:]
        for old in olds:
            con.execute("DELETE FROM qpf_frame WHERE tmfc=?", (old,))
            d = CACHE / "qpf" / old
            if d.exists():
                for f in d.iterdir():
                    f.unlink()
                d.rmdir()

    ok = saved > 0 or bool(have)
    db.log_collect("qpf", ok, at, f"발표 {tmfc[8:12]} · {saved}장"
                                  + (f" · 실패 {len(failed)}" if failed else ""))
    return {"tmfc": tmfc, "saved": saved, "failed": failed}

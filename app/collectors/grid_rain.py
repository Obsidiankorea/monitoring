"""격자 강수 수집 — 경남 지도 판의 출처.

    grid   고해상도 격자 500m, NetCDF(`sfc_grid_nc_down.php`) — rn_15m · rn_60m · rn_day
    odam   동네예보 실황 RN1 5km(`nph-dfs_odam_grd`)

받자마자 경남 bbox 만 잘라 gridstore 에 둔다. 전국 원본은 저장하지 않는다.
과거를 거슬러 채우지 않는다 — 늘 가장 최근 것 하나만 받는다.

⚠️ 500m 는 바이너리(disp=B)가 아니라 **NetCDF** 로 받는다. 같은 자료가 16.8MB 대 46~430KB 다
   (실측 2026-10-01). 10분마다 셋이면 하루 7GB 대 0.1GB — 기관키 한도는 여러 PC 가 나눠 쓴다.
⚠️ 기준시각 +5분 남짓에 만들어진다(NetCDF time_in 실측). 그래서 6분 물러선 10분 칸부터
   묻고, 아직 없으면 한 칸 더 물러선다. 아직 없는 시각은 `# file not found` 같은 한 줄이 온다.
⚠️ 격자 틀(원점 칸·간격·기준 경위도)을 **받을 때마다 확인한다.** 기상청이 틀을 바꾸면
   경계와 어긋난 자리에 비가 그려진다 — 그때는 저장하지 않고 실패로 남긴다.
⚠️ 일강수 00:00 은 **전날 총량**, 00:05 는 반쯤 리셋된 값이다(실측: 8.28. 최대 140.2 → 00:05
   13.2 → 00:10 0.4). 두 칸은 받지 않는다 — 그동안 화면에는 23:55 값이 제 시각과 함께 남는다.
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timedelta

import numpy as np

from .. import db, gridstore
from ..kma import KmaError, fetch_bytes, fetch_text
from .forecast import _parse_grid

log = logging.getLogger("collect.grid")

OBS = {"rn_15m": "obs15", "rn_60m": "obs60", "rn_day": "obsday"}
LAG_MIN = 6
SKIP_DAY = ("0000", "0005")

# NetCDF 전역 속성 — 실측과 다르면 격자 틀이 바뀐 것이다(README '경남 지도')
FRAME = {"map_sx": 880, "map_sy": 1540, "map_slon": 126.0, "map_slat": 38.0,
         "grid_size": 0.5, "grid_nx": 2049, "grid_ny": 2049}


def hr_slots(now: datetime) -> list[datetime]:
    """10분 칸(:00·:10·…)만 받는다. 자료는 5분마다 있지만, 지도 재생 간격(10·20·30·60분)이
    늘 맞아떨어지게 칸을 고정한다 — 수집 주기의 위상에 따라 :05·:15… 만 쌓이면 정시 칸이 없다."""
    t = (now - timedelta(minutes=LAG_MIN)).replace(second=0, microsecond=0)
    t -= timedelta(minutes=t.minute % 10)
    return [t, t - timedelta(minutes=10)]


def parse_nc(body: bytes) -> np.ndarray:
    """NetCDF(HDF5) → 2049×2049 ㎜. 결측은 NaN. 행은 남→북(바이너리·ASCII 와 같은 순서)."""
    import h5py       # 없으면 이 수집기만 실패로 남는다 — 서버는 뜬다

    with h5py.File(io.BytesIO(body), "r") as f:
        for k, want in FRAME.items():
            got = float(np.ravel(f.attrs.get(k, [np.nan]))[0])
            if not abs(got - want) < 1e-6:
                raise KmaError(f"격자 틀이 바뀌었다({k}={got}, 실측 {want}) — 그리지 않는다")
        ds = f["data"]
        if ds.shape != (2049, 2049):
            raise KmaError(f"격자 크기가 {ds.shape} — 2049×2049 여야 한다")
        raw = ds[...]
        scale = float(np.ravel(ds.attrs.get("data_scale", [1.0]))[0])
    out = raw.astype("f8") / scale
    out[raw <= -9000] = np.nan         # −9990 = −999.0 결측
    return out


async def _fetch_hr(obs: str, tm: str) -> np.ndarray | None:
    """None = 아직 안 만들어졌다(조회 실패가 아니다)."""
    body = await fetch_bytes("/api/typ01/url/sfc_grid_nc_down.php", {"obs": obs, "tm": tm})
    if body[:4] == b"\x89HDF":
        return parse_nc(body)
    head = body[:120].decode("euc-kr", errors="replace").strip()
    if head.startswith("#"):
        return None
    raise KmaError(f"NetCDF 가 아니다: {head[:60]}")


async def collect(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    at = now.strftime("%Y-%m-%d %H:%M")
    got, fresh, failed = {}, 0, []
    for obs, layer in OBS.items():
        for t in hr_slots(now):
            tm = t.strftime("%Y%m%d%H%M")
            if layer == "obsday" and tm[8:] in SKIP_DAY:
                continue
            if gridstore.has(layer, tm):
                got[layer] = tm
                break
            try:
                full = await _fetch_hr(obs, tm)
            except KmaError as e:
                failed.append(f"{obs} {tm[8:]}: {e}")
                break
            if full is None:
                continue                          # 아직 없다 — 한 칸 물러선다
            gridstore.save(layer, tm, gridstore.crop_hr(full))
            got[layer] = tm
            fresh += 1
            break
    gridstore.prune(OBS.values(), now)
    ok = not failed
    tms = sorted(set(got.values()))
    msg = f"500m {tms[-1][8:10]}:{tms[-1][10:12]}" if tms else "500m 아직 없음"
    msg += f" · 새로 {fresh}"
    if failed:
        msg += f" · 실패 {'; '.join(failed)}"
    db.log_collect("grid", ok, at, msg)
    return {"got": got, "fresh": fresh, "failed": failed}


# ── 실황 5km ────────────────────────────────────────────────────────────
def odam_slots(now: datetime) -> list[datetime]:
    """10분 발표. 지연은 3~13분 사이로 봤다(08:13 에 08:00 은 있고 08:10 은 없었다)."""
    t = (now - timedelta(minutes=5)).replace(second=0, microsecond=0)
    t -= timedelta(minutes=t.minute % 10)
    return [t, t - timedelta(minutes=10)]


async def collect_odam(now: datetime | None = None) -> dict:
    now = now or datetime.now()
    at = now.strftime("%Y-%m-%d %H:%M")
    got, fresh, failed = None, 0, []
    for t in odam_slots(now):
        tm = t.strftime("%Y%m%d%H%M")
        if gridstore.has("odam", tm):
            got = tm
            break
        try:
            text = await fetch_text("/api/typ01/cgi-bin/url/nph-dfs_odam_grd",
                                    {"tmfc": tm, "vars": "RN1"})
        except KmaError as e:
            failed.append(f"{tm[8:]}: {e}")
            break
        vals = _parse_grid(text)
        if not vals:
            if "file_read" in text:
                continue                          # 아직 없다
            failed.append(f"{tm[8:]}: {text.strip()[:60]}")
            break
        try:
            arr = gridstore.crop_dfs(vals)
        except ValueError as e:
            failed.append(f"{tm[8:]}: {e}")
            break
        gridstore.save("odam", tm, arr)
        got, fresh = tm, 1
        break
    gridstore.prune(("odam",), now)
    msg = f"실황 {got[8:10]}:{got[10:12]}" if got else "실황 아직 없음"
    if failed:
        msg += f" · 실패 {'; '.join(failed)}"
    db.log_collect("odam", not failed, at, msg)
    return {"got": got, "fresh": fresh, "failed": failed}

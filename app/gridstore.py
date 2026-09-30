"""격자 강수 프레임 — 경남 bbox 만 잘라 파일로 둔다. 경남 지도 판의 출처.

형식: 0.1㎜ 단위 uint16 리틀엔디언, gzip. 행은 **남→북**(기상청 순서 그대로), 한 행은 서→동.
    0          무강수
    1~65533    값 × 10
    65535      결측 — 기상청 −999·−99. 경남 bbox 안에서는 거의 다 분석 영역 밖 바다다
조회 실패는 **파일이 없는 것**이다. 결측(65535)과 다르다 — 화면은 meta 의 기준시각으로 안다.

경로: data/cache/grid/{층}/{키}.u16.gz
    obs15 · obs60 · obsday   500m   키 = 기준시각 YYYYMMDDHHMI
    odam                     5km    키 = 발표시각 YYYYMMDDHHMI
    vsrt                     5km    키 = {tmfc}_{tmef}        초단기 RN1
    shrt                     5km    키 = {tmfc}_{tmef}        단기 PCP(1시간), 10자리

⚠️ 5km 층은 5km 칸 그대로 저장한다. 시군 통계를 낼 때만 500m 칸으로 펼친다 —
   두 격자는 지구 모양이 달라(타원체/구면) 정확히 겹치지 않으므로 아핀으로 옮긴다.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timedelta
from functools import lru_cache

import numpy as np

from .config import CACHE, DATA
from .domain import gridproj

GEO = DATA / "geo"
ROOT = CACHE / "grid"
MISSING = 65535
KEEP_DAYS = 3            # 실측 층(obs*·odam) 보관
KEEP_RUNS = 3            # 예측 층(vsrt·shrt) 발표분 보관

GRID_OF = {"obs15": "hr", "obs60": "hr", "obsday": "hr", "odam": "dfs", "vsrt": "dfs", "shrt": "dfs"}


@lru_cache(maxsize=1)
def geo() -> dict:
    return json.loads((GEO / "grids.json").read_text(encoding="utf-8"))


def shape(grid: str) -> tuple[int, int]:
    b = geo()[grid]["bbox"]
    return b["h"], b["w"]


@lru_cache(maxsize=1)
def masks() -> tuple[np.ndarray, np.ndarray]:
    h, w = shape("hr")
    sig = np.frombuffer(gzip.decompress((GEO / "mask_sigun.u8.gz").read_bytes()), np.uint8)
    emd = np.frombuffer(gzip.decompress((GEO / "mask_emd.u16.gz").read_bytes()), "<u2")
    return sig.reshape(h, w), emd.reshape(h, w)


# ── 자르기 ─────────────────────────────────────────────────────────────
def crop_hr(full: np.ndarray) -> np.ndarray:
    """2049×2049(행 남→북) → 경남 bbox. 결측은 NaN."""
    b = geo()["hr"]["bbox"]
    return full[b["j0"]:b["j1"] + 1, b["i0"]:b["i1"] + 1]


def crop_dfs(vals) -> np.ndarray:
    """동네예보 격자 37,697개 → 경남 bbox. −99·−999 는 NaN.

    ⚠️ 경남 bbox 안의 −99 는 늘 같은 564칸이다(격자 영역 밖 바다). 무강수는 0 으로 온다.
    """
    g = geo()["dfs"]
    a = np.asarray(vals, dtype="f8")
    if a.size != g["nx"] * g["ny"]:
        raise ValueError(f"격자 크기가 {a.size} — {g['nx'] * g['ny']} 이어야 한다")
    a = a.reshape(g["ny"], g["nx"])
    b = g["bbox"]
    out = a[b["j0"]:b["j1"] + 1, b["i0"]:b["i1"] + 1].copy()
    out[out <= -90] = np.nan
    return out


# ── 부호화 ─────────────────────────────────────────────────────────────
def encode(arr: np.ndarray) -> bytes:
    """NaN → 65535, 나머지는 0.1㎜ 반올림. 음수는 0 으로 두지 않고 결측으로 본다."""
    a = np.asarray(arr, dtype="f8")
    bad = ~np.isfinite(a) | (a < 0)
    u = np.clip(np.rint(np.where(bad, 0, a) * 10), 0, MISSING - 2).astype("<u2")
    u[bad] = MISSING
    return u.tobytes()


def decode(raw: bytes, grid: str) -> np.ndarray:
    u = np.frombuffer(raw, "<u2").reshape(shape(grid))
    out = u.astype("f8") / 10
    out[u == MISSING] = np.nan
    return out


# ── 파일 ───────────────────────────────────────────────────────────────
def _path(layer: str, key: str):
    return ROOT / layer / f"{key}.u16.gz"


def save(layer: str, key: str, arr: np.ndarray) -> None:
    """임시 파일에 쓰고 바꿔 끼운다 — 화면이 반쯤 쓴 파일을 읽지 않게."""
    p = _path(layer, key)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(encode(arr), 6))
    os.replace(tmp, p)


def has(layer: str, key: str) -> bool:
    return _path(layer, key).exists()


def keys(layer: str) -> list[str]:
    d = ROOT / layer
    if not d.exists():
        return []
    return sorted(f.name[:-len(".u16.gz")] for f in d.glob("*.u16.gz"))


def raw_gz(layer: str, key: str) -> bytes | None:
    p = _path(layer, key)
    return p.read_bytes() if p.exists() else None


def load(layer: str, key: str) -> np.ndarray | None:
    gz = raw_gz(layer, key)
    return None if gz is None else decode(gzip.decompress(gz), GRID_OF[layer])


def prune(layers=None, now: datetime | None = None) -> dict[str, int]:
    """실측은 KEEP_DAYS 일, 예측은 최근 KEEP_RUNS 발표분만 남긴다.

    수집기가 받을 때마다 제 층만 치운다 — 초단기는 10분마다 6장씩 쌓여 새벽 정리만
    기다리면 하루 860장이 된다. 새벽 정리(maint)는 전부 한 번 더 돈다.
    """
    now = now or datetime.now()
    cut = (now - timedelta(days=KEEP_DAYS)).strftime("%Y%m%d%H%M")
    removed: dict[str, int] = {}
    for layer in layers or GRID_OF:
        ks = keys(layer)
        if layer in ("vsrt", "shrt"):
            runs = sorted({k.split("_")[0] for k in ks})
            keep = set(runs[-KEEP_RUNS:])
            gone = [k for k in ks if k.split("_")[0] not in keep]
        else:
            gone = [k for k in ks if k < cut]
        for k in gone:
            _path(layer, k).unlink(missing_ok=True)
        if gone:
            removed[f"grid/{layer}"] = len(gone)
    return removed


def usage() -> tuple[int, int]:
    """(바이트, 파일 수)."""
    n = tot = 0
    if ROOT.exists():
        for f in ROOT.rglob("*.u16.gz"):
            tot += f.stat().st_size
            n += 1
    return tot, n


# ── 5km → 500m 펼치기 ───────────────────────────────────────────────────
@lru_cache(maxsize=1)
def _dfs_index() -> np.ndarray:
    """500m bbox 칸마다 그 칸 가운데가 드는 5km bbox 칸의 평탄 인덱스(밖이면 −1)."""
    g = geo()
    hb, db = g["hr"]["bbox"], g["dfs"]["bbox"]
    a, b, c = g["dfs_to_hr"]["col"]
    d, e, f = g["dfs_to_hr"]["row"]
    inv = np.linalg.inv(np.array([[a, b], [d, e]]))
    rr, cc = np.mgrid[0:hb["h"], 0:hb["w"]]
    col = cc + hb["i0"] - c
    row = rr + hb["j0"] - f
    x5 = inv[0, 0] * col + inv[0, 1] * row
    y5 = inv[1, 0] * col + inv[1, 1] * row
    ix = np.rint(x5).astype(int) - db["i0"]
    iy = np.rint(y5).astype(int) - db["j0"]
    ok = (ix >= 0) & (ix < db["w"]) & (iy >= 0) & (iy < db["h"])
    return np.where(ok, iy * db["w"] + ix, -1)


def to_hr(arr5: np.ndarray) -> np.ndarray:
    idx = _dfs_index()
    flat = arr5.ravel()
    out = np.full(idx.shape, np.nan)
    ok = idx >= 0
    out[ok] = flat[idx[ok]]
    return out


# ── 시군 통계 ──────────────────────────────────────────────────────────
def sigun_stats(arr_hr: np.ndarray) -> list[dict]:
    """시군마다 최대·평균·위치. 결측 칸은 평균에서 **뺀다**(0 으로 치지 않는다).

    최대 위치는 그 칸이 드는 읍면동. 같은 최대가 여러 칸이면(5km 칸이 펼쳐진 경우 등)
    그 칸들의 한가운데에서 가장 가까운 칸을 고른다 — 래스터 순서 첫 칸은 한쪽 끝이다.
    """
    g = geo()
    hb = g["hr"]["bbox"]
    msig, memd = masks()
    emds = {e["id"]: e for e in g["emd"]}
    out = []
    for s in g["sigun"]:
        inside = msig == s["id"]
        vals = arr_hr[inside]
        good = vals[np.isfinite(vals)]
        row = {"sigun": s["name"], "kind": s["kind"], "cells": int(inside.sum()),
               "missing": int(vals.size - good.size), "max": None, "mean": None, "where": None}
        if good.size:
            mx = float(good.max())
            row["max"] = round(mx, 1)
            row["mean"] = round(float(good.mean()), 2)
            row["wet"] = round(float((good >= 0.1).mean()), 3)
            if mx < 0.1:
                out.append(row)                 # 비가 없으면 '어디서 최대'도 없다
                continue
            rr, cc = np.nonzero(inside & np.isfinite(arr_hr) & (arr_hr >= mx - 1e-9))
            k = int(np.argmin((rr - rr.mean()) ** 2 + (cc - cc.mean()) ** 2))
            r, c = int(rr[k]), int(cc[k])
            col, lat_row = c + hb["i0"], r + hb["j0"]
            e = emds.get(int(memd[r, c]))
            if e is None or e["sigun"] != s["name"]:
                # 경계 칸 — 읍면동 지도와 시군 지도가 어긋난 자리. 같은 시군에서 가까운 곳
                cand = [x for x in g["emd"] if x["sigun"] == s["name"] and x["c"]]
                e = min(cand, key=lambda x: (x["c"][0] - col) ** 2 + (x["c"][1] - lat_row) ** 2,
                        default=None)
            lon, lat = gridproj.hr_lonlat(col, lat_row)
            row["where"] = {"emd": e["name"] if e else None, "col": col, "row": lat_row,
                            "lon": round(lon, 4), "lat": round(lat, 4)}
        out.append(row)
    return out

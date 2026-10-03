"""경남 지도 재현 사례 — data/demo/map/{사례}/ 를 읽는다. 기상청을 부르지 않는다.

사례는 tools/build_map_case.py 가 굳혀 둔다(500m 60분 격자 매시 정각 + meta.json).
층은 둘이다.
    obs60   그 시각 60분 강수(= 그 앞 한 시간)
    acc     사례 처음부터 그 시각까지 칸마다 더한 누적 — 결측 칸은 결측으로 남는다

⚠️ 사례의 특보는 **산출**이다(격자 3시간·12시간 합에 호우 기준). 특보 이력 API 가 이 키로 403 이라
   실제 발표 내역을 담을 수 없다. 화면은 '산출'이라 적는다.
"""
from __future__ import annotations

import gzip
import json
import re
from functools import lru_cache

import numpy as np

from . import gridstore
from .config import DATA

ROOT = DATA / "demo" / "map"
_SLUG = re.compile(r"^[a-z0-9-]{1,64}$")


def _dir(slug: str):
    if not _SLUG.match(slug or "") or not (ROOT / slug / "meta.json").exists():
        raise LookupError(f"모르는 사례: {slug}")
    return ROOT / slug


def listing() -> list[dict]:
    out = []
    if ROOT.exists():
        for m in sorted(ROOT.glob("*/meta.json")):
            j = json.loads(m.read_text("utf-8"))
            out.append({k: j.get(k) for k in ("slug", "title", "start", "end", "peak")})
    return out


@lru_cache(maxsize=8)
def meta(slug: str) -> dict:
    return json.loads((_dir(slug) / "meta.json").read_text("utf-8"))


@lru_cache(maxsize=128)
def obs(slug: str, tm: str) -> np.ndarray:
    p = _dir(slug) / "obs60" / f"{tm}.u16.gz"
    if not p.exists():
        raise LookupError(f"{slug} {tm} 없음")
    a = gridstore.decode(gzip.decompress(p.read_bytes()), "hr")
    a.setflags(write=False)
    return a


@lru_cache(maxsize=96)
def acc(slug: str, tm: str) -> np.ndarray:
    frames = meta(slug)["frames"]
    if tm not in frames:
        raise LookupError(f"{slug} {tm} 없음")
    i = frames.index(tm)
    a = (acc(slug, frames[i - 1]) if i else 0) + obs(slug, tm)   # 앞 시각 누적에 한 시간을 더한다
    a.setflags(write=False)
    return a


def frame(slug: str, layer: str, tm: str | None) -> dict:
    m = meta(slug)
    tm = tm or m["end"]
    if layer not in ("obs60", "acc"):
        raise LookupError(f"사례에는 1시간(obs60)·누적(acc)만 있다: {layer}")
    arr = obs(slug, tm) if layer == "obs60" else acc(slug, tm)
    return {"grid": "hr", "tm": tm, "arr": arr, "case": slug,
            **({"from": m["start"]} if layer == "acc" else {})}


def flow(slug: str) -> dict:
    """재생 흐름 — 사례 처음부터 끝까지 매시. 예측은 없다(그때의 실측만)."""
    m = meta(slug)
    frames = [{"t": t, "kind": "obs", "layer": "obs60", "key": t} for t in m["frames"]]
    return {"now": m["end"], "start": m["start"], "hours": len(frames), "step": 60, "tmfc": None,
            "frames": frames, "case": {k: m[k] for k in ("slug", "title", "start", "end", "peak")},
            "series": [{"sigun": s["sigun"], "max": s["h1"], "mean": s.get("h1m", s["h1"])} for s in m["series"]],
            "total": {"max": m["total"]["h1"], "mean": m["total"].get("h1m", m["total"]["h1"])}}

"""스방(내부망) 자체 지점의 위치 — 정확한 계기 위치를 받기 전까지 **임시로** 읍면동 가운데에 둔다.

스방 지점 가운데 기상청 지점번호로 오는 것은 data/geo/stations.json 에 위치가 있다. 나머지(스방 장치코드
lnk_id)는 위치를 모른다. 그래서 이름이 가리키는 읍면동을 찾아 그 읍면동 **안쪽 가장 깊은 점**
(emd.topo.json 의 lx·ly — mapshaper innerX/innerY. 무게중심은 오목한 읍면동이면 밖에 떨어진다)에 둔다.

    '시천면(가상)' → 시천면   '시천' → 시천면   '덕산(시천면)' → 시천면   '회원' → 회원1동·회원2동 중 하나라 못 정함

⚠️ 추정 위치다(est=True). 화면은 '스방 지점은 읍면동 가운데에 임시로 둔다'고 적는다.
정확한 위치를 받으면 data/geo/bangjae_sites.json 에 장치코드별로 적는다 — 그 값이 먼저다:

    {"sites": {"<lnk_id>": {"lon": 127.83, "lat": 35.26}, ...}}
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from . import gridstore
from .domain import gridproj

OVERRIDE = gridstore.GEO / "bangjae_sites.json"


@lru_cache(maxsize=1)
def _emd_points() -> dict[str, dict[str, tuple[float, float]]]:
    """{시군: {읍면동: (열, 행)}} — 읍면동 이름 자리(안쪽 가장 깊은 점)."""
    t = json.loads((gridstore.GEO / "emd.topo.json").read_text("utf-8"))
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for g in t["objects"]["emd"]["geometries"]:
        p = g["properties"]
        out.setdefault(p["sigun"], {})[p["name"]] = (p["lx"], p["ly"])
    return out


def _overrides() -> dict:
    """정확한 위치(받으면 적는 파일). 파일이 바뀌면 바로 따라가게 캐시하지 않는다 — 작다."""
    try:
        return json.loads(OVERRIDE.read_text("utf-8")).get("sites", {})
    except (OSError, ValueError):
        return {}


def emd_of(name: str, sigun: str) -> str | None:
    """지점 이름 → 그 시군 읍면동 이름. 못 정하면 None."""
    pts = _emd_points().get(sigun, {})
    if not pts or not name:
        return None
    inner = re.findall(r"\(([^)]*)\)", name)
    base = re.sub(r"\([^)]*\)", "", name)
    for tok in [base, *inner]:
        t = re.sub(r"\s+", "", tok)
        if not t or t in ("가상",):
            continue
        if t in pts:
            return t
        for suf in ("읍", "면", "동"):
            if t + suf in pts:
                return t + suf
        hit = [e for e in pts if e.startswith(t)]
        if len(hit) == 1:                       # 여럿이면(회원1동·회원2동) 정하지 않는다
            return hit[0]
    return None


def position(stn: str, name: str, sigun: str) -> dict | None:
    """{x, y(500m 칸), est, emd?} — 받은 정확한 위치가 있으면 그것, 없으면 읍면동 가운데(est=True)."""
    o = _overrides().get(stn)
    if o:
        if "x" in o and "y" in o:
            x, y = float(o["x"]), float(o["y"])
        else:
            x, y = gridproj.hr_xy(float(o["lon"]), float(o["lat"]))
        return {"x": round(x, 2), "y": round(y, 2), "est": False}
    e = emd_of(name, sigun)
    if not e:
        return None
    x, y = _emd_points()[sigun][e]
    return {"x": x, "y": y, "est": True, "emd": e}

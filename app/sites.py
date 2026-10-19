"""경남 AWS(스방 — 경남 스마트 통합 방재시스템, 내부망) 지점의 위치와 관리기관.

**위치는 경남 AWS 목록(data/geo/aws_sites.json — tools/build_aws_sites.py 가 엑셀로 만든다)이 먼저다.**
스방은 지점을 장치코드(lnk_id) · 장치명 · 시군으로 주는데 목록에는 장치코드가 없어 **시군 + 장치명**으로
짝짓는다(띄어쓰기 · 괄호 · '김해시'처럼 시군 이름에 붙은 시/군은 떼고 본다 — 목록 '거창북상'은 스방 '북상'이라
앞머리 시군 이름도 뗀다). 같은 시군에 같은 이름이 경남 · 기상청 둘이면(합천 · 거창 북상) 기상청 지점번호로 오는
것이 기상청이다(그건 stations.json 이 위치를 안다).
목록에서 못 찾은 지점만 아래처럼 이름이 가리키는 읍면동 가운데에 **임시로** 둔다(est).

스방 지점 가운데 기상청 지점번호로 오는 것은 data/geo/stations.json 에 위치가 있다. 나머지(스방 장치코드
lnk_id)는 위치를 모른다. 그래서 이름이 가리키는 읍면동을 찾아 그 읍면동 **안쪽 가장 깊은 점**
(emd.topo.json 의 lx·ly — mapshaper innerX/innerY. 무게중심은 오목한 읍면동이면 밖에 떨어진다)에 둔다.

    '시천면(가상)' → 시천면   '시천' → 시천면   '덕산(시천면)' → 시천면   '회원' → 회원1동·회원2동 중 하나라 못 정함

⚠️ 추정 위치다(est=True). 화면은 '경남 AWS ○곳은 읍면동 가운데에 임시로 둔다'고 적는다.
장치코드로 따로 바로잡을 지점은 data/geo/bangjae_sites.json 에 적는다 — 그 값이 무엇보다 먼저다:

    {"sites": {"<lnk_id>": {"lon": 127.83, "lat": 35.26}, "<lnk_id>": {"sigun": "산청"}, ...}}

`sigun` 은 스방이 시군을 잘못 줄 때다(8857 '신등'을 '사천'으로 준다 — 엑셀 · 비 값 모두 산청 신등면).
DB(bangjae_hourly)에는 스방이 준 그대로 두고 **읽을 때** `sigun_of()` 로 바꾼다 — 시군 평균 · 짝짓기 · 위치가 다 그걸 따른다.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache

from . import gridstore
from .domain import gridproj

OVERRIDE = gridstore.GEO / "bangjae_sites.json"
AWS = gridstore.GEO / "aws_sites.json"


@lru_cache(maxsize=1)
def _aws() -> dict[tuple[str, str], list[dict]]:
    """{(시군, 이름 열쇠): [지점]} — 경남 AWS 목록. 없으면 비어 있다(읍면동 짐작으로 물러선다)."""
    try:
        sites = json.loads(AWS.read_text("utf-8"))["sites"]
    except (OSError, ValueError, KeyError):
        return {}
    out: dict[tuple[str, str], list[dict]] = {}
    for s in sites:
        for k in _keys(s["name"], s["sigun"]):
            lst = out.setdefault((s["sigun"], k), [])
            if s not in lst:
                lst.append(s)
    return out


def _keys(name: str, sigun: str) -> list[str]:
    """짝짓는 열쇠 — 띄어쓰기 · 괄호를 뗀 것, '김해시' → '김해', 끝의 AWS · 관측소를 뗀 것,
    앞머리 시군 이름을 뗀 것('거창북상' → '북상'. '거창읍'처럼 한 글자만 남으면 떼지 않는다)."""
    n = re.sub(r"\s+", "", name or "")
    base = re.sub(r"\([^)]*\)", "", n)
    out = []
    for t in (n, base):
        for x in (t, re.sub(r"(AWS|aws|자동기상관측소|기상관측소|관측소)$", "", t)):
            if x in (sigun + "시", sigun + "군"):
                x = sigun
            for y in (x, x[len(sigun):] if x.startswith(sigun) and len(x) - len(sigun) >= 2 else ""):
                if y and y not in out:
                    out.append(y)
    return out


def aws_site(name: str, sigun: str, kma: bool = False) -> dict | None:
    """경남 AWS 목록에서 그 지점. 같은 이름이 경남 · 기상청 둘이면 kma(기상청 지점번호로 왔나)로 고른다.
    '(가상)' 은 테스트 합성 지점이다 — 실제 지점에 짝짓지 않는다."""
    if "(가상)" in (name or ""):
        return None
    hit: list[dict] = []
    for k in _keys(name, sigun):
        for s in _aws().get((sigun, k), []):
            if s not in hit:
                hit.append(s)
    if not hit:
        return None
    want = "kma" if kma else "gn"
    cand = [s for s in hit if s["org"] == want] or hit
    n = re.sub(r"\s+", "", name or "")
    return next((s for s in cand if s["name"] == n), cand[0])     # 같은 기관 둘이면 이름이 똑같은 쪽


@lru_cache(maxsize=1)
def gn_sites() -> list[dict]:
    """경남 AWS(관리기관 경상남도) 지점 — 지도 관측소 층에 기상청 지점과 함께 짚는다. stn 은 'G<차례>'."""
    try:
        sites = json.loads(AWS.read_text("utf-8"))["sites"]
    except (OSError, ValueError, KeyError):
        return []
    return [{"stn": f"G{i}", "name": s["name"], "sigun": s["sigun"], "x": s["x"], "y": s["y"],
             "ht": s.get("ht") or 0, "org": "gn", "addr": s.get("addr", ""), "place": s.get("place", "")}
            for i, s in enumerate(x for x in sites if x["org"] == "gn")]


def org_of(stn: str, name: str, sigun: str, kma: bool) -> str:
    """관리기관 — 'kma'(기상청 AWS) | 'gn'(경남 AWS). 기상청 지점번호로 오면 기상청, 아니면 목록, 목록에 없으면 경남."""
    if kma:
        return "kma"
    s = aws_site(name, sigun)
    return s["org"] if s else "gn"


def _emd_at(x: float, y: float, sigun: str) -> str | None:
    hb = gridstore.geo()["hr"]["bbox"]
    c, r = round(x) - hb["i0"], round(y) - hb["j0"]
    if not (0 <= r < hb["h"] and 0 <= c < hb["w"]):
        return None
    e = _emd_by_id().get(int(gridstore.masks()[1][r, c]))
    return e["name"] if e and e["sigun"] == sigun else None


@lru_cache(maxsize=1)
def _emd_by_id() -> dict[int, dict]:
    return {e["id"]: e for e in gridstore.geo()["emd"]}


@lru_cache(maxsize=1)
def _emd_points() -> dict[str, dict[str, tuple[float, float]]]:
    """{시군: {읍면동: (열, 행)}} — 읍면동 이름 자리(안쪽 가장 깊은 점)."""
    t = json.loads((gridstore.GEO / "emd.topo.json").read_text("utf-8"))
    out: dict[str, dict[str, tuple[float, float]]] = {}
    for g in t["objects"]["emd"]["geometries"]:
        p = g["properties"]
        out.setdefault(p["sigun"], {})[p["name"]] = (p["lx"], p["ly"])
    return out


_ov: dict = {}


def _overrides() -> dict:
    """장치코드로 바로잡은 위치 · 시군(받으면 적는 파일). 파일이 바뀌면 바로 따라가게 고친 시각으로만 캐시한다
    — 시간 강우량 줄마다(수천 번) 부른다."""
    try:
        key = (str(OVERRIDE), OVERRIDE.stat().st_mtime_ns)
        if _ov.get("key") != key:
            _ov.update(key=key, sites=json.loads(OVERRIDE.read_text("utf-8")).get("sites", {}))
        return _ov["sites"]
    except (OSError, ValueError):
        return {}


def sigun_of(stn: str, sigun: str) -> str:
    """스방이 준 시군 — bangjae_sites.json 에 그 장치코드의 시군을 바로잡아 두었으면 그것."""
    return str((_overrides().get(stn) or {}).get("sigun") or sigun)


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
    """{x, y(500m 칸), est, emd?, src} — 장치코드로 바로잡은 것 > 경남 AWS 목록 > 읍면동 가운데(est=True)."""
    o = _overrides().get(stn)
    if o and (("x" in o and "y" in o) or ("lon" in o and "lat" in o)):      # 시군만 바로잡은 것은 목록으로
        if "x" in o and "y" in o:
            x, y = float(o["x"]), float(o["y"])
        else:
            x, y = gridproj.hr_xy(float(o["lon"]), float(o["lat"]))
        return {"x": round(x, 2), "y": round(y, 2), "est": False, "emd": _emd_at(x, y, sigun), "src": "fix"}
    s = aws_site(name, sigun)
    if s:
        return {"x": s["x"], "y": s["y"], "est": False, "emd": _emd_at(s["x"], s["y"], sigun), "src": "aws"}
    e = emd_of(name, sigun)
    if not e:
        return None
    x, y = _emd_points()[sigun][e]
    return {"x": x, "y": y, "est": True, "emd": e, "src": "emd"}

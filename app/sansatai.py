"""산림청 디지털사면통합산사태정보시스템(sansatai.forest.go.kr) — 지도 '산사태' 층 · 보고서용.

두 갈래다.
  공개(로그인 없이) — 강우반영 산사태위험도. 산림청이 매시 분석한 등급 격자(1등급 빨강 ~ 5등급 파랑)를 iServer 가
      그림으로 준다(공개 화면 mhms_pub/…/lndsMapLivePage.do 가 쓰는 것). 경남 범위를 경위도로 잘라 한 장 받고
      ① 그 그림(raw, 경위도 평면) ② 우리 500m 격자를 5×5 로 나눈 100m 칸 지도(지도 그림 · 면적) ③ 500m 칸 지도
      (칸에서 면적이 가장 넓은 등급 — 다른 500m 자료와 맞춰 볼 때)를 둔다. 강수 격자와 같은 칸 체계라 지도에 그대로
      얹히고, 시군 칸 지도(mask_sigun)로 시군별 등급 면적(㎢)을 센다.
  로그인(SANSATAI_ID · SANSATAI_PW) — 경상남도 기관 계정으로 보이는 것.
      실황 · 예측(읍면동) · 예측 대비 예보 발령 현황(시군) · 산악기상 관측소(경남 41곳 시간 강우) ·
      산림청 AWS(10분) · 중기(48시간) 예측. 예측 · 실황은 지난 날짜도 조회된다(backfill).

⚠️ 응답에 계정 정보(userInfo — 비밀번호 해시 · 전화번호)와 작성자 실명이 실려 오는 화면이 있다. 저장 전에 뺀다(_clean).
⚠️ 읍면동 행에는 도형(geom, 수백 KB)이 같이 온다 — 쓰지 않아 뺀다.
⚠️ 로그인은 /login.do 에 아이디 · 비밀번호를 그대로 보낸다(사이트가 2021-09 RSA 암호화를 뺐다). 값은 로그에 남기지 않는다.

코드 뜻(화면 스크립트 alarmTypeText, 2026-11-28 확인): alarmType 1 주의보 · 3 예비경보 · 2 경보.
위험도 색(iServer HAZARD 층 colors): 1 (255,0,0) · 2 (255,201,0) · 3 (182,255,142) · 4 (48,194,255) · 5 (0,0,255).
조사 기록은 docs/api/sansatai.md.
"""
from __future__ import annotations

import gzip
import io
import json
import logging
import re
from datetime import datetime, timedelta
from functools import lru_cache

import httpx
import numpy as np

from . import config, db

log = logging.getLogger("sansatai")

BASE = config.KEYS.get("SANSATAI_BASE") or "https://sansatai.forest.go.kr"
RISK_SVC = "/gis1/ictout/rtldm_risk_service/iserver/services"   # 공개 화면이 조각을 받는 길(ictout). 목록이 주는 /gis1/rtldm… 은 404
# 경남 500m 격자(hr bbox 416×378칸) 전체를 덮는 경위도 상자 · 한 픽셀 0.001°(약 91×111m, 2410×1810).
# 상자가 격자보다 좁으면 가장자리 칸이 번진다(2026-11-28).
BBOX = (127.32, 34.30, 129.73, 36.11)
PX = 0.001
# 100m 칸 — 500m 칸 하나를 SUB×SUB 로 나눠 원본 픽셀(가장 가까운 것)을 옮긴다. 지도 그림 · 면적은 이것으로.
# ⚠️ 처음엔 500m 칸마다 '창 안에서 가장 위험한 등급'을 칠했다 — 원본은 약 10m 칸이라 골짜기 · 하천 · 도심이 다 메워져
#    진주 일대 산지 면적 56% 가 94% 로 칠해졌다(2026-11-28 원본 0.00002° 로 받아 비교). 1등급 한 점이 500m 칸을 통째 빨갛게 만든다.
SUB = 5
SUB_KM2 = (0.5 / SUB) ** 2              # 100m 칸 하나 = 0.01㎢
RGB_GRADE = {(255, 0, 0): 1, (255, 201, 0): 2, (182, 255, 142): 3, (48, 194, 255): 4, (0, 0, 255): 5}
GRADE_RGBA = {g: (*rgb, 255) for rgb, g in RGB_GRADE.items()}
ALARM = {"1": (1, "주의보"), "3": (2, "예비경보"), "2": (3, "경보")}          # 코드 → (세기, 이름)
STORE = config.CACHE / "sansatai"
KEEP_RAW_H = 24          # 경위도 원본 그림(약 200KB) — 하루치
KEEP_GRID_D = 14         # 500m 칸 지도(gzip 수 KB) — 2주
KEEP_SUB_D = 3           # 100m 칸 지도(gzip 수십~수백 KB) — 사흘. 면적 집계는 DB(sansatai_risk)에 늘 남는다
TIMEOUT = 30.0
DROP = re.compile(r"^(s?keyword\d+|select[A-Z].*|search[A-Z].*|is[A-Z].*|paging|sord|rows|page|distinct|geom|"
                  r"pageIndex|recordCountPerPage|lastRecordIndex|displayRow|displayPage|beginPage|endPage|prev|next|"
                  r"startNum|endNum|totalPage|rowNum|totalCount|sortColumn|sortDir|count|groupCnt|"
                  r".*Cnt|ntfcn.*|rainInfo|rainFrom|rainTo|frcstlist|infoArcd|searchSiguCode|emdcnt)$")
PERSONAL = ("userInfo", "frcstWriterNm", "frcstIssuWritrNm", "frcstWriterPstnNm", "rgterId", "upusrId",
            "frstRgterId", "lastUpusrId", "lastUpusrNm", "userPhone", "userPwd")

_LIVE: dict = {"at": {}, "err": {}, "risk": None, "pred": [], "status": [], "mtn": [], "aws": [], "mid": []}


class SansataiError(RuntimeError):
    pass


# ── 계정 · 세션 ──────────────────────────────────────────────────────────
def credentials() -> tuple[str, str] | None:
    i, p = config.KEYS.get("SANSATAI_ID"), config.KEYS.get("SANSATAI_PW")
    return (str(i), str(p)) if i and p else None


def _clean(o):
    """저장 · 화면에 넘기기 전 — 계정 · 실명 · 도형 · 화면용 빈 칸을 뺀다(재귀)."""
    if isinstance(o, dict):
        return {k: _clean(v) for k, v in o.items()
                if k not in PERSONAL and not DROP.match(k) and v not in ("", None)}
    if isinstance(o, list):
        return [_clean(x) for x in o]
    return o


class Client:
    """세션 하나. 공개 자료는 로그인 없이, 로그인 자료는 JSON 이 아닌 답(로그인 화면 · '시스템에 문제')이 오면 한 번 로그인하고 다시."""

    def __init__(self) -> None:
        self._c = httpx.AsyncClient(base_url=BASE, follow_redirects=True, verify=config.VERIFY_SSL,
                                    timeout=httpx.Timeout(TIMEOUT, connect=8.0),
                                    headers={"User-Agent": "Mozilla/5.0 (gn-monitor)"})
        self.logged = False

    async def __aenter__(self) -> "Client":
        return self

    async def __aexit__(self, *exc) -> None:
        await self._c.aclose()

    async def login(self) -> None:
        cred = credentials()
        if not cred:
            raise SansataiError("산사태정보시스템 계정이 없다 — 설정 › API 키의 SANSATAI_ID · SANSATAI_PW")
        await self._c.get("/login.do")                                   # 세션 쿠키
        r = await self._c.post("/login.do", data={"userId": cred[0], "userPwd": cred[1]})
        r.raise_for_status()
        chk = await self._c.get("/dgt/api/common/menu.do")              # 로그인이면 메뉴 JSON, 아니면 '시스템에 문제'
        try:
            ok = isinstance(chk.json(), list)
        except ValueError:
            ok = False
        if not ok:
            raise SansataiError("로그인 실패 — 아이디 · 비밀번호를 확인한다(5회 틀리면 잠길 수 있다)")
        self.logged = True

    async def post(self, path: str, data: dict | None = None, need_login: bool = True):
        for attempt in (0, 1):
            r = await self._c.post(path, data=data or {})
            r.raise_for_status()
            try:
                return r.json()
            except ValueError:
                if attempt or not need_login or self.logged:
                    raise SansataiError(f"{path} — JSON 이 아닌 답: {r.text.strip()[:60]}") from None
                await self.login()

    async def get(self, path: str, **params) -> httpx.Response:
        r = await self._c.get(path, params=params)
        r.raise_for_status()
        return r


# ── 공개: 강우반영 산사태위험도 ────────────────────────────────────────────
async def risk_latest(c: Client) -> str | None:
    """최신 분석 시각 YYYYMMDDHH. 공개 화면이 부르는 것."""
    j = (await c.get("/mhms_pub/mhms/lndsInfo/getRealTimeMapView.do")).json()
    m = re.search(r"real_time_hazard_(\d{10})", j.get("serviceUrl") or "")
    return m.group(1) if m else None


def risk_url(anal: str) -> str:
    return f"{RISK_SVC}/map-real_time_hazard_{anal}/rest/maps/HAZARD/image.png"


def risk_params(w: int, h: int, bbox=BBOX) -> dict:
    return {"width": w, "height": h, "transparent": "true", "cacheEnabled": "false",
            "viewBounds": json.dumps({"leftBottom": {"x": bbox[0], "y": bbox[1]}, "rightTop": {"x": bbox[2], "y": bbox[3]}}),
            "prjCoordSys": json.dumps({"epsgCode": 4326})}


def raw_size() -> tuple[int, int]:
    return round((BBOX[2] - BBOX[0]) / PX), round((BBOX[3] - BBOX[1]) / PX)


async def risk_png(c: Client, anal: str) -> bytes:
    w, h = raw_size()
    r = await c.get(risk_url(anal), **risk_params(w, h))
    if not r.headers.get("content-type", "").startswith("image/"):
        raise SansataiError(f"위험도 그림이 아니다: {r.text[:60]}")
    return r.content


def grade_image(png: bytes) -> np.ndarray:
    """그림 → 픽셀 등급(0 = 없음 · 바다 · 산지 밖). 색이 정확히 맞는 것만(가장자리 섞인 색은 0)."""
    from PIL import Image
    a = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))
    g = np.zeros(a.shape[:2], np.uint8)
    for (r, gg, b), grade in RGB_GRADE.items():
        g[(a[..., 0] == r) & (a[..., 1] == gg) & (a[..., 2] == b) & (a[..., 3] > 0)] = grade
    return g


@lru_cache(maxsize=1)
def _cell_pxf() -> tuple[np.ndarray, np.ndarray]:
    """경남 500m 칸(행 북→남) 가운데의 원본 그림 픽셀 좌표(실수, 열 · 행). 한 번만 계산(약 1초)."""
    from . import gridstore
    from .domain.gridproj import hr_lonlat
    b = gridstore.geo()["hr"]["bbox"]
    px = np.empty((b["h"], b["w"]), np.float64)
    py = np.empty((b["h"], b["w"]), np.float64)
    for r in range(b["h"]):
        gy = b["j1"] - r                                      # 행 0 = 북쪽 끝
        for k in range(b["w"]):
            lon, lat = hr_lonlat(b["i0"] + k, gy)
            px[r, k] = (lon - BBOX[0]) / PX
            py[r, k] = (BBOX[3] - lat) / PX
    return px, py


@lru_cache(maxsize=1)
def _sub_px() -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """100m 칸(500m 칸 × SUB, 행 북→남)마다 원본 픽셀 위치(정수)와 그림 안인지.
    칸 가운데 값 사이를 기울기로 메운다 — LCC 는 500m 안에서 거의 곧아 hr_lonlat 을 칸마다 다시 풀 필요가 없다."""
    pxf, pyf = _cell_pxf()
    h, w = pxf.shape
    off = (np.arange(SUB) + 0.5) / SUB - 0.5                 # 칸 가운데에서 100m 칸 가운데까지(칸 단위)
    rep = lambda a: np.repeat(np.repeat(a, SUB, 0), SUB, 1)  # noqa: E731
    ok = np.tile(off, w)[None, :]
    orr = np.tile(off, h)[:, None]
    px = rep(pxf) + rep(np.gradient(pxf, axis=1)) * ok + rep(np.gradient(pxf, axis=0)) * orr
    py = rep(pyf) + rep(np.gradient(pyf, axis=1)) * ok + rep(np.gradient(pyf, axis=0)) * orr
    pxi, pyi = np.floor(px).astype(np.int32), np.floor(py).astype(np.int32)
    rw, rh = raw_size()
    inside = (pxi >= 0) & (pxi < rw) & (pyi >= 0) & (pyi < rh)   # 그림 범위 밖 — 가장자리 색이 번지지 않게 비운다
    return np.where(inside, pxi, 0), np.where(inside, pyi, 0), inside


def to_sub(g: np.ndarray) -> np.ndarray:
    """픽셀 등급 → 100m 칸 등급(행 북→남, 경남 hr bbox × SUB). 칸 가운데에 가장 가까운 원본 픽셀."""
    px, py, inside = _sub_px()
    out = g[py, px]
    out[~inside] = 0
    return out


def to_cells(sub: np.ndarray) -> np.ndarray:
    """100m 칸 → 500m 칸. 칠해진 100m 칸이 절반이 안 되면 비우고, 넘으면 **면적이 가장 넓은 등급**(같으면 위험한 쪽).
    지도 위 다른 500m 자료(강수 격자 · 지구)와 칸을 맞춰 볼 때만 쓴다 — 그림 · 면적은 100m 칸으로."""
    h, w = sub.shape[0] // SUB, sub.shape[1] // SUB
    blk = sub.reshape(h, SUB, w, SUB)
    cnt = np.stack([(blk == g).sum(axis=(1, 3)) for g in range(1, 6)])     # (5, h, w)
    best = (np.argmax(cnt, axis=0) + 1).astype(np.uint8)                 # argmax 는 같은 수면 앞(1등급 쪽 = 위험)을 고른다
    best[cnt.sum(axis=0) * 2 < SUB * SUB] = 0
    return best


def sigun_area(sub: np.ndarray) -> dict:
    """경남 시군별 등급 면적(㎢) {'창원': [1등급, 2, 3, 4, 5], …, '경남': […]}. 100m 칸 × 0.01㎢.
    시군 경계는 500m 칸 지도(mask_sigun, 남→북)를 5×5 로 펼친 것 — 경계 칸에서 ±0.25㎢ 쯤 오간다."""
    from . import gridstore
    sig = np.repeat(np.repeat(gridstore.masks()[0][::-1], SUB, 0), SUB, 1)
    names = {s["id"]: s["name"] for s in gridstore.geo()["sigun"] if s["kind"] == "gn"}
    idx = sig.astype(np.int32) * 8 + sub                                     # 시군 × 등급을 한 번에 센다
    cnt = np.bincount(idx.ravel(), minlength=256 * 8)
    out, tot = {}, [0.0] * 5
    for sid, name in names.items():
        row = [round(float(cnt[sid * 8 + g]) * SUB_KM2, 2) for g in range(1, 6)]
        out[name] = row
        tot = [a + b for a, b in zip(tot, row)]
    out["경남"] = [round(x, 2) for x in tot]
    return out


def cells_png(cells: np.ndarray, max_grade: int = 5, scale: int = 1) -> bytes:
    """칸 등급 → 투명 PNG(산림청 색). scale 배로 키운다(보고서 그림용, 칸이 네모로 보이게 nearest)."""
    from PIL import Image
    a = np.zeros((*cells.shape, 4), np.uint8)
    for g, rgba in GRADE_RGBA.items():
        if g <= max_grade:
            a[cells == g] = rgba
    im = Image.fromarray(a, "RGBA")
    if scale > 1:
        im = im.resize((im.width * scale, im.height * scale), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def _risk_paths(anal: str):
    return STORE / f"raw_{anal}.png", STORE / f"grid_{anal}.u8.gz", STORE / f"sub_{anal}.u8.gz"


def _save_u8(p, a: np.ndarray) -> None:
    tmp = p.with_suffix(".tmp")
    tmp.write_bytes(gzip.compress(a.tobytes(), 6))
    tmp.replace(p)                                            # 화면이 반쯤 쓴 파일을 읽지 않게


def load_cells(anal: str | None = None, res: int = 500) -> tuple[str, np.ndarray] | None:
    """칸 지도 — res 500(500m 칸, 면적 최다 등급) | 100(100m 칸). 행 북→남."""
    anal = anal or (_LIVE["risk"] or {}).get("anal") or _newest_grid()
    if not anal:
        return None
    p = _risk_paths(anal)[2 if res == 100 else 1]
    if not p.exists():
        return None
    from . import gridstore
    b = gridstore.geo()["hr"]["bbox"]
    k = SUB if res == 100 else 1
    return anal, np.frombuffer(gzip.decompress(p.read_bytes()), np.uint8).reshape(b["h"] * k, b["w"] * k)


def _newest_grid() -> str | None:
    fs = sorted(STORE.glob("grid_*.u8.gz")) if STORE.exists() else []
    return fs[-1].name[5:15] if fs else None


def raw_path(anal: str | None = None):
    anal = anal or (_LIVE["risk"] or {}).get("anal") or _newest_grid()
    p = _risk_paths(anal)[0] if anal else None
    return p if p and p.exists() else None


def _risk_summary(anal: str, area: dict) -> dict:
    """요약 — 면적은 ㎢. top = 1 · 2등급 면적이 있는 시군(1등급 큰 순)."""
    top = sorted(((n, v[0], v[1]) for n, v in area.items() if n != "경남" and (v[0] or v[1])),
                 key=lambda x: (-x[1], -x[2]))
    return {"anal": anal, "at": f"{anal[:4]}-{anal[4:6]}-{anal[6:8]} {anal[8:]}:00", "unit": "km2", "gn": area["경남"],
            "sigun": area, "top": [{"sigun": n, "g1": a, "g2": b} for n, a, b in top]}


def build_risk(png: bytes) -> tuple[np.ndarray, np.ndarray, dict]:
    """원본 그림 → (100m 칸, 500m 칸, 시군 면적). 수집과 테스트가 같이 쓴다."""
    sub = to_sub(grade_image(png))
    return sub, to_cells(sub), sigun_area(sub)


async def collect_risk(c: Client, now: datetime) -> dict | None:
    anal = await risk_latest(c)
    if not anal:
        raise SansataiError("위험도 분석 시각을 못 읽었다")
    if (_LIVE["risk"] or {}).get("anal") == anal and _risk_paths(anal)[2].exists():
        return _LIVE["risk"]
    png = await risk_png(c, anal)
    import asyncio
    sub, cells, area = await asyncio.to_thread(build_risk, png)          # 몇 초 — 화면 응답을 막지 않게
    STORE.mkdir(parents=True, exist_ok=True)
    raw, grid, subp = _risk_paths(anal)
    raw.write_bytes(png)
    _save_u8(grid, cells)
    _save_u8(subp, sub)
    s = _risk_summary(anal, area)
    with db.tx() as con:
        con.execute("INSERT OR REPLACE INTO sansatai_risk(anal, gn, sigun, fetched_at) VALUES(?,?,?,?)",
                    (anal, json.dumps(s["gn"]), json.dumps(area, ensure_ascii=False), now.isoformat(timespec="seconds")))
    _prune(now)
    return s


def _prune(now: datetime) -> None:
    for pat, keep in (("raw_*.png", timedelta(hours=KEEP_RAW_H)), ("grid_*.u8.gz", timedelta(days=KEEP_GRID_D)),
                      ("sub_*.u8.gz", timedelta(days=KEEP_SUB_D))):
        for f in STORE.glob(pat):
            if f.stat().st_mtime < (now - keep).timestamp():
                f.unlink(missing_ok=True)


# ── 로그인: 실황 · 예측 · 발령 현황 · 산악기상 · 중기 ─────────────────────────
def _sigun(addr: str) -> str | None:
    from .safety import sigun_of
    return sigun_of(addr)


def parse_pred(rows: list[dict], kind: str) -> list[dict]:
    """selectForecastList 행 → [{kind 실황|예측, anal, sigun, gu, lv, name, emd[], emd_cd[], sta}] (경남만)."""
    out = []
    for r in rows or []:
        sg = _sigun(r.get("sigun", ""))
        a = ALARM.get(str(r.get("alarmType")))
        if not sg or not a:
            continue
        anal = str(r.get("analDate", "")).replace("시", "").strip()          # '2026-09-03 16시' → '2026-09-03 16'
        out.append({"kind": kind, "anal": anal, "sigun": sg, "gu": r.get("sigun", "").split()[-1],
                    "lv": a[0], "name": a[1], "emd": [x for x in str(r.get("emdNm") or "").split(",") if x],
                    "emd_cd": [x for x in str(r.get("emdCd") or "").split(",") if x], "sta": str(r.get("staId") or "")})
    return out


def parse_status(rows: list[dict]) -> list[dict]:
    """forecastStatusSearch — 시군마다 '예측(산림청) ↔ 예보(시군 발령)'. issued 가 None 이면 예측만 있고 발령이 없다."""
    out = []
    for r in rows or []:
        sg = _sigun(r.get("doSiGun", ""))
        a = ALARM.get(str(r.get("alarmType")))
        if not sg or not a:
            continue
        iss = ALARM.get(str(r.get("frcstIssuKindCd")))
        first = r.get("frstFrcstIssuDtm")
        out.append({"sigun": sg, "anal": r.get("analDate"), "lv": a[0], "name": a[1],
                    "issued": iss[1] if iss else None, "issued_at": None if first in (None, "-") else first,
                    "released_at": None if r.get("lastFrcstRlsDtm") in (None, "-") else r.get("lastFrcstRlsDtm"),
                    "code": str(r.get("siguCode") or "")})
    return out


def parse_mtn(rows: list[dict]) -> list[dict]:
    """산악기상 관측소(산림청) — 위치 · 시간 강우(격자 실황 QPM)."""
    out = []
    for r in rows or []:
        try:
            out.append({"name": r["wtherObsrrNm"], "sigun": _sigun(r.get("wtherObsrrAddr", "")),
                        "lon": float(r["wtherObsrrLctnXcrd"]), "lat": float(r["wtherObsrrLctnYcrd"]),
                        "mm": None if r.get("rainHour") in (None, "-", "") else float(r["rainHour"]),
                        "at": str(r.get("rainAnlssDtm") or "").replace("시", ":00")})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def parse_aws(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows or []:
        try:
            out.append({"name": r["wtherObsrrNm"], "stn": r.get("cdStn"), "sigun": _sigun(r.get("wtherObsrrAddr", "")),
                        "lon": float(r["wtherObsrrLctnXcrd"]), "lat": float(r["wtherObsrrLctnYcrd"]),
                        "ta": r.get("airTemp"), "ws": r.get("windSpeed"), "wd": r.get("windDir"),
                        "hm": r.get("relHumidity"), "rn": r.get("amoOfPreciptF")})
        except (KeyError, TypeError, ValueError):
            continue
    return out


def _span(now: datetime, hours: int) -> tuple[str, str]:
    fr = now - timedelta(hours=hours)
    return fr.strftime("%Y-%m-%d %H:00:00"), now.strftime("%Y-%m-%d %H:00:00")


async def fetch_pred(c: Client, fr: str, to: str) -> list[dict]:
    """실황(0) · 예측(1)을 따로 — 행에 둘을 가르는 칸이 없다. fr · to = 'YYYY-MM-DD HH:00:00'."""
    out = []
    for ip, kind in (("0", "실황"), ("1", "예측")):
        page = 1
        while True:
            j = await c.post("/dgt/forecast/selectForecastList.do",
                             {"isSearch": "Y", "searchBtnType": "rltmList", "pageIndex": page, "rows": 500,
                              "searchDateType": "01", "infoPeriod": ip, "searchFrom": fr, "searchTo": to,
                              "selectSidoCode": "48"})
            rows = j.get("forecastList") or []
            out += parse_pred(rows, kind)
            if len(rows) < 500 or page >= 20:
                break
            page += 1
    return out


async def fetch_status(c: Client, day_fr: str, day_to: str) -> list[dict]:
    j = await c.post("/dgt/forecast/forecastStatusSearch.do",
                     {"isSearch": "Y", "pageIndex": 1, "rows": 500, "searchFrom": day_fr, "searchTo": day_to,
                      "searchTime": "00", "searchToTime": "23", "selectSidoCode": "48"})
    return parse_status(j.get("forecastStatusList") or [])


async def fetch_mtn(c: Client) -> list[dict]:
    j = await c.post("/dgt/forecast/selectMtnWeatherStatusAll.do",
                     {"page": 1, "rows": 200, "wtherObsrrAddr": "경상남도", "type": "QPM"})
    return parse_mtn(j.get("rows") or [])


async def fetch_aws(c: Client) -> list[dict]:
    j = await c.post("/dgt/forecast/selectMountainAWS10mList.do", {"page": 1, "rows": 200, "wtherObsrrAddr": "경상남도"})
    return parse_aws(j.get("rows") or [])


async def fetch_mid(c: Client) -> list[dict]:
    """중기(48시간) 예측 — 걸린 곳만 온다(평시 빈 목록). 모양을 아직 못 봐 걸러 낸 원자료 그대로."""
    j = await c.post("/midterm/tankAlarmList.do", {"selectSidoCode": "48"})
    return _clean(j.get("tankAlarmList") or [])


def store_pred(rows: list[dict], now: datetime) -> int:
    at = now.isoformat(timespec="seconds")
    with db.tx() as con:
        for r in rows:
            con.execute("""INSERT OR REPLACE INTO sansatai_pred(anal, kind, sigun, gu, sta, lv, emd, emd_cd, fetched_at)
                           VALUES(?,?,?,?,?,?,?,?,?)""",
                        (r["anal"], r["kind"], r["sigun"], r["gu"], r["sta"], r["lv"],
                         ",".join(r["emd"]), ",".join(r["emd_cd"]), at))
    return len(rows)


def history(fr: str, to: str) -> list[dict]:
    """쌓인 실황 · 예측(읍면동). fr · to = 'YYYY-MM-DD HH'."""
    with db.tx() as con:
        rows = con.execute("SELECT * FROM sansatai_pred WHERE anal BETWEEN ? AND ? ORDER BY anal, sigun, kind",
                           (fr, to)).fetchall()
    return [{**dict(r), "emd": r["emd"].split(",") if r["emd"] else []} for r in rows]


def risk_history(fr: str, to: str) -> list[dict]:
    with db.tx() as con:
        rows = con.execute("SELECT anal, gn, sigun FROM sansatai_risk WHERE anal BETWEEN ? AND ? ORDER BY anal",
                           (fr, to)).fetchall()
    return [{"anal": r["anal"], "gn": json.loads(r["gn"]), "sigun": json.loads(r["sigun"])} for r in rows]


# ── 스케줄 ─────────────────────────────────────────────────────────────
async def _step(name: str, coro_fn, now: datetime):
    try:
        v = await coro_fn()
        _LIVE["at"][name] = now.isoformat(timespec="seconds")
        _LIVE["err"].pop(name, None)
        return v
    except Exception as e:                                          # noqa: BLE001 — 다음 차례에 다시
        _LIVE["err"][name] = str(e)[:200]
        log.warning("산사태정보시스템 %s 실패: %s", name, _LIVE["err"][name])
        return None


async def run(now: datetime | None = None) -> None:
    """스케줄러가 10분마다. 위험도는 새 분석 시각일 때만 그림을 받는다. 로그인 자료는 계정이 있을 때만."""
    if config.DEMO:
        return
    now = now or datetime.now()
    async with Client() as c:
        r = await _step("risk", lambda: collect_risk(c, now), now)
        if r:
            _LIVE["risk"] = r
        if not credentials():
            _LIVE["err"]["login"] = "계정 없음 — 실황 · 예측 · 발령 현황 · 산악기상은 받지 않는다"
            db.log_collect("sansatai", r is not None, now.strftime("%Y-%m-%d %H:%M"),
                           f"위험도 {(r or {}).get('anal', '실패')} · 계정 없음")
            return
        # 먼저 로그인한다 — 로그인 없이 부르면 '시스템에 문제'가 아니라 빈 목록이 올 수도 있어 '없음'과 갈라지지 않는다
        if await _step("login", c.login, now) is None and "login" in _LIVE["err"]:
            db.log_collect("sansatai", False, now.strftime("%Y-%m-%d %H:%M"), _LIVE["err"]["login"])
            return
        fr, to = _span(now, 6)
        pred = await _step("pred", lambda: fetch_pred(c, fr, to), now)
        if pred is not None:
            _LIVE["pred"] = pred
            store_pred(pred, now)
        st = await _step("status", lambda: fetch_status(c, now.strftime("%Y-%m-%d"), now.strftime("%Y-%m-%d")), now)
        if st is not None:
            _LIVE["status"] = st
        for name, fn in (("mtn", fetch_mtn), ("aws", fetch_aws), ("mid", fetch_mid)):
            v = await _step(name, lambda fn=fn: fn(c), now)
            if v is not None:
                _LIVE[name] = v
    bad = sorted(_LIVE["err"])
    db.log_collect("sansatai", not bad, now.strftime("%Y-%m-%d %H:%M"),
                   f"위험도 {(_LIVE['risk'] or {}).get('anal', '-')} · 예측 {len(_LIVE['pred'])}줄"
                   + (f" · 실패 {', '.join(bad)}" if bad else ""))


def unissued() -> list[dict]:
    """예측(산림청)은 걸렸는데 시군 예보 발령이 없는 곳 — 상황실이 먼저 볼 것."""
    return [s for s in _LIVE["status"] if not s["issued"]]


def status() -> dict:
    return {"demo": config.DEMO, "login": bool(credentials()), "at": _LIVE["at"], "err": _LIVE["err"],
            "risk": _LIVE["risk"], "pred": _LIVE["pred"], "status": _LIVE["status"], "unissued": unissued(),
            "mtn": _LIVE["mtn"], "aws": _LIVE["aws"], "mid": _LIVE["mid"],
            "grid": {"w": raw_size()[0], "h": raw_size()[1], "bbox": BBOX, "px": PX, "sub": SUB}}


async def backfill(fr_day: str, to_day: str) -> int:
    """지난 실황 · 예측을 날마다 받아 쌓는다(로그인 필요). python -m app.sansatai backfill 2026-06-01 2026-11-28"""
    d, end, n = datetime.fromisoformat(fr_day), datetime.fromisoformat(to_day), 0
    async with Client() as c:
        while d <= end:
            rows = await fetch_pred(c, d.strftime("%Y-%m-%d 00:00:00"), d.strftime("%Y-%m-%d 23:00:00"))
            n += store_pred(rows, datetime.now())
            d += timedelta(days=1)
    return n


if __name__ == "__main__":                                           # pragma: no cover — 손으로 돌리는 것
    import asyncio
    import sys
    db.init()
    if len(sys.argv) == 4 and sys.argv[1] == "backfill":
        print(f"{asyncio.run(backfill(sys.argv[2], sys.argv[3]))}줄 쌓음")
    else:
        asyncio.run(run())
        s = status()
        print(json.dumps({k: s[k] for k in ("at", "err")} | {"risk": (s["risk"] or {}).get("gn"),
                          "pred": len(s["pred"]), "mtn": len(s["mtn"]), "aws": len(s["aws"])}, ensure_ascii=False, indent=1))

"""경남 지도 0단계 실측 — 격자 강수 API 의 형식·투영·범위를 받아 보고 확정한다.

기관키가 있고 기상청 호스트가 닿는 PC(상황실)에서 **한 번** 돌린다. 앱을 띄울 필요는 없다.

    윈도  .venv\\Scripts\\python.exe -m pip install netCDF4
          .venv\\Scripts\\python.exe tools\\probe_grid.py
    맥    .venv/bin/python -m pip install netCDF4
          .venv/bin/python tools/probe_grid.py

netCDF4 는 이 실측에만 쓴다(앱에는 필요 없다). 500m 위경도 API 가 403 이라 지금은 NetCDF 속
위경도가 투영을 확정할 유일한 길이다 — 없으면 그 단계가 '미확정'으로 남는다.

선택
    --tm YYYYMMDDHHMI       실측 시각. 기본은 지금에서 받을 수 있는 최신 5분
    --rain-tm YYYYMMDDHHMI  비가 온 과거 시각 — AWS 대조용(기본 202608281100, 8.28. 호우)
    --latlon-nc PATH        API허브 '융합기상고해상도 격자자료' 쪽에 붙은 위경도 NetCDF 가
                            있으면 그 경로. 500m 격자 투영을 이것으로 확정할 수 있다
    --no-text               disp=A(텍스트, 수십 MB) 대조를 건너뛴다

결과
    data/probe/<시각>/report.md · report.json · *.png   ← 커밋해도 된다. 키는 남지 않는다
    data/cache/probe/                                    ← 원본(16.8MB)·NetCDF. 커밋 안 됨

호출은 약 30번, 받는 양은 약 120MB, 1~3분 걸린다(500m 격자 한 장이 16.8MB).

⚠️ 여기서 추측하지 않는다. 투영은 위경도(API·NetCDF)와 맞춰 본 잔차로만 '확정'이라 적고,
   위경도를 못 받으면 '미확정'으로 남긴다. 눈대중으로 맞춘 격자는 틀린 곳에 비를 그린다.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import re
import struct
import sys
import time
from array import array
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import httpx  # noqa: E402

from app.config import CACHE, DATA, KMA_HOST, ORG_API_KEY, VERIFY_SSL  # noqa: E402

# httpx 는 요청 URL(=authKey)을 통째로 찍는다
logging.getLogger("httpx").setLevel(logging.WARNING)

# 윈도 콘솔(cp949)은 ⚠·— 를 찍다 죽는다(pitfalls 14)
for s in (sys.stdout, sys.stderr):
    try:
        s.reconfigure(errors="replace")
    except Exception:                                   # noqa: BLE001
        pass

NC_API = "/api/typ01/cgi-bin/url/nph-sfc_obs_nc_api"
NC_IMG = "/api/typ01/cgi-bin/url/nph-sfc_obs_nc_img"
NC_LATLON = "/api/typ01/cgi-bin/url/nph-sfc_obs_latlon_api"
NC_DOWN = "/api/typ01/url/sfc_grid_nc_down.php"
DFS_LATLON = "/api/typ01/cgi-bin/url/nph-dfs_latlon_api"
ODAM = "/api/typ01/cgi-bin/url/nph-dfs_odam_grd"
VSRT = "/api/typ01/cgi-bin/url/nph-dfs_vsrt_grd"
SHRT = "/api/typ01/cgi-bin/url/nph-dfs_shrt_grd"
AWS_MIN = "/api/typ01/cgi-bin/url/nph-aws2_min"
STN_INF = "/api/typ01/url/stn_inf.php"

# 경남 18개 시군 경계의 볼록 껍질(lon, lat). SGIS 2020 경계(statgarten/maps)에서 뽑았다.
# bbox(경계 외곽 + 20km)를 격자 인덱스로 옮기는 데만 쓴다 — 극점만 맞으면 된다.
GN_HULL = [
    (128.7330, 34.5347), (128.4371, 34.5375), (128.1794, 34.5579), (128.1767, 34.5585),
    (127.8575, 34.7279), (127.8367, 34.7499), (127.6181, 35.1909), (127.5774, 35.2952),
    (127.5761, 35.3035), (127.5761, 35.3061), (127.5849, 35.5539), (127.5888, 35.5648),
    (127.6623, 35.7608), (127.6664, 35.7694), (127.7445, 35.8444), (127.8595, 35.9065),
    (127.8795, 35.9099), (127.8851, 35.9096), (129.0027, 35.6203), (129.0225, 35.6142),
    (129.1970, 35.4389), (129.2182, 35.4115), (129.2191, 35.4077), (129.1988, 35.3665),
    (128.7347, 34.5372),
]
BUFFER_KM = 20.0
STATIONS = {"155": "창원", "192": "진주"}

# 동네예보 5km 격자 — 기상청이 공개한 변환 코드(lamcproj)의 상수. 여기서 **대조**한다.
DFS = dict(re=6371.00877, grid=5.0, slat1=30.0, slat2=60.0, olon=126.0, olat=38.0,
           xo=43, yo=136, nx=149, ny=253)
# 500m 격자는 표준위도·기준점이 같다고 **가정하고** 위경도와 맞춰 본다. 잔차가 크면 버린다.
LCC_GUESS = dict(re=6371.00877, slat1=30.0, slat2=60.0, olon=126.0, olat=38.0)
FIT_OK_KM = 0.05          # 500m 칸의 1/10

# ── 기록 ──────────────────────────────────────────────────────────────
CALLS: list[dict] = []
MD: list[str] = []
JS: dict = {}


def scrub(s: str) -> str:
    """키가 어디에도 남지 않게. 오류 문구에도 URL 이 통째로 실린다(httpx)."""
    if ORG_API_KEY:
        s = s.replace(ORG_API_KEY, "***")
    return re.sub(r"(authKey=)[^&\s'\"]+", r"\1***", s)


def say(line: str = "") -> None:
    line = scrub(line)
    print(line)
    MD.append(line)


def head_text(body: bytes, n: int = 600) -> str:
    for enc in ("utf-8", "euc-kr"):
        try:
            return body[:n].decode(enc)
        except UnicodeDecodeError:
            continue
    return body[:n].decode("latin-1", errors="replace")


def is_text(body: bytes) -> bool:
    chunk = body[:512]
    return bool(chunk) and sum(b < 9 or 13 < b < 32 for b in chunk) < 4


def get(path: str, params: dict, *, timeout: float = 60.0) -> tuple[dict, bytes]:
    shown = path + "?" + "&".join(f"{k}={v}" for k, v in params.items())
    rec: dict = {"url": shown, "status": None, "size": 0}
    t0 = time.time()
    body = b""
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, verify=VERIFY_SSL) as c:
            r = c.get(KMA_HOST + path, params={**params, "authKey": ORG_API_KEY})
        body = r.content
        rec.update(status=r.status_code, size=len(body),
                   ctype=r.headers.get("content-type", ""))
    except Exception as e:                              # noqa: BLE001
        rec["error"] = scrub(f"{type(e).__name__}: {e}")
    rec["sec"] = round(time.time() - t0, 1)
    if body and (rec["status"] != 200 or is_text(body)):
        rec["head"] = scrub(head_text(body, 300))
    CALLS.append(rec)
    st = rec.get("error") or f"{rec['status']} · {rec['size']:,} B · {rec['sec']}s"
    print(scrub(f"  → {shown}  {st}"))
    return rec, body


# ── 투영 ──────────────────────────────────────────────────────────────
def lcc_km(lat: float, lon: float, p: dict) -> tuple[float, float]:
    """기상청 구면 람베르트 정각원추. 기준점(olon, olat)이 (0, 0), 단위 km, y 는 북쪽."""
    D = math.pi / 180
    s1, s2, olon, olat = p["slat1"] * D, p["slat2"] * D, p["olon"] * D, p["olat"] * D
    sn = math.log(math.cos(s1) / math.cos(s2)) / math.log(
        math.tan(math.pi / 4 + s2 / 2) / math.tan(math.pi / 4 + s1 / 2))
    sf = math.tan(math.pi / 4 + s1 / 2) ** sn * math.cos(s1) / sn
    ro = p["re"] * sf / math.tan(math.pi / 4 + olat / 2) ** sn
    ra = p["re"] * sf / math.tan(math.pi / 4 + lat * D / 2) ** sn
    th = lon * D - olon
    th = (th + math.pi) % (2 * math.pi) - math.pi
    th *= sn
    return ra * math.sin(th), ro - ra * math.cos(th)


def dfs_xy(lat: float, lon: float) -> tuple[float, float]:
    """동네예보 격자 X, Y (1부터, 실수). 반올림하면 API 의 X, Y."""
    x, y = lcc_km(lat, lon, DFS)
    return x / DFS["grid"] + DFS["xo"], y / DFS["grid"] + DFS["yo"]


# ── 파싱 ──────────────────────────────────────────────────────────────
def parse_b(body: bytes) -> dict | None:
    """disp=B: int16 nx, int16 ny + float32 × nx·ny. 바이트 순서는 크기로 가린다."""
    if len(body) < 8:
        return None
    for bo in ("<", ">"):
        nx, ny = struct.unpack(bo + "hh", body[:4])
        if nx > 0 and ny > 0 and 4 + 4 * nx * ny == len(body):
            vals = array("f")
            vals.frombytes(body[4:])
            if (bo == "<") != (sys.byteorder == "little"):
                vals.byteswap()
            return {"nx": nx, "ny": ny, "order": "little" if bo == "<" else "big", "v": vals}
    return None


def parse_text_floats(text: str) -> tuple[array, list[int]]:
    """'#' 줄을 빼고 숫자를 모두 읽는다. 줄마다 숫자 개수도 센다(행 구조를 보려고)."""
    vals = array("f")
    per_line: list[int] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        n = 0
        for tok in s.replace(",", " ").split():
            try:
                vals.append(float(tok))
                n += 1
            except ValueError:
                pass
        per_line.append(n)
    return vals, per_line


def stats(v) -> dict:
    neg: dict[float, int] = {}
    zero = pos = 0
    vmax = None
    for x in v:
        if x < 0:
            k = round(x, 2)
            neg[k] = neg.get(k, 0) + 1
        elif x == 0:
            zero += 1
        else:
            pos += 1
            vmax = x if vmax is None or x > vmax else vmax
    top_neg = sorted(neg.items(), key=lambda kv: -kv[1])[:5]
    return {"n": len(v), "zero": zero, "pos": pos, "max": vmax,
            "neg": [{"value": k, "count": c} for k, c in top_neg]}


def fmt_stats(s: dict) -> str:
    neg = ", ".join(f"{d['value']}×{d['count']:,}" for d in s["neg"]) or "없음"
    return (f"{s['n']:,}칸 · 0 {s['zero']:,} · 양수 {s['pos']:,}"
            f" (최대 {s['max']}) · 음수 {neg}")


def floor_min(t: datetime, step: int) -> datetime:
    t = t.replace(second=0, microsecond=0)
    return t - timedelta(minutes=t.minute % step)


# ── 그림 ──────────────────────────────────────────────────────────────
def mask_png(g: dict, path: Path, marks: list[tuple[int, int]] = ()) -> None:
    """저장 순서 그대로(첫 행이 그림 맨 위). 결측 검정 · 0 회색 · 비 파랑 · 지점 빨강."""
    from PIL import Image
    nx, ny, v, step = g["nx"], g["ny"], g["v"], 2
    w, h = (nx + step - 1) // step, (ny + step - 1) // step
    px = bytearray(w * h * 3)
    for jj in range(h):
        row = jj * step * nx
        for ii in range(w):
            x = v[row + ii * step]
            o = (jj * w + ii) * 3
            if x < 0:
                px[o:o + 3] = b"\x18\x18\x18"
            elif x == 0:
                px[o:o + 3] = b"\xb4\xb4\xb4"
            else:
                k = min(1.0, x / 30.0)
                px[o:o + 3] = bytes((int(150 - 130 * k), int(200 - 150 * k), 255))
    for (i, j) in marks:
        for dj in range(-4, 5):
            for di in range(-4, 5):
                a, b = i // step + di, j // step + dj
                if 0 <= a < w and 0 <= b < h:
                    o = (b * w + a) * 3
                    px[o:o + 3] = b"\xff\x20\x20"
    Image.frombytes("RGB", (w, h), bytes(px)).save(path)


# ── NetCDF ────────────────────────────────────────────────────────────
def inspect_nc(path: Path, want: tuple[int, int] | None) -> dict:
    """속성을 통째로 적고, 위경도·격자 좌표 변수가 있으면 꺼낸다."""
    out: dict = {"file": path.name, "magic": path.read_bytes()[:8].hex()}
    try:
        import netCDF4  # type: ignore
    except ImportError:
        netCDF4 = None
    if netCDF4 is None:
        try:
            import h5py  # type: ignore
        except ImportError:
            out["note"] = ("netCDF4·h5py 없음 — `pip install netCDF4` 뒤 다시 돌리면 이 단계가 채워진다. "
                           "아래는 파일에서 뽑은 글자열뿐이다")
            raw = path.read_bytes()[:200_000]
            words = sorted({w.decode() for w in re.findall(rb"[A-Za-z_][A-Za-z0-9_ .:-]{3,60}", raw)})
            out["strings"] = [w for w in words if re.search(
                r"lat|lon|proj|lambert|parallel|origin|false|grid|map|nx|ny|dx|dy|x_|y_", w, re.I)][:200]
            return out
        with h5py.File(path, "r") as f:
            out["attrs"] = {k: repr(v) for k, v in f.attrs.items()}
            items = {}
            f.visititems(lambda n, o: items.__setitem__(n, {
                "shape": list(getattr(o, "shape", []) or []),
                "attrs": {k: repr(v) for k, v in o.attrs.items()}}))
            out["vars"] = items
            out["arrays"] = {}
            for n, it in items.items():
                if re.fullmatch(r"(lat|latitude|lon|longitude|x|y)", n.split("/")[-1], re.I):
                    out["arrays"][n.split("/")[-1].lower()] = f[n][()]
        return out

    with netCDF4.Dataset(path) as ds:
        out["dims"] = {k: len(d) for k, d in ds.dimensions.items()}
        out["attrs"] = {k: repr(ds.getncattr(k)) for k in ds.ncattrs()}
        out["vars"] = {}
        out["arrays"] = {}
        for name, var in ds.variables.items():
            out["vars"][name] = {"dims": list(var.dimensions), "shape": list(var.shape),
                                 "dtype": str(var.dtype),
                                 "attrs": {k: repr(var.getncattr(k)) for k in var.ncattrs()}}
            key = name.lower()
            if key in ("lat", "latitude", "lon", "longitude", "x", "y") or (
                    want and list(var.shape)[-2:] == [want[1], want[0]]):
                var.set_auto_mask(False)
                out["arrays"][key] = var[:]
    return out


def flat2d(a, nx: int, ny: int) -> array | None:
    """(ny, nx) 배열 → 행 우선 1차원(float). 모양이 다르면 None."""
    try:
        shp = list(a.shape)
    except AttributeError:
        return None
    while len(shp) > 2 and shp[0] == 1:
        a = a[0]
        shp = shp[1:]
    if shp != [ny, nx]:
        return None
    out = array("f")
    for row in a:
        out.extend(float(x) for x in row)
    return out


# 저장 순서가 다를 수 있다 — 뒤집힘·전치 8가지를 모두 대조한다.
# B 의 (i, j) 칸이 다른 배열의 (row, col) 어디에 있나. 전치는 nx == ny 일 때만 뜻이 있다.
ORDERS = {
    "같음":        lambda i, j, nx, ny: (j, i),
    "상하 뒤집힘":  lambda i, j, nx, ny: (ny - 1 - j, i),
    "좌우 뒤집힘":  lambda i, j, nx, ny: (j, nx - 1 - i),
    "180도":       lambda i, j, nx, ny: (ny - 1 - j, nx - 1 - i),
    "전치":        lambda i, j, nx, ny: (i, j),
    "전치+상하":    lambda i, j, nx, ny: (nx - 1 - i, j),
    "전치+좌우":    lambda i, j, nx, ny: (i, ny - 1 - j),
    "전치+180도":   lambda i, j, nx, ny: (nx - 1 - i, ny - 1 - j),
}


def order_match(f, vb, nx: int, ny: int, stride: int = 97) -> dict[str, float]:
    """f(다른 배열, 행 우선 ny×nx) 와 vb(disp=B) 가 각 순서에서 몇 % 맞나(표본)."""
    ks = range(0, nx * ny, stride)
    out = {}
    for name, fn in ORDERS.items():
        if name.startswith("전치") and nx != ny:
            continue
        hit = 0
        for k in ks:
            r, c = fn(k % nx, k // nx, nx, ny)
            hit += abs(f[r * nx + c] - vb[k]) <= 0.05
        out[name] = hit / len(ks)
    return out


def best_order(m: dict[str, float]) -> str | None:
    """98% 넘게 맞고 둘째와 2%p 넘게 벌어져야 인정한다. 아니면 모른다."""
    top = sorted(m.items(), key=lambda kv: -kv[1])
    if top and top[0][1] >= 0.98 and (len(top) < 2 or top[0][1] - top[1][1] >= 0.02):
        return top[0][0]
    return None


def to_b(f, order: str, nx: int, ny: int) -> array:
    """다른 순서의 배열을 disp=B 순서로 옮긴다."""
    fn = ORDERS[order]
    out = array("f", bytes(4 * nx * ny))
    for k in range(nx * ny):
        r, c = fn(k % nx, k // nx, nx, ny)
        out[k] = f[r * nx + c]
    return out


def fmt_match(m: dict[str, float]) -> str:
    return " · ".join(f"{k} {v:.1%}" for k, v in sorted(m.items(), key=lambda kv: -kv[1])[:3])


# ── 500m 투영 맞추기 ────────────────────────────────────────────────────
def fit_lcc(lat: array, lon: array, nx: int, ny: int) -> dict:
    """위경도를 LCC_GUESS 로 옮겨 x = a + b·i + c·j, y = d + e·i + f·j 로 맞춘다."""
    samples = []
    step = max(1, nx // 64)
    for j in range(0, ny, step):
        for i in range(0, nx, step):
            k = j * nx + i
            la, lo = lat[k], lon[k]
            if -90 <= la <= 90 and -180 <= lo <= 360:
                samples.append((i, j, *lcc_km(la, lo, LCC_GUESS)))
    if len(samples) < 10:
        return {"ok": False, "why": "위경도 표본이 모자란다"}

    def lsq(idx: int) -> tuple[float, float, float]:
        # 정규방정식 3×3
        s = [[0.0] * 4 for _ in range(3)]
        for smp in samples:
            r = (1.0, smp[0], smp[1])
            for a in range(3):
                for b in range(3):
                    s[a][b] += r[a] * r[b]
                s[a][3] += r[a] * smp[idx]
        for c in range(3):                                   # 가우스 소거
            p = max(range(c, 3), key=lambda r_: abs(s[r_][c]))
            s[c], s[p] = s[p], s[c]
            for r_ in range(3):
                if r_ != c:
                    f = s[r_][c] / s[c][c]
                    for k in range(c, 4):
                        s[r_][k] -= f * s[c][k]
        return tuple(s[r_][3] / s[r_][r_] for r_ in range(3))

    ax, bx, cx = lsq(2)
    ay, by, cy = lsq(3)
    worst = rms = 0.0
    for i, j, x, y in samples:
        e = math.hypot(x - (ax + bx * i + cx * j), y - (ay + by * i + cy * j))
        worst = max(worst, e)
        rms += e * e
    rms = math.sqrt(rms / len(samples))
    res = {"params": LCC_GUESS, "samples": len(samples),
           "x_km": [ax, bx, cx], "y_km": [ay, by, cy],
           "max_err_km": worst, "rms_km": rms,
           "ok": worst < FIT_OK_KM and abs(cx) < 1e-3 and abs(by) < 1e-3}
    if abs(bx) > 1e-9 and abs(cy) > 1e-9:
        # 기준점(126E, 38N)이 앉는 격자 좌표(0부터, 실수)
        res["ref_ij"] = [-ax / bx, -ay / cy]
        res["grid_km"] = [bx, cy]
    return res


def ij_from_fit(fit: dict, lat: float, lon: float) -> tuple[float, float]:
    x, y = lcc_km(lat, lon, LCC_GUESS)
    ax, bx, _ = fit["x_km"]
    ay, _, cy = fit["y_km"]
    return (x - ax) / bx, (y - ay) / cy


def station_latlon(text: str, stn: str) -> tuple[float, float, str, str] | None:
    """stn_inf 응답에서 (위도, 경도, 그 줄, 머리줄). 칸 순서는 머리줄(# … LON … LAT …)로 정한다."""
    cols = None
    for line in text.splitlines():
        if line.startswith("#"):
            toks = line.lstrip("#").split()
            if "LON" in toks and "LAT" in toks:
                cols = (toks.index("LAT"), toks.index("LON"), line.strip())
            continue
        p = line.split()
        if not p or p[0] != stn:
            continue
        if cols and len(p) > max(cols[:2]):
            try:
                la, lo = float(p[cols[0]]), float(p[cols[1]])
            except ValueError:
                return None
            if 33 < la < 39 and 124 < lo < 132:
                return la, lo, scrub(line.strip())[:160], scrub(cols[2])[:160]
        return None
    return None


def nearest(lat: array, lon: array, nx: int, la: float, lo: float) -> tuple[int, int, float]:
    c = math.cos(math.radians(la))
    best, bk = 1e9, -1
    for k in range(len(lat)):
        d = (lat[k] - la) ** 2 + ((lon[k] - lo) * c) ** 2
        if d < best:
            best, bk = d, k
    return bk % nx, bk // nx, math.sqrt(best) * 111.0


# ── 본체 ──────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tm")
    ap.add_argument("--rain-tm", default="202608281100")
    ap.add_argument("--latlon-nc")
    ap.add_argument("--no-text", action="store_true")
    a = ap.parse_args()

    if not ORG_API_KEY:
        print("ORG_API_KEY 없음 — config/api_keys.txt 를 확인하세요")
        return 2

    now = datetime.now()
    stamp = now.strftime("%Y%m%d%H%M")
    out = DATA / "probe" / stamp
    raw = CACHE / "probe"
    out.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)
    JS.update({"at": now.strftime("%Y-%m-%d %H:%M"), "host": KMA_HOST})

    say(f"# 경남 지도 0단계 실측 — {now:%Y-%m-%d %H:%M} (KST, 이 PC 시계)")
    say()
    say(f"호스트 `{KMA_HOST}` · 원본은 `data/cache/probe/`(커밋 안 됨)")

    # 1. 500m 격자 disp=B — 최신 가용 시각을 찾는다 ──────────────────────
    say()
    say("## 1. 500m 격자 disp=B (rn_60m)")
    g60 = None
    tms = [a.tm] if a.tm else [
        floor_min(now - timedelta(minutes=lag), 5).strftime("%Y%m%d%H%M") for lag in range(5, 65, 5)]
    for tm in tms:
        rec, body = get(NC_API, {"obs": "rn_60m", "tm": tm, "disp": "B"}, timeout=180)
        g = parse_b(body) if rec["status"] == 200 else None
        if g:
            g60, tm60 = g, tm
            (raw / f"rn_60m_{tm}.bin").write_bytes(body)
            break
        say(f"- {tm}: 형식 불일치 — {rec.get('error') or rec.get('head', '')[:120]!r}")
    if not g60:
        say("- ⚠️ disp=B 를 한 번도 못 읽었다. 여기서 멈춘다(형식 불명 — 추측하지 않는다).")
        return finish(out)
    lag = (now - datetime.strptime(tm60, "%Y%m%d%H%M")).total_seconds() / 60
    nx, ny = g60["nx"], g60["ny"]
    s60 = stats(g60["v"])
    say(f"- 시각 {tm60} (지금보다 {lag:.0f}분 전이 첫 가용분) · 크기 {4 + 4 * nx * ny:,} B")
    say(f"- 머리 int16 nx={nx}, ny={ny} · 바이트 순서 **{g60['order']}-endian** (크기가 맞는 쪽)")
    say(f"- 값: {fmt_stats(s60)}")
    JS["b"] = {"tm": tm60, "lag_min": lag, "nx": nx, "ny": ny, "order": g60["order"], "stats": s60}
    mask_png(g60, out / "b_rn60_asis.png")
    say("- 그림 `b_rn60_asis.png` — **저장 순서 그대로**(첫 행을 맨 위에). 한반도가 거꾸로면 첫 행이 남쪽이다")

    # 다른 요소도 같은 모양인가(크기·결측값) ─────────────────────────────
    for obs in ("rn_15m", "rn_day"):
        rec, body = get(NC_API, {"obs": obs, "tm": tm60, "disp": "B"}, timeout=180)
        g = parse_b(body)
        if g:
            st = stats(g["v"])
            say(f"- {obs}: nx={g['nx']}, ny={g['ny']} · {fmt_stats(st)}")
            JS.setdefault("b_other", {})[obs] = {"nx": g["nx"], "ny": g["ny"], "size": rec["size"],
                                                  "stats": st}
        else:
            say(f"- {obs}: 형식 불일치 — {rec.get('error') or rec.get('head', '')[:120]!r}")

    # 확인용 이미지 ─────────────────────────────────────────────────────
    rec, body = get(NC_IMG, {"obs": "rn_60m", "tm": tm60, "map": "HR", "size": 800})
    if rec["status"] == 200 and not is_text(body):
        (out / "kma_img_rn60.png").write_bytes(body)
        say("- 기상청 그림 `kma_img_rn60.png` — 위 마스크 그림과 방향을 견준다")

    # 2. disp=A 와 대조 ────────────────────────────────────────────────
    say()
    say("## 2. disp=A 와 대조 (순서·행 방향)")
    if a.no_text:
        say("- 건너뜀(--no-text)")
    else:
        rec, body = get(NC_API, {"obs": "rn_60m", "tm": tm60, "disp": "A"}, timeout=300)
        text = head_text(body, len(body)) if body else ""
        lines = text.splitlines()
        say(f"- 크기 {len(body):,} B · {len(lines):,}줄 · 앞 12줄:")
        say("```")
        for ln in lines[:12]:
            say(ln[:160])
        say("```")
        va, per = parse_text_floats(text)
        mode = max(set(per), key=per.count) if per else 0
        say(f"- 숫자 {len(va):,}개 · 줄당 숫자 최빈값 {mode} (nx={nx})")
        JS["a"] = {"size": len(body), "lines": len(lines), "floats": len(va), "per_line_mode": mode,
                   "head": [scrub(x[:160]) for x in lines[:12]]}
        if len(va) == nx * ny:
            m = order_match(va, g60["v"], nx, ny)
            say(f"- B 와 견준 순서(표본 일치율): {fmt_match(m)} → **{best_order(m) or '불명'}**")
            JS["a"].update(order=m, order_best=best_order(m))
        else:
            say("- 숫자 개수가 nx·ny 와 다르다 — 좌표가 함께 실린 형식일 수 있다. 위 앞줄을 본다")

    # 3. 500m 위경도 ────────────────────────────────────────────────────
    say()
    say("## 3. 500m 격자 위경도 · 투영")
    lat5 = lon5 = None
    for disp in ("B", "A"):
        got = {}
        for ll in ("lat", "lon"):
            rec, body = get(NC_LATLON, {"latlon": ll, "disp": disp}, timeout=300)
            if rec["status"] != 200:
                say(f"- latlon={ll} disp={disp}: {rec['status']} {rec.get('head', '')[:80]!r}")
                continue
            g = parse_b(body) if disp == "B" else None
            if g and (g["nx"], g["ny"]) == (nx, ny):
                got[ll] = g["v"]
            elif disp == "A":
                v, _ = parse_text_floats(head_text(body, len(body)))
                if len(v) == nx * ny:
                    got[ll] = v
            if ll not in got:
                say(f"- latlon={ll} disp={disp}: 200 이지만 모양이 다르다 ({rec['size']:,} B)")
        if len(got) == 2:
            lat5, lon5 = got["lat"], got["lon"]
            say(f"- 위경도 API(disp={disp})로 받았다")
            break

    ncs = []
    rec, body = get(NC_DOWN, {"obs": "rn_60m", "tm": tm60}, timeout=300)
    if rec["status"] == 200 and body and not is_text(body):
        p = raw / f"rn_60m_{tm60}.nc"
        p.write_bytes(body)
        ncs.append(("자료 NetCDF", p))
    else:
        say(f"- NetCDF 다운로드 실패: {rec.get('error') or rec['status']} {rec.get('head', '')[:80]!r}")
    if a.latlon_nc:
        ncs.append(("위경도 NetCDF", Path(a.latlon_nc)))

    JS["nc"] = {}
    nc_order = None                        # NetCDF 저장 순서 ↔ disp=B
    nc_latlon = None
    for label, p in ncs:
        try:
            info = inspect_nc(p, (nx, ny))
        except Exception as e:                          # noqa: BLE001
            say(f"- {label} `{p.name}` 을 못 열었다: {type(e).__name__}: {e}")
            continue
        arrays = info.pop("arrays", {}) or {}
        JS["nc"][label] = info
        say(f"### {label} `{p.name}`")
        for k in ("note", "dims", "attrs"):
            if info.get(k):
                say(f"- {k}: `{scrub(json.dumps(info[k], ensure_ascii=False))[:1500]}`")
        for vn, vi in (info.get("vars") or {}).items():
            say(f"- 변수 `{vn}` {vi.get('dims', '')} {vi.get('shape')} "
                f"`{scrub(json.dumps(vi.get('attrs', {}), ensure_ascii=False))[:600]}`")
        if info.get("strings"):
            say(f"- 글자열: `{', '.join(info['strings'][:80])}`")
        for key, arr in arrays.items():
            try:
                shp = list(arr.shape)
            except AttributeError:
                continue
            if len(shp) == 1 and shp[0] in (nx, ny) and key in ("x", "y"):
                say(f"- 좌표 `{key}`: 처음 {float(arr[0])}, 둘째 {float(arr[1])}, 끝 {float(arr[-1])}")
                JS["nc"][label][f"coord_{key}"] = [float(arr[0]), float(arr[1]), float(arr[-1])]
        la = next((flat2d(arrays[k], nx, ny) for k in ("lat", "latitude") if k in arrays), None)
        lo = next((flat2d(arrays[k], nx, ny) for k in ("lon", "longitude") if k in arrays), None)
        if la and lo and nc_latlon is None:
            nc_latlon = (la, lo, label)
        # 자료 변수와 disp=B 의 순서 관계 — 위경도를 B 순서로 옮기는 근거가 된다
        for key, arr in arrays.items():
            if key in ("lat", "latitude", "lon", "longitude", "x", "y"):
                continue
            f = flat2d(arr, nx, ny)
            if f is None:
                continue
            m = order_match(f, g60["v"], nx, ny)
            best = best_order(m)
            say(f"- NetCDF `{key}` ↔ disp=B 순서(표본 일치율): {fmt_match(m)} → **{best or '불명'}**")
            JS["nc"][label][f"order_{key}"] = {"match": m, "best": best}
            if best and nc_order is None:
                nc_order = best

    if lat5 is None and nc_latlon:
        la, lo, label = nc_latlon
        if nc_order:
            lat5, lon5 = to_b(la, nc_order, nx, ny), to_b(lo, nc_order, nx, ny)
            say(f"- 위경도를 {label} 에서 얻어 disp=B 순서로 옮겼다(NetCDF ↔ B: {nc_order})")
        else:
            say(f"- ⚠️ {label} 에 위경도는 있으나 NetCDF ↔ disp=B 순서를 못 정했다 — "
                "B 에 붙이지 않는다(6절 AWS 대조도 건너뛴다)")
    JS["nc_order"] = nc_order

    fit = None
    if lat5 is None:
        say("- ⚠️ **500m 위경도를 못 얻었다 → 투영 미확정.** 여기서 추측하지 않는다.")
        say("  API허브 '융합기상고해상도 격자자료' 쪽 위경도 NetCDF 를 받아 `--latlon-nc` 로 다시 돌린다")
    else:
        corners = {"(0,0)": 0, "(nx-1,0)": nx - 1, "(0,ny-1)": (ny - 1) * nx,
                   "(nx-1,ny-1)": ny * nx - 1, "가운데": (ny // 2) * nx + nx // 2}
        for name, k in corners.items():
            say(f"- 칸 {name}: 위도 {lat5[k]:.5f}, 경도 {lon5[k]:.5f}")
        JS["latlon500_corners"] = {n_: [lat5[k], lon5[k]] for n_, k in corners.items()}
        say(f"- 첫 행은 **{'남쪽' if lat5[0] < lat5[(ny - 1) * nx] else '북쪽'}**, "
            f"첫 열은 **{'서쪽' if lon5[0] < lon5[nx - 1] else '동쪽'}** (저장 순서 기준)")
        fit = fit_lcc(lat5, lon5, nx, ny)
        JS["fit500"] = fit
        say(f"- 람베르트(표준위도 30·60, 기준 126E·38N, 구 반지름 6371.00877km)로 맞춘 결과: "
            f"최대 오차 {fit.get('max_err_km', float('nan')):.4f} km · RMS {fit.get('rms_km', float('nan')):.4f} km")
        if "grid_km" in fit:
            say(f"  - 격자 간격 x {fit['grid_km'][0]:.5f} km/열, y {fit['grid_km'][1]:.5f} km/행")
            say(f"  - 기준점(126E, 38N)의 격자 좌표(0부터) i={fit['ref_ij'][0]:.3f}, j={fit['ref_ij'][1]:.3f}")
        say(f"- 판정: **{'확정' if fit['ok'] else '불일치 — 쓰지 않는다'}** (기준 최대 오차 < {FIT_OK_KM} km)")

    # 4. 5km 동네예보 격자 ─────────────────────────────────────────────
    say()
    say("## 4. 5km 동네예보 격자 투영 (nph-dfs_latlon_api 와 공식 대조)")
    got, dec = {}, 0
    for ll in ("lat", "lon"):
        rec, body = get(DFS_LATLON, {"fct": "VSRT", "latlon": ll, "disp": "A"})
        if rec["status"] == 200:
            text = head_text(body, len(body))
            v, per = parse_text_floats(text)
            got[ll] = v
            # 소수 자릿수 — 위경도를 몇 자리로 주느냐에 따라 공식과의 차이가 그만큼 생긴다
            dec = max([dec] + [len(t.split(".")[1]) for t in re.findall(r"-?\d+\.\d+", text[:20000])])
            say(f"- {ll}: {len(v):,}개 · 줄당 최빈 {max(set(per), key=per.count) if per else 0} · 소수 {dec}자리")
    n5 = DFS["nx"] * DFS["ny"]
    if len(got.get("lat", [])) == n5 and len(got.get("lon", [])) == n5:
        la, lo = got["lat"], got["lon"]
        worst, hit = 0.0, 0
        for k in range(n5):
            X, Y = k % DFS["nx"] + 1, k // DFS["nx"] + 1
            fx, fy = dfs_xy(la[k], lo[k])
            worst = max(worst, abs(fx - X), abs(fy - Y))
            hit += (int(fx + 0.5), int(fy + 0.5)) == (X, Y)
        # 판정: 모든 칸에서 공식의 반올림 X, Y 가 API 의 X, Y 와 같고, 차이가 반 칸보다 한참 작을 것.
        # 위경도가 소수 둘째 자리면 반올림만으로 0.1칸 남짓 벌어진다 — 그건 공식 탓이 아니다.
        ok = hit == n5 and worst < 0.25
        say(f"- 인덱스 (Y-1)·149+(X-1) 로 읽어 공식과 견줌: 반올림 X,Y 일치 {hit:,}/{n5:,}칸 · "
            f"최대 차이 {worst:.4f}칸 → **{'확정' if ok else '불일치 — 쓰지 않는다'}**")
        say(f"- (X=1,Y=1) 위경도 {la[0]:.4f}, {lo[0]:.4f} · (X=149,Y=253) {la[-1]:.4f}, {lo[-1]:.4f}")
        JS["dfs"] = {"ok": ok, "index_match": hit, "max_diff_cells": worst, "decimals": dec,
                     "params": DFS, "first": [la[0], lo[0]], "last": [la[-1], lo[-1]]}
    else:
        say(f"- ⚠️ 개수가 {n5:,} 가 아니다 — 대조 못 함")

    # 5. 경남 bbox ─────────────────────────────────────────────────────
    say()
    say(f"## 5. 경남 bbox (시군 경계 외곽 + {BUFFER_KM:.0f}km) → 격자 인덱스")
    xs, ys = zip(*(dfs_xy(la_, lo_) for lo_, la_ in GN_HULL))
    b = BUFFER_KM / DFS["grid"]
    X0, X1 = math.floor(min(xs) - b), math.ceil(max(xs) + b)
    Y0, Y1 = math.floor(min(ys) - b), math.ceil(max(ys) + b)
    say(f"- 5km: X {X0}~{X1}, Y {Y0}~{Y1} (1부터) → {X1 - X0 + 1}×{Y1 - Y0 + 1} = "
        f"{(X1 - X0 + 1) * (Y1 - Y0 + 1):,}칸")
    JS["bbox5"] = {"x": [X0, X1], "y": [Y0, Y1]}
    if fit and fit.get("ok"):
        ij = [ij_from_fit(fit, la_, lo_) for lo_, la_ in GN_HULL]
        bi = BUFFER_KM / abs(fit["grid_km"][0])
        bj = BUFFER_KM / abs(fit["grid_km"][1])
        i0, i1 = max(0, math.floor(min(p[0] for p in ij) - bi)), min(nx - 1, math.ceil(max(p[0] for p in ij) + bi))
        j0, j1 = max(0, math.floor(min(p[1] for p in ij) - bj)), min(ny - 1, math.ceil(max(p[1] for p in ij) + bj))
        say(f"- 500m: i {i0}~{i1}, j {j0}~{j1} (0부터, 저장 순서) → {i1 - i0 + 1}×{j1 - j0 + 1} = "
            f"{(i1 - i0 + 1) * (j1 - j0 + 1):,}칸 · uint16 {(i1 - i0 + 1) * (j1 - j0 + 1) * 2 / 1024:.0f} KB")
        JS["bbox500"] = {"i": [i0, i1], "j": [j0, j1]}
    else:
        say("- 500m: 투영 미확정이라 못 정한다")

    # 6. AWS 대조 ──────────────────────────────────────────────────────
    say()
    say("## 6. AWS 대조 — 창원(155)·진주(192)")
    pos: dict[str, tuple[float, float]] = {}
    for stn in STATIONS:
        for inf in ("AWS", "SFC"):
            rec, body = get(STN_INF, {"inf": inf, "stn": stn})
            ll = station_latlon(head_text(body, len(body)) if body else "", stn)
            if ll:
                pos[stn] = ll[:2]
                say(f"- 지점정보({inf}) `{ll[2]}` · 머리 `{ll[3]}`")
                break
    say(f"- 좌표: {', '.join(f'{STATIONS[s]} {v[0]:.4f}N {v[1]:.4f}E' for s, v in pos.items()) or '못 읽음'}")

    # 지점이 앉는 칸 — 위경도 배열에서 가장 가까운 칸(참값). 투영이 맞았으면 투영으로도 구해 견준다
    cell: dict[str, tuple[int, int]] = {}
    for stn, (la_, lo_) in pos.items():
        if lat5 is not None:
            i, j, dkm = nearest(lat5, lon5, nx, la_, lo_)
            cell[stn] = (i, j)
            msg = f"- {STATIONS[stn]}: 위경도로 가장 가까운 칸 ({i},{j}) · {dkm:.2f} km"
            if fit and fit.get("ok"):
                fi, fj = ij_from_fit(fit, la_, lo_)
                msg += f" · 투영으로 ({fi:.2f},{fj:.2f})"
            say(msg)

    cases = [("최신", tm60, g60)]
    if a.rain_tm and a.rain_tm != tm60:
        rec, body = get(NC_API, {"obs": "rn_60m", "tm": a.rain_tm, "disp": "B"}, timeout=180)
        g = parse_b(body)
        if g:
            cases.append(("비 온 때", a.rain_tm, g))
        else:
            say(f"- {a.rain_tm} 격자를 못 받았다 — {rec.get('error') or rec.get('head', '')[:100]!r}")
    JS["aws"] = []
    marks = []
    for label, tm, g in cases:
        rec, body = get(AWS_MIN, {"tm2": tm, "stn": "0"})
        aws = {}
        for line in (head_text(body, len(body)).splitlines() if body else []):
            p = line.split()
            if len(p) >= 14 and not line.startswith("#") and p[1] in STATIONS:
                aws[p[1]] = p[11]                                   # RN-60m (rain.py 와 같은 칸)
        for stn, name in STATIONS.items():
            if stn not in cell:
                say(f"- {label} {tm} {name}: AWS {aws.get(stn, '—')} · 격자 — (위경도·좌표 미확정)")
                continue
            i, j = cell[stn]
            v = g["v"][j * nx + i]
            around = [g["v"][(j + dj) * nx + i + di] for dj in (-1, 0, 1) for di in (-1, 0, 1)
                      if 0 <= i + di < nx and 0 <= j + dj < ny]
            if label == "최신":
                marks.append((i, j))
            say(f"- {label} {tm} {name}: AWS RN-60m **{aws.get(stn, '—')}** · 격자({i},{j}) **{v:.1f}** "
                f"(3×3 {min(around):.1f}~{max(around):.1f})")
            JS["aws"].append({"case": label, "tm": tm, "stn": stn, "aws": aws.get(stn),
                              "cell": [i, j], "grid": v, "around": [min(around), max(around)]})
    if marks:
        mask_png(g60, out / "b_rn60_stations.png", marks)
        say("- 그림 `b_rn60_stations.png` — 두 지점 칸을 빨갛게 찍었다(저장 순서 그대로)")

    # 7. 5km 격자 자료(실황·초단기·단기) ─────────────────────────────────
    say()
    say("## 7. 5km 격자 — 실황 RN1 · 초단기 RN1 · 단기 PCP")
    odam = []
    for lag_ in range(10, 90, 10):
        tmfc = floor_min(now - timedelta(minutes=lag_), 10).strftime("%Y%m%d%H%M")
        rec, body = get(ODAM, {"tmfc": tmfc, "vars": "RN1"})
        v, _ = parse_text_floats(head_text(body, len(body))) if rec["status"] == 200 else (array("f"), [])
        if len(v) == n5:
            odam.append((tmfc, rec["size"], v))
            if len(odam) == 3:
                break
        else:
            say(f"- 실황 {tmfc}: {len(v):,}개 — {rec.get('head', '')[:80]!r}")
    for tmfc, size, v in odam:
        say(f"- 실황 {tmfc}: {size:,} B · {fmt_stats(stats(v))}")
    if len(odam) >= 2:
        diff = sum(1 for k in range(n5) if odam[0][2][k] != odam[1][2][k])
        say(f"- 실황 {odam[0][0]} ↔ {odam[1][0]}: 다른 칸 {diff:,} (0 이면 10분마다 새로 나오지 않는다)")
    JS["odam"] = [{"tmfc": t, "size": s, "stats": stats(v)} for t, s, v in odam]

    tmfc = (floor_min(now, 10) - timedelta(minutes=20)).strftime("%Y%m%d%H%M")
    tmef = (floor_min(now, 60) + timedelta(hours=1)).strftime("%Y%m%d%H%M")
    rec, body = get(VSRT, {"tmfc": tmfc, "tmef": tmef, "vars": "RN1"})
    JS["vsrt_size"] = rec["size"]
    say(f"- 초단기 {tmfc}→{tmef}: {rec['size']:,} B")

    base = now - timedelta(minutes=20)
    bh = max([h for h in (2, 5, 8, 11, 14, 17, 20, 23) if h <= base.hour], default=None)
    bdt = base.replace(hour=bh, minute=0) if bh is not None else \
        (base - timedelta(days=1)).replace(hour=23, minute=0)
    shrt_cases = [(bdt.strftime("%Y%m%d%H"), (bdt + timedelta(hours=h)).strftime("%Y%m%d%H"))
                  for h in (1, 6)]
    # 지금 수집기(shortfc)는 tmef 를 12자리로 준다 — 두 형태가 같은 답을 내는지 본다
    shrt_cases.append((shrt_cases[0][0], shrt_cases[0][1] + "00"))
    if a.rain_tm:
        rt = datetime.strptime(a.rain_tm, "%Y%m%d%H%M")
        rb = max(h for h in (2, 5, 8, 11, 14, 17, 20, 23) if h <= rt.hour - 1) if rt.hour > 2 else 23
        rbd = rt.replace(hour=rb, minute=0) if rt.hour > 2 else (rt - timedelta(days=1)).replace(hour=23, minute=0)
        shrt_cases += [(rbd.strftime("%Y%m%d%H"), (rbd + timedelta(hours=h)).strftime("%Y%m%d%H"))
                       for h in (1, 2, 3)]
    JS["shrt"] = []
    for tf, te in shrt_cases:
        rec, body = get(SHRT, {"tmfc": tf, "tmef": te, "vars": "PCP"})
        text = head_text(body, len(body)) if body else ""
        v, _ = parse_text_floats(text)
        words = sorted({t for ln in text.splitlines() if not ln.startswith("#")
                        for t in ln.replace(",", " ").split()
                        if not re.fullmatch(r"-?\d+(\.\d+)?", t)})[:20]
        distinct = sorted({round(x, 2) for x in v if x > 0})
        say(f"- 단기 PCP {tf}→{te}: {rec['status']} · {rec['size']:,} B · {len(v):,}개 · "
            f"양수 값 종류 {len(distinct)}: {distinct[:30]}"
            + (f" · 숫자 아닌 글자 {words}" if words else ""))
        JS["shrt"].append({"tmfc": tf, "tmef": te, "status": rec["status"], "size": rec["size"],
                           "n": len(v), "positive_values": distinct[:60], "words": words})

    # 8. 호출량·용량 ──────────────────────────────────────────────────
    say()
    say("## 8. 하루 호출 수 · 용량 (실측 크기로)")
    bsz = 4 + 4 * nx * ny
    osz = odam[0][1] if odam else 0
    ssz = max((s["size"] for s in JS["shrt"]), default=0)
    shrt_calls = sum(48 - h for h in (2, 5, 8, 11, 14, 17, 20, 23))      # 오늘·내일
    rows = [("500m rn_15m · 10분", 144, bsz), ("500m rn_60m · 10분", 144, bsz),
            ("500m rn_day · 10분", 144, bsz), ("실황 RN1 5km · 10분", 144, osz),
            ("단기 PCP 오늘·내일 · 발표당", shrt_calls, ssz)]
    say("| 자료 | 하루 호출 | 한 번 | 하루 |")
    say("|---|---:|---:|---:|")
    tc = tb = 0
    for name, calls, size in rows:
        tc += calls
        tb += calls * size
        say(f"| {name} | {calls:,} | {size / 1e6:.2f} MB | {calls * size / 1e9:.2f} GB |")
    say(f"| **합계** | **{tc:,}** | | **{tb / 1e9:.2f} GB** |")
    say("- 한도: 하루 30,000회 / 50GB. 단기 PCP 는 지금 수집기(shortfc)가 이미 부르는 호출이다")
    JS["volume"] = {"rows": rows, "calls": tc, "bytes": tb}

    return finish(out)


def finish(out: Path) -> int:
    say()
    say("## 부른 것")
    say("| 주소(키 없음) | 상태 | 크기 | 초 |")
    say("|---|---|---:|---:|")
    for c in CALLS:
        say(f"| `{c['url']}` | {c.get('error') or c['status']} | {c['size']:,} | {c['sec']} |")
    JS["calls"] = CALLS
    (out / "report.md").write_text(scrub("\n".join(MD)) + "\n", encoding="utf-8")
    (out / "report.json").write_text(
        scrub(json.dumps(JS, ensure_ascii=False, indent=1, default=str)), encoding="utf-8")
    print(f"\n보고서: {out / 'report.md'}")
    print("이 폴더(data/probe/…)를 커밋·푸시하면 다음 단계에서 읽는다. 키는 들어 있지 않다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

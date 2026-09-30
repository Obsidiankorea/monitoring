"""격자 투영 — 경위도 ↔ 격자 칸. 외부 라이브러리 없이 식으로만.

두 격자는 도법이 같아 보여도 **지구 모양이 다르다.** 섞으면 경남 안에서 800m 어긋난다.

| 격자 | 도법 | 칸 | 원점 칸(0부터) |
|---|---|---|---|
| 고해상도 500m (`nph-sfc_obs_nc_api`) | **타원체(GRS80)** 람베르트, 30°·60°, 126°E·38°N | 2049 × 2049, 500m | (880, 1540) |
| 동네예보 5km (`nph-dfs_*_grd`)      | **구면**(Re 6371.00877km) 람베르트, 같은 매개변수 | 149 × 253, 5km | (42, 135) |

⚠️ 실측(2026-10-01, README '경남 지도'): 500m 는 API허브 첨부 `sfc_grid_latlon.nc` 의 칸별
   위경도와 전 칸 0.0016칸 안에서 맞고, 같은 매개변수를 구면으로 풀면 최대 3.8칸 어긋난다.
   5km 는 `nph-dfs_latlon_api` 와 전 칸 0.0001칸. NetCDF 속성에는 표준위도가 없다 —
   그래서 여기 숫자는 추측이 아니라 칸별 위경도에 맞춰 확인한 값이다.

칸 좌표는 **칸 가운데가 정수**다. 행은 남→북(기상청 자료 순서 그대로)이라 화면에
그릴 때만 뒤집는다.
"""
from __future__ import annotations

import math

D = math.pi / 180

# ── 고해상도 500m — 타원체 람베르트 정각원추(2 표준위도) ───────────────────
HR = {"nx": 2049, "ny": 2049, "xo": 880, "yo": 1540, "grid_m": 500.0,
      "slat1": 30.0, "slat2": 60.0, "olon": 126.0, "olat": 38.0,
      "ellps": "GRS80", "a": 6378137.0, "f": 1 / 298.257222101}

_E = math.sqrt(HR["f"] * (2 - HR["f"]))


def _m(phi: float) -> float:
    s = math.sin(phi)
    return math.cos(phi) / math.sqrt(1 - _E * _E * s * s)


def _t(phi: float) -> float:
    s = math.sin(phi)
    return math.tan(math.pi / 4 - phi / 2) / ((1 - _E * s) / (1 + _E * s)) ** (_E / 2)


_p1, _p2, _p0 = HR["slat1"] * D, HR["slat2"] * D, HR["olat"] * D
_N = (math.log(_m(_p1)) - math.log(_m(_p2))) / (math.log(_t(_p1)) - math.log(_t(_p2)))
_F = _m(_p1) / (_N * _t(_p1) ** _N)
_AF = HR["a"] * _F
_RHO0 = _AF * _t(_p0) ** _N


def hr_xy(lon: float, lat: float) -> tuple[float, float]:
    """경위도 → 500m 격자 칸(열, 행). 0부터, 칸 가운데가 정수."""
    rho = _AF * _t(lat * D) ** _N
    th = _N * (lon - HR["olon"]) * D
    x = rho * math.sin(th)
    y = _RHO0 - rho * math.cos(th)
    return x / HR["grid_m"] + HR["xo"], y / HR["grid_m"] + HR["yo"]


def hr_lonlat(col: float, row: float) -> tuple[float, float]:
    """500m 격자 칸 → 경위도. 위도는 반복해 푼다(타원체라 닫힌 식이 없다)."""
    x = (col - HR["xo"]) * HR["grid_m"]
    y = (row - HR["yo"]) * HR["grid_m"]
    dy = _RHO0 - y
    rho = math.copysign(math.hypot(x, dy), _N)
    th = math.atan2(x, dy)
    t = (rho / _AF) ** (1 / _N)
    phi = math.pi / 2 - 2 * math.atan(t)
    for _ in range(15):
        s = math.sin(phi)
        nxt = math.pi / 2 - 2 * math.atan(t * ((1 - _E * s) / (1 + _E * s)) ** (_E / 2))
        if abs(nxt - phi) < 1e-12:
            phi = nxt
            break
        phi = nxt
    return th / _N / D + HR["olon"], phi / D


# ── 동네예보 5km — 구면 람베르트(기상청 lamcproj 와 같은 식) ────────────────
DFS = {"nx": 149, "ny": 253, "xo": 42, "yo": 135, "grid_km": 5.0,
       "slat1": 30.0, "slat2": 60.0, "olon": 126.0, "olat": 38.0, "re_km": 6371.00877}

_s1, _s2, _o0 = DFS["slat1"] * D, DFS["slat2"] * D, DFS["olat"] * D
_SN = math.log(math.cos(_s1) / math.cos(_s2)) / math.log(
    math.tan(math.pi / 4 + _s2 / 2) / math.tan(math.pi / 4 + _s1 / 2))
_SF = math.tan(math.pi / 4 + _s1 / 2) ** _SN * math.cos(_s1) / _SN
_RE = DFS["re_km"] / DFS["grid_km"]
_RO = _RE * _SF / math.tan(math.pi / 4 + _o0 / 2) ** _SN


def dfs_xy(lon: float, lat: float) -> tuple[float, float]:
    """경위도 → 5km 격자 칸. **0부터**다 — 기상청 X·Y(1부터)는 여기에 1을 더한 값."""
    ra = _RE * _SF / math.tan(math.pi / 4 + lat * D / 2) ** _SN
    th = (lon - DFS["olon"]) * D
    if th > math.pi:
        th -= 2 * math.pi
    if th < -math.pi:
        th += 2 * math.pi
    th *= _SN
    return ra * math.sin(th) + DFS["xo"], _RO - ra * math.cos(th) + DFS["yo"]


def dfs_lonlat(col: float, row: float) -> tuple[float, float]:
    xn = col - DFS["xo"]
    yn = _RO - row + DFS["yo"]
    ra = math.copysign(math.hypot(xn, yn), _SN)
    lat = 2 * math.atan((_RE * _SF / ra) ** (1 / _SN)) - math.pi / 2
    th = math.atan2(xn, yn)
    return th / _SN / D + DFS["olon"], lat / D


# ── UTM-K (EPSG:5179) → 경위도. 경계 파일(SGIS) 읽기에만 쓴다 ──────────────
# 횡메르카토르, GRS80, 중앙경선 127.5°, 원점위도 38°, k0 0.9996, (1,000,000, 2,000,000).
# 크뤼거 급수(3차) — 중앙경선에서 3° 안이면 mm 안쪽으로 맞는다.
_UK = {"lon0": 127.5, "lat0": 38.0, "k0": 0.9996, "fe": 1_000_000.0, "fn": 2_000_000.0}
_n = HR["f"] / (2 - HR["f"])
_A = HR["a"] / (1 + _n) * (1 + _n ** 2 / 4 + _n ** 4 / 64)
_ALPHA = (_n / 2 - 2 * _n ** 2 / 3 + 5 * _n ** 3 / 16, 13 * _n ** 2 / 48 - 3 * _n ** 3 / 5,
          61 * _n ** 3 / 240)
_BETA = (_n / 2 - 2 * _n ** 2 / 3 + 37 * _n ** 3 / 96, _n ** 2 / 48 + _n ** 3 / 15,
         17 * _n ** 3 / 480)
_DELTA = (2 * _n - 2 * _n ** 2 / 3 - 2 * _n ** 3, 7 * _n ** 2 / 3 - 8 * _n ** 3 / 5,
          56 * _n ** 3 / 15)


def _xi_on_meridian(lat: float) -> float:
    """중앙경선 위 위도 lat 의 ξ(북거리 ÷ k0A)."""
    s = math.sin(lat * D)
    c = 2 * math.sqrt(_n) / (1 + _n)
    t = math.sinh(math.atanh(s) - c * math.atanh(c * s))
    xi_ = math.atan(t)
    return xi_ + sum(a * math.sin(2 * (j + 1) * xi_) for j, a in enumerate(_ALPHA))


_XI0 = _xi_on_meridian(_UK["lat0"])


def utmk_lonlat(e: float, n: float) -> tuple[float, float]:
    k0a = _UK["k0"] * _A
    xi = (n - _UK["fn"]) / k0a + _XI0
    eta = (e - _UK["fe"]) / k0a
    xi_, eta_ = xi, eta
    for j, b in enumerate(_BETA):
        k = 2 * (j + 1)
        xi_ -= b * math.sin(k * xi) * math.cosh(k * eta)
        eta_ -= b * math.cos(k * xi) * math.sinh(k * eta)
    chi = math.asin(math.sin(xi_) / math.cosh(eta_))
    lat = chi + sum(d * math.sin(2 * (j + 1) * chi) for j, d in enumerate(_DELTA))
    lon = _UK["lon0"] * D + math.atan2(math.sinh(eta_), math.cos(xi_))
    return lon / D, lat / D

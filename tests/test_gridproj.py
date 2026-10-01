"""격자 투영 — 기상청이 준 칸별 위경도(알려진 지점)와 맞는가.

값은 API허브 첨부 `sfc_grid_latlon.nc`(500m)와 `nph-dfs_latlon_api`(5km)에서 뽑았다(2026-10-01).
UTM-K 값은 pyproj(EPSG:5179 → 4326)로 뽑았다.
"""
import pytest

from app.domain import gridproj as gp

# (열, 행, 경도, 위도) — 칸 번호는 0부터
HR = [
    (0, 0, 121.382278, 30.830734),          # 남서 모서리 — 자료가 여기서 시작한다
    (2048, 2048, 133.069901, 40.114571),    # 북동 모서리
    (1340, 933, 128.573196, 35.168133),     # 창원(155) 관측소 칸
    (1200, 1100, 127.811501, 35.953266),    # 거창 북쪽
    (880, 1540, 126.0, 38.0),               # 원점
]
DFS = [
    (0, 0, 123.761261, 31.794424),
    (148, 252, 132.774963, 43.217545),
    (88, 74, 128.578812, 35.159767),        # 기상청 X=89, Y=75 — 창원
    (42, 135, 126.0, 38.0),                 # X=43, Y=136
]


@pytest.mark.parametrize("col,row,lon,lat", HR)
def test_hr_forward(col, row, lon, lat):
    x, y = gp.hr_xy(lon, lat)
    assert abs(x - col) < 0.01 and abs(y - row) < 0.01        # 0.01칸 = 5m


@pytest.mark.parametrize("col,row,lon,lat", HR)
def test_hr_inverse(col, row, lon, lat):
    lo, la = gp.hr_lonlat(col, row)
    assert abs(lo - lon) < 1e-4 and abs(la - lat) < 1e-4       # 파일이 float32 다


@pytest.mark.parametrize("col,row,lon,lat", DFS)
def test_dfs_forward_inverse(col, row, lon, lat):
    x, y = gp.dfs_xy(lon, lat)
    assert abs(x - col) < 0.001 and abs(y - row) < 0.001
    lo, la = gp.dfs_lonlat(col, row)
    assert abs(lo - lon) < 1e-5 and abs(la - lat) < 1e-5


def test_sphere_formula_misplaces_500m_grid():
    """⚠️ 함정 기록: 같은 매개변수를 구면(동네예보식)으로 풀면 500m 격자가 어긋난다.

    d3.geoConicConformal 이 구면이다. 경남(창원)에서도 한 칸이 넘게 빗나간다.
    """
    lon, lat = 128.573196, 35.168133
    x5, y5 = gp.dfs_xy(lon, lat)
    sx, sy = (x5 - gp.DFS["xo"]) * 10 + gp.HR["xo"], (y5 - gp.DFS["yo"]) * 10 + gp.HR["yo"]
    x, y = gp.hr_xy(lon, lat)
    assert max(abs(sx - x), abs(sy - y)) > 0.5


@pytest.mark.parametrize("e,n,lon,lat", [
    (1_000_000, 2_000_000, 127.5, 38.0),
    (1_100_000, 1_700_000, 128.599749014, 35.290512166),
    (1_164_133.5, 1_711_697.9, 129.307151796, 35.387472344),
])
def test_utmk(e, n, lon, lat):
    lo, la = gp.utmk_lonlat(e, n)
    assert abs(lo - lon) < 1e-8 and abs(la - lat) < 1e-8

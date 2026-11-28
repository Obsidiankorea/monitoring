"""산림청 산사태정보시스템 — 위험도 그림 → 500m 칸 등급, 응답 행 고르기(2026-11-28 실제 모양), 계정 · 실명 빼기."""
import io
from datetime import datetime

import numpy as np
from PIL import Image

from app import apikeys, config, gridstore, sansatai
from app.domain.gridproj import hr_xy


def _png(a: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(a, "RGBA").save(buf, "PNG")
    return buf.getvalue()


def test_grade_image_reads_only_exact_forest_colors():
    a = np.zeros((2, 4, 4), np.uint8)
    a[0, 0] = (255, 0, 0, 255)            # 1등급
    a[0, 1] = (255, 201, 0, 255)          # 2등급
    a[0, 2] = (0, 0, 255, 255)            # 5등급
    a[0, 3] = (250, 0, 0, 255)            # 섞인 색 — 버린다
    a[1, 0] = (255, 0, 0, 0)              # 투명 — 버린다
    g = sansatai.grade_image(_png(a))
    assert g[0].tolist() == [1, 2, 5, 0] and g[1].tolist() == [0, 0, 0, 0]


S = sansatai.SUB


def _sub_of(lon, lat):
    """경위도 → 100m 칸 지도(행 북→남)의 (행, 열)."""
    b = gridstore.geo()["hr"]["bbox"]
    c, r = hr_xy(lon, lat)                                        # 칸 가운데가 정수 — 칸 왼쪽(아래) 끝은 −0.5
    return int((b["j1"] + 0.5 - r) * S), int((c - b["i0"] + 0.5) * S)


def _raw_with(points, base=5):
    w, h = sansatai.raw_size()
    g = np.full((h, w), base, np.uint8)
    for lon, lat, grade in points:
        g[int((sansatai.BBOX[3] - lat) / sansatai.PX), int((lon - sansatai.BBOX[0]) / sansatai.PX)] = grade
    return g


def test_sub_keeps_a_single_pixel_small_and_in_place():
    lon, lat = 127.8705, 35.3705                                  # 산청 산지
    sub = sansatai.to_sub(_raw_with([(lon, lat, 1)]))
    b = gridstore.geo()["hr"]["bbox"]
    assert sub.shape == (b["h"] * S, b["w"] * S)
    r, c = _sub_of(lon, lat)
    assert (sub[r - 1:r + 2, c - 1:c + 2] == 1).any()            # 그 자리(±100m)에
    assert 1 <= (sub == 1).sum() <= 2                             # 원본 픽셀 하나(약 100m) — 500m 칸을 통째 칠하지 않는다


def test_cells_use_the_widest_grade_and_leave_mostly_empty_cells_blank():
    sub = np.zeros((2 * S, 2 * S), np.uint8)
    sub[:S, :S] = 5
    sub[0, 0] = 1                                                 # 1등급 한 칸 + 5등급 24칸 → 5등급
    sub[:S, S:S + S // 2] = 3                                     # 25칸 중 10칸만 — 절반이 안 돼 비운다
    sub[S:, :S] = 4
    sub[S:, :2] = 2                                               # 2등급 10칸 · 4등급 15칸 → 4등급
    sub[S:, S:] = 0
    sub[S:, S:S + 3] = 2
    sub[S:S + 1, S + 3:] = 1
    sub[S + 1:, S + 3:] = 1                                       # 2등급 15칸 · 1등급 10칸 → 2등급
    assert sansatai.to_cells(sub).tolist() == [[5, 0], [4, 2]]


def test_cells_tie_goes_to_the_dangerous_grade():
    sub = np.zeros((S, S), np.uint8)
    sub.flat[:12] = 1
    sub.flat[12:24] = 3                                           # 12 대 12 (+빈 1) → 1등급
    assert sansatai.to_cells(sub).tolist() == [[1]]


def test_sigun_area_is_hundred_metre_cells_times_001_km2():
    b = gridstore.geo()["hr"]["bbox"]
    sub = np.zeros((b["h"] * S, b["w"] * S), np.uint8)
    r, c = _sub_of(127.87, 35.37)                                 # 산청
    sub[r, c] = 1
    sub[r, c + 1] = 1
    area = sansatai.sigun_area(sub)
    assert area["산청"][0] == 0.02 and area["경남"][0] == 0.02
    assert sum(v[0] for k, v in area.items() if k != "경남") == 0.02


def test_cells_png_filters_grades_and_scales():
    cells = np.array([[1, 3, 5, 0]], np.uint8)
    a = np.asarray(Image.open(io.BytesIO(sansatai.cells_png(cells, max_grade=3, scale=2))))
    assert a.shape == (2, 8, 4)
    assert tuple(a[0, 0]) == (255, 0, 0, 255) and tuple(a[0, 2]) == (182, 255, 142, 255)
    assert a[0, 4, 3] == 0 and a[0, 6, 3] == 0                    # 5등급(max 3 밖) · 없음은 투명


def test_parse_pred_keeps_gyeongnam_and_maps_levels():
    rows = [{"alarmType": "1", "analDate": "2026-09-03 16시", "sigun": "경상남도 창원시 의창구", "staId": "308821",
             "emdCd": "4812110600,4812131000", "emdNm": "동정동,북면", "geom": "MULTIPOLYGON(...)"},
            {"alarmType": "2", "analDate": "2026-08-31 06시", "sigun": "경상남도 하동군", "staId": "692489", "emdNm": "옥종면"},
            {"alarmType": "3", "analDate": "2026-08-31 06시", "sigun": "충청남도 당진시", "staId": "1"}]
    out = sansatai.parse_pred(rows, "예측")
    assert [(x["sigun"], x["lv"], x["name"]) for x in out] == [("창원", 1, "주의보"), ("하동", 3, "경보")]
    assert out[0]["anal"] == "2026-09-03 16" and out[0]["emd"] == ["동정동", "북면"] and out[0]["gu"] == "의창구"
    assert "geom" not in str(out)


def test_parse_status_marks_unissued():
    rows = [{"doSiGun": "경상남도 거창군", "alarmType": "2", "analDate": "2026-08-30 17:00", "siguCode": "48880",
             "frstFrcstIssuDtm": "-", "lastFrcstRlsDtm": "-", "frcstIssuWritrNm": "-", "frcstIssuKindCd": "-"},
            {"doSiGun": "경상남도 하동군", "alarmType": "1", "analDate": "2026-08-30 17:00", "siguCode": "48850",
             "frstFrcstIssuDtm": "2026-08-30 17:20", "lastFrcstRlsDtm": "-", "frcstIssuWritrNm": "홍길동", "frcstIssuKindCd": "1"}]
    out = sansatai.parse_status(rows)
    assert out[0]["issued"] is None and out[0]["name"] == "경보"
    assert out[1]["issued"] == "주의보" and out[1]["issued_at"] == "2026-08-30 17:20"
    assert "홍길동" not in str(out)                                 # 작성자 실명은 넘기지 않는다


def test_parse_mtn():
    out = sansatai.parse_mtn([{"wtherObsrrNm": "거제 북병산", "wtherObsrrAddr": "경상남도 거제시 삼거동  산162 임",
                               "wtherObsrrLctnXcrd": 128.66629, "wtherObsrrLctnYcrd": 34.82425, "rainHour": 0,
                               "rainAnlssDtm": "2026-11-28 14시"}])
    assert out == [{"name": "거제 북병산", "sigun": "거제", "lon": 128.66629, "lat": 34.82425, "mm": 0.0, "at": "2026-11-28 14:00"}]


def test_clean_drops_account_and_personal_fields():
    j = {"userInfo": {"userPwd": "B1oj…", "userPhone": "055"}, "frcstIssuList": [
        {"frcstWriterNm": "오미연", "prctnInfoArnm": "충청남도 당진시", "keyword01": "", "geom": "X", "lndslFrcstIssuId": "12440"}]}
    out = sansatai._clean(j)
    assert out == {"frcstIssuList": [{"prctnInfoArnm": "충청남도 당진시", "lndslFrcstIssuId": "12440"}]}


def test_pred_history_roundtrip(tdb):
    rows = sansatai.parse_pred([{"alarmType": "1", "analDate": "2026-09-03 16시", "sigun": "경상남도 하동군",
                                 "staId": "9", "emdNm": "옥종면,청암면"}], "실황")
    sansatai.store_pred(rows, datetime(2026, 9, 3, 16, 5))
    sansatai.store_pred(rows, datetime(2026, 9, 3, 16, 15))     # 같은 분석 · 묶음은 한 줄
    h = sansatai.history("2026-09-03 00", "2026-09-03 23")
    assert len(h) == 1 and h[0]["emd"] == ["옥종면", "청암면"] and h[0]["kind"] == "실황"


def test_password_tail_is_never_shown(tmp_path, monkeypatch):
    f = tmp_path / "api_keys.txt"
    f.write_text("", "utf-8")
    monkeypatch.setattr(apikeys, "FILE", f)
    monkeypatch.setattr(config, "KEYS", {})
    apikeys.save("SANSATAI_ID", "m48000abcdef")
    apikeys.save("SANSATAI_PW", "secretpass1234")
    st = {k["name"]: k for k in apikeys.status()}
    assert st["SANSATAI_PW"]["set"] and st["SANSATAI_PW"]["tail"] == "" and "1234" not in str(st["SANSATAI_PW"])
    assert sansatai.credentials() == ("m48000abcdef", "secretpass1234")

"""재난안전데이터 4종 — 응답(2026-11-03 실제 모양)을 경남 지도용으로 고르는 것."""
from datetime import datetime

from app import safety

NOW = datetime(2026, 8, 18, 12, 0)


def test_sigun():
    assert safety.sigun_of("경상남도 창원시 의창구") == "창원" and safety.sigun_of("전북특별자치도 정읍시") is None
    assert safety.sigun_of_code("48125") == "창원" and safety.sigun_of_code("48720") == "의령" and safety.sigun_of_code("46790") is None


def test_fcst_latest_per_sigun_and_kind():
    r = lambda st, dt, nm="경상남도 진주시", k="주의보": {"FRCST_APNT_KND_CD_NM": k, "FRCST_APNT_STTS": st,  # noqa: E731
                                                          "FRCST_APNT_DT": dt, "OCRN_FRCST_APNT_INST_NM": nm}
    out = safety.parse_fcst([r("발령", "2026-08-17 08:43:00"), r("해제", "2026-08-17 20:00:00"),
                             r("발령", "2026-08-18 09:00:00", "경상남도 통영시"), r("발령", "2026-08-10 09:00:00", "경상남도 하동군"),
                             r("발령", "2026-08-18 09:00:00", "전북특별자치도 정읍시")], NOW)
    on = {x["sigun"]: x["on"] for x in out}
    assert on == {"진주": False, "통영": True, "하동": False}           # 해제됨 · 발령 중 · 72시간 지남, 경남 밖은 빠진다


def test_pred_on_only_within_a_day_and_with_level():
    r = lambda dt, nm, sg="경상남도 사천시": {"PREDC_ANLS_DT": dt, "SGG_NM": sg, "LNLD_FRCST_NM": nm}  # noqa: E731
    out = {x["sigun"]: x for x in safety.parse_pred([r("2026-08-17 10:00:00", "주의보"), r("2026-08-18 08:00:00", "경보"),
                                                       r("2026-08-18 08:00:00", None, "경상남도 남해군")], NOW)}
    assert out["사천"]["on"] and out["사천"]["lv"] == 2 and not out["남해"]["on"]


def test_res_last_record_per_sensor():
    r = lambda cd, se, dt, senu=1: {"MNG_INST_CD": "48240", "DST_RSK_DSTRCT_FCLTY_CD": "4824030001", "MEMENT_SENU": senu,  # noqa: E731
                                    "MEMENT_NM": f"계측{senu}", "LAT": "35.0", "LOT": "128.1", "WRN_CD": cd, "APNT_SE": se,
                                    "WRN_APNT_DT": dt, "MDFCN_DT": "", "WRN_APNT_CN": "(현수위) 2.61m * 계측기 고장 등에 의한 오측이 발생할수도 있으니 참고하시기 바랍니다."}
    out = safety.parse_res([r("03", "1", "20261018212629"), r("03", "2", "20261019010000"), r("02", "1", "20261020000000", 2),
                            {**r("05", "1", "20261020000000", 3), "MNG_INST_CD": "46790"}], now=datetime(2026, 10, 20, 1))
    assert [(x["name"], x["on"], x["lvn"]) for x in out] == [("계측2", True, "주의"), ("계측1", False, "경계")]
    # 해제 없이 72시간 넘은 발령은 지금 발령이 아니다(old) — 2025-07 발령이 '발령 중'으로 남던 것
    old = safety.parse_res([r("03", "1", "20250717150500")], now=datetime(2026, 11, 9, 22))
    assert not old[0]["on"] and old[0]["old"] and old[0]["days"] > 400
    assert out[0]["cn"] == "(현수위) 2.61m" and out[0]["at"] == "2026-10-20 00:00"


def test_flood_polygon_to_lonlat():
    g = "MULTIPOLYGON(((14391405.95 4297942.32,14391326.56 4297765.22,14391439.95 4297713.70,14391405.95 4297942.32)))"
    out = safety.parse_flood([{"STDG_CTPV_CD": "48", "STDG_SGG_CD": "48170", "GEOM": g, "FLDN_YR": "2002"},
                              {"STDG_CTPV_CD": "47", "GEOM": g}])
    assert len(out) == 1 and out[0]["sigun"] == "진주"
    lon, lat = out[0]["r"][0][0]
    assert 129.2 < lon < 129.3 and 35.9 < lat < 36.0


def test_slide_only_during_rain_or_typhoon_or_manual(tdb, monkeypatch):
    """산사태는 경남 호우 · 태풍 특보(바다 빼고) 때만, 또는 '늘 받기'."""
    from app import queries
    groups = []
    monkeypatch.setattr(queries, "alerts", lambda: {"data": {"groups": groups}})
    assert safety.slide_mode() == "auto" and safety.slide_why() is None
    groups[:] = [{"name": "태풍주의보", "sea": True}, {"name": "강풍주의보", "sea": False}]
    assert safety.slide_why() is None
    groups.append({"name": "호우주의보", "sea": False})
    assert safety.slide_why() == "호우주의보 중"
    groups[:] = []
    tdb.put_setting("sd_slide", {"mode": "on"})
    assert safety.slide_why() == "늘 받기(수동)"

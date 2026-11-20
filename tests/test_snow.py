"""적설 — 지점 목록(경남만 · 시군 · 산지) · CSV 값(결측) · 시군 대표(산지 빼고) · 도 대설 비상단계 · 사건 이력 · AI 한 줄."""
from fastapi.testclient import TestClient

from app import ai, events, main, snow

STN = """#START7777
# STN LON LAT STN_SP HT STN STN_KO FCT_ID LAW_ID
  284 127.90990000 35.66739000 608 228.45 152 거창 11H20502 4888025028
  872 127.75629000 35.31913000 618 864.70 155 지리산 11H20700 4886036021
  289 127.87910000 35.41299000 618 138.07 155 산청 11H20703 4886025023
  155 128.57285000 35.17020000 500 37.60 155 창원 11H20301 4812510100
  90 128.5 37.7 000 18.0 105 속초 11D20401 4282010100
#7777END"""


def _csv(vals: dict) -> str:
    return "#START7777\n# TM, STN, KO, LON, LAT, SP, SD\n" + "\n".join(
        f"202611201500, {k}, x, 127.9, 35.6, 000-----, {v},=" for k, v in vals.items()) + "\n#7777END"


def test_parse_and_build():
    st = snow.parse_stations(STN)
    assert set(st) == {"284", "872", "289", "155"}                     # 속초(강원) 빠짐
    assert st["155"]["sigun"] == "창원" and st["872"]["mt"] and not st["284"]["mt"]
    tm, tot = snow.parse_values(_csv({"284": 4.2, "872": 12.0, "289": 0.0, "155": -99.9}))
    assert tm == "202611201500" and tot["155"] is None and tot["289"] == 0.0
    d = snow.build(st, tot, {"d24": snow.parse_values(_csv({"284": 5.5, "872": 9.0, "289": 0.3}))[1]}, [], tm)
    assert d["active"] and d["siguns"]["거창"]["d24"] == 5.5
    assert "산청" not in d["siguns"]                                   # 지리산(산지) 12cm 가 산청 값이 되지 않는다
    assert next(r for r in d["stations"] if r["stn"] == "289")["d24"] == 0.0   # 0.5 미만 잡음은 0


def test_do_stage_snow(monkeypatch):
    monkeypatch.setattr(ai, "overrides", lambda: {})
    g = lambda name, sg: {"name": name, "siguns": sg, "sea": False}    # noqa: E731
    assert ai.do_stage([g("대설주의보", ["거창"])])["stage"] == "초기대응"
    assert ai.do_stage([g("대설주의보", ["거창", "함양"]), g("대설경보", ["산청", "합천"])])["stage"] == "비상 1단계"
    assert ai.do_stage([g("대설경보", ["거창", "함양", "산청", "합천"])])["stage"] == "비상 2단계"
    # 호우와 대설이 같이면 높은 쪽
    assert ai.do_stage([g("호우경보", ["창원", "김해", "양산"]), g("대설주의보", ["거창"])])["stage"] == "비상 2단계"
    assert events.alert_names([g("대설주의보", ["거창"])]) == ["대설주의보"]


def test_api_and_ai_text(tdb):
    st = snow.parse_stations(STN)
    tot = snow.parse_values(_csv({"284": 4.2, "872": 12.0, "289": 0.0, "155": 0.0}))[1]
    tdb.put_snapshot("snow", "202611201500", "2026-11-20 15:02",
                     snow.build(st, tot, {"d24": {"284": 6.0}}, ["거창"], "202611201500"))
    j = TestClient(main.app).get("/api/snow").json()
    assert j["active"] and j["alert"] == ["거창"] and len(j["stations"]) == 4
    t = snow.text()
    assert "거창 4.2cm" in t and "지리산 12cm" in t and "대설주의보 기준" in t
    assert snow.text("창원") is not None and "거창" not in snow.text("창원")


def test_pty_and_meeting(tdb, monkeypatch):
    """실황 강수형태 → 읍면동마다 눈 · 비/눈 · 비, 지금 눈이 오는 시군은 active · AI 줄 · 회의 '적설현황'에."""
    monkeypatch.setattr(snow, "_pick", lambda vals, w: {"거창": {"북상면": 3.0, "거창읍": 2.0, "남하면": 0.0}, "진주": {"문산읍": 1.0}})
    pty = snow.pty_by_emd([0.0])
    assert pty == {"거창": {"snow": ["북상면"], "mix": ["거창읍"], "rain": []}, "진주": {"snow": [], "mix": [], "rain": ["문산읍"]}}
    st = snow.parse_stations(STN)
    tot = {k: 0.0 for k in st}
    d = snow.build(st, tot, {}, [], "202611201500", pty, "202611201450")
    assert d["active"] and d["falling"] == ["거창"]                  # 비만 오는 진주는 아니다
    tdb.put_snapshot("snow", "202611201500", "2026-11-20 15:02", d)
    assert "지금 눈(실황): 거창" in snow.text()
    lines, basis = snow.meeting_lines(["거창"])
    assert lines[0]["text"].startswith("거창: 쌓인 눈 없음 · 지금 눈") and basis
    from app import meeting
    monkeypatch.setattr(meeting, "alert_siguns", lambda: ([], [], None))
    body, _ = meeting.extras(["대설"], {"특보지역현황": False, "과거사례": False, "조위현황": False})
    assert "적설현황" in body
    tdb.put_snapshot("snow", "202611201510", "2026-11-20 15:12", snow.build(st, tot, {}, [], "202611201510"))
    assert snow.meeting_lines()[0] is None                          # 눈 · 대설특보가 없으면 넣지 않는다

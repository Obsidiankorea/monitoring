"""상황판단 모드 — 판단 기록(서버 공유) · 도달 시각을 단기예보까지 · 만약에 배수."""
from fastapi.testclient import TestClient

from app import ai, main


def test_decisions_record_list_delete(tdb):
    c = TestClient(main.app)
    assert c.post("/api/ai/decisions", json={"sigun": "창원", "act": "발송"}).status_code == 400   # 모르는 결정
    r = c.post("/api/ai/decisions", json={"sigun": "창원", "emd": "진동면", "fam": "산사태", "stage": "긴급대피",
                                          "act": "보류", "pct": 62, "eta": "02"}).json()["rows"]
    assert r[0]["act"] == "보류" and r[0]["pct"] == 62 and r[0]["eta"] == "02"
    c.post("/api/ai/decisions", json={"sigun": "거제", "act": "메모", "note": "x"})
    assert len(c.get("/api/ai/decisions?sigun=창원").json()["rows"]) == 1
    c.delete(f"/api/ai/decisions/{r[0]['id']}")
    assert c.get("/api/ai/decisions?sigun=창원").json()["rows"] == []


def test_eta_runs_into_short_forecast():
    """초단기 6시간 안에 안 닿아도 단기예보(eta_hours)를 이어 '내일 01' 같은 시각을 낸다 — 산사태 긴급대피 누적 270㎜."""
    r = {"rain": {"1h": 5, "3h": 10, "24h": 245, "48h": 245}, "fc_peak": 4, "fc_run30": 0, "m15": 1, "ante": 0,
         "fc_hours": [4] * 6, "fc_labels": ["19", "20", "21", "22", "23", "00"]}
    pick = lambda r: next(x for x in ai.ladders(r, False, [])["산사태"] if x["rule"].startswith("누적"))  # noqa: E731
    assert pick(r)["gap"]["eta"]["at"] is None                     # 245 + 24 = 269
    r |= {"eta_hours": [4] * 6 + [10, 10], "eta_labels": r["fc_labels"] + ["내일 01", "내일 02"]}
    assert pick(r)["gap"]["eta"]["at"] == "내일 01"

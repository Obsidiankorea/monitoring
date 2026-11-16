"""보고서 창 — 재난상황보고서 서버(jaenan-weather)를 흉내 낸 가짜 응답으로: 만들기 · 받기, 토큰 가림, 시연 막힘, 한글 파일 이름."""
from urllib.parse import unquote

import httpx
import pytest
from fastapi.testclient import TestClient

from app import config, main, reports

TOK = "jaenan-secret-token-xyz"
HWP = b"HWP Document File fake"


def _fake(seen: list, status: int = 200, body: dict | None = None):
    def h(req: httpx.Request):
        seen.append(req)
        assert req.headers["Authorization"] == f"Bearer {TOK}"
        if req.url.path.startswith("/api/run/"):
            j = req.url.path.rsplit("/", 1)[1]
            n = f"20261116_135813_{j}_긴급상황보고_202611161300.hwp"
            return httpx.Response(status, json=body or {"ok": True, "names": [n], "files": [f"/files/{n}"], "took": 3.2})
        if req.url.path.startswith("/files/"):
            return httpx.Response(200, content=HWP)
        return httpx.Response(404)
    return httpx.Client(transport=httpx.MockTransport(h))


@pytest.fixture
def keys(monkeypatch):
    monkeypatch.setitem(config.KEYS, "JAENAN_TOKEN", TOK)
    monkeypatch.setitem(config.KEYS, "JAENAN_URL", "http://nas.test:8765")
    monkeypatch.setattr(config, "DEMO", False)


def test_run_fetches_file_and_strips_prefix(keys):
    seen = []
    name, data = reports.run("report", {"tm": "2026-11-16 13:00", "evil": "x"}, _fake(seen))
    assert data == HWP and name == "긴급상황보고_202611161300.hwp"                     # 서버가 붙인 앞머리를 뗀다
    assert seen[0].url.params["tm"] == "202611161300" and "evil" not in seen[0].url.params   # 등록부 옵션만, 꼴을 맞춰
    with pytest.raises(ValueError):
        reports.run("report", {"tm": "2026"}, _fake([]))
    with pytest.raises(ValueError):
        reports.run("heat", {}, _fake([]))                                            # 준비 중


def test_token_never_leaks(keys, monkeypatch):
    with pytest.raises(RuntimeError) as e:
        reports.run("weather", {}, _fake([], 500, {"ok": False, "error": f"boom token={TOK}"}))
    assert TOK not in str(e.value) and "***" in str(e.value)
    assert TOK not in str(reports.listing())

    def down(req):
        raise httpx.ConnectError(f"cannot reach http://x/?token={TOK}")
    with pytest.raises(RuntimeError) as e:
        reports.run("weather", {}, httpx.Client(transport=httpx.MockTransport(down)))
    assert TOK not in str(e.value)


def test_api_download_korean_name_and_tg(keys, monkeypatch):
    monkeypatch.setattr(reports, "run", lambda rid, opts: ("풍수해보고_202611161358.hwp", HWP))
    sent = []
    monkeypatch.setattr(reports, "send_tg", lambda name, data, cap="": sent.append(name))
    c = TestClient(main.app)
    lst = c.get("/api/reports").json()
    assert lst["ready"] and {r["id"] for r in lst["reports"]} >= {"weather", "daily", "nature", "report", "heat"}
    by = {r["id"]: r for r in lst["reports"]}
    assert by["heat"]["ready"] is False and by["heat"]["thumb"] is False and by["weather"]["thumb"] is True   # 썸네일이 없으면 자리표시
    r = c.post("/api/reports/run", json={"id": "nature", "tg": True})
    cd = r.headers["content-disposition"]
    assert r.status_code == 200 and r.content == HWP and r.headers["x-tg"] == "ok" and sent == ["풍수해보고_202611161358.hwp"]
    assert "filename*=UTF-8''" in cd and unquote(cd.split("UTF-8''")[1]) == "풍수해보고_202611161358.hwp" and cd.isascii()
    j = c.post("/api/reports/run", json={"id": "nature", "tg": True, "dl": False}).json()
    assert j == {"ok": True, "name": "풍수해보고_202611161358.hwp", "tg": "ok"}
    assert c.post("/api/reports/run", json={"id": "nature", "tg": False, "dl": False}).status_code == 400


def test_demo_does_not_make(keys, monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(reports, "run", lambda *a: pytest.fail("시연에서 만들면 안 된다"))
    c = TestClient(main.app)
    assert c.post("/api/reports/run", json={"id": "weather"}).status_code == 403
    assert c.get("/api/reports").json()["demo"] is True


def test_send_tg_masks_token(monkeypatch):
    monkeypatch.setitem(config.KEYS, "TELEGRAM_BOT_TOKEN", "123:tg-secret")
    monkeypatch.setitem(config.KEYS, "TELEGRAM_CHAT_ID", "-100")
    got = []

    def h(req):
        got.append(req)
        return httpx.Response(401)
    with pytest.raises(RuntimeError) as e:
        reports.send_tg("a.hwp", HWP, "c", httpx.Client(transport=httpx.MockTransport(h)))
    assert "tg-secret" not in str(e.value) and got[0].url.path.endswith("/sendDocument")


def test_options_validated_by_registry(keys):
    o = reports._opts(reports.BY_ID["report"], {"codes": ["R", "T", "ZZ"], "interval": "20", "forecast": False, "fc_max": "200", "evil": 1})
    assert o == {"codes": "R,T", "interval": "20", "forecast": "0", "fc_max": "200"}
    for bad in ({"fc_max": "201"}, {"interval": "15"}, {"codes": ["ZZ"]}, {"tm": "2026"}):
        with pytest.raises(ValueError):
            reports._opts(reports.BY_ID["report"], bad)
    assert reports._opts(reports.BY_ID["nature"], {"wrn": "호우,태풍", "tail": "(최종)", "stage": "x" * 99})["stage"] == "x" * 60
    assert all(o["kind"] in ("datetime", "int", "choice", "multi", "bool", "text") for r in reports.REG for o in r["opts"])


def _waitjaenan(state: dict):
    def h(req):
        if req.url.path.startswith("/api/run/"):
            assert req.url.params.get("wait1700") == "1"
            if not state["out"]:
                return httpx.Response(200, json={"ok": False, "waiting": True, "status": "통보문 11시 · 단기예보 11시"})
            return httpx.Response(200, json={"ok": True, "names": ["20261116_170501_weather_기상상황보고_202611161700.hwp"],
                                             "files": ["/files/x.hwp"]})
        return httpx.Response(200, content=HWP)
    return httpx.Client(transport=httpx.MockTransport(h))


@pytest.fixture
def waitdir(tmp_path, monkeypatch, keys):
    monkeypatch.setattr(reports, "WAIT_FILE", tmp_path / "reports_wait.json")
    monkeypatch.setattr(reports, "WAIT_DIR", tmp_path / "reports")
    return tmp_path


def test_wait_flow_not_yet_then_ready_with_tg(waitdir, monkeypatch):
    from datetime import datetime as D
    st, sent = {"out": False}, []
    monkeypatch.setitem(config.KEYS, "TELEGRAM_BOT_TOKEN", "1:t")
    monkeypatch.setitem(config.KEYS, "TELEGRAM_CHAT_ID", "-1")
    tg = httpx.Client(transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200)))
    reports.wait_set("weather", {"wicon": "text"}, True, now=D(2026, 11, 16, 16, 40))
    assert reports.wait_state()["weather"]["until"] == "2026-11-16T18:30:00" and reports.wait_any()
    assert reports.wait_tick(D(2026, 11, 16, 16, 41), _waitjaenan(st), tg) == 1
    w = reports.wait_state()["weather"]
    assert w["state"] == "waiting" and w["status"] == "통보문 11시 · 단기예보 11시" and not sent
    # 컨테이너가 다시 떠도 — 상태는 파일에서 이어진다
    assert reports._wload()["weather"]["opts"] == {"wicon": "text"}
    st["out"] = True
    reports.wait_tick(D(2026, 11, 16, 17, 6), _waitjaenan(st), tg)
    w = reports.wait_state()["weather"]
    assert w["state"] == "ready" and w["name"] == "기상상황보고_202611161700.hwp" and w["tg_st"] == "ok" and len(sent) == 1
    assert reports.wait_file("weather") == ("기상상황보고_202611161700.hwp", HWP) and not reports.wait_any()
    reports.wait_tick(D(2026, 11, 17, 17, 7), _waitjaenan(st), tg)                         # 하루 지나면 파일과 함께 지운다
    assert reports.wait_state() == {} and not list((waitdir / "reports").iterdir())


def test_wait_gives_up_after_cutoff_and_late_arm_runs_now(waitdir):
    from datetime import datetime as D
    st = {"out": False}
    reports.wait_set("weather", {}, False, now=D(2026, 11, 16, 17, 0))
    reports.wait_tick(D(2026, 11, 16, 17, 1), _waitjaenan(st))
    reports.wait_tick(D(2026, 11, 16, 18, 30), _waitjaenan(st))
    w = reports.wait_state()["weather"]
    assert w["state"] == "fail" and "18:30 까지" in w["why"] and "통보문 11시" in w["why"]
    reports.wait_set("weather", {}, False, now=D(2026, 11, 16, 19, 0))                     # 18:30 뒤 — 이미 나왔으니 바로 한 번
    assert reports.wait_state()["weather"]["until"] == "2026-11-16T19:10:00"
    st["out"] = True
    reports.wait_tick(D(2026, 11, 16, 19, 0), _waitjaenan(st))
    assert reports.wait_state()["weather"]["state"] == "ready"
    with pytest.raises(ValueError):
        reports.wait_set("daily", {}, False)                                               # 등록부에서 안 켠 보고서


def test_wait_api_demo_and_cancel(waitdir, monkeypatch):
    c = TestClient(main.app)
    monkeypatch.setattr(reports, "wait_tick", lambda *a, **k: 0)
    assert c.post("/api/reports/wait", json={"id": "weather", "tg": True}).json()["wait"]["weather"]["state"] == "waiting"
    assert c.get("/api/reports/wait/file?id=weather").status_code == 404
    assert c.delete("/api/reports/wait?id=weather").json()["wait"] == {}
    monkeypatch.setattr(config, "DEMO", True)
    assert c.post("/api/reports/wait", json={"id": "weather"}).status_code == 403
    assert c.get("/api/reports").json()["reports"][0]["wait"] is True

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
    monkeypatch.setattr(reports, "fetch", lambda rid, opts, picked=None, extra=None, meta=None: [("풍수해보고_202611161358.hwp", HWP)])
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
    assert j == {"ok": True, "name": "풍수해보고_202611161358.hwp", "tg": "ok", "basis": []}
    assert c.post("/api/reports/run", json={"id": "nature", "tg": False, "dl": False}).status_code == 400


def test_demo_live_weather_else_sample(keys, monkeypatch, tmp_path):
    """시연 — 기상상황보고는 지금 시각으로 실제로(안 되면 샘플), 나머지는 샘플만(만들지 않는다). 텔레그램은 보내지 않는다."""
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "SNAPS", tmp_path)
    (tmp_path / "_reports").mkdir()
    (tmp_path / "_reports" / "weather.hwp").write_bytes(b"SAMPLE-W")
    (tmp_path / "_reports" / "temp.png").write_bytes(b"SAMPLE-T")
    called = []
    monkeypatch.setattr(reports, "send_tg", lambda *a, **k: pytest.fail("시연에서 텔레그램을 보내면 안 된다"))
    def fake(rid, *a, **k):
        called.append(rid)
        if called.count(rid) > 1:
            raise RuntimeError("서버 안 됨")
        return [("기상상황보고_202611180900.hwp", HWP)]
    monkeypatch.setattr(reports, "fetch", fake)
    c = TestClient(main.app)
    r = c.post("/api/reports/run", json={"id": "weather", "tg": True})
    assert r.content == HWP and r.headers["x-tg"] == "off"                                          # 지금 시각으로
    r = c.post("/api/reports/run", json={"id": "weather"})
    assert r.content == b"SAMPLE-W" and "샘플" in unquote(r.headers["content-disposition"])          # 안 되면 샘플
    r = c.post("/api/reports/run", json={"id": "temp"})
    assert r.content == b"SAMPLE-T" and called == ["weather", "weather"]                            # 나머지는 만들지 않는다
    assert c.post("/api/reports/run", json={"id": "nature"}).status_code == 404                     # 샘플 없음
    rs = {x["id"]: x for x in c.get("/api/reports").json()["reports"]}
    assert rs["temp"]["sample"] and not rs["nature"]["sample"] and rs["weather"]["live"]
    assert set(c.get("/api/reports/phrases").json()) == {"유의사항", "조치계획"}                             # 시연 — 받아 둔 문구 후보(작성 창이 열린다)


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


PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 20


def test_logos_proxy_checks_and_masks(keys, monkeypatch):
    got = []

    def h(req):
        got.append(req)
        assert req.headers["Authorization"] == f"Bearer {TOK}"
        if req.url.path == "/api/logos":
            if req.method == "POST":
                return httpx.Response(200, json={"ok": True, "name": req.url.params["name"]})
            return httpx.Response(200, json={"ok": True, "logos": [{"name": "도민과 함께 경남 대도약", "user": False}], "selected": "도민과 함께 경남 대도약"})
        if req.url.path == "/api/logos/selected":
            return httpx.Response(400, json={"ok": False, "error": f"없는 로고입니다 {TOK}"})
        return httpx.Response(200, content=PNG)
    c = httpx.Client(transport=httpx.MockTransport(h))
    assert reports.logos(c)["selected"] == "도민과 함께 경남 대도약"
    assert reports.logo_upload("2027 로고", PNG, c) == "2027 로고" and got[-1].content == PNG
    with pytest.raises(ValueError):
        reports.logo_upload("x", b"GIF89a....", c)                                      # 종류 — jaenan 까지 안 간다
    with pytest.raises(ValueError):
        reports.logo_upload("x", PNG + b"0" * reports.LOGO_MAX, c)
    with pytest.raises(ValueError) as e:
        reports.logo_select("없음", c)
    assert TOK not in str(e.value)
    assert reports.logo_img("x", c) == PNG


def test_logos_api_demo_and_upload(keys, monkeypatch):
    c = TestClient(main.app)
    monkeypatch.setattr(reports, "logo_upload", lambda name, data: f"{name}:{len(data)}")
    assert c.post("/api/reports/logos?name=새 로고", content=PNG).json() == {"name": f"새 로고:{len(PNG)}"}
    monkeypatch.setattr(config, "DEMO", True)
    assert c.get("/api/reports/logos").status_code == 403 and c.post("/api/reports/logos", content=PNG).status_code == 403


def test_meeting_posts_picked_items_and_validates(keys):
    seen = []
    files = reports.fetch("meeting", {"kinds": ["호우", "폭염", "눈"], "title": "x" * 99}, _fake(seen),
                          picked={"중점유의사항": [{"text": " 가 **나** ", "subs": ["- 다", ""]}, {"text": ""}, "bad"],
                                  "조치계획": [{"text": "라"}] * 99, "evil": [{"text": "x"}]})
    req = seen[0]
    assert req.method == "POST" and files[0][1] == HWP
    assert req.url.params["kinds"] == "호우,폭염" and req.url.params["title"] == "x" * 60
    import json as _j
    b = _j.loads(req.content)
    assert b["중점유의사항"] == [{"text": "가 **나**", "subs": ["- 다"]}] and len(b["조치계획"]) == reports.ITEM_MAX and "evil" not in b
    by = {r["id"]: r for r in reports.listing()["reports"]}
    assert by["meeting"]["compose"] == "meeting" and by["meeting"]["thumb"] and by["nature"]["compose"] == ""


def _multi(seen: list):
    def h(req):
        seen.append(req)
        if req.url.path.startswith("/api/run/"):
            ns = ["20261117_010101_combo_combo_1.png", "20261117_010101_combo_combo_2.png"]
            return httpx.Response(200, json={"ok": True, "names": ns, "files": [f"/files/{n}" for n in ns]})
        return httpx.Response(200, content=PNG + req.url.path.encode())
    return httpx.Client(transport=httpx.MockTransport(h))


def test_picture_jobs_fetch_all_files_zip_and_tg_each(keys, monkeypatch):
    files = reports.fetch("combo", {"pages": "2", "theme": "dark"}, _multi(seen := []))
    assert [n for n, _ in files] == ["combo_1.png", "combo_2.png"] and seen[0].method == "GET"
    assert dict(seen[0].url.params) == {"pages": "2", "theme": "dark"}
    with pytest.raises(ValueError):
        reports.fetch("combo", {"theme": "x"}, _multi([]))
    import io
    import zipfile
    name, data = reports.bundle(files, reports.BY_ID["combo"])
    assert name.startswith("강수현황 종합_") and name.endswith(".zip")
    assert zipfile.ZipFile(io.BytesIO(data)).namelist() == ["combo_1.png", "combo_2.png"]
    assert reports.bundle(files[:1]) == files[0]                                          # 하나면 그대로
    sent = []
    monkeypatch.setattr(reports, "fetch", lambda rid, opts, picked=None, extra=None, meta=None: files)
    monkeypatch.setattr(reports, "send_tg", lambda n, d, cap="": sent.append((n, cap)))
    r = TestClient(main.app).post("/api/reports/run", json={"id": "combo", "tg": True})
    assert r.headers["content-type"] == "application/zip" and r.headers["x-tg"] == "ok"
    assert [n for n, _ in sent] == ["combo_1.png", "combo_2.png"] and sent[0][1] and sent[1][1] == ""   # 설명은 첫 장에만


def test_send_tg_picks_method_by_type(monkeypatch):
    monkeypatch.setitem(config.KEYS, "TELEGRAM_BOT_TOKEN", "123:tg-secret")
    monkeypatch.setitem(config.KEYS, "TELEGRAM_CHAT_ID", "-100")
    got = []
    c = httpx.Client(transport=httpx.MockTransport(lambda r: got.append(r) or httpx.Response(200)))
    for n in ("a.png", "b.gif", "c.hwp", "d.zip"):
        reports.send_tg(n, b"x", "", c)
    assert [r.url.path.rsplit("/", 1)[1] for r in got] == ["sendPhoto", "sendAnimation", "sendDocument", "sendDocument"]
    assert b'name="photo"' in got[0].content and b'name="animation"' in got[1].content


def test_phrases_proxy_cached_and_filtered(keys, monkeypatch):
    monkeypatch.setattr(reports, "_PH", {"t": 0.0, "v": None})
    calls = []

    def h(req):
        calls.append(req)
        assert req.url.path == "/api/phrases/meeting"
        return httpx.Response(200, json={"ok": True, "유의사항": [{"text": "가", "kinds": ["호우", "눈"], "subs": [], "src": "u"}, {"x": 1}],
                                         "조치계획": [{"text": "나", "kinds": ["폭염"], "subs": ["- 다"]}]})
    c = httpx.Client(transport=httpx.MockTransport(h))
    v = reports.phrases(c)
    assert v == {"유의사항": [{"text": "가", "kinds": ["호우"], "subs": []}], "조치계획": [{"text": "나", "kinds": ["폭염"], "subs": ["- 다"]}]}
    assert reports.phrases(c) == v and len(calls) == 1                                    # 5분 캐시
    monkeypatch.setattr(reports, "phrases", lambda: v)
    assert TestClient(main.app).get("/api/reports/phrases").json() == v


def test_meeting_sends_river_levels_in_column_order(keys, monkeypatch):
    from app import river
    rows = [{"kind": "wl", "name": "합천군(적포교)", "v": 9.51, "stage": 0, "t": "202611170940"},
            {"kind": "wl", "name": "하동군(읍내리)", "v": 11.2, "stage": 1, "t": "202611170950"},
            {"kind": "wl", "name": "밀양시(남포동)", "v": 3.0, "stage": 0, "t": "202611170940", "stale": True}]
    monkeypatch.setattr(river, "status", lambda: {"rows": rows})
    got = reports.river_rows(reports.BY_ID["meeting"]["river"])
    assert len(got) == 10 and got[0]["v"] is None and got[0]["st"] == "-"            # 성하리 — 지도에 없으면 '-'
    assert got[1] == {"name": "적포교", "v": 9.51, "st": "정상", "t": "202611170940", "late": False, "thr": []}
    assert got[2]["v"] is None and got[2]["late"] and got[2]["t"] == "202611170940"   # 늦은 값(stale)은 안 쓰고 각주에 시각
    assert got[9]["st"] == "관심"
    import json as _j
    from app import meeting
    monkeypatch.setattr(meeting, "extras", lambda kinds, on: ({"과거사례": [{"text": "x", "subs": []}]}, [{"name": "조위", "at": "t"}]))
    meta = {}
    reports.fetch("meeting", {}, _fake(seen := []), picked={}, meta=meta)
    b = _j.loads(seen[0].content)
    assert b["수위"][1]["v"] == 9.51 and b["과거사례"][0]["text"] == "x"
    assert meta["basis"] == [{"name": "하천 수위(홍수통제소)", "at": "2026-11-17 09:50 관측"}, {"name": "조위", "at": "t"}]


def test_basis_passed_to_screen(keys, monkeypatch):
    """jaenan 이 실은 기상청 자료 시각 → 받기는 X-Basis 머리(퍼센트 인코딩 JSON), 텔레그램만은 JSON basis."""
    import json as _j

    def fake(rid, opts, picked=None, extra=None, meta=None):
        meta["basis"] = [{"name": "통보문", "at": "11.17. 05:00 발표"}]
        return [("a.hwp", HWP)]
    monkeypatch.setattr(reports, "fetch", fake)
    monkeypatch.setattr(reports, "send_tg", lambda *a, **k: None)
    c = TestClient(main.app)
    r = c.post("/api/reports/run", json={"id": "nature"})
    assert _j.loads(unquote(r.headers["x-basis"])) == [{"name": "통보문", "at": "11.17. 05:00 발표"}] and r.headers["x-basis"].isascii()
    assert c.post("/api/reports/run", json={"id": "nature", "tg": True, "dl": False}).json()["basis"][0]["name"] == "통보문"


def test_fetch_basis_from_jaenan(keys):
    def h(req):
        if req.url.path.startswith("/api/run/"):
            return httpx.Response(200, json={"ok": True, "names": ["x.hwp"], "files": ["/files/x.hwp"], "basis": [{"name": "특보", "at": "a"}, "bad"]})
        return httpx.Response(200, content=HWP)
    meta = {}
    reports.fetch("nature", {}, httpx.Client(transport=httpx.MockTransport(h)), meta=meta)
    assert meta["basis"] == [{"name": "특보", "at": "a"}]


def test_jaenan_kma_failures_shown_first(keys):
    """기상청 조회가 끝내 실패한 자료(jaenan warn)는 자료 기준 창 맨 위에 경고로 — 보고서 칸이 비었을 수 있다"""
    def h(req):
        if req.url.path.startswith("/api/run/"):
            return httpx.Response(200, json={"ok": True, "names": ["x.hwp"], "files": ["/files/x.hwp"], "basis": [{"name": "특보", "at": "a"}],
                                             "warn": [{"label": "기상특보", "fail": 18, "total": 207}, {"label": "파고", "fail": 1, "total": 1}, "bad"]})
        return httpx.Response(200, content=HWP)
    meta = {}
    reports.fetch("daily", {}, httpx.Client(transport=httpx.MockTransport(h)), meta=meta)
    assert meta["warn"] == "기상특보 18/207번 · 파고 1/1번(못 받음)"
    assert meta["basis"][0]["warn"] and meta["basis"][1] == {"name": "특보", "at": "a"}

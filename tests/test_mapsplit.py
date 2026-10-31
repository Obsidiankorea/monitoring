import re

from fastapi.testclient import TestClient

from app import main


def test_map_page_gets_a_version_and_every_file_it_names_is_served():
    c = TestClient(main.app)
    r = c.get("/map.html?x=1")
    assert r.status_code == 200 and "{{V}}" not in r.text
    assert "no-cache" in r.headers["cache-control"]                       # 쪼갠 파일을 가리키는 쪽은 늘 새로
    urls = re.findall(r'(?:src|href)="((?:js|css)/[^"]+\?v=[0-9a-f]+)"', r.text)
    assert len(urls) >= 12                                                 # css 1 + js 11
    assert len({u.split("?v=")[1] for u in urls}) == 1                     # 모두 같은 버전 값
    for u in urls:
        assert c.get("/" + u).status_code == 200, u


def test_check_map_script_passes():
    import importlib.util
    import pathlib
    p = pathlib.Path(__file__).resolve().parent.parent / "tools" / "check_map.py"
    spec = importlib.util.spec_from_file_location("check_map", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert m.main() == 0

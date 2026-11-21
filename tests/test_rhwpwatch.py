from app.rhwpwatch import decide

R = {"tag_name": "v0.9.2", "name": "rhwp v0.9.2", "html_url": "https://github.com/edwardkim/rhwp/releases/tag/v0.9.2"}


def test_new_release_told_once():
    assert "v0.9.2" in decide(R, "v0.9.1", "")
    assert decide(R, "v0.9.1", "v0.9.2") is None          # 이미 알림
    assert decide(R, "v0.9.2", "") is None                # 이미 그 판
    assert "판 모름" in decide(R, "", "")                  # 보고서 서버가 안 답해도 알림

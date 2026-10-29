from app import llm


def test_claude_env_token_file(tmp_path, monkeypatch):
    """config/claude/token.txt — 값만 한 줄(BOM 괜찮음) 또는 KEY=값. API 키가 있으면 빼서 구독으로 나가게."""
    f = tmp_path / "token.txt"
    monkeypatch.setattr(llm, "TOKEN_FILE", f)
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    assert "CLAUDE_CODE_OAUTH_TOKEN" not in llm._claude_env()
    f.write_text("﻿tok-1\n", "utf-8")
    env = llm._claude_env()
    assert env["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-1" and "ANTHROPIC_API_KEY" not in env
    f.write_text("CLAUDE_CODE_OAUTH_TOKEN = tok-2\n", "utf-8")
    assert llm._claude_env()["CLAUDE_CODE_OAUTH_TOKEN"] == "tok-2"

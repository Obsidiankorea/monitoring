"""AI 상황판단의 자유 질문 — LLM 백엔드를 고른다(GN_AI). 숫자 계산 · 기준 대조는 LLM 에 맡기지 않는다(app/ai.py).

  GN_AI 없음      — 끔. 예상 질문(규칙)만 답한다
  GN_AI=openai    — OpenAI 호환 /v1/chat/completions. NAS Hermes(API 서버) 등. GN_AI_URL · GN_AI_KEY · GN_AI_MODEL
  GN_AI=claude-cli — `claude -p`(Claude Code, 구독 사용량). 느리다(수십 초). 도구를 다 막고(읽기 · 쓰기 · 웹 없이)
                     받은 맥락만으로 답하게 한다. PC 는 깔린 claude 의 로그인을, NAS(도커)는 장기 토큰을 쓴다:
                     `claude setup-token` 으로 받은 값을 config/claude/token.txt 에 — 부를 때마다 읽으니 넣으면 바로 켜진다.
                     GN_AI_MODEL 이 있으면 --model 로 넘긴다.
⚠️ Max · Pro 구독은 본인 사용 전제다 — 여러 사람이 쓰는 업무용이면 API 키(GN_AI=openai 호환 또는 Console 키)로.
⚠️ 키 · 토큰은 config/ 파일 또는 환경변수로만. 로그 · 화면에 찍지 않는다.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import httpx

from . import config

TIMEOUT = 150
_DENY = "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Task Agent"
TOKEN_FILE = config.ROOT / "config" / "claude" / "token.txt"


def _claude_env() -> dict:
    """claude 에 넘길 환경 — 토큰 파일이 있으면 CLAUDE_CODE_OAUTH_TOKEN 으로(값만 한 줄, 또는 KEY=값)."""
    env = dict(os.environ)
    try:
        t = TOKEN_FILE.read_text("utf-8-sig").strip()
    except OSError:
        return env
    t = t.partition("=")[2].strip() if t.startswith("CLAUDE_CODE_OAUTH_TOKEN") else t
    if t:
        env["CLAUDE_CODE_OAUTH_TOKEN"] = t
        env.pop("ANTHROPIC_API_KEY", None)           # 있으면 이쪽이 이겨 API 요금으로 나간다
    return env


def configured() -> str | None:
    """GN_AI 가 있으면 그것, 없어도 토큰 파일이 있으면 claude-cli(행정 PC 처럼 환경변수를 못 쓰는 곳)."""
    m = (os.environ.get("GN_AI") or "").strip().lower()
    if m in ("openai", "claude-cli"):
        return m
    try:
        return "claude-cli" if TOKEN_FILE.read_text("utf-8-sig").strip() else None
    except OSError:
        return None


def mode() -> str | None:
    return configured()


def ask(system: str, user: str) -> str:
    m = mode()
    if m == "openai":
        url = os.environ.get("GN_AI_URL", "").rstrip("/")
        key = os.environ.get("GN_AI_KEY", "")
        if not url:
            raise RuntimeError("GN_AI_URL 이 없다")
        r = httpx.post(f"{url}/v1/chat/completions", timeout=TIMEOUT,
                       headers={"Authorization": f"Bearer {key}"} if key else {},
                       json={"model": os.environ.get("GN_AI_MODEL", "default"),
                             "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
    if m == "claude-cli":
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("claude 명령이 없다")
        model = os.environ.get("GN_AI_MODEL")
        p = subprocess.run([exe, "-p", "--output-format", "text", "--no-session-persistence",
                            *(["--model", model] if model else []),
                            "--append-system-prompt", system, "--disallowedTools", _DENY],
                           input=user, capture_output=True, text=True, encoding="utf-8", timeout=TIMEOUT,
                           cwd=str(config.ROOT / "data"), env=_claude_env())
        if p.returncode != 0:
            msg = (p.stderr or p.stdout or "claude 실패")[-300:]
            if any(w in msg.lower() for w in ("auth", "log in", "logged in", "/login", "401")):
                msg = f"Claude 로그인이 없거나 만료됐다 — `claude setup-token` 값을 {TOKEN_FILE.relative_to(config.ROOT)} 에. ({msg.strip()[:120]})"
            raise RuntimeError(msg)
        return p.stdout.strip()
    raise RuntimeError("LLM 이 꺼져 있다(GN_AI)")

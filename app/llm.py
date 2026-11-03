"""AI 상황판단의 자유 질문 — LLM 백엔드를 고른다(GN_AI). 숫자 계산 · 기준 대조는 LLM 에 맡기지 않는다(app/ai.py).

  GN_AI 없음      — 끔. 예상 질문(규칙)만 답한다
  GN_AI=openai    — OpenAI 호환 /v1/chat/completions. NAS Hermes(API 서버) 등. GN_AI_URL · GN_AI_KEY · GN_AI_MODEL
  GN_AI=claude-cli — `claude -p`(Claude Code, 구독 사용량). 느리다(수십 초). 도구를 다 막고(읽기 · 쓰기 · 웹 없이)
                     받은 맥락만으로 답하게 한다. PC 는 깔린 claude 의 로그인을, NAS(도커)는 장기 토큰을 쓴다:
                     `claude setup-token` 으로 받은 값을 config/claude/token.txt 에 — 부를 때마다 읽으니 넣으면 바로 켜진다.
                     GN_AI_MODEL 이 있으면 --model 로 넘긴다. 환경변수를 못 쓰는 PC 는 config/claude/model.txt 한 줄(예: haiku).
  설정 › AI 답변(db 'ai_llm')이 위를 덮는다 — 자동(위 환경변수) · 끔 · Claude · 로컬 · 기타.
  로컬 = 이 PC 의 llama.cpp llama-server(Vulkan, OpenAI 호환) — 주소 · 모델만 설정에, 키 없음.
  기타 = GN_AI_URL · GN_AI_KEY · GN_AI_MODEL(키는 설정 DB 에 두지 않는다).
⚠️ Max · Pro 구독은 본인 사용 전제다 — 여러 사람이 쓰는 업무용이면 API 키(GN_AI=openai 호환 또는 Console 키)로.
⚠️ 키 · 토큰은 config/ 파일 또는 환경변수로만. 로그 · 화면에 찍지 않는다.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import httpx

from . import config, db

TIMEOUT = 150
MODES = ("auto", "off", "claude-cli", "local", "openai")
LOCAL_URL = "http://127.0.0.1:8080"             # llama-server 기본 포트
LLAMA_DIR = Path(os.environ.get("GN_LLAMA_DIR") or Path.home() / "llm")   # vulkan/llama-server.exe · qwen3-8b.gguf
_PROC: subprocess.Popen | None = None
_DENY = "Bash Edit Write Read Glob Grep WebFetch WebSearch NotebookEdit Task Agent"
TOKEN_FILE = config.ROOT / "config" / "claude" / "token.txt"
MODEL_FILE = config.ROOT / "config" / "claude" / "model.txt"


def _model() -> str | None:
    """GN_AI_MODEL, 없으면 config/claude/model.txt(부를 때마다 읽는다 — 바꾸면 바로)."""
    m = (os.environ.get("GN_AI_MODEL") or "").strip()
    if m:
        return m
    try:
        return MODEL_FILE.read_text("utf-8-sig").strip() or None
    except OSError:
        return None


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


def _claude_exe() -> str | None:
    """PATH 의 claude, 없으면 설치기가 두는 자리(~/.local/bin) — 서버가 설치 전에 켜져 PATH 가 옛것이어도 찾는다."""
    exe = shutil.which("claude")
    if exe:
        return exe
    for c in (Path.home() / ".local" / "bin" / "claude.exe", Path.home() / ".local" / "bin" / "claude"):
        if c.is_file():
            return str(c)
    return None


def configured() -> str | None:
    """GN_AI 가 있으면 그것, 없어도 토큰 파일이 있으면 claude-cli(행정 PC 처럼 환경변수를 못 쓰는 곳)."""
    m = (os.environ.get("GN_AI") or "").strip().lower()
    if m in ("openai", "claude-cli"):
        return m
    try:
        return "claude-cli" if TOKEN_FILE.read_text("utf-8-sig").strip() else None
    except OSError:
        return None


def setting() -> dict:
    """설정 › AI 답변 — {mode, url, model}. 없거나 이상하면 자동."""
    s = db.get_setting("ai_llm", {})
    s = s if isinstance(s, dict) else {}
    return {"mode": s.get("mode") if s.get("mode") in MODES else "auto",
            "url": (s.get("url") or "").strip(), "model": (s.get("model") or "").strip()}


def put_setting(body: dict) -> dict:
    m = body.get("mode") or "auto"
    if m not in MODES:
        raise ValueError(f"모르는 방식: {m}")
    url = str(body.get("url") or "").strip().rstrip("/")
    if url and not re.match(r"^https?://", url):
        raise ValueError("주소는 http:// 또는 https:// 로")
    db.put_setting("ai_llm", {"mode": m, "url": url, "model": str(body.get("model") or "").strip()})
    return setting()


def mode() -> str | None:
    m = setting()["mode"]
    return None if m == "off" else configured() if m == "auto" else m


def _openai(url: str, key: str, model: str, system: str, user: str) -> str:
    r = httpx.post(f"{url.rstrip('/')}/v1/chat/completions", timeout=TIMEOUT,
                   headers={"Authorization": f"Bearer {key}"} if key else {},
                   json={"model": model or "default",
                         "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]})
    r.raise_for_status()
    out = r.json()["choices"][0]["message"].get("content") or ""
    out = re.sub(r"<think>.*?</think>", "", out, flags=re.S).strip()    # Qwen3 생각 줄은 빼고
    return re.sub(r"\A```\w*\n(.*)\n```\Z", r"\1", out, flags=re.S)       # 답 전체를 감싼 코드 블록은 벗긴다


def ping() -> dict:
    """로컬 서버가 떠 있는지 — /v1/models(2초). 로컬이 아니면 묻지 않는다."""
    s = setting()
    if s["mode"] != "local":
        return {}
    url = s["url"] or LOCAL_URL
    try:
        r = httpx.get(f"{url}/v1/models", timeout=2)
        r.raise_for_status()
        return {"up": True, "models": [re.split(r"[\\/]", m.get("id") or "")[-1] for m in r.json().get("data", [])][:5]}
    except Exception as e:                      # noqa: BLE001
        return {"up": False, "err": f"{type(e).__name__}"}


def _llama() -> tuple[Path, Path] | None:
    """이 PC 의 llama-server 와 모델 — 설정 모델이 .gguf 이름이면 그것, 아니면 qwen3-8b.gguf."""
    exe = next((p for p in (LLAMA_DIR / "vulkan" / "llama-server.exe", LLAMA_DIR / "vulkan" / "llama-server") if p.is_file()), None)
    name = setting()["model"]
    gguf = LLAMA_DIR / (name if name.endswith(".gguf") else "qwen3-8b.gguf")
    return (exe, gguf) if exe and gguf.is_file() else None


def start_local(wait: float = 0) -> dict:
    """로컬 서버가 꺼져 있으면 켠다(이 PC 주소일 때만). wait 초 동안 뜨기를 기다린다 — 모델 올리기 10~20초."""
    global _PROC
    url = setting()["url"] or LOCAL_URL
    if ping().get("up"):
        return {"started": False, "up": True}
    port = re.match(r"^https?://(?:127\.0\.0\.1|localhost)(?::(\d+))?", url)
    found = _llama()
    if not port or not found:
        raise RuntimeError(f"여기서 켤 수 없다 — {'이 PC 주소가 아니다' if not port else f'{LLAMA_DIR} 에 vulkan/llama-server 와 모델(.gguf)이 없다'}")
    if not (_PROC and _PROC.poll() is None):
        log = open(config.ROOT / "data" / "llama-server.log", "ab")
        _PROC = subprocess.Popen([str(found[0]), "-m", str(found[1]), "-ngl", "99", "-c", "16384", "--jinja",
                                  "--host", "127.0.0.1", "--port", port.group(1) or "80"],
                                 stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    import time
    end = time.monotonic() + wait
    while time.monotonic() < end:
        if _PROC.poll() is not None:
            raise RuntimeError("llama-server 가 바로 꺼졌다 — data/llama-server.log 를 본다")
        if ping().get("up"):
            return {"started": True, "up": True}
        time.sleep(1)
    return {"started": True, "up": ping().get("up", False)}


def ask(system: str, user: str) -> str:
    m = mode()
    if m == "local":
        s = setting()
        try:
            return _openai(s["url"] or LOCAL_URL, "", s["model"], system, user)
        except httpx.ConnectError:
            if not start_local(wait=60)["up"]:       # 꺼져 있으면 켜고 한 번 더
                raise RuntimeError("로컬 LLM 서버를 켰지만 1분 안에 뜨지 않았다 — 잠시 뒤 다시 묻는다") from None
            return _openai(s["url"] or LOCAL_URL, "", s["model"], system, user)
    if m == "openai":
        url = os.environ.get("GN_AI_URL", "")
        if not url:
            raise RuntimeError("GN_AI_URL 이 없다")
        return _openai(url, os.environ.get("GN_AI_KEY", ""), os.environ.get("GN_AI_MODEL", ""), system, user)
    if m == "claude-cli":
        exe = _claude_exe()
        if not exe:
            raise RuntimeError("claude 명령이 없다 — Claude Code 를 설치했으면 PATH 에 넣거나 서버를 다시 켠다")
        model = _model()
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

#!/bin/bash
# 경남 기상 대시보드 — 한 번에 실행
#
# 터미널:  ./run.command
# 파인더:  더블클릭
#
# 처음 실행하면 가상환경을 만들고 의존성을 받는다(1~2분).
# 두 번째부터는 바로 뜬다.

set -u
cd "$(dirname "$0")" || exit 1

PORT="${PORT:-8000}"
HOST="${HOST:-127.0.0.1}"
PY=".venv/bin/python"

say() { printf '\033[36m▸\033[0m %s\n' "$*"; }
err() { printf '\033[31m✕\033[0m %s\n' "$*" >&2; }

# ── 1. 가상환경 ────────────────────────────────────────────────────
if [ ! -x "$PY" ]; then
  say "가상환경을 만듭니다"
  python3 -m venv .venv || { err "python3 가 없습니다. Xcode 명령줄 도구를 설치하세요: xcode-select --install"; exit 1; }
fi

# requirements.txt 가 더 새로우면 다시 설치한다
if [ ! -f .venv/.installed ] || [ requirements.txt -nt .venv/.installed ]; then
  say "의존성을 설치합니다 (처음 한 번, 1~2분)"
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -r requirements.txt || { err "설치 실패"; exit 1; }
  touch .venv/.installed
fi

# ── 2. 기상청 키 ───────────────────────────────────────────────────
# ⚠️ 키는 저장소에 없다(.gitignore). 없으면 인수인계 묶음에서 가져온다.
if [ ! -f config/api_keys.txt ]; then
  if [ -f handoff-mac/config/api_keys.txt ]; then
    mkdir -p config && cp handoff-mac/config/api_keys.txt config/
    say "키 파일을 config/ 로 복사했습니다"
  else
    err "config/api_keys.txt 가 없습니다. ORG_API_KEY 를 넣은 파일을 만드세요."
    exit 1
  fi
fi

# ── 3. 포트 ────────────────────────────────────────────────────────
# 이미 쓰고 있으면 다음 빈 포트를 찾는다. 수집기가 둘 돌면 API 호출이 두 배가 된다.
while lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; do
  say "포트 $PORT 은 이미 사용 중입니다"
  PORT=$((PORT + 1))
done

URL="http://localhost:$PORT"
say "서버를 띄웁니다 → $URL"
say "처음에는 자료를 받느라 화면이 채워지기까지 10~40초 걸립니다"
echo

# 서버가 응답하면 브라우저를 연다
( for _ in $(seq 1 60); do
    sleep 1
    curl -sf -o /dev/null "$URL/api/status" && { open "$URL"; break; }
  done ) &

PORT="$PORT" HOST="$HOST" exec "$PY" -m app.main

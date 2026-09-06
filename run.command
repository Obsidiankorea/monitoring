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

# ── 1. 업데이트 ────────────────────────────────────────────────────
# 저장소를 내려받아 쓰는 기기에서만 동작한다. 새 버전이 있으면 물어본다.
#
# ⚠️ 10초 안에 답이 없으면 **아니오**다. 상주 서버라 부팅하며 스스로 뜨는데,
#    아무도 없는 새벽에 물음표에 걸려 화면이 안 뜨면 안 된다.
# ⚠️ 받기가 실패해도 멈추지 않는다. 지금 버전으로라도 뜨는 게 낫다.
# ⚠️ 의존성 설치보다 **먼저** 한다. requirements.txt 가 함께 바뀔 수 있어서,
#    받은 뒤에 설치해야 새 목록이 반영된다.
if command -v git >/dev/null && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  say "새 버전이 있는지 확인합니다..."
  # 인터넷이 막힌 곳에서 오래 매달리지 않게 — 8초간 느리면 포기한다
  if GIT_TERMINAL_PROMPT=0 GIT_HTTP_LOW_SPEED_LIMIT=1000 GIT_HTTP_LOW_SPEED_TIME=8      git fetch --quiet origin 2>/dev/null; then
    behind=$(git rev-list --count HEAD..@{u} 2>/dev/null || echo 0)
    if [ "${behind:-0}" -gt 0 ]; then
      echo
      echo "  ── 새 버전 ${behind}개 ──────────────────────────────"
      git --no-pager log --format='   - %s' -5 HEAD..@{u}
      echo "  ────────────────────────────────────────────────"
      echo
      printf '  지금 받을까요? (y/N, 10초 뒤 자동으로 N) '
      ans=""
      read -r -t 10 ans || true
      echo
      case "${ans:-}" in
        [Yy]*)
          if git pull --ff-only; then say "받았습니다"
          else
            err "받지 못했습니다. 이 기기에서 고친 파일이 새 버전과 겹칠 수 있습니다."
            err "지금 버전 그대로 실행합니다."
            sleep 3
          fi ;;
        *) say "받지 않고 실행합니다" ;;
      esac
    else
      say "최신입니다"
    fi
  else
    say "확인하지 못했습니다(인터넷이 막혔을 수 있습니다). 그대로 실행합니다."
  fi
fi

# ── 2. 가상환경 ────────────────────────────────────────────────────
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

# 서버가 응답하면 **웹앱 창**으로 연다 — 주소창·탭 없는 창(--app).
# 창 아이콘은 화면의 파비콘(비바람)을 그대로 쓴다.
# 크롬이 없으면 기본 브라우저로 그냥 연다.
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
[ -x "$CHROME" ] || CHROME=""
( for _ in $(seq 1 90); do
    sleep 1
    if curl -sf -o /dev/null "$URL/api/status"; then
      if [ -n "$CHROME" ]; then
        "$CHROME" --app="$URL" --window-size=1600,900 >/dev/null 2>&1 &
      else
        open "$URL"
      fi
      break
    fi
  done ) &

# 화면에서 [업데이트]로 새 코드를 받으면 서버가 종료 코드 42로 스스로 끝난다.
# 그때만 다시 띄운다. 다른 코드로 끝나면(닫기·오류) 그대로 멈춘다 —
# 오류로 죽는 서버를 무한히 되살리면 무엇이 잘못됐는지 알 수가 없다.
while true; do
  PORT="$PORT" HOST="$HOST" "$PY" -m app.main
  code=$?
  [ "$code" = "42" ] || exit "$code"
  echo
  echo "[*] 업데이트를 반영해 다시 띄웁니다"
  echo
done

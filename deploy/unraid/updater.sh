#!/bin/bash
# 서버 갱신 대행 — 언레이드 예약 작업이 1분마다 돌린다(/boot/config/plugins/dynamix/gn-monitor.cron).
#
#   화면(설정 › 업데이트 › 서버)이 state/update/request 를 두면 → deploy.sh 로 갱신
#   10분마다(또는 state/update/check 가 있으면) GitHub 를 보고 → state/update/status.json
#
# 컨테이너는 도커를 못 만진다(도커 권한을 주지 않는다) — 파일로 부탁만 하고, 갱신은 언레이드가 한다.
# 자동 갱신은 하지 않는다 — 새 판이 있으면 '새 판 있음'만 적는다(발표 · 관제 중에 저절로 재시작하지 않게).
# 설치(한 번): bash /mnt/user/appdata/gn-monitor/repo/deploy/unraid/updater.sh --install
set -uo pipefail
D=/mnt/user/appdata/gn-monitor
U=$D/state/update
R=$D/repo
# ⚠️ update_cron 은 dynamix 폴더와 '설치된 플러그인' 폴더의 *.cron 만 모은다 — 따로 만든 폴더는 무시한다.
#    그래서 dynamix 폴더에 **우리 것 한 파일**(gn-monitor.cron)만 둔다. 다른 파일은 건드리지 않는다
CRON=/boot/config/plugins/dynamix/gn-monitor.cron

if [ "${1:-}" = "--install" ]; then
  mkdir -p "$(dirname "$CRON")" "$U"
  echo "* * * * * bash $R/deploy/unraid/updater.sh >/dev/null 2>&1" > "$CRON"
  update_cron
  echo "[updater] 예약함: $(cat "$CRON")"
  exit 0
fi
if [ "${1:-}" = "--uninstall" ]; then
  rm -f "$CRON"; update_cron; echo "[updater] 예약 지움"; exit 0
fi

# ⚠️ 이 파일을 복사본으로 돌린다 — 갱신(git pull)이 도는 중에 이 파일을 바꾸면 bash 가 나머지를 엉뚱하게 읽는다
if [ -z "${UPD_COPY:-}" ]; then
  cp "$0" /tmp/gn-updater.sh && UPD_COPY=1 exec bash /tmp/gn-updater.sh "$@"
fi
mkdir -p "$U"
exec 9>/tmp/gn-updater.lock
flock -n 9 || exit 0                       # 앞 차례가 아직 갱신 중

now() { TZ=Asia/Seoul date "+%Y-%m-%d %H:%M:%S"; }
running() { docker inspect gn-monitor --format '{{.Config.Image}}' 2>/dev/null | sed 's/.*://'; }   # gn-monitor:<판>

write_status() {                           # $1 = deploying(true|false)
  local run head remote behind commits base
  run=$(running)
  head=$(git -C "$R" rev-parse --short HEAD 2>/dev/null)
  remote=$(git -C "$R" rev-parse --short origin/main 2>/dev/null)
  # 밀린 커밋은 **돌고 있는 판**에서 센다 — 저장소만 당기고 다시 안 띄웠으면 그것도 '새 판'이다
  base=HEAD
  git -C "$R" cat-file -e "${run}^{commit}" 2>/dev/null && base=$run
  behind=$(git -C "$R" rev-list --count "$base"..origin/main 2>/dev/null || echo 0)
  commits=$(git -C "$R" log --format='%h%x09%cd%x09%s' --date=format:'%m-%d %H:%M' -12 "$base"..origin/main 2>/dev/null \
            | jq -R -s 'split("\n") | map(select(length>0) | split("\t") | {h: .[0], at: .[1], s: .[2]})')
  [ -n "$commits" ] || commits='[]'
  jq -n --arg checked "${CHECKED:-}" --arg run "$run" --arg head "$head" --arg remote "$remote" \
        --argjson behind "${behind:-0}" --argjson commits "$commits" --argjson deploying "$1" \
        --slurpfile last <( [ -s "$U/last.json" ] && cat "$U/last.json" || echo null ) \
        '{checked_at: $checked, running: $run, repo: $head, remote: $remote, behind: $behind,
          commits: $commits, deploying: $deploying, last: $last[0], updater: true}' > "$U/status.json.tmp" \
    && mv "$U/status.json.tmp" "$U/status.json"
}

# 1) GitHub 확인 — 10분마다, 또는 화면이 '다시 확인'을 눌렀을 때
CHECKED=$(jq -r '.checked_at // ""' "$U/status.json" 2>/dev/null || true)
if [ -e "$U/check" ] || [ "$(( 10#$(date +%M) % 10 ))" = 0 ] || [ ! -s "$U/status.json" ]; then
  rm -f "$U/check"
  if git -C "$R" fetch -q origin main 2>"$U/fetch.err"; then CHECKED=$(now); fi
fi
write_status false

# 2) 갱신 — 화면이 부탁했을 때만
if [ -e "$U/request" ]; then
  WHO=$(cat "$U/request" 2>/dev/null | head -c 200)
  rm -f "$U/request"
  write_status true
  START=$(now)
  if bash "$R/deploy/unraid/deploy.sh" > "$U/deploy.log" 2>&1; then OK=true; else OK=false; fi
  git -C "$R" fetch -q origin main 2>/dev/null && CHECKED=$(now)
  jq -n --arg at "$START" --arg done "$(now)" --argjson ok "$OK" --arg who "$WHO" \
        --arg version "$(git -C "$R" rev-parse --short HEAD 2>/dev/null)" \
        --arg tail "$(grep -v -e 'swap limit' -e 'curl: (56)' "$U/deploy.log" | tail -8)" \
        '{at: $at, done: $done, ok: $ok, version: $version, who: $who, log: $tail}' > "$U/last.json"
  write_status false
fi

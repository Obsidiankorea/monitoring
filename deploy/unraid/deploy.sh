#!/bin/bash
# 언레이드에서 경남 기상 대시보드 올리기·갱신 — 받기(GitHub, 공개 저장소) → 이미지 빌드 → 컨테이너 갈아끼우기.
#
#   bash /mnt/user/appdata/gn-monitor/repo/deploy/unraid/deploy.sh
#
# 폴더(/mnt/user/appdata/gn-monitor):
#   repo/      저장소 받은 것(이 서버에서는 고치지 않는다 — ff-only 로만 당긴다)
#   config/    api_keys.txt(기상청 API허브 기관용 키 ORG_API_KEY) — PC 에서 SSH 로 복사해 둔다
#   state/     DB(gnweather.db) · 격자 캐시 — 컨테이너를 갈아도 남는다(GN_STATE)
# 화면: http://<서버>:8000/  (지도: /map.html)
# ⚠️ 스방(내부망)은 집 서버에서 닿지 않는다 — 수집기를 끈다(SKIP_COLLECT=bangjae, Dockerfile).
# ⚠️ PC 에서도 수집기가 돌면 기상청 호출이 두 배가 된다(같은 키).
set -euo pipefail
D=/mnt/user/appdata/gn-monitor
REPO=https://github.com/Obsidiankorea/monitoring.git
NAME=gn-monitor
PORT=${PORT:-8000}

mkdir -p "$D/config" "$D/state"
# ⚠️ 받은 뒤에는 **새로 받은 이 스크립트로 다시** 시작한다 — bash 는 스크립트를 읽어 가며 돌아서,
#    도는 중에 git 이 이 파일을 바꾸면 나머지가 옛 내용으로 돈다.
if [ -z "${DEPLOY_PULLED:-}" ]; then
  if [ -d "$D/repo/.git" ]; then
    git -C "$D/repo" pull -q --ff-only origin main
  else
    git clone -q "$REPO" "$D/repo"
  fi
  export DEPLOY_PULLED=1
  exec bash "$D/repo/deploy/unraid/deploy.sh" "$@"
fi
V=$(git -C "$D/repo" rev-parse --short HEAD)
echo "[deploy] 판 $V"
[ -s "$D/config/api_keys.txt" ] || { echo "[deploy] ⚠ $D/config/api_keys.txt 가 없다(ORG_API_KEY)"; exit 1; }

docker build -q -t "$NAME:$V" -t "$NAME:latest" --build-arg APP_VERSION="$V" "$D/repo" >/dev/null
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --restart unless-stopped --memory 2g -p "$PORT:8000" \
  -e TZ=Asia/Seoul \
  -v "$D/state:/state" \
  -v "$D/config/api_keys.txt:/app/config/api_keys.txt:ro" \
  -l net.unraid.docker.webui="http://[IP]:[PORT:8000]/" \
  "$NAME:$V" >/dev/null

# 옛 판 이미지 정리(지금 판 · latest 만 남긴다)
docker image ls "$NAME" --format '{{.Tag}}' | grep -vE "^($V|latest)$" \
  | xargs -r -I{} docker rmi "$NAME:{}" >/dev/null 2>&1 || true

# 뜰 때까지 기다린다(첫 수집은 뒤에서 돈다)
for _ in $(seq 1 40); do
  curl -fsS -o /dev/null "http://127.0.0.1:$PORT/api/status" && { echo "[deploy] $NAME $V 떴다 → http://<서버>:$PORT/"; exit 0; }
  sleep 2
done
echo "[deploy] ⚠ 80초 안에 안 떴다 — docker logs $NAME"
exit 1

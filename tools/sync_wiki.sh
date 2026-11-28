#!/usr/bin/env bash
# 위키(PC 옵시디언) → NAS 헤르메스 knowledge/재난 — 한 방향 동기화. 대시보드 AI 가 이 NAS 복사본을 /wiki 로 읽는다.
# 그리고 NAS 가 만든 '법령 변경 제안'(app/lawwatch.py)을 PC 위키의 proposals/ 로 받아 온다(이미 있는 파일은 덮지 않는다).
#
#   bash tools/sync_wiki.sh           동기화
#   bash tools/sync_wiki.sh --dry     바뀔 파일만 보여 준다(보내지 않는다)
#   bash tools/sync_wiki.sh --prune   PC 에서 지운 페이지를 NAS 에서도 지운다(.md · data 만, raw 는 건드리지 않는다)
#
# 커밋된 상태(git HEAD)만 보낸다 — 작업 폴더의 미커밋 · 미추적 파일(다른 세션 작업 중)은 안 간다.
# 보내지 않는 것: .obsidian · .git · PDF · zip(원본 · 위키 묶음 — 바뀌지 않는다) · raw/추출본. raw/*.md(원본 목록)는 보낸다.
# NAS 의 그 폴더는 헤르메스 컨테이너(uid 10000) 소유 · 본인만 읽기라 보낸 뒤 소유자와 권한(700/600)을 맞춘다. 보내기 전에 gn-monitor 쪽에 백업을 남긴다.
set -euo pipefail
# 2026-11-28 위키 원본을 NAS 로 옮김 — 원본은 NAS knowledge/재난(git, 허브 claude-dev:/home/dev/repos/재난.git). PC 는 허브에서 pull/push.
# 이 스크립트로 보내면 PC 판이 NAS 원본을 덮으므로 막는다. 옛 방식이 꼭 필요할 때만 SYNC_WIKI_LEGACY=1.
[ "${SYNC_WIKI_LEGACY:-0}" = 1 ] || { echo "중단: 위키 원본이 NAS 로 옮겨졌다(2026-11-28). PC→NAS 덮어쓰기는 막혀 있다 — 허브 git 으로 push 하라."; exit 3; }
VAULT=${WIKI_VAULT:-"$HOME/obsidian/재난"}
HOST=${NAS_HOST:-root@100.106.116.92}
KEY=${NAS_KEY:-"$HOME/.ssh/unraid_tower"}
DEST=${NAS_WIKI:-/mnt/user/appdata/hermes-agent/knowledge/재난}
BAK=${NAS_BACKUP:-/mnt/user/appdata/gn-monitor/backup}
PROP=${NAS_PROPOSALS:-/mnt/user/appdata/gn-monitor/state/law/proposals}
DASH=${NAS_DASH:-http://100.106.116.92:8000}
DRY=0; PRUNE=0
for a in "$@"; do case "$a" in --dry) DRY=1;; --prune) PRUNE=1;; *) echo "알 수 없는 옵션: $a"; exit 2;; esac; done
[ -d "$VAULT" ] || { echo "위키 폴더가 없다: $VAULT"; exit 1; }
git -C "$VAULT" rev-parse --verify -q HEAD >/dev/null || { echo "위키가 git 저장소가 아니다: $VAULT"; exit 1; }
SRC=$(mktemp -d); git -C "$VAULT" archive HEAD | tar -xf - -C "$SRC"
echo "보낼 판: $(git -C "$VAULT" log --oneline -1)$(git -C "$VAULT" status --porcelain | grep -qv '^.. \.obsidian/' && echo ' (미커밋 변경은 안 보낸다)')"
SSH=(ssh -i "$KEY" -o ConnectTimeout=15 "$HOST")
EXC=(--exclude=./.obsidian --exclude=./.git --exclude='*.pdf' --exclude='*.zip' --exclude=./raw/추출본 --exclude='./raw/*.txt' --exclude='./raw/*.hwp' --exclude='./raw/*.hwpx')   # raw 의 추출본 · 한글 원문은 안 보낸다(판결문에 실명)

# 보낼 파일 목록 · 크기(PC) / NAS 에 있는 것 — 다른 것만 보여 준다
local_list() { (cd "$SRC" && find . -type f ! -path './.obsidian/*' ! -path './.git/*' ! -path './raw/추출본/*' ! -path './raw/*.txt' ! -path './raw/*.hwp' ! -path './raw/*.hwpx' ! -name '*.pdf' ! -name '*.zip' -printf '%P\t%s\n' | sort); }
remote_list() { "${SSH[@]}" "cd '$DEST' && find . -type f ! -path './.obsidian/*' ! -path './raw/추출본/*' ! -path './raw/*.txt' ! -path './raw/*.hwp' ! -path './raw/*.hwpx' ! -name '*.pdf' ! -name '*.zip' -printf '%P\t%s\n' | sort"; }
L=$(mktemp); R=$(mktemp); trap 'rm -rf "$L" "$R" "$SRC"' EXIT
local_list > "$L"; remote_list > "$R"
echo "PC $(wc -l < "$L")개 · NAS $(wc -l < "$R")개"
NEW=$(comm -23 "$L" "$R" | cut -f1 | sort -u)            # PC 에만 있거나 크기가 다른 것
GONE=$(comm -13 "$L" "$R" | cut -f1 | sort -u | comm -13 <(cut -f1 "$L" | sort -u) -)   # NAS 에만 있는 것
echo "── 보낼(새로 · 바뀐) 파일 $(printf '%s\n' "$NEW" | grep -c . || true)개"; printf '%s\n' "$NEW" | head -40
echo "── NAS 에만 있는 파일 $(printf '%s\n' "$GONE" | grep -c . || true)개$([ "$PRUNE" = 1 ] || echo ' (--prune 이 없으면 그대로 둔다)')"; printf '%s\n' "$GONE" | head -20
[ "$DRY" = 1 ] && { echo "(--dry — 여기까지)"; exit 0; }

"${SSH[@]}" "mkdir -p '$BAK' && tar czf \"$BAK/wiki-knowledge-\$(date +%Y%m%d-%H%M).tgz\" -C '$(dirname "$DEST")' --exclude='재난/raw' --exclude='*.zip' '$(basename "$DEST")' && ls -1t '$BAK'/wiki-knowledge-*.tgz | tail -n +6 | xargs -r rm -f"
echo "백업 완료 → $BAK"

tar -C "$SRC" -cf - "${EXC[@]}" . | "${SSH[@]}" "tar -xf - -C '$DEST' --no-same-owner && chown -R 10000:10000 '$DEST' && chmod -R u=rwX,go= '$DEST'"
echo "보냈다 → $HOST:$DEST"

if [ "$PRUNE" = 1 ] && [ -n "$GONE" ]; then
  printf '%s\n' "$GONE" | grep -vE '^(raw/|\.obsidian/)' | while IFS= read -r f; do "${SSH[@]}" "rm -f -- '$DEST/$f'"; echo "지움: $f"; done
fi

# NAS 가 만든 법령 변경 제안 → PC 위키 proposals/ (있을 때만, 이미 있는 파일은 덮지 않는다)
if "${SSH[@]}" "[ -d '$PROP' ] && ls '$PROP'/*.md >/dev/null 2>&1"; then
  mkdir -p "$VAULT/proposals"
  "${SSH[@]}" "tar -C '$PROP' -cf - ." | tar -xf - -C "$VAULT/proposals" --skip-old-files
  echo "법령 변경 제안 → $VAULT/proposals ($(ls "$VAULT/proposals" | wc -l)개)"
fi

curl -s -m 30 -X POST "$DASH/api/ai/wiki/reset" >/dev/null && echo "대시보드 위키 캐시를 비웠다" || echo "⚠ 대시보드 캐시를 못 비웠다($DASH) — 2분 안에 저절로 바뀐다"

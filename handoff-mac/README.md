# 경남 기상 모니터링 대시보드 — 인수인계 묶음

맥미니 서버에서 운영할 **웹 대시보드** 프로젝트를 시작하기 위한 자료 모음입니다.
기존 Windows 프로젝트(`재난상황보고서`)에서 **맥/웹으로 가져갈 수 있는 부분만** 추렸습니다.

이 폴더를 통째로 맥으로 옮긴 뒤, 새 저장소의 뿌리에 두고 시작하면 됩니다.

## 무엇이 들어 있나

| 파일 | 내용 | 언제 보나 |
|---|---|---|
| [AGENTS.md](AGENTS.md) | **AI 코딩 에이전트용 규약** (프로젝트 헌법) | 새 저장소 뿌리에 두면 Claude Code·Codex·Cursor가 자동으로 읽는다 |
| [docs/01-requirements.md](docs/01-requirements.md) | 요구사항 명세 | 무엇을 만들지 합의할 때 |
| [docs/02-architecture.md](docs/02-architecture.md) | 시스템 구조·기술 선택 | 뼈대를 세울 때 |
| [docs/03-kma-api.md](docs/03-kma-api.md) | **기상청 API 레퍼런스** ★ | 데이터를 가져올 때 |
| [docs/04-domain-gyeongnam.md](docs/04-domain-gyeongnam.md) | 경남 도메인 지식 | 시군·특보구역·격자를 다룰 때 |
| [docs/05-pitfalls.md](docs/05-pitfalls.md) | **실측으로 배운 함정 모음** ★ | 뭔가 이상하게 동작할 때 **여기부터** |
| [docs/06-workflow.md](docs/06-workflow.md) | AI와 함께 개발하는 절차 | 작업을 시작·마칠 때 |
| `config/api_keys.txt` | **실제 API 키** ⚠️ | 그대로 옮겨 쓰거나 `.env`로 변환 |
| `data/aws_stations.json` | 경남 AWS 관측지점 56곳 | 강수량 수집 |
| `data/gyeongnam_grids.json` | 읍면동 ↔ 격자 매핑 206곳 | 초단기예측 |

★ 표시가 이 묶음의 핵심 가치입니다. 나머지는 다시 쓸 수 있지만, 저 둘은
**실제로 부딪혀 보지 않으면 알 수 없는 내용**입니다.

## ⚠️ 먼저 읽을 것

### 1. `config/api_keys.txt`에 실제 키가 들어 있습니다

기상청 API 키와 **텔레그램 봇 토큰**이 평문으로 있습니다.

- 새 저장소를 만들면 **가장 먼저 `.gitignore`에 등록**하세요. 이 폴더에도
  `.gitignore`를 넣어 뒀지만, 저장소 뿌리로 옮기면 경로가 달라집니다.
- 공개 저장소에는 절대 올리지 마세요. 토큰이 새면 봇을 아무나 조종할 수 있습니다.
- 이미 노출된 적이 있다고 판단되면 @BotFather에서 `/revoke` 후 재발급하세요.

### 2. HWP(한글) 관련은 하나도 가져올 수 없습니다

원본 프로젝트의 절반은 한글 문서 자동화(`pyhwpx` + Windows COM)입니다.
**맥에는 이식 불가**입니다. 대시보드는 화면 표출과 알림에 집중하고, 한글 보고서
작성은 기존 Windows 프로그램에 남겨 두는 것이 맞습니다.

가져올 수 있는 것: **API 호출 · 데이터 가공 · 판정 규칙 · 이미지 생성 · 텔레그램**

## 시작 순서

```bash
# 1) 새 저장소 만들고 이 폴더 내용을 뿌리에 배치
git init 경남기상대시보드 && cd 경남기상대시보드
# (handoff-mac 안의 파일들을 여기로 복사)

# 2) 비밀 파일부터 잠그기
printf 'config/api_keys.txt\n.env\n__pycache__/\n*.pyc\ndata/cache/\n' > .gitignore
git add -A && git commit -m "chore: 인수인계 문서·데이터 반입"

# 3) AI 에이전트에게 맡길 준비 — AGENTS.md가 뿌리에 있어야 한다
ls AGENTS.md
```

그다음 [docs/01-requirements.md](docs/01-requirements.md)를 읽고, 합의되지 않은
부분을 먼저 정리한 뒤 [docs/06-workflow.md](docs/06-workflow.md)의 절차대로
첫 기능부터 착수하세요.

## 원본 프로젝트에서 참고할 코드

맥으로 옮기지는 않지만, 로직을 확인하고 싶을 때 볼 파일들입니다.

| 원본 파일 | 무엇을 배울 수 있나 |
|---|---|
| `weather_report_generator.py` | 특보 파싱·지역명 정규화·집계 표기 규칙 |
| `emergency/rain.py` | AWS 강수량 수집, 정시+매분 보강 |
| `emergency/forecast.py` | 초단기예측 격자 → 읍면동 값 |
| `emergency/qpf.py`, `vsrt_img.py` | 예측 이미지 받아 경남만 크롭 |
| `watch.py` | 감시 루프, 특보 변경 감지, 반복 알림 억제 |
| `telegram_notify.py` | 텔레그램 전송(그대로 재사용 가능) |
| `nuri_images.py` | 날씨누리 특보·예비특보 지도 |
| `main.py`의 `_alert_region_lines` | 특보 지역목록 표기 규칙(가장 까다로운 부분) |

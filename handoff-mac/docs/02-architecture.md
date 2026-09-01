# 02. 시스템 구조

## 큰 그림

```
                    ┌──────────────────── 맥미니 (상주) ────────────────────┐
  기상청 API ──────▶│  수집기(스케줄러)                                      │
  날씨누리   ──────▶│    · 주기적으로 API 호출 → 정규화 → 저장               │
                    │    · 이미지 내려받아 캐시                              │
                    │           │                                           │
                    │           ▼                                           │
                    │  저장소 (SQLite + 파일)                                │
                    │    · 관측/예측/특보 스냅샷, 알림 이력                  │
                    │    · 이미지·업로드 문서(PDF/사진)                      │
                    │           │                                           │
                    │     ┌─────┴──────┐                                    │
                    │     ▼            ▼                                    │
                    │  웹 서버       감시기 ──────▶ 텔레그램 봇 ──▶ 휴대폰   │
                    │  (FastAPI)      · 조건 판정                            │
                    │     │           · 반복 억제                            │
                    └─────┼───────────────────────────────────────────────┘
                          ▼
                   브라우저 (휴대폰 / PC)
```

### 핵심 원칙: 수집과 표출을 분리한다

**화면을 열 때 API를 부르지 않는다.** 수집기가 주기적으로 받아 저장하고, 웹은
저장된 것을 읽기만 한다. 이유:

- 여러 사람이 접속해도 기상청 호출은 한 번
- API가 느리거나 실패해도 화면은 마지막 정상 자료를 보여준다
- 감시기와 웹이 **같은 자료**를 본다 → 화면과 알림이 어긋나지 않는다

원본 Windows 프로젝트는 이 분리가 없어서, 대시보드에 잘못된 값이 찍히면 다음
조회(10분)까지 그대로 남는 문제가 있었다. → `docs/05-pitfalls.md`

## 기술 선택 (제안)

맥미니 상주 + 파이썬 자산 재사용을 전제로 한 권장안. 바꿔도 되지만, 바꾸면
이 문서를 고칠 것.

| 층 | 선택 | 왜 |
|---|---|---|
| 언어 | **Python 3.12+** | 원본 프로젝트의 API·가공 로직을 그대로 옮길 수 있다 |
| 패키지 | **uv** | 빠르고 락파일이 확실하다 |
| 웹 | **FastAPI + Jinja2** | 비동기 수집과 잘 맞고, 서버 렌더링이면 프런트 빌드가 없다 |
| 상호작용 | **HTMX** | 부분 갱신에 충분하다. SPA 빌드 체계를 안 들여도 된다 |
| 스타일 | **Tailwind CDN** 또는 손수 CSS | 반응형을 빨리 잡는다 |
| 스케줄 | **APScheduler** | 앱 안에서 돌아 배포 대상이 하나로 유지된다 |
| 저장 | **SQLite** | 단일 서버·단일 작성자. 별도 DB 서버가 필요 없다 |
| 이미지 | **Pillow / matplotlib** | 원본 프로젝트 코드 재사용 |
| 상주 | **launchd** | macOS의 표준. systemd 아님 |

### 왜 SPA가 아닌가

새벽에 휴대폰으로 여는 화면이다. **첫 화면이 빨리 뜨는 것**이 상호작용보다 중요하다.
서버 렌더링 + HTMX면 자바스크립트 번들이 거의 없고, 부분 갱신도 된다.
나중에 필요하면 특정 화면만 SPA로 바꿔도 된다.

## 디렉터리 구조 (제안)

```
app/
  main.py              FastAPI 진입점
  config.py            설정·비밀 로드 (.env)
  collectors/          기상청에서 받아오는 층
    rain.py            AWS 강수량
    alerts.py          기상특보 (wrn_now_data)
    forecast.py        초단기예측 격자 (RN1)
    images.py          특보 지도·예측 분포도
  domain/              가공·판정 (API를 모른다)
    regions.py         시군·특보구역 정규화
    aggregate.py       집계 표기 규칙
    thresholds.py      경보 판정
  store/               저장
    db.py              SQLite
    files.py           이미지·업로드 문서
  web/
    routes/            화면·API 라우트
    templates/         Jinja2
    static/
  notify/
    telegram.py        전송
    watcher.py         감시 루프·반복 억제
data/
  aws_stations.json    (인수인계 묶음에서 가져옴)
  gyeongnam_grids.json (인수인계 묶음에서 가져옴)
  uploads/             사용자가 올린 PDF·사진
  cache/               내려받은 이미지
docs/                  이 문서들
tests/
```

**`domain/`은 기상청 API를 모르게 유지한다.** 순수 함수로 두면 테스트가 쉽고,
API가 바뀌어도 판정 규칙은 그대로 간다.

## 데이터 모델 (초안)

```sql
-- 관측·예측 스냅샷: 언제 받은 무슨 자료인지
CREATE TABLE snapshot (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,        -- 'rain' | 'alert' | 'forecast'
  base_time TEXT NOT NULL,   -- 자료 기준 시각 (KST, 'YYYY-MM-DD HH:MM')
  fetched_at TEXT NOT NULL,  -- 실제로 받은 시각
  payload TEXT NOT NULL,     -- 정규화된 JSON
  UNIQUE(kind, base_time)
);

-- 알림 이력: 무엇을 언제 왜 보냈나 (중복 억제·사후 확인용)
CREATE TABLE notification (
  id INTEGER PRIMARY KEY,
  kind TEXT NOT NULL,        -- 'rain' | 'alert'
  sent_at TEXT NOT NULL,
  peak REAL,                 -- 시우량 알림의 최대치 (반복 억제 기준)
  body TEXT NOT NULL,
  ok INTEGER NOT NULL        -- 전송 성공 여부
);

-- 업로드 문서
CREATE TABLE document (
  id INTEGER PRIMARY KEY,
  filename TEXT NOT NULL,
  stored_path TEXT NOT NULL,
  content_type TEXT NOT NULL,
  size INTEGER NOT NULL,
  title TEXT,
  uploaded_at TEXT NOT NULL
);
```

`base_time`에 UNIQUE를 두면 같은 자료를 두 번 저장하지 않는다.

## 수집 주기 (제안)

| 자료 | 주기 | 근거 |
|---|---|---|
| 기상특보 | 1분 | 아무 때나 발표된다. 발표 리듬이 없다 |
| 초단기예측(RN1) | 10분 | 발표 주기가 10분. 발표 +2~8분 뒤 실제로 올라온다 |
| AWS 강수량(정시) | 10분 | 정시 자료 + 최근 구간은 매분자료로 보강 |
| 특보 지도 이미지 | 특보 지문이 바뀔 때만 | 안 바뀌면 다시 만들 이유가 없다 |

**이미지는 '바뀔 때만' 만든다.** 특보 상태의 지문(해시)을 떠 두고, 같으면
캐시를 쓴다. 원본 프로젝트에서 이 방식으로 재생성 9초 → 캐시 0.2초가 됐다.

## macOS 상주 설정

`~/Library/LaunchAgents/kr.gn.weather.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>kr.gn.weather</string>
  <key>ProgramArguments</key>
  <array>
    <string>/Users/사용자명/.local/bin/uv</string>
    <string>run</string>
    <string>uvicorn</string>
    <string>app.main:app</string>
    <string>--host</string><string>0.0.0.0</string>
    <string>--port</string><string>8000</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/사용자명/경남기상대시보드</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/tmp/gnweather.log</string>
  <key>StandardErrorPath</key><string>/tmp/gnweather.err</string>
</dict>
</plist>
```

```bash
launchctl load  ~/Library/LaunchAgents/kr.gn.weather.plist
launchctl list | grep kr.gn.weather
```

⚠️ 맥미니는 **잠자기(sleep)로 들어가면 서버가 멈춘다.** 시스템 설정에서
'디스플레이 꺼짐 시 자동 잠자기 방지'를 켜거나 `caffeinate`를 쓸 것.
전원 복구 후 자동 시작도 켜 둘 것(정전 대비).

## 외부 접근

| 방법 | 장단점 |
|---|---|
| **Tailscale** | 설정이 가장 쉽고 안전. 접속자가 모두 앱을 깔아야 함 |
| **Cloudflare Tunnel** | 공인 IP·포트포워딩 불필요, 도메인·인증 붙이기 쉬움 |
| 포트포워딩 + 인증서 | 공유기 설정 필요, 보안 부담이 가장 큼 |

부서 내부 공유가 목적이면 **Cloudflare Tunnel + 간단한 인증**이 무난하다.
어느 쪽이든 **인증 없이 공개하지 말 것** — 문서 열람 기능에 피해현황 PDF가 올라간다.

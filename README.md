# 경남 기상 대시보드

경상남도 18개 시군의 강수·특보·초단기예측을 한 화면에 표출하는 재난상황실 대시보드.
맥미니 상주 서버 하나로 수집·저장·표출을 모두 한다.

## 실행

폴더째 옮겨 놓고 실행 파일 하나만 누르면 된다. 가상환경 생성·의존성 설치·키 배치·
포트 찾기·브라우저 열기를 알아서 한다.

| | |
|---|---|
| **맥** | `run.command` 더블클릭 (또는 터미널에서 `./run.command`) |
| **윈도** | `run.bat` 더블클릭 |

처음 실행은 의존성을 받느라 1~2분, 뜬 뒤에도 자료를 받느라 화면이 채워지기까지
10~40초 걸린다. 받아 둔 것은 `data/` 에 남으므로 두 번째부터는 바로 뜬다.

포트를 바꾸려면 `PORT=9000 ./run.command`, 다른 기기에서도 보려면 `HOST=0.0.0.0`.
포트가 이미 쓰이고 있으면 다음 빈 포트를 알아서 찾는다 — **수집기가 둘 돌면
기상청 호출이 두 배가 되므로** 같은 포트에 겹쳐 띄우지 않는다.

### 직접 띄우기

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
mkdir -p config && cp handoff-mac/config/api_keys.txt config/   # 키는 저장소에 없다
.venv/bin/python -m app.main
```

윈도는 `.venv\Scripts\python.exe -m app.main`.

## 구조 — 수집과 표출을 분리한다

**화면을 열 때 기상청을 부르지 않는다.** 수집기가 주기적으로 받아 SQLite에 넣고,
웹은 저장된 것을 읽기만 한다. 접속자가 몇이든 기상청 호출은 한 번이고,
API가 죽어도 마지막 정상 자료가 화면에 남는다.

```
기상청 API ──▶ app/collectors/ ──▶ SQLite(data/gnweather.db) ──▶ /api/* ──▶ 화면
               (APScheduler)          + data/cache/qpf/*.png
```

| 파일 | 하는 일 |
|---|---|
| `app/config.py` | 키 로드, 수집 주기, 화면 폴링 기본값 |
| `app/kma.py` | 기상청 호출 한 곳. euc-kr, 타임아웃, 재시도, 200인데 본문이 오류인 경우 |
| `app/db.py` | 스키마. `quality` 열이 무강수·결측·조회실패를 가른다 |
| `app/domain/regions.py` | 관제순, 대표지점, 특보구역 세분화, 강원 고성 배제, 중대경보 파싱 |
| `app/collectors/rain.py` | AWS 정시(`awsh`) + 매분 보강(`nph-aws2_min`) |
| `app/collectors/forecast.py` | 초단기예측 격자 RN1(`nph-dfs_vsrt_grd`) |
| `app/collectors/alerts.py` | 기상특보(`wrn_now_data`) |
| `app/collectors/qpf.py` | 예측 분포 이미지(`nph-qpf_ana_img`) — 전국을 받아 PIL로 경남만 크롭 |
| `app/queries.py` | DB 읽기. 결측을 0으로 더하지 않고 뺀 시간 수를 함께 준다 |
| `app/main.py` | FastAPI + 스케줄러 + `/api/*` |
| `app/web/static/index.html` | 화면 |

## 수집 주기

| 자료 | 주기 | 근거 |
|---|---|---|
| 특보 | 1분 | 발표 리듬이 없다. 아무 때나 나온다 |
| 강수량 | 10분 | 정시 자료 + 최근 구간은 매분자료로 보강 |
| 초단기예측 | 10분 | 발표 주기 10분, 실제 업로드는 발표 +2~8분 뒤 |
| 예측 분포 이미지 | 10분 | 발표분이 바뀔 때만 실제로 받는다 |

화면의 갱신 주기는 **이것과 별개**다. 메뉴바에서 활성 창의 자료별로 따로 정하고,
바꿔도 기상청 호출량은 변하지 않는다 — 화면은 DB만 읽는다.

## API

| 경로 | 내용 |
|---|---|
| `GET /api/rain?hours=N` | 지점별 시간대별 강수량 + 누적 (`bad`=결측 시간 수) |
| `GET /api/forecast?hours=N` | 읍면동·시군 예측 순위 |
| `GET /api/alerts` | 특보 현황(집계는 시군 수) |
| `GET /api/qpf` · `/api/qpf/{tmfc}/{ef}.png` | 예측 분포 프레임 목록·이미지 |
| `GET /api/status` | 수집기 상태 + 발표 지연 통계 |
| `GET /api/settings` · `PUT /api/settings/qpf` | 예측 이미지 간격·선행시간 |
| `POST /api/refresh/{kind}?force=true` | 수동 조회 — 주기와 무관하게 실제로 다녀온다 |

## 예측 이미지 호출량

한 발표분의 장수 = **최대 선행시간 ÷ 간격**. 발표가 10분마다 나오므로
이 숫자가 곧 10분당 호출 수다. 화면의 `예측 분포 재생` 창 메뉴에서 바꾼다.

| 간격 · 선행 | 장수 | 하루 호출 |
|---|---|---|
| 10분 · 6시간 | 36 | 5,184 |
| 20분 · 3시간 | 9 | 1,296 |
| 30분 · 3시간 | 6 | 864 |

**발표가 났는지 먼저 확인하고 난 것만 받는다.** 미래 시각을 요청하면 최신
발표분이 오는 성질을 이용해, 이미지에 찍힌 발표시각 표시를 해시로 비교한다.
확인은 호출 한 번이고, 정시 이후 감시 구간에서만 한다.
재는 방법과 실측값은 `docs/02-발표주기.md`.

## 지켜야 할 것

- **비밀은 저장소에 넣지 않는다.** `config/api_keys.txt`·`.env`는 `.gitignore`에 있다.
  로그에도 남지 않게 httpx 로거를 WARNING으로 낮춰 뒀다(요청 URL에 `authKey`가 실린다).
- **조회 실패와 '자료 없음'을 구분한다.** 실패는 저장하지 않고 다음 주기에 다시 시도한다.
  DB의 `quality`, 화면의 `0.0` / `—` / `✕`가 그 구분이다.
- **시각은 전부 KST.** UTC로 바꾸지 않는다(기상청 API가 KST를 쓴다).

함정 목록은 `handoff-mac/docs/05-pitfalls.md`, 화면 설계는 `handoff-mac/docs/07-dashboard-design.md`.

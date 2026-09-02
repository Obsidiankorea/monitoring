# 경남 기상 대시보드

경상남도 18개 시군의 강수·특보·초단기예측을 한 화면에 표출하는 재난상황실 대시보드.
맥미니 상주 서버 하나로 수집·저장·표출을 모두 한다.

## 빠른 시작

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp handoff-mac/config/api_keys.txt config/          # 기상청 키 (저장소에 안 올라감)
.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

브라우저에서 `http://localhost:8000`.

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
| `GET /api/status` | 수집기 상태 |
| `POST /api/refresh/{kind}` | 수동 조회 — 주기와 무관하게 실제로 다녀온다 |

## 지켜야 할 것

- **비밀은 저장소에 넣지 않는다.** `config/api_keys.txt`·`.env`는 `.gitignore`에 있다.
  로그에도 남지 않게 httpx 로거를 WARNING으로 낮춰 뒀다(요청 URL에 `authKey`가 실린다).
- **조회 실패와 '자료 없음'을 구분한다.** 실패는 저장하지 않고 다음 주기에 다시 시도한다.
  DB의 `quality`, 화면의 `0.0` / `—` / `✕`가 그 구분이다.
- **시각은 전부 KST.** UTC로 바꾸지 않는다(기상청 API가 KST를 쓴다).

함정 목록은 `handoff-mac/docs/05-pitfalls.md`, 화면 설계는 `handoff-mac/docs/07-dashboard-design.md`.

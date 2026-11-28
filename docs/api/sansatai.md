---
이름: 산림청 디지털사면통합산사태정보시스템 (sansatai.forest.go.kr)
키이름: SANSATAI_ID · SANSATAI_PW (기관아이디 · 비밀번호) — 위험도 그림은 키 없이
발급처: 산림청 (헬프데스크 042-716-5050)
관리URL: https://sansatai.forest.go.kr/login.do
계정: 경상남도(자연재난과) 기관아이디 — 아이디 값도 키 파일에만 둔다
신청일:
승인일:
만료: 없음 (비밀번호 변경 주기는 사이트 규칙을 따른다)
한도: 확인 못함 — 화면이 5분마다 새로 부르는 것과 같은 정도(10분마다 6~7번)로만 부른다
IP등록: 불필요 (인터넷에서 열린다 — 행망 PC · 집 회선 둘 다 2026-11-28 확인)
상태: 위험도 그림 사용 중 · 로그인 자료는 키를 넣으면 사용 (2026-11-28)
쓰는곳: app/sansatai.py — 지도 레이어 '산사태'(J)의 위험도 칸 · 범례(예측 대비 발령 · 읍면동 · 산악기상), /api/sansatai*
---

# 산림청 디지털사면통합산사태정보시스템

2026-11-28 행망 PC 내장 브라우저로 경상남도(자연재난과) 계정에 로그인해 화면 스크립트를 읽어 찾은 것. 계정 권한 등급은 `PI` — 메뉴 168개 중 자료가 나오는 것은 30개쯤이고 상황관리(피해 · 119 신고, 상황전파) · 취약지역 대장은 막혀 있다.

## 로그인
- `GET /login.do`(세션 쿠키 `JSESSIONID`) → `POST /login.do` 폼 `userId` · `userPwd` **평문**(화면의 RSA 암호화는 2021-09 주석 처리). 성공 여부는 `GET /dgt/api/common/menu.do` 가 JSON 배열이면 성공, 아니면 '시스템에 문제가 있습니다' 글.
- ⚠️ 몇몇 응답(`alertSearchList.do`)에 **`userInfo`(비밀번호 해시 · 전화번호)** 가 실려 온다. 작성자 실명(`frcstWriterNm` · `frcstIssuWritrNm`)도. `sansatai._clean` · 각 `parse_*` 가 빼고 넘긴다. 원응답을 파일로 떨구지 않는다.

## 받는 것

| 자료 | 주소 (POST, 폼) | 인자 | 로그인 | 주기 |
|---|---|---|---|---|
| 위험도 최신 분석 시각 | `GET /mhms_pub/mhms/lndsInfo/getRealTimeMapView.do` | — | 아니오 | 매시 |
| 위험도 그림 | `GET /gis1/ictout/rtldm_risk_service/iserver/services/map-real_time_hazard_<YYYYMMDDHH>/rest/maps/HAZARD/image.png` | `width` `height` `viewBounds`(경위도) `prjCoordSys={"epsgCode":4326}` `transparent=true` | 아니오 | 매시 |
| 실황 · 예측(읍면동) | `/dgt/forecast/selectForecastList.do` | `searchBtnType=rltmList` `infoPeriod`(0 실황 · 1 예측) `searchFrom`/`searchTo`(`YYYY-MM-DD HH:00:00`) `selectSidoCode=48` `rows` `pageIndex` | 예 | 매시 분석 · **지난 날짜 조회 됨** |
| 예측 대비 예보 발령 | `/dgt/forecast/forecastStatusSearch.do` | `searchFrom`/`searchTo`(날짜) `searchTime=00` `searchToTime=23` `selectSidoCode=48` | 예 | 매시 |
| 산악기상(경남 41곳) | `/dgt/forecast/selectMtnWeatherStatusAll.do` | `wtherObsrrAddr=경상남도` `type=QPM`(또는 MQI) | 예 | 매시(격자 실황 강우) |
| 산림청 AWS 10분 | `/dgt/forecast/selectMountainAWS10mList.do` | `wtherObsrrAddr=경상남도` `rows` | 예 | 10분 |
| 중기(48시간) 예측 | `/midterm/tankAlarmList.do` | `selectSidoCode=48` | 예 | 발표 때(주기 미확인 — 비 올 때 본다) |

코드: `alarmType` 1 주의보 · 3 예비경보 · 2 경보(화면 `alarmTypeText`). `frcstIssuKindCd` 가 `-` 면 예측만 있고 시군 발령이 없다.

### 위험도 그림 → 우리 지도
- 원본은 산림청 등급 격자(iServer GRID, 색 6개 — 흰 0 · 빨강 1 · 주황 2 · 연두 3 · 하늘 4 · 파랑 5, 보간 NEARESTNEIGHBOR). 산지만 칠해지고 도심 · 농지 · 바다는 투명.
- 경남 500m 격자(hr bbox) 전체를 덮는 경위도 상자 `127.32~129.73 · 34.30~36.11` 를 0.001°/px(2410×1810, 약 290KB)로 받는다. 상자가 격자보다 좁으면 가장자리 칸이 번졌다.
- 원본 칸은 **약 10m**(0.00002°로 받아 가장 짧은 덩어리 5~6px × 1.8m, 2026-11-28).
- 우리 500m 칸을 5×5 로 나눈 **100m 칸**(2080×1890)에 가장 가까운 원본 픽셀을 옮긴다 → 지도 그림 · 면적. 칸 가운데의 원본 좌표는 `hr_lonlat` 로 한 번 풀고(약 10초, 띄운 뒤 첫 회만), 100m 칸은 그 사이를 기울기로 메운다.
- ⚠️ 처음엔 500m 칸마다 '창 안에서 가장 위험한 등급'을 칠했다 — 골짜기 · 하천 · 도심이 메워져 산지 면적이 진주 56%→94%, 창원 51%→84% 로 부풀었다. 1등급 한 점이 500m 칸을 통째 빨갛게 만든다. 100m 로 바꾼 뒤 세 곳 모두 실제와 같은 면적(56 · 51 · 86%), 칸별 차이 평균 3~6%p.
- 500m 칸 판정(`res=500`)은 칸에서 **면적이 가장 넓은 등급**(같으면 위험한 쪽), 칠해진 100m 칸이 절반 미만이면 비운다 — 다른 500m 자료와 맞춰 볼 때만.
- 시군 등급 면적(㎢) = 100m 칸 수 × 0.01 — 시군 경계는 `mask_sigun`(500m)을 펼친 것이라 경계에서 ±0.25㎢ 쯤 오간다 → `sansatai_risk` 표(분석 시각마다, JSON [1등급 … 5등급]).
- 색: 1 (255,0,0) · 2 (255,201,0) · 3 (182,255,142) · 4 (48,194,255) · 5 (0,0,255) — 산림청 범례와 같은 다섯 색. 정확히 이 색인 픽셀만 센다.

### 부담 (2026-11-28 행망 PC 실측)
| | 매시 1번 | 비고 |
|---|---|---|
| 받기 | 약 290KB · 2~8초 | 새 분석 시각일 때만 |
| 변환 | 0.5초 · 최대 55MB | 서버를 띄운 뒤 첫 회만 약 11초 · 138MB(투영 표) |
| 저장 | 원본 24시간 ≈ 7MB · 100m 칸 사흘 ≈ 17MB · 500m 칸 2주 ≈ 4MB | 면적은 DB 에 영구 |
| 화면 | 그림 약 335KB/시간 · GPU 텍스처 약 16MB | 층 '산사태'를 켰을 때만 받는다 |
| 로그인 자료 | 10분마다 POST 6~7번 · 수십 KB | 계정 있을 때만 |

## 화면 · API
- `GET /api/sansatai` — 요약(위험도 시군별 등급 면적 ㎢ · 실황 · 예측 · 미발령 · 산악기상 · AWS · 중기).
- `GET /api/sansatai/risk.png?anal=&max=&res=&scale=` — 칸 지도 그림(지도 격자 네 모서리에 그대로). 기본 `res=100`(2080×1890) — 보고서 그림은 이것 그대로. `res=500&scale=4` 는 500m 칸. `max=2` 면 1 · 2등급만. `raw=1` 이면 산림청 원본(경위도).
- `GET /api/sansatai/history?fr=YYYY-MM-DD&to=YYYY-MM-DD` — 쌓인 실황 · 예측(읍면동)과 위험도 시군 등급 면적.
- 지난 실황 · 예측 메우기: `.venv\Scripts\python.exe -m app.sansatai backfill 2026-06-01 2026-11-28` (로그인 필요).

## 아직 안 붙인 것 (권한은 있음)
- `/dgt/forecast/alertSearchList.do` 예보 발령 이력 — `prctnInfoArcd=48000` 으로 걸러지지 않아(충남이 섞여 옴) 보류. 시군 발령은 재난안전데이터(app/safety.py)로 받는다.
- `/forecast/selectCbsSendResultList.do` CBS 발송 결과, `/api/broadcast/riskhistory/list.do` 위험예측 이력(JSON 본문), `KLES 모델` — 쓸 자리가 생기면.

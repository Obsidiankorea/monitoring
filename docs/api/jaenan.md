---
이름: 재난상황보고서 서버(jaenan-weather)
키이름: JAENAN_URL, JAENAN_TOKEN
발급처: 우리 언레이드 NAS — jaenan-weather 컨테이너(재난상황보고서 저장소 server/)
관리URL: https://login.tailscale.com/admin/machines
계정:
신청일:
승인일:
만료: 없음 (NAS 의 토큰 파일을 바꾸기 전까지)
한도: 한 번에 한 작업(서버 잠금) · 같은 인자 2분 캐시 · 풍수해보고는 1분 안팎
IP등록: 불필요 (테일스케일 망 안)
상태: 사용 중
쓰는곳: app/reports.py — 지도의 보고서 창(받기 · 텔레그램 보내기)
---

# 재난상황보고서 서버 (jaenan-weather)

- 주소: 비우면 `http://100.106.116.92:8765`(테일스케일). 관리URL 은 그 NAS 에 접속하는 길(테일스케일 기기 목록)이다.
- 토큰: NAS 의 jaenan-weather 설정 폴더에 있는 서버 토큰 파일과 같은 값. **값을 화면 · 문서 · 커밋에 적지 않는다** — `config/api_keys.txt` 에만.
- 부르는 것: `GET /api/run/<작업>`(만들기) → `GET /files/<이름>`(받기), 둘 다 `Authorization: Bearer`.
- 보고서 목록과 늘리는 법은 [[04-보고서-창|보고서 창]].

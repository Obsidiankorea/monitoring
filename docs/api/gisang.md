---
이름: 기상 서버(gisang.day) 읽기 열쇠
키이름: GN_SERVER_KEY
발급처: 우리 언레이드 NAS — gn-monitor 컨테이너의 기계 열쇠(서버 config/api_keys.txt 의 GN_API_KEY)
관리URL: https://gisang.day
계정:
신청일:
승인일:
만료: 없음 (서버의 GN_API_KEY 를 바꾸기 전까지)
한도: 읽기(GET)만 — 연락처 · 회신 · 쓰기는 서버가 막는다(app/auth.py NO_MACHINE)
IP등록: 불필요
상태: 행망 PC(서버 + 이 PC 스방)에서 사용
쓰는곳: app/origin.py — 자료 받는 곳 '서버 + 이 PC 스방'(mix)이 서버 자료를 읽을 때 X-GN-Key 머리로
---

# 기상 서버 읽기 열쇠 (GN_SERVER_KEY)

- 값: 서버(언레이드 gn-monitor)의 `GN_API_KEY` 와 같은 값. **값을 화면 · 문서 · 커밋에 적지 않는다** — 이 PC `config/api_keys.txt` 에만.
- 쓰임: 설정 › 자료 › 받는 곳 **서버 + 이 PC 스방** — 기상청 자료는 서버에서 읽고(호출 절약), 스방(내부망)만 이 PC 가 수집한다.
  이 PC 에서 서버로는 아무것도 쓰지 않는다(읽기만 넘긴다).
- 확인: 같은 화면 [연결 확인] — 열쇠가 틀리면 '서버가 기계 열쇠(GN_SERVER_KEY)를 받지 않는다'.

---
이름: 한강홍수통제소 OpenAPI (HRFCO)
키이름: HRFCO_KEY
발급처: 홍수통제소 오픈API
관리URL: https://www.hrfco.go.kr/web/openapiPage/reference.do
계정:
신청일:
승인일:
만료:
한도:
IP등록: 불필요
상태: 사용 중
쓰는곳: app/river.py — 하천 수위 · 댐 · 보 · 홍수예보 → 지도 레이어 '하천·댐'(D), AI 사다리, 텔레그램
---

# 한강홍수통제소 OpenAPI

한강만이 아니라 **전국 4대강 홍수통제소** 자료를 한 주소에서 준다. 경남은 낙동강 쪽이라 낙동강홍수통제소 자료가 온다.

## 부르는 법
`https://api.hrfco.go.kr/{키}/{waterlevel|rainfall|dam|bo}/{info|list/10M}.json`, 홍수예보는 `fldfct/list.json`.
키는 **주소 경로**에 들어간다 → 로그·화면에 주소를 찍지 않는다.

## 알아 둘 것
- 낙동강 쪽 값은 11분 이상 늦게 온다. 원시값(검수 전)이다 — 공식 판단은 홍수통제소 발표로.
- 목록에 `null` 항목이 섞여 온다(코드가 걸러낸다).
- 수위 관측소 기준 수위(관심·주의보·경보·심각)가 없는 곳은 단계를 매기지 않는다.
- 아직 안 붙인 것: 강수 관측소(rainfall, 72곳).

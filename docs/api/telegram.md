---
이름: 텔레그램 봇
키이름: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
발급처: 텔레그램 BotFather
관리URL: https://t.me/BotFather
계정:
신청일:
승인일:
만료: 없음 (폐기하기 전까지)
한도: 초당 약 30건 · 같은 채팅 분당 20건 안팎
IP등록: 불필요
상태: 사용 중
쓰는곳: app/aiwatch.py · app/lawwatch.py · app/river.py — AI 알림 · 법령 알림 · 하천 알림
---

# 텔레그램 봇

- 토큰: BotFather 에서 `/newbot`. 잃거나 새면 `/revoke` 로 새로 받는다(옛 토큰은 즉시 죽는다).
- 채팅 번호: 봇에게 말을 건 뒤 `getUpdates` 로 `chat.id` 를 본다. 그룹이면 음수다.
- **알림은 한 서버에서만 켠다** — PC 와 서버를 둘 다 켜면 같은 알림이 두 번 간다.

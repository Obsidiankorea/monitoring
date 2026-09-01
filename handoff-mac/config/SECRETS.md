# 비밀 값 안내

## ⚠️ 이 폴더의 `api_keys.txt`에는 실제 키가 들어 있습니다

기상청 API 키와 **텔레그램 봇 토큰**이 평문으로 있습니다.
새 저장소로 옮기면 **가장 먼저** `.gitignore`에 등록하세요.

```bash
printf 'config/api_keys.txt\n.env\n' >> .gitignore
git check-ignore -v config/api_keys.txt      # 무시되는지 확인
```

⚠️ **`.gitignore`에 줄 끝 주석을 쓰지 마세요.** 패턴의 일부로 인식돼 무시가 안 됩니다.

## 무엇이 필요한가

| 이름 | 용도 | 발급처 |
|---|---|---|
| **`ORG_API_KEY`** | **기상청 API 전부** (기관용 계정) | [API허브](https://apihub.kma.go.kr) |
| `TELEGRAM_BOT_TOKEN` | 알림 전송 | 텔레그램 `@BotFather` → `/newbot` |
| `TELEGRAM_CHAT_ID` | 알림 수신처 | 아래 참고 |

**기상청 키는 하나뿐이다.** 2026-08에 쓰는 API 전부가 기관용으로 승인되어
개인 키 5개(API_KEY / WAVE / WEATHER_ALERT / TEMPERATURE / FORECAST)를 없앴다.

⚠️ **기관용 키는 `apihub-pub.kma.go.kr` 호스트에서만 동작한다.**
구 호스트(`apihub.kma.go.kr`)에 쓰면 403이다.

## chat_id 찾기

**봇 username(`@…bot`)이 아닙니다.** 개인 대화방은 양수, 그룹은 `-100…`으로
시작하는 음수입니다. `@이름` 형태가 통하는 건 공개 채널뿐입니다.

1. 텔레그램에서 봇을 찾아 **시작(Start)** → 아무 메시지나 한 줄
   (단톡방으로 받으려면 봇을 그 방에 초대한 뒤 방에 메시지)
2. 브라우저에서 열기:
   `https://api.telegram.org/bot<토큰>/getUpdates`
3. `"chat":{"id":...}` 값을 쓴다

⚠️ 봇에게 **먼저 말을 걸어야** 합니다. 텔레그램은 봇이 먼저 말을 걸지 못하게 막아
두었고, `getUpdates`는 봇이 *받은* 메시지만 보여줍니다.
⚠️ 대기열은 계속 남아 있지 않습니다(확인되면 빠지고 24시간 지나면 사라짐).
비어 있으면 메시지를 다시 보내고 재시도하세요.

## macOS에서 `.env`로 바꾸기

새 프로젝트는 `.env`가 표준입니다. 형식이 같으므로 이름만 바꿔도 됩니다.

```bash
grep -v '^#' config/api_keys.txt | grep '=' > .env
```

```python
# app/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    org_api_key: str
    telegram_bot_token: str = ""     # 없으면 알림 기능이 조용히 꺼지도록
    telegram_chat_id: str = ""

    class Config:
        env_file = ".env"

settings = Settings()
```

⚠️ **코드의 기본값에 실제 키를 넣지 마세요.** 그 파일은 커밋됩니다.
원본 프로젝트가 그렇게 되어 있는데, 옮기면서 정리하는 게 좋습니다.

## 노출됐다고 판단되면

- 기상청: API허브에서 키 재발급
- 텔레그램: `@BotFather` → `/revoke` → 새 토큰 발급

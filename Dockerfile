# 경남 기상 대시보드 — 언레이드(도커)용. 화면 + 수집기를 한 컨테이너에.
#   빌드·실행은 deploy/unraid/deploy.sh 가 한다.
# ⚠️ 키(config/api_keys.txt)와 DB·격자 캐시는 이미지에 굽지 않는다 — 실행할 때 연결한다(.dockerignore).
#    키: -v .../api_keys.txt:/app/config/api_keys.txt:ro   쌓이는 자료: -v .../state:/state (GN_STATE)
FROM python:3.14.3-slim-bookworm

# tzdata — 시각은 전부 KST(datetime.now · 스케줄러). slim 에는 시간대 자료가 없다
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 TZ=Asia/Seoul \
    HOST=0.0.0.0 PORT=8000 GN_STATE=/state \
    SKIP_COLLECT=bangjae

# AI 상황판단 자유 질문(GN_AI=claude-cli) — Claude Code 를 공식 설치 스크립트로. 인증은 실행할 때
# config/claude/token.txt(claude setup-token)로 한다 — 이미지에 굽지 않는다. 빼려면 --build-arg WITH_CLAUDE=0
ARG WITH_CLAUDE=1
ENV PATH="/root/.local/bin:$PATH" DISABLE_AUTOUPDATER=1
RUN if [ "$WITH_CLAUDE" = "1" ]; then \
      apt-get update && apt-get install -y --no-install-recommends curl ca-certificates \
      && rm -rf /var/lib/apt/lists/* \
      && curl -fsSL https://claude.ai/install.sh | bash && claude --version; fi

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
EXPOSE 8000
CMD ["python", "-m", "app.main"]

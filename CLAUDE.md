# CLAUDE.md — 경남 기상 대시보드

이 저장소에서 일하는 Claude 는 **[HANDOFF.md](HANDOFF.md) → [README.md](README.md)(필요한 절만)** 순서로 읽고 시작한다.
HANDOFF 에 지금까지 한 일 · 남은 일 · 지켜 온 약속이 있다. 최근 흐름은 `git log --oneline -30`.

## 꼭 지킬 것(자세한 것은 HANDOFF '지켜 온 약속')
- 키 · 토큰(`config/api_keys.txt`)은 커밋하지 않고 화면 · 로그에 찍지 않는다.
- 커밋 · 푸시 · 서버 갱신은 사용자가 말할 때만. main 은 사용자가 'ㅇㅇ' · '합쳐' 할 때만 fast-forward.
- 사용자의 실행 중인 대시보드(:8000, `run.bat` — CP949, 손대지 않는다)를 끄지 않는다. 시험 서버는 `--no-collect` + 다른 포트.
- 언레이드는 `/mnt/user/appdata/{gn-monitor,jaenan-weather}` 밖을 건드리지 않는다. 시험 중 바꾼 공유 DB 설정은 되돌린다.
- 문서는 옵시디언 스타일(frontmatter · `[[위키링크]]` · 콜아웃). 화면을 바꾸면 README 와 지도 도움말도 같이.

## 어디에 무엇이
- 서버: `app/main.py`(FastAPI) · `app/gridview.py`(격자 · 지도 설정) · `app/collectors/`(수집) · `app/domain/regions.py`(시군 · 특보구역)
- 화면: `app/web/static/map.html`(경남 강수 지도) · `app/web/static/index.html`(종합 화면) — 각각 한 파일
- 시험: `python -m pytest -q`

"""내려받은 저장소를 최신으로 맞추기 — `git pull` 을 감싼 것.

배포처는 GitHub 하나다. 상주 서버(NAS)가 없어도, 각 PC 가 저장소를 클론해 두었으면
화면에서 단추 한 번으로 최신 코드를 받을 수 있다.

⚠️ **덮어쓰지 않는다.** `--ff-only` 로만 당긴다. 그 PC 에서 손댄 파일이 있으면
   합치기를 시도하다 어중간한 상태로 남는 대신, 실패하고 이유를 그대로 보여 준다.
   현장 PC 가 반쯤 병합된 코드로 도는 것보다 안 받는 편이 낫다.
⚠️ **받았다고 바로 바뀌지 않는다.** 화면(index.html)은 새로고침이면 되지만
   파이썬 코드는 프로세스를 다시 띄워야 한다. 무엇이 바뀌었는지 보고 알려 준다.
⚠️ 인터넷이 막힌 내부망 PC 도 있다. 확인이 실패해도 화면이 죽지 않게, 실패를
   '최신'으로 읽지 않고 실패라고 적는다.
⚠️ **requirements.txt 가 바뀌었으면 받는 자리에서 깐다.** 화면의 '재시작'(종료 코드 42)은
   run.bat 의 설치 단계를 건너뛰고 서버만 다시 띄운다(run.bat `:runserver` 고리). 여기서
   안 깔면 새 의존성(예: 경남 지도의 h5py)이 없는 채로 떠서, run.bat 을 새로 누를 때까지
   그 기능만 실패로 남는다. run.bat 은 CP949 라 고치지 않고 이쪽에서 막는다.
"""
from __future__ import annotations

import logging
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .config import ROOT

log = logging.getLogger("update")

TIMEOUT = 25          # 초. 인터넷이 막힌 PC 에서 오래 매달리지 않게
PIP_TIMEOUT = 300     # 초. 휠 몇 개 받는 데 충분하다
_PY = (".py",)        # 이게 바뀌면 서버를 다시 띄워야 한다


def _git(*args: str, timeout: int = TIMEOUT) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                           timeout=timeout, text=True, encoding="utf-8",
                           errors="replace")
    except FileNotFoundError:
        return 127, "git 이 없다"
    except subprocess.TimeoutExpired:
        return 124, f"{timeout}초 안에 응답이 없다(인터넷이 막혔을 수 있다)"
    return p.returncode, ((p.stdout or "") + (p.stderr or "")).strip()


def available() -> bool:
    """이 폴더가 git 저장소이고 원격이 있는가."""
    ok, _ = _git("rev-parse", "--is-inside-work-tree", timeout=5)
    if ok != 0:
        return False
    ok, out = _git("remote", timeout=5)
    return ok == 0 and bool(out.strip())


def _head() -> dict:
    _, sha = _git("rev-parse", "--short", "HEAD", timeout=5)
    _, msg = _git("log", "-1", "--format=%s", timeout=5)
    _, when = _git("log", "-1", "--format=%cd", "--date=format:%Y-%m-%d %H:%M", timeout=5)
    return {"sha": sha, "subject": msg, "at": when}


def status(fetch: bool = True) -> dict:
    """지금 버전과, 원격에 새 것이 있는지."""
    if not available():
        return {"available": False, "reason": "git 저장소가 아니다(압축을 풀어 쓰는 중)"}

    out = {"available": True, "here": _head(), "dirty": False,
           "behind": 0, "ahead": 0, "checked_at": None, "error": None}

    # ⚠️ **추적 중인** 파일이 바뀐 것만 센다. 새로 생긴 파일(로그·내보낸 그림 따위)은
    #    받기를 막지 않는데, 그걸 '손댔다'고 적으면 멀쩡한 PC 마다 경고가 뜬다.
    _, st = _git("status", "--porcelain", "--untracked-files=no", timeout=8)
    out["dirty"] = bool(st.strip())
    out["dirty_files"] = [l[3:] for l in st.splitlines() if l.strip()][:8]

    if fetch:
        code, msg = _git("fetch", "--quiet", "origin")
        out["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        if code != 0:
            # ⚠️ 확인 실패를 '최신'으로 읽지 않는다. 모르는 것과 최신은 다르다.
            out["error"] = msg or "원격을 확인하지 못했다"
            return out

    code, counts = _git("rev-list", "--left-right", "--count", "HEAD...@{u}", timeout=8)
    if code == 0 and "\t" in counts:
        a, b = counts.split("\t")[:2]
        out["ahead"], out["behind"] = int(a or 0), int(b or 0)
    if out["behind"]:
        _, log_ = _git("log", "--format=%h %s", "-8", "HEAD..@{u}", timeout=8)
        out["incoming"] = [l for l in log_.splitlines() if l.strip()]
    return out


def install_deps() -> dict:
    """requirements.txt 대로 깐다 — 이 서버를 돌리는 바로 그 파이썬(가상환경)에.

    `--upgrade` 는 주지 않는다. 없는 것·판이 모자란 것만 깐다 — 돌고 있는 서버가 쥐고 있는
    파일(윈도)을 갈아 끼우려다 실패하지 않게.
    """
    cmd = [sys.executable, "-m", "pip", "install", "-q", "--disable-pip-version-check",
           "--timeout", "15", "--retries", "1", "-r", "requirements.txt"]
    try:
        p = subprocess.run(cmd, cwd=ROOT, capture_output=True, timeout=PIP_TIMEOUT,
                           text=True, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"{PIP_TIMEOUT}초 안에 끝나지 않았다(인터넷이 막혔을 수 있다)"}
    except OSError as e:
        return {"ok": False, "error": str(e)}
    if p.returncode != 0:
        tail = [l for l in ((p.stderr or "") + (p.stdout or "")).splitlines() if l.strip()][-3:]
        return {"ok": False, "error": " / ".join(tail)[:300] or f"pip 종료 코드 {p.returncode}"}
    # run.bat·run.command 는 requirements.txt 가 이 표시보다 새로우면 다시 깐다 — 깔았다고 적어 둔다
    if sys.prefix != getattr(sys, "base_prefix", sys.prefix):
        try:
            (Path(sys.prefix) / ".installed").write_text("\n", encoding="ascii")
        except OSError:
            pass
    return {"ok": True}


def pull() -> dict:
    """`git pull --ff-only`. 무엇이 바뀌었고 다시 띄워야 하는지 함께 돌려준다."""
    if not available():
        return {"ok": False, "error": "git 저장소가 아니다"}

    before = _head()["sha"]
    code, msg = _git("pull", "--ff-only", "--quiet", timeout=60)
    if code != 0:
        # 손댄 파일이 있거나 갈래가 나뉜 것이다. 억지로 합치지 않는다.
        return {"ok": False, "error": msg or "받지 못했다", "here": _head()}

    after = _head()["sha"]
    if before == after:
        return {"ok": True, "changed": [], "restart": False,
                "here": _head(), "note": "이미 최신이다"}

    _, files = _git("diff", "--name-only", f"{before}..{after}", timeout=10)
    changed = [f for f in files.splitlines() if f.strip()]
    restart = any(f.endswith(_PY) or f == "requirements.txt" for f in changed)
    log.info("업데이트 %s → %s, %d개 파일%s", before, after, len(changed),
             " (재시작 필요)" if restart else "")
    out = {"ok": True, "changed": changed, "restart": restart, "here": _head(), "from": before}
    if "requirements.txt" in changed:
        out["deps"] = install_deps()
        log.info("의존성 설치: %s", out["deps"])
    return out

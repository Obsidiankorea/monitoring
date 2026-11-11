"""경남 강수 지도 — exe 시작점(PyInstaller, tools/gn_monitor.spec). run.bat 이 하던 일을 한다:
키 파일이 없으면 틀을 복사해 메모장으로 열고, 서버를 켠 뒤 브라우저를 연다. 창을 닫으면 서버도 꺼진다.
"""
import os
import shutil
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
os.chdir(ROOT)
for _s in (sys.stdout, sys.stderr):   # 출력을 파일로 돌리면 cp949 — '—' 같은 글자에 죽지 않게
    if _s:
        _s.reconfigure(errors="replace")


def _key_ok(f: Path) -> bool:
    for line in f.read_text("utf-8-sig").splitlines():
        k, _, v = line.strip().partition("=")
        if k.strip() == "ORG_API_KEY" and len(v.strip()) >= 10 and not v.strip().startswith("여기에"):
            return True
    return False


def _listening(port: int) -> bool:
    import socket
    with socket.socket() as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", port)) == 0


def main() -> None:
    import uvicorn
    if "--demo" in sys.argv:              # 시연 서버(:8001) — 굳혀 둔 그때 자료, 수집 안 함. 실황 exe 가 곁에 띄운다(run.bat 4-1 과 같다)
        os.environ["GN_DEMO"] = "1"       # GN_SNAP 은 시연을 갈아 탈 때 main._reexec 가 넣어 준다
        from app.main import app
        uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=8001)
        return
    keys = ROOT / "config" / "api_keys.txt"
    if not keys.exists():
        shutil.copy2(ROOT / "config" / "api_keys.example.txt", keys)
        print("[*] config\\api_keys.txt 를 만들었습니다 — 키를 넣고 저장한 뒤 메모장을 닫으세요")
    if not _key_ok(keys):
        print("[!] ORG_API_KEY(기상청 API허브 기관용 키)가 비어 있습니다. 메모장을 닫으면 계속합니다.")
        subprocess.run(["notepad", str(keys)])
        if not _key_ok(keys):
            print("[!] 키 없이 켭니다 — 강수 · 특보를 받지 못합니다")

    host, port = os.environ.get("HOST", "127.0.0.1"), int(os.environ.get("PORT", "8000"))
    if "--no-browser" not in sys.argv:
        threading.Timer(3, lambda: webbrowser.open(f"http://127.0.0.1:{port}/")).start()
    if not _listening(8001):              # 화면의 시연 줄은 :8001 로 간다 — 같은 창에 붙여 띄워 창을 닫으면 함께 꺼진다
        me = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, __file__]
        subprocess.Popen([*me, "--demo"], env={k: v for k, v in os.environ.items() if k != "PORT"})
    from app.main import app
    print(f"[*] http://127.0.0.1:{port}/ — 이 창을 닫으면 꺼집니다")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    main()

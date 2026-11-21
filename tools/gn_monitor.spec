# -*- mode: python ; coding: utf-8 -*-
"""경남 강수 지도 exe — PyInstaller 명세. 빌드: python -m PyInstaller tools/gn_monitor.spec --noconfirm
결과: dist/경남강수지도/ 폴더(통째로 복사해 배포).

contents_directory='.' — _internal 없이 exe 옆에 app/ · data/ · config/ 를 둔다. 그래서 config.ROOT
(app/config.py 의 parent.parent)가 exe 폴더가 되고, 코드는 그대로 돈다. 키 파일 · DB 도 exe 옆에 쌓인다.
자료는 저장소에 든 것만(git ls-files) — DB · 캐시 · 지형 조각 · 키는 넣지 않는다.
"""
import subprocess
from pathlib import Path
from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent
files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "app/web", "data", "docs", "deploy/hermes",
                        "config/api_keys.example.txt", "config/law_watch.json"],
                       capture_output=True, check=True).stdout.decode("utf-8").split("\0")
datas = [(str(ROOT / f), str(Path(f).parent)) for f in files if f and (ROOT / f).is_file()]

hidden = collect_submodules("app") + collect_submodules("uvicorn") + collect_submodules("apscheduler") + ["anthropic"]

a = Analysis([str(ROOT / "tools" / "exe_main.py")], pathex=[str(ROOT)], datas=datas, hiddenimports=hidden,
             excludes=["PyQt5", "PyQt6", "PySide6", "tkinter", "matplotlib", "pytest", "IPython"])
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="경남강수지도", console=True, upx=False, contents_directory=".")
coll = COLLECT(exe, a.binaries, a.datas, name="경남강수지도", upx=False)

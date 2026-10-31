"""지도 화면(app/web/static/map.html + js/*.js + css/map.css) 검사 — 쪼갠 뒤에도 한 덩어리처럼 돌아가는지.

  python tools/check_map.py

  · map.html 이 부르는 js · css 파일이 모두 있고, js 는 번호 순서대로 불린다
  · 첫 파일 말고는 "use strict" 한 줄로 시작한다(스크립트마다 따로 켜야 한다)
  · 파일마다 · 이어 붙인 것 모두 `node --check` 문법 검사(node 가 있을 때)
  · 같은 이름의 최상위 let/const/class/function 이 두 파일에 겹치지 않는다(겹치면 불러올 때 오류)
⚠️ 한계: 앞 파일이 불러오는 중에 뒤 파일의 함수를 부르면(호이스팅은 파일 안에서만) 오류가 나는데, 이건 브라우저에서 열어 봐야 안다.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "app" / "web" / "static"
TOP = re.compile(r"^(?:async\s+)?function\s*\*?\s*([A-Za-z_$][\w$]*)|^(?:let|const|var|class)\s+([A-Za-z_$][\w$]*)")


def main() -> int:
    html = (STATIC / "map.html").read_text("utf-8")
    js = re.findall(r'<script src="(js/[^"?]+)', html)
    css = re.findall(r'<link rel="stylesheet" href="(css/[^"?]+)', html)
    bad = []
    for f in js + css:
        if not (STATIC / f).exists():
            bad.append(f"없는 파일: {f}")
    if js != sorted(js):
        bad.append(f"js 순서가 번호 순이 아니다: {js}")
    seen: dict[str, str] = {}
    texts = []
    for i, f in enumerate(js):
        t = (STATIC / f).read_text("utf-8")
        texts.append(t)
        if i and not t.startswith('"use strict";'):
            bad.append(f"{f}: 첫 줄이 \"use strict\" 가 아니다")
        for line in t.split("\n"):
            m = TOP.match(line)
            name = m and (m.group(1) or m.group(2))
            if name:
                if name in seen and seen[name] != f:
                    bad.append(f"{name}: {seen[name]} 와 {f} 에 둘 다 있다")
                seen.setdefault(name, f)
    node = shutil.which("node")
    if node and not bad:
        with tempfile.TemporaryDirectory() as d:
            whole = Path(d) / "all.js"
            whole.write_text("\n".join(texts), "utf-8")
            for p in [*(STATIC / f for f in js), whole]:
                r = subprocess.run([node, "--check", str(p)], capture_output=True, text=True)
                if r.returncode:
                    bad.append(f"문법 오류 {p.name}: {r.stderr.strip()[:300]}")
    elif not node:
        print("(node 가 없어 문법 검사는 건너뛴다)")
    for b in bad:
        print("✗", b)
    print(f"{'실패' if bad else '통과'} — js {len(js)}개 · css {len(css)}개 · 최상위 이름 {len(seen)}개")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

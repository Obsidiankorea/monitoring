"""문서 보기 — docs/ 의 마크다운(옵시디언 꼴)을 게시판 '문서' 탭에서 서식 입혀 보인다.

보이는 것: docs/ 맨 위 · 재난온톨로지 · 아이디어 · 산사태. docs/api 는 뺀다(키 관리 사이트 · 계정 이름이 적혀 있다).
변환기는 이 문서들이 쓰는 만큼만 — 머리말(frontmatter) · 제목 · 문단 · 목록(두 단) · 표 · 코드 · 인용/콜아웃(> [!note]) ·
굵게 · 기울임 · `코드` · [링크](주소) · [[위키링크|별칭]](같은 이름 문서가 있으면 그 문서로, 없으면 위키 표시만). HTML 은 모두 걸러 낸다.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

from . import config

DOCS = config.ROOT / "docs"
SHOW = ("", "재난온톨로지", "아이디어", "산사태")         # docs/ 아래 이 폴더들만(""= 맨 위)
CALLOUT = {"note": "참고", "info": "알림", "tip": "도움", "important": "중요", "warning": "주의", "caution": "주의",
           "danger": "위험", "example": "예", "question": "물음", "summary": "요약", "abstract": "요약", "todo": "할 일"}


def _files() -> list[Path]:
    out = []
    for sub in SHOW:
        d = DOCS / sub if sub else DOCS
        out += sorted(p for p in d.glob("*.md") if p.is_file())
    return out


def _front(text: str) -> tuple[dict, str]:
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n", text, re.S)
    if not m:
        return {}, text
    meta = {}
    for line in m.group(1).splitlines():
        if ":" in line and not line.startswith(" "):
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta, text[m.end():]


def _title(meta: dict, body: str, p: Path) -> str:
    h = re.search(r"^#\s+(.+)$", body, re.M)
    return h.group(1).strip() if h else p.stem


def listing() -> list[dict]:
    out = []
    for p in _files():
        meta, body = _front(p.read_text("utf-8", errors="replace"))
        rel = p.relative_to(DOCS).as_posix()
        out.append({"path": rel, "group": rel.split("/")[0] if "/" in rel else "대시보드", "title": _title(meta, body, p),
                    "summary": meta.get("summary", ""), "updated": meta.get("updated", "")})
    return out


def _inline(s: str, names: dict[str, str]) -> str:
    s = html.escape(s, quote=False)
    code: list[str] = []

    def keep(m):
        code.append(m.group(1))
        return f"\x00{len(code) - 1}\x00"
    s = re.sub(r"`([^`]+)`", keep, s)

    def wiki(m):
        target, alias = m.group(1), m.group(2)
        name = target.split("#")[0].strip()
        label = alias or target.replace("#", " › ")        # 이미 걸러 낸 글이라 다시 거르지 않는다
        if name in names:
            return f'<a href="#doc={html.escape(names[name])}" class="wl">{label}</a>'
        return f'<span class="wk" title="위키 문서">{label}</span>'
    s = re.sub(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]", wiki, s)
    s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", lambda m: f'<a href="{m.group(2)}" target="_blank" rel="noopener">{m.group(1)}</a>', s)
    s = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"(?<![*\w])\*([^*\s][^*]*?)\*(?!\*)", r"<i>\1</i>", s)
    return re.sub(r"\x00(\d+)\x00", lambda m: f"<code>{code[int(m.group(1))]}</code>", s)


def _table(rows: list[str], names) -> str:
    cells = [[c.strip() for c in r.strip().strip("|").split("|")] for r in rows]
    head, body = cells[0], [r for r in cells[2:]] if len(cells) > 1 and set("".join(cells[1])) <= set("-: ") else cells[1:]
    th = "".join(f"<th>{_inline(c, names)}</th>" for c in head)
    tb = "".join("<tr>" + "".join(f"<td>{_inline(c, names)}</td>" for c in r) + "</tr>" for r in body)
    return f'<div class="tw"><table><thead><tr>{th}</tr></thead><tbody>{tb}</tbody></table></div>'


def render(text: str, names: dict[str, str] | None = None) -> str:
    """마크다운 → HTML(위의 부분만). names = {문서 이름: 경로} — 위키링크를 문서 링크로."""
    names = names or {}
    lines = text.splitlines()
    out: list[str] = []
    i = 0
    para: list[str] = []

    def flush():
        if para:
            out.append(f"<p>{_inline(' '.join(x.strip() for x in para), names)}</p>")
            para.clear()
    while i < len(lines):
        ln = lines[i]
        st = ln.strip()
        if st.startswith("```"):
            flush()
            j = i + 1
            while j < len(lines) and not lines[j].strip().startswith("```"):
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(lines[i + 1:j])) + "</code></pre>")
            i = j + 1
            continue
        if not st:
            flush(); i += 1
            continue
        if m := re.match(r"^(#{1,4})\s+(.+)$", st):
            flush()
            n = len(m.group(1))
            out.append(f"<h{n + 1}>{_inline(m.group(2), names)}</h{n + 1}>")
            i += 1
            continue
        if re.match(r"^(-{3,}|\*{3,})$", st):
            flush(); out.append("<hr>"); i += 1
            continue
        if st.startswith("|"):
            flush()
            j = i
            while j < len(lines) and lines[j].strip().startswith("|"):
                j += 1
            out.append(_table(lines[i:j], names))
            i = j
            continue
        if st.startswith(">"):
            flush()
            j = i
            while j < len(lines) and lines[j].strip().startswith(">"):
                j += 1
            inner = [re.sub(r"^\s*>\s?", "", x) for x in lines[i:j]]
            m = re.match(r"^\[!(\w+)\][+-]?\s*(.*)$", inner[0].strip()) if inner else None
            if m:
                kind = m.group(1).lower()
                head = m.group(2) or CALLOUT.get(kind, kind)
                out.append(f'<div class="co {html.escape(kind)}"><div class="co-h">{_inline(head, names)}</div>{render(chr(10).join(inner[1:]), names)}</div>')
            else:
                out.append(f"<blockquote>{render(chr(10).join(inner), names)}</blockquote>")
            i = j
            continue
        if re.match(r"^\s*([-*+]|\d+\.)\s+", ln):
            flush()
            j, items = i, []
            while j < len(lines) and (re.match(r"^\s*([-*+]|\d+\.)\s+", lines[j]) or (lines[j].startswith("  ") and lines[j].strip() and items)):
                m = re.match(r"^(\s*)([-*+]|\d+\.)\s+(.*)$", lines[j])
                if m:
                    items.append([len(m.group(1).expandtabs(4)) >= 2, m.group(2)[0].isdigit(), m.group(3)])
                else:
                    items[-1][2] += " " + lines[j].strip()
                j += 1
            tag = "ol" if items[0][1] else "ul"
            buf, sub = [f"<{tag}>"], None
            for deep, num, txt in items:
                if deep and buf[-1].endswith("</li>"):
                    if sub is None:
                        sub = "ol" if num else "ul"
                        buf[-1] = buf[-1][:-5] + f"<{sub}>"
                    buf.append(f"<li>{_inline(txt, names)}</li>")
                    continue
                if sub:
                    buf.append(f"</{sub}></li>"); sub = None
                buf.append(f"<li>{_inline(txt, names)}</li>")
            if sub:
                buf.append(f"</{sub}></li>")
            buf.append(f"</{tag}>")
            out.append("".join(buf))
            i = j
            continue
        para.append(ln)
        i += 1
    flush()
    return "\n".join(out)


def view(rel: str) -> dict | None:
    """보이는 문서 하나 → {path, title, meta, html}. 목록에 없는 경로는 None(경로 장난 막기)."""
    files = {p.relative_to(DOCS).as_posix(): p for p in _files()}
    p = files.get(rel)
    if not p:
        return None
    meta, body = _front(p.read_text("utf-8", errors="replace"))
    names = {q.stem: k for k, q in files.items()}
    return {"path": rel, "title": _title(meta, body, p), "summary": meta.get("summary", ""), "updated": meta.get("updated", ""),
            "html": render(body, names)}

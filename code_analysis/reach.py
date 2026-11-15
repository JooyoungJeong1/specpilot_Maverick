"""③ 근거 재확인용 도달 정보: 화면마다 실제 처리 과정에서 닿는 메서드·파일, 미사용 코드 위치.

사실(facts)은 ③ 프롬프트에 들어가 "어느 코드를 볼지" 알려 주는 용도이고, 이 정보는 프롬프트에 넣지 않는다.
③이 판정을 받은 뒤 프로그램이 근거 줄을 다시 확인할 때 쓴다 (backend/specpilot/grounding.py).

- methods: 이 코드의 모든 메서드와 줄 범위 (근거 줄이 어느 메서드 안인지 찾는 데 씀)
- screens: 화면 → 그 화면의 템플릿·JS·경로에서 콜그래프로 이어지는 메서드 이름, 관련 파일
  (화면 → 폼·링크·JS가 부르는 경로 → Controller → Service → Repository. 화면별 사실 나누기와 같은 고리를 쓴다)
- unused: 어디에서도 부르지 않는 경로의 처리 메서드, 어떤 컨트롤러도 반환하지 않는 템플릿 (미사용 후보)

LLM을 쓰지 않는다.
"""
from __future__ import annotations

import re

from .facts import Fact

_STRING = re.compile(r'"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'')


def method_end(lines: list[str], start: int) -> int:
    """start줄(메서드 선언)부터 중괄호 짝을 세어 메서드가 끝나는 줄을 찾는다. 몸체가 없으면 start."""
    depth, opened, in_block = 0, False, False
    for i in range(start - 1, len(lines)):
        s = _STRING.sub('""', lines[i])
        j = 0
        while j < len(s):
            if in_block:
                k = s.find("*/", j)
                if k < 0:
                    break
                in_block, j = False, k + 2
                continue
            two = s[j:j + 2]
            if two == "//":
                break
            if two == "/*":
                in_block, j = True, j + 2
                continue
            ch = s[j]
            if ch == "{":
                depth, opened = depth + 1, True
            elif ch == "}":
                depth -= 1
                if opened and depth == 0:
                    return i + 1
            elif ch == ";" and not opened:
                return i + 1          # 몸체 없는 선언 (인터페이스·추상 메서드)
            j += 1
    return len(lines)


def build_reach(fb, splitter, facts: list[Fact]) -> dict:
    """fb: FactsBuilder, splitter: 화면별 고리를 만든 ScreenSplitter."""
    m, code = fb.m, fb.code
    methods, by_q = [], {}
    for c in m.classes:
        lines = code.files.get(c.file)
        if lines is None:
            continue
        for mt in c.methods:
            if not mt.has_body:
                continue
            item = {"name": mt.qname, "file": c.file, "start": min(mt.ann_line, mt.line),
                    "end": method_end(lines, mt.line)}
            methods.append(item)
            by_q.setdefault(mt.qname, []).append(item)
    methods.sort(key=lambda x: (x["file"], x["start"]))

    screens = {}
    for sid, anchors in sorted(splitter.anchors.items()):
        names = sorted(a[len("method:"):] for a in anchors if a.startswith("method:"))
        files = {a[len("file:"):] for a in anchors if a.startswith("file:")}
        for n in names:
            files |= {x["file"] for x in by_q.get(n, [])}
            c = m.find(n.split(".")[0])          # 몸체 없는 메서드(Spring Data 저장소, 인터페이스)는 선언한 파일
            if c is not None:
                files.add(c.file)
        for a in anchors:
            if a.startswith("class:"):
                c = m.find(a[len("class:"):])
                if c is not None:
                    files.add(c.file)
            elif a.startswith("view:"):                      # 포함 조각(레이아웃 등)도 그 화면이 그리는 파일
                t = m.templates.get(a[len("view:"):])
                for inc in (t or {}).get("includes", []):
                    it = m.templates.get(inc.get("view", "").strip("/"))
                    if it:
                        files.add(it["file"])
        if names or files:
            screens[sid] = {"methods": names, "files": sorted(f for f in files if f in code.files)}

    unused = []
    for f in facts:
        if f.kind != "unused":
            continue
        if f.file.endswith(".java"):
            r = next((r for r in m.routes if r["file"] == f.file and r["line"] == f.line), None)
            mt = m.route_method(r) if r else None
            if mt is not None:
                unused.append({"file": f.file, "start": min(mt.ann_line, mt.line),
                               "end": method_end(code.files[f.file], mt.line), "label": f.fact})
        else:
            unused.append({"file": f.file, "start": 1, "end": len(code.files[f.file]), "label": f.fact})
    return {"methods": methods, "screens": screens, "unused": unused}

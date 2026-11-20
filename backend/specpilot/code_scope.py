"""③ 화면별 코드 묶음 고르기 (프로그램, LLM 호출 없음).

코드가 SPECPILOT_CODE_TOKEN_LIMIT보다 커서 화면별 묶음(screen 방식)으로 판정할 때, 화면마다 넣을 파일을 고른다.
전에는 LLM이 파일 목록을 보고 골랐는데(code_select), ③에 LLM 호출이 하나 더 생기고 고른 근거를 다시 확인할 수 없었다.
지금은 아래 순서로 프로그램이 고르고, 파일마다 왜 들어갔는지(why)를 judge/code_map.json에 남긴다.

1. 씨앗 (그 화면에서 출발할 파일)
   - code_analysis의 도달 정보 reach (judge --facts): 화면 → 폼·링크·JS가 부르는 경로 → Controller → Service → Repository
   - 문구 검색: 단위의 exact 문구·대상·값, 화면 이름의 앞부분(공백·기호 뺀 6글자)이 들어 있는 파일
   - 팝업·반복 화면은 부모 화면(repeats_from, 이름의 괄호 앞, 같은 depth의 앞 화면)의 씨앗도 쓴다. 팝업은 부모 템플릿 안에 있다
2. 참조 따라가기 (씨앗에서 3단계까지)
   - 템플릿 → 불러오는 JS·CSS, 포함 조각(th:replace·th:insert·layout:decorate), 그 화면 이름(view)을 반환하는 Java 파일
   - Java → 본문에 이름이 나오는 이 프로젝트의 클래스 (Controller → Service·Form·DTO → Repository·Entity), 인터페이스면 구현 클래스
   - 씨앗이 Java면 그 클래스를 쓰는 Java로 한 번 거슬러 올라간다 (문구가 서비스·폼에만 있을 때 컨트롤러 → 템플릿까지 가도록)
3. 공통 파일: 보안·설정(@Configuration, SecurityFilterChain), 전역 예외 처리(@ControllerAdvice), application.yml/properties
4. 크기 제한: 화면 묶음이 토큰 제한을 넘으면 먼 참조(깊이가 큰 파일)부터 뺀다. 뺀 파일은 dropped에 남긴다

judge/code_map.json은 사람이 고쳐도 되고, 있으면 다시 만들지 않는다.
"""
from __future__ import annotations

import re
from pathlib import PurePosixPath

from .code_prep import Codebase, files_mentioning

MAX_DEPTH = 3

JAVA_EXT = (".java", ".kt")
TEMPLATE_EXT = (".html", ".htm")
CLASS_NAME = re.compile(r"\b[A-Z][A-Za-z0-9_]*\b")
STRING_LIT = re.compile(r'"([^"\\\n]{1,120})"')
ASSET_REF = re.compile(r'(?:src|href)\s*=\s*"(?:@\{)?([^"{}$]+?\.(?:js|css))[^"]*"')
FRAGMENT_REF = re.compile(r'(?:th:replace|th:insert|th:include|layout:decorate|layout:decorator)\s*=\s*"(?:~\{)?\s*([\w/.-]+)')
IMPLEMENTS = re.compile(r"\bimplements\s+([\w\s,<>.]+?)\s*\{")
COMMON_SIGNS = ("@Configuration", "@EnableWebSecurity", "SecurityFilterChain", "@ControllerAdvice",
                "@RestControllerAdvice", "WebMvcConfigurer")


class RefGraph:
    """파일 사이 참조. 프로그램이 정규식으로 만든다 (code_analysis가 없어도 돈다)."""

    def __init__(self, cb: Codebase):
        self.cb = cb
        self.classes: dict[str, str] = {}          # 클래스 이름(파일 이름) → 경로
        self.views: dict[str, str] = {}            # 화면 이름(templates/ 아래 경로, 확장자 없이) → 경로
        self.assets: list[str] = [p for p in cb.files if p.endswith((".js", ".css"))]
        for p in cb.files:
            pp = PurePosixPath(p)
            if p.endswith(JAVA_EXT):
                self.classes.setdefault(pp.stem, p)
            elif p.endswith(TEMPLATE_EXT) and "templates/" in p:
                self.views[p.split("templates/", 1)[1].rsplit(".", 1)[0]] = p
        self.forward: dict[str, set[str]] = {p: self._refs(p) for p in cb.files}
        self.users: dict[str, set[str]] = {}       # Java 파일 → 그 클래스를 쓰는 Java 파일 (씨앗에서 한 번만 거꾸로 따라감)
        for p, refs in self.forward.items():
            if p.endswith(JAVA_EXT):
                for r in refs:
                    if r.endswith(JAVA_EXT):
                        self.users.setdefault(r, set()).add(p)
        self.view_users: dict[str, set[str]] = {}  # 템플릿 → 그 화면 이름을 쓰는 Java (컨트롤러)
        self.impls: dict[str, set[str]] = {}       # 인터페이스 파일 → 구현 클래스 파일
        for p, lines in cb.files.items():
            if not p.endswith(JAVA_EXT):
                continue
            text = "\n".join(lines)
            for lit in STRING_LIT.findall(text):
                t = self.views.get(lit.strip("/"))
                if t:
                    self.view_users.setdefault(t, set()).add(p)
            for grp in IMPLEMENTS.findall(text):
                for name in CLASS_NAME.findall(grp):
                    if name in self.classes:
                        self.impls.setdefault(self.classes[name], set()).add(p)

    def _refs(self, p: str) -> set[str]:
        lines = self.cb.files[p]
        out: set[str] = set()
        if p.endswith(JAVA_EXT):
            me = PurePosixPath(p).stem
            for line in lines:
                s = line.strip()
                if s.startswith(("import ", "package ", "//", "*", "/*")):
                    continue
                for name in CLASS_NAME.findall(s):
                    if name != me and name in self.classes:
                        out.add(self.classes[name])
                for lit in STRING_LIT.findall(s):            # return "notice/form" 처럼 반환하는 화면
                    t = self.views.get(lit.strip("/"))
                    if t:
                        out.add(t)
        elif p.endswith(TEMPLATE_EXT):
            text = "\n".join(lines)
            for ref in ASSET_REF.findall(text):
                tail = ref.strip().lstrip("/")
                out |= {a for a in self.assets if a.endswith("/" + tail) or a.endswith(tail)}
            for ref in FRAGMENT_REF.findall(text):
                t = self.views.get(ref.strip().strip("/").split("::")[0].strip())
                if t:
                    out.add(t)
        out.discard(p)
        return out

    def neighbors(self, p: str) -> set[str]:
        return self.forward.get(p, set()) | self.view_users.get(p, set()) | self.impls.get(p, set())


def common_files(cb: Codebase) -> list[str]:
    out = []
    for p, lines in cb.files.items():
        name = PurePosixPath(p).name
        if name.startswith("application") and name.endswith((".yml", ".yaml", ".properties")):
            out.append(p)
        elif p.endswith(JAVA_EXT) and any(sign in line for line in lines for sign in COMMON_SIGNS):
            out.append(p)
    return sorted(out)


def _unit_phrases(units: list[dict]) -> list[str]:
    out = []
    for u in units:
        ex = u.get("exact") or {}
        out += [ex.get("message"), ex.get("target")] + [v for v in (ex.get("values") or []) if isinstance(v, str)]
    return [p for p in dict.fromkeys(out) if p]


def parent_of(screen: dict, screens: list[dict]) -> str | None:
    """팝업·반복 화면의 부모: repeats_from → 이름의 괄호 앞과 같은 화면 → 같은 depth의 바로 앞 화면."""
    rf = screen.get("repeats_from") or {}
    if rf.get("screen_id"):
        return rf["screen_id"]
    if screen.get("type") != "팝업":
        return None
    base = re.split(r"[(（]", screen.get("name") or "")[0].strip()
    for s in screens:
        if s is not screen and s.get("type") != "팝업" and (s.get("name") or "").strip() == base:
            return s["screen_id"]
    prev = None
    for s in screens:
        if s is screen:
            return prev
        if s.get("type") != "팝업" and s.get("depth") == screen.get("depth"):
            prev = s["screen_id"]
    return None


def select(cb: Codebase, requirements: dict, units: dict[str, list[dict]], reach=None,
           token_limit: int = 100_000) -> dict:
    """화면마다 파일과 들어간 이유. 반환 형식은 judge/code_map.json."""
    graph = RefGraph(cb)
    common = common_files(cb)
    screens = list(requirements.get("app_profile", {}).get("screens", []))
    sids = [s["screen_id"] for s in screens] + [sid for sid in units if sid not in {s["screen_id"] for s in screens}]
    by_id = {s["screen_id"]: s for s in screens}

    seeds: dict[str, dict[str, str]] = {}
    for sid in sids:
        why: dict[str, str] = {}
        if reach is not None and sid in getattr(reach, "screens", {}):
            for f in reach.screens[sid]["files"]:
                if f in cb.files:
                    why.setdefault(f, "정적 분석: 화면에서 처리 과정으로 닿음")
        phrases = _unit_phrases(units.get(sid, []))
        name = (by_id.get(sid) or {}).get("name")
        for f in sorted(files_mentioning(cb, phrases)):
            why.setdefault(f, "문구 검색: 단위 문구가 들어 있음")
        if name:
            for f in sorted(files_mentioning(cb, [re.split(r"[(（]", name)[0]])):
                why.setdefault(f, f"문구 검색: 화면 이름 '{name}'")
        seeds[sid] = why
    for sid in sids:                       # 팝업은 부모 화면 템플릿 안에 있다
        parent = parent_of(by_id[sid], screens) if sid in by_id else None
        if parent and parent in seeds:
            for f in list(seeds[parent]):
                seeds[sid].setdefault(f, f"부모 화면 {parent}")

    sizes: dict[str, int] = {}

    def size(f: str) -> int:                # 파일 하나가 묶음에서 차지하는 토큰 (머리글·줄 번호 포함)
        if f not in sizes:
            sizes[f] = cb.tokens([f])
        return sizes[f]

    mapping, dropped = [], {}
    common_set = set(common)
    for sid in sids:
        why = dict(seeds[sid])
        depth = {f: 0 for f in why}
        frontier = list(why)
        for d in range(1, MAX_DEPTH + 1):
            nxt = []
            for f in frontier:
                near = graph.neighbors(f)
                if d == 1:                          # 문구가 서비스·폼에만 있으면 그것을 쓰는 컨트롤러로 거슬러 올라가 화면까지 간다
                    near = near | graph.users.get(f, set())
                for n in sorted(near):
                    if n not in depth:
                        depth[n] = d
                        a, b = PurePosixPath(f).name, PurePosixPath(n).name
                        why[n] = f"참조: {a} → {b}" if n in graph.neighbors(f) else f"사용처: {b}가 {a}를 씀"
                        nxt.append(n)
            frontier = nxt
        files = [f for f in why if f not in common_set]
        # 크기 제한: 먼 참조부터 뺀다 (씨앗은 남김)
        out: list[str] = []
        used = sum(size(f) for f in common)
        for f in sorted(files, key=lambda f: (depth[f], f)):
            if depth[f] > 0 and used + size(f) > token_limit:
                dropped.setdefault(sid, []).append(f)
                continue
            out.append(f)
            used += size(f)
        if not out and not why:
            continue
        mapping.append({"screen_id": sid, "files": sorted(out), "why": {f: why[f] for f in sorted(out)}})
    return {"source": "program", "mapping": mapping, "common_files": common, "dropped_over_limit": dropped,
            "unmapped_screens": [sid for sid in sids if not seeds[sid]]}

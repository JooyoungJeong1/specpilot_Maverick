"""여러 파일을 맞대 봐야 나오는 사실.

- 컨트롤러가 화면에 넘긴 모델 값을 그 템플릿(과 포함한 조각)이 실제로 출력하는지 (2주차 분석기의 Controller-템플릿 연결)
- 입력값 검사(@Valid)에 실패해 다시 보여 주는 화면에 검증 오류를 출력하는 곳이 있는지
- 템플릿이 불러오는 JS, JS가 어떤 요소에 어떤 이벤트를 붙였는지
- 어디서도 부르지 않는 경로·템플릿, 처리하는 곳이 없는 링크
"""
from __future__ import annotations

import re

from .codebase import Code
from .facts import Fact
from .java_facts import JavaFacts, Route, short
from .web_facts import (NOTABLE_INPUT_ATTRS, NOTABLE_INPUT_TYPES, JsAnalyzer, JsFile, Template, is_template,
                        norm_url, parse_template)

MESSAGE_LIKE = re.compile(r"(error|message|msg|alert|success|exists)", re.I)
WATCHED_EVENTS = ("blur", "focusout", "submit")


def _route_pattern(path: str) -> str:
    p = re.sub(r"\{[^}]*\}", "{}", path)
    p = p.split("?")[0]
    return p.rstrip("/") or "/"


def _match(pattern: str, url: str) -> bool:
    """/notices/{} 와 /notices/{} 또는 /notices/3 처럼 경로 조각이 맞는지. 보안 설정의 * 와 ** 도 받는다."""
    a, b = pattern.strip("/").split("/"), url.strip("/").split("/")
    if "**" in a:
        i = a.index("**")
        return b[:i] == a[:i] or all(x in ("{}", "*") or x == y for x, y in zip(a[:i], b[:i]))
    if len(a) != len(b):
        return False
    return all(x == y or x in ("{}", "*") or y == "{}" for x, y in zip(a, b))


class Linker:
    def __init__(self, code: Code, jf: JavaFacts):
        self.code = code
        self.jf = jf
        self.templates: dict[str, Template] = {}       # 뷰 이름 → 템플릿
        for p in code.files:
            if is_template(p):
                t = parse_template(code, p)
                self.templates[t.view] = t
        js = JsAnalyzer(code)
        self.js: dict[str, JsFile] = {p: js.analyze(p) for p in code.by_suffix(".js")}
        self.facts: list[Fact] = []
        self.js_users: dict[str, list[str]] = {}       # JS 경로 → 그 JS를 불러오는 템플릿 경로

    def run(self) -> "Linker":
        self._scripts()
        self._bindings()
        self._html()
        self._js()
        self._unused_and_unhandled()
        self._error_pages()
        return self

    # ------------------------------------------------ 도우미

    def template_of(self, view: str) -> Template | None:
        return self.templates.get(view.strip("/"))

    def with_fragments(self, t: Template) -> list[Template]:
        out, todo, seen = [t], [v for v, _ in t.includes], {t.view}
        while todo:
            v = todo.pop()
            if v in seen:
                continue
            seen.add(v)
            ft = self.template_of(v)
            if ft is not None:
                out.append(ft)
                todo += [x for x, _ in ft.includes]
        return out

    def js_path(self, url: str) -> str | None:
        u = norm_url(url)
        if not u:
            return None
        hits = [p for p in self.js if p.endswith("static" + u) or p.endswith(u)]
        return hits[0] if hits else None

    # ------------------------------------------------ 템플릿 → JS

    def _scripts(self):
        for t in self.templates.values():
            for url, _ in t.scripts:
                jp = self.js_path(url)
                if jp:
                    self.js_users.setdefault(jp, []).append(t.path)

    # ------------------------------------------------ 컨트롤러 → 템플릿 모델 값

    def _bindings(self):
        for r in self.jf.routes:
            for ret in r.views():
                t = self.template_of(ret.value)
                if t is None:
                    self.facts.append(Fact("template", r.method.file, ret.line,
                                           f"{r.label} {ret.context}: 반환하는 화면 {ret.value}의 템플릿 파일이 없음",
                                           anchors={f"route:{r.label}"}))
                    continue
                parts = self.with_fragments(t)
                shown = ", ".join(x.view for x in parts[1:])
                where = f"{t.view} 템플릿" + (f"(포함 조각 {shown})" if shown else "")
                for a in self._attrs_reaching(r, ret.context):
                    refs = [(x.path, line, src) for x in parts for line, src in x.refers(a.name)]
                    related = {t.path}
                    if not refs:
                        how = "(@ModelAttribute로 자동으로 넣는 값)" if a.implicit else ""
                        self.facts.append(Fact(
                            "template", a.file, a.line,
                            f"{r.label} {ret.context}: 모델 값 {a.name}{how}을(를) {ret.value} 화면에 넘기지만 "
                            f"{where} 어디에서도 출력하지 않음", related=related, anchors={f"route:{r.label}"}))
                    elif MESSAGE_LIKE.search(a.name) and not a.implicit:
                        p, line, src = refs[0]
                        self.facts.append(Fact(
                            "template", p, line,
                            f"{r.label} {ret.context}: 모델 값 {a.name} 출력 위치 {p.split('templates/')[-1]} {line}줄 ({short(src, 60)})",
                            related=related, anchors={f"route:{r.label}"}))
                if ret.context.startswith("입력값 검사 실패") and r.valid_params:
                    self._error_output(r, ret, t, parts)

    def _attrs_reaching(self, r: Route, ctx: str):
        seen, out = set(), []
        for a in r.attrs:
            if a.flash:
                continue
            if a.implicit or a.context in ("정상 흐름", ctx) or ctx.startswith(a.context):
                if a.name not in seen:
                    seen.add(a.name)
                    out.append(a)
        return out

    def _error_output(self, r: Route, ret, t: Template, parts: list[Template]):
        outs = [(x.path, line, src) for x in parts for line, src in x.error_outputs]
        forms = ", ".join(p.type for p in r.valid_params)
        line = r.hasErrors_line or ret.line
        related = {t.path}
        anchors = {f"route:{r.label}"}
        if not outs:
            self.facts.append(Fact(
                "template", r.method.file, line,
                f"{r.label}: @Valid {forms} 검사에 실패하면 {t.view} 화면을 다시 보여 주지만, 이 템플릿"
                f"{'과 포함 조각' if len(parts) > 1 else ''}에 검증 오류를 출력하는 곳(th:errors, #fields.errors 등)이 없음. "
                f"애노테이션 메시지가 화면에 나오지 않음", related=related, anchors=anchors))
        else:
            fields = [re.sub(r'.*\*\{(\w+)\}.*', r"\1", s) for _, _, s in outs if "th:errors" in s]
            desc = f"th:errors {len(fields)}곳({', '.join(fields)})" if fields else f"{len(outs)}곳"
            self.facts.append(Fact(
                "template", outs[0][0], outs[0][1],
                f"{r.label}: @Valid {forms} 검사에 실패하면 {t.view} 화면을 다시 보여 주고, 검증 오류를 {desc}에서 출력",
                related=related, anchors=anchors))
        if r.rejects and not any("global" in s.lower() for _, _, s in outs):
            self.facts.append(Fact(
                "template", r.method.file, r.rejects[0],
                f"{r.label}: 서비스 예외를 BindingResult 전역 오류(reject)로 넣지만 {t.view} 템플릿에 전역 오류를 출력하는 곳"
                f"(#fields.globalErrors 등)이 없음", related=related, anchors=anchors))

    # ------------------------------------------------ HTML 구조

    def _html(self):
        for t in self.templates.values():
            for line, a in t.inputs:
                typ = (a.get("type") or "").lower()
                notable = [k for k in NOTABLE_INPUT_ATTRS if k in a]
                if typ not in NOTABLE_INPUT_TYPES and not notable:
                    continue
                name = a.get("id") or a.get("name") or a.get("th:field") or typ
                bits = []
                if typ in NOTABLE_INPUT_TYPES:
                    bits.append(f"type={typ}" + (" (브라우저 날짜·시간 선택기)" if typ in ("date", "datetime-local", "month", "time")
                                                 else " (브라우저 기본 형식 검사: 제출할 때 동작하고 문구는 브라우저가 정함)"))
                for k in notable:
                    v = a[k]
                    bits.append({"required": "required (비어 있으면 브라우저가 제출을 막음)",
                                 "maxlength": f"maxlength={v} (그 이상은 입력되지 않음)",
                                 "minlength": f"minlength={v} (브라우저가 제출할 때 검사)",
                                 "pattern": f"pattern={v} (브라우저가 제출할 때 검사)",
                                 "readonly": "readonly (수정할 수 없음)",
                                 "disabled": "disabled (처음부터 비활성)",
                                 "min": f"min={v}", "max": f"max={v}"}[k])
                self.facts.append(Fact("html", t.path, line, f"입력란 {name}: {', '.join(bits)}"))
            for c in t.controls:
                cond = next((c.attrs[k] for k in ("th:if", "th:unless", "sec:authorize", "data-th-if") if k in c.attrs), None)
                confirm = next((c.attrs[k] for k in ("onclick", "onsubmit") if "confirm(" in c.attrs.get(k, "")), None)
                if not cond and not confirm:
                    continue
                label = c.text or c.attrs.get("value") or c.attrs.get("id") or c.tag
                what = {"a": "링크", "button": "버튼", "form": "폼"}[c.tag]
                url = norm_url(c.attrs.get("th:action") or c.attrs.get("action") or c.attrs.get("th:href") or c.attrs.get("href"))
                bits = []
                if cond:
                    key = "th:unless" if "th:unless" in c.attrs else "조건"
                    bits.append(f"{cond} {'아닐 때만' if key == 'th:unless' else '일 때만'} 보임")
                if confirm:
                    bits.append(f"누르면 확인 창({short(confirm, 40)})")
                self.facts.append(Fact("html", t.path, c.line,
                                       f"{what} '{short(label, 30)}'{f'({url})' if url else ''}: {', '.join(bits)}"))

    # ------------------------------------------------ JS

    def _js(self):
        for path, jf in self.js.items():
            users = sorted(self.js_users.get(path, []))
            for b in jf.user_bindings():
                eff = "; ".join(b.effects) if b.effects else "효과를 정적으로 찾지 못함"
                # 여러 화면이 같이 쓰는 JS면, 대상 요소가 실제로 있는 템플릿에만 이 이벤트를 붙인다
                having = [u for u in users if self._has_element(u, b.target)
                          and (not b.effect_targets or any(self._has_element(u, x) for x in b.effect_targets))]
                where = ""
                if len(users) > 1 and having:
                    where = f" (대상 요소가 있는 템플릿: {', '.join(u.split('templates/')[-1] for u in having)})"
                elif len(users) > 1 and not having:
                    having = users
                self.facts.append(Fact("js", path, b.line,
                                       f"{b.target} {b.event} 이벤트 → {b.handler}: {eff}{where}",
                                       related=set(having) | {path}, anchor_self=not users))
            events = sorted(jf.events - {"DOMContentLoaded", "load", "readystatechange"})
            missing = [e for e in WATCHED_EVENTS if e not in jf.events]
            name = path.split("/")[-1]
            summary = f"{name}: 붙이는 이벤트 {', '.join(events) or '없음'}"
            if missing:
                summary += f" ({'·'.join(missing)} 이벤트 없음)"
            summary += ". 정규식 " + ("있음" if jf.has_regex else "없음")
            calls = [f"{m} {u}" for m, u, _, kind in jf.url_refs]
            if calls:
                summary += ". 서버 요청·이동: " + ", ".join(dict.fromkeys(calls))
            if users:
                summary += f". 이 파일을 불러오는 템플릿 {len(users)}개: {', '.join(u.split('templates/')[-1] for u in users)}"
            self.facts.append(Fact("js", path, 1, summary, related={path} | set(users)))

    def _has_element(self, template_path: str, target: str) -> bool:
        text = self.code.text(template_path)
        for sel in target.replace("의 각 요소", "").split(","):
            sel = sel.strip()
            if sel.startswith("#") and re.search(r'\bid\s*=\s*["\']' + re.escape(sel[1:]) + r'["\']', text):
                return True
            if sel.startswith(".") and re.search(r'class\s*=\s*["\'][^"\']*\b' + re.escape(sel[1:]) + r'\b', text):
                return True
            if re.fullmatch(r"[a-zA-Z][\w-]*", sel) and f"<{sel.lower()}" in text.lower():     # 태그 선택자 (input 등)
                return True
            if sel and not re.fullmatch(r"[#.]?[\w-]+", sel):                                 # 복합 선택자는 판단하지 않고 있다고 본다
                return True
        return False

    # ------------------------------------------------ 미사용·처리하는 곳 없음

    def _refs(self):
        refs = []        # (메서드, 경로, 파일, 줄, 종류)
        for t in self.templates.values():
            refs += [(m, u, t.path, line, kind) for m, u, line, kind in t.url_refs]
        for path, jf in self.js.items():
            refs += [(m, u, path, line, kind) for m, u, line, kind in jf.url_refs]
        for r in self.jf.routes:
            refs += [("GET", norm_url(x.value), r.method.file, x.line, "redirect") for x in r.returns
                     if x.kind == "redirect" and norm_url(x.value)]
        for f in self.jf.facts:
            if f.kind == "security":
                for u in re.findall(r"(?:성공 시 항상|성공 시.*?없으면|실패 시) (/[\w/\-?=]*)", f.fact):
                    refs.append(("GET", norm_url(u), f.file, f.line, "보안 설정"))
                m = re.search(r"로그인 화면 주소 (/\S+)\.", f.fact)
                if m:
                    refs.append(("GET", norm_url(m.group(1)), f.file, f.line, "보안 설정"))
        return [x for x in refs if x[1]]

    def _unused_and_unhandled(self):
        refs = self._refs()
        for r in self.jf.routes:
            pats = [_route_pattern(p) for p in r.paths]
            if not any(_match(p, u) for p in pats for _, u, *_ in refs):
                self.facts.append(Fact("unused", r.method.file, r.line,
                                       f"{r.label}({r.method.qname}): 템플릿·JS·리다이렉트·보안 설정 어디에서도 이 주소를 부르지 않음 (미사용 후보)",
                                       anchors={f"route:{r.label}"}))
        handled = [(r.http, _route_pattern(p)) for r in self.jf.routes for p in r.paths]
        handled += [tuple(x.split(" ", 1)) for x in self.jf.security_urls]
        static_prefixes = ("/css/", "/js/", "/images/", "/img/", "/static/", "/webjars/", "/favicon", "/h2-console")
        for method, url, path, line, kind in refs:
            if kind in ("보안 설정",) or url.startswith(static_prefixes) or url == "/error":
                continue
            if url.startswith("/oauth2/") and self.jf.oauth2_login:
                continue
            same_path = [h for h in handled if _match(h[1], url)]
            if not same_path:
                note = " (보안 설정에 oauth2Login 없음)" if url.startswith("/oauth2/") else ""
                self.facts.append(Fact("html" if not path.endswith(".java") else "route", path, line,
                                       f"{kind} {method} {url}: 이 주소를 처리하는 컨트롤러나 보안 설정이 없음{note}"))
        returned = {v.strip("/") for v in self.jf.views_returned}
        included = {v for t in self.templates.values() for v, _ in t.includes}
        for t in self.templates.values():
            if t.view in returned or t.view in included or t.provides_fragment or t.view.startswith("error"):
                continue
            self.facts.append(Fact("unused", t.path, 1,
                                   f"{t.view}: 어떤 컨트롤러도 이 화면을 반환하지 않고 다른 템플릿에 포함되지도 않음 (미사용 후보)"))

    def _error_pages(self):
        errs = sorted(t.path for t in self.templates.values() if t.view.startswith("error/"))
        if errs:
            names = ", ".join(p.split("/")[-1] for p in errs)
            self.facts.append(Fact("global", errs[0], 1,
                                   f"templates/error/ 의 {names}: 컨트롤러 없이 오류 상태 코드에 맞춰 Spring Boot가 보여 주는 화면"
                                   " (403, 404, 500 등은 파일 이름으로 고름)"))

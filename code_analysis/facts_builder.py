"""백엔드 분석 결과(Java 분석기)와 JS 분석 결과(analyze_frontend_js)로 ③에 줄 사실 문장을 만든다."""
from __future__ import annotations

import re

from .analyze_frontend_js import PAGE_EVENTS, norm_url as js_norm_url, user_bindings
from .backend_model import BackendModel, Call, Cls, Meth
from .codebase import Code
from .facts import Fact

VALIDATION_ANNS = ["NotBlank", "NotNull", "NotEmpty", "Email", "Size", "Length", "Min", "Max", "Range", "Pattern",
                   "AssertTrue", "AssertFalse", "Past", "PastOrPresent", "Future", "FutureOrPresent", "Positive",
                   "PositiveOrZero", "Negative", "NegativeOrZero", "DecimalMin", "DecimalMax", "Digits", "URL"]
SECURITY_RULES = {"permitAll": "로그인 없이 접근", "authenticated": "로그인한 사용자만", "denyAll": "모두 차단",
                  "anonymous": "로그인하지 않은 사용자만", "fullyAuthenticated": "로그인한 사용자만(자동 로그인 제외)"}
NOTABLE_INPUT_ATTRS = ("required", "maxlength", "minlength", "pattern", "readonly", "disabled", "min", "max")
NOTABLE_INPUT_TYPES = {"email", "url", "number", "date", "tel", "datetime-local", "month", "time"}
MESSAGE_LIKE = re.compile(r"(error|message|msg|alert|success|exists)", re.I)
WATCHED_EVENTS = ("blur", "focusout", "submit")
STATIC_PREFIXES = ("/css/", "/js/", "/images/", "/img/", "/static/", "/webjars/", "/favicon", "/h2-console")


def short(text: str, n: int = 90) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def thymeleaf_url(raw: str | None) -> str | None:
    """@{/notices/{id}/edit(id=${notice.id})} → /notices/{}/edit"""
    if not raw:
        return None
    u = raw.strip()
    if u.startswith("@{") and u.endswith("}"):
        u = u[2:-1]
    u = re.sub(r"\([^()]*\)$", "", u)
    u = re.sub(r"\$\{[^}]*\}", "{}", u)
    return js_norm_url(u)


def route_label(r: dict) -> str:
    return f"{r['http']} {', '.join(r['paths'])}"


def route_pattern(path: str) -> str:
    p = re.sub(r"\{[^}]*\}", "{}", path).split("?")[0]
    return p.rstrip("/") or "/"


def url_match(pattern: str, url: str) -> bool:
    """/notices/{} 와 /notices/{} 또는 /notices/3 처럼 경로 조각이 맞는지. 보안 설정의 * 와 ** 도 받는다."""
    a, b = pattern.strip("/").split("/"), url.strip("/").split("/")
    if "**" in a:
        i = a.index("**")
        return all(x in ("{}", "*") or x == y for x, y in zip(a[:i], b[:i])) and len(b) >= i
    if len(a) != len(b):
        return False
    return all(x == y or x in ("{}", "*") or y == "{}" for x, y in zip(a, b))


class FactsBuilder:
    def __init__(self, code: Code, model: BackendModel, js: dict[str, dict]):
        self.code = code
        self.m = model
        self.js = js
        self.facts: list[Fact] = []
        self.security_urls: set[tuple[str, str]] = set()
        self.oauth2_login = False
        self.views_returned: set[str] = set()
        self.js_users: dict[str, list[str]] = {}          # JS 경로 → 그 JS를 불러오는 템플릿 경로
        for t in model.templates.values():
            for s in t["scripts"]:
                jp = self.js_path(s["url"])
                if jp:
                    self.js_users.setdefault(jp, []).append(t["file"])

    def run(self) -> list[Fact]:
        self._routes()
        self._security()
        self._global()
        self._spring_data()
        self._services()
        self._messages()
        self._validation()
        self._bindings()
        self._html()
        self._js()
        self._unused_and_unhandled()
        return self.facts

    # ------------------------------------------------ 도우미

    def js_path(self, url: str) -> str | None:
        raw = url.strip()
        if raw.startswith("@{") and raw.endswith("}"):
            raw = raw[2:-1]
        u = js_norm_url(raw)
        if not u:
            return None
        hits = [p for p in self.js if p.endswith("static" + u) or p.endswith(u)]
        return hits[0] if hits else None

    def is_service_like(self, c: Cls) -> bool:
        return c.has("Service", "Component", "Repository") or c.is_spring_data

    def interesting(self, call: Call, owner: Cls) -> bool:
        t = call.target
        if t is None or t is owner:
            return False
        if self.is_service_like(t):
            return True
        if t.kind == "interface" and any(self.is_service_like(c) for c in self.m.implementations(t.name)):
            return True                          # 인터페이스로 주입받은 서비스 (MemberService ← MemberServiceImpl)
        return call.raw.get("receiver") == t.name   # 정적 호출 (PasswordValidator.isValid)

    def call_label(self, call: Call) -> str:
        t = call.target
        name = call.raw["name"]
        if t is not None and t.is_spring_data:
            return f"{t.name}.{name}" + ("(이름 규칙 쿼리)" if t.method(name) else "(Spring Data 기본 기능)")
        if t is not None and t.kind == "interface":
            impls = [mm.cls.name for mm in self.m.resolve_targets(call) if mm.cls is not t]
            if impls:
                return f"{call.label}(구현: {', '.join(dict.fromkeys(impls))})"
        return call.label

    def route_calls(self, r: dict) -> list[Call]:
        """경로 처리 메서드와 그 메서드가 부르는 같은 컨트롤러의 헬퍼 메서드 안의 호출."""
        method = self.m.route_method(r)
        if method is None:
            return []
        out, todo, seen = [], [method], set()
        while todo:
            mm = todo.pop()
            if (mm.file, mm.line) in seen:
                continue
            seen.add((mm.file, mm.line))
            for c in self.m.calls_of(mm):
                if self.interesting(c, mm.cls):
                    out.append(c)
                elif c.target is mm.cls and c.raw["name"] in r.get("helpers", []):
                    todo += [x for x in mm.cls.method(c.raw["name"])]
        return out

    # ------------------------------------------------ 컨트롤러 경로

    def _routes(self):
        for r in self.m.routes:
            label = route_label(r)
            for x in r["returns"]:
                if x["kind"] in ("view", "forward"):
                    self.views_returned.add(x["value"].strip("/"))
            parts = [f"{label} → {r['controller']}.{r['method']}"]
            if r["json"]:
                parts.append("응답은 JSON·데이터(화면 아님)")
            for p in r["valid_params"]:
                parts.append(f"@Valid {p} 입력값 검사")
            if r["request_params"]:
                parts.append("요청 값 " + ", ".join(r["request_params"]))
            calls = list(dict.fromkeys(self.call_label(c) for c in self.route_calls(r)))
            if calls:
                parts.append("호출 " + ", ".join(calls))
            rets = []
            for x in r["returns"]:
                what = {"view": f"{x['value']} 화면", "redirect": f"redirect:{x['value']}",
                        "forward": f"forward:{x['value']}", "body": f"응답 {x['value']}"}[x["kind"]]
                rets.append(f"{x['context']} {what}" if x["context"] != "정상 흐름" or len(r["returns"]) > 1 else what)
            if rets:
                parts.append("반환: " + " / ".join(dict.fromkeys(rets)))
            if r["rejects"]:
                parts.append("서비스 예외를 BindingResult 전역 오류로 추가")
            self.facts.append(Fact("route", r["file"], r["line"], ". ".join(parts), anchors={f"route:{label}"}))

    # ------------------------------------------------ 보안 설정

    def _security(self):
        by_file: dict[str, list[dict]] = {}
        for s in self.m.security:
            by_file.setdefault(s["file"], []).append(s)
        for path, items in by_file.items():
            names = {s.get("name") for s in items if s["kind"] == "call"}
            first = lambda n: next((s["strings"][0] for s in items if s.get("name") == n and s["strings"]), None)
            for s in items:
                line = s["line"]
                if s["kind"] == "matcher":
                    target = "그 밖의 모든 경로" if s["matcher"] == "anyRequest" else \
                        ((" ".join(s["methods"]) + " ") if s["methods"] else "") + ", ".join(s["paths"])
                    rule, rargs = s["rule"], s["rule_args"]
                    if rule in ("hasRole", "hasAnyRole"):
                        who = ", ".join(rargs) + " 역할만 (ROLE_ 접두사 자동)"
                    elif rule in ("hasAuthority", "hasAnyAuthority"):
                        who = ", ".join(rargs) + " 권한만"
                    else:
                        who = SECURITY_RULES.get(rule, rule)
                    self.facts.append(Fact("security", path, line, f"{target} → {who}"))
                    continue
                n, strs = s["name"], s["strings"]
                if n == "loginPage" and strs:
                    proc = first("loginProcessingUrl") or strs[0]
                    user = first("usernameParameter") or "username"
                    self.security_urls.add(("POST", proc))
                    self.facts.append(Fact("security", path, line,
                                           f"로그인 화면 주소 {strs[0]}. 로그인 제출(POST {proc})은 컨트롤러가 아니라 "
                                           f"Spring Security가 처리한다 (아이디 입력 이름 '{user}')"))
                elif n == "defaultSuccessUrl" and strs:
                    always = "true" in s["args"]
                    self.facts.append(Fact("security", path, line,
                                           f"로그인 성공 시 항상 {strs[0]} 화면으로 이동 (두 번째 인자 true: 로그인 전에 열려던 화면으로 돌려보내지 않음)"
                                           if always else f"로그인 성공 시 로그인 전에 열려던 화면이 있으면 그 화면, 없으면 {strs[0]} 화면으로 이동"))
                elif n in ("failureUrl", "failureForwardUrl") and strs:
                    self.facts.append(Fact("security", path, line, f"로그인 실패 시 {strs[0]} 주소로 이동"))
                elif n == "logoutUrl" and strs:
                    self.security_urls.add(("POST", strs[0]))
                    succ = first("logoutSuccessUrl")
                    self.facts.append(Fact("security", path, line,
                                           f"로그아웃 POST {strs[0]}: Spring Security가 처리"
                                           + (f" → {succ} 화면으로 이동" if succ else "")
                                           + (", 세션 무효화" if "invalidateHttpSession" in names else "")))
                elif n == "ignoringRequestMatchers" and strs:
                    self.facts.append(Fact("security", path, line, "CSRF 검사 제외: " + ", ".join(strs)))
                elif n == "oauth2Login":
                    self.oauth2_login = True
                    self.facts.append(Fact("security", path, line, "소셜 로그인(oauth2Login) 설정 있음"))
            auth = next((s for s in items if s.get("name") in ("authorizeHttpRequests", "authorizeRequests")), None)
            if auth is not None and not ({"accessDeniedPage", "accessDeniedHandler"} & names):
                self.facts.append(Fact("security", path, auth["line"],
                                       "권한이 없는 경로에 접근했을 때의 처리(accessDeniedPage, accessDeniedHandler)를 "
                                       "설정하지 않음 (기본 동작: 403 응답)"))
            if "formLogin" in names and not any(s.get("name") == "logoutUrl" for s in items):
                self.security_urls.add(("POST", "/logout"))
            if "formLogin" in names and not any(s.get("name") == "loginPage" for s in items):
                self.security_urls.add(("POST", "/login"))
        for c in self.m.classes:
            if "UserDetailsService" in c.implements:
                for mm in c.method("loadUserByUsername"):
                    calls = [self.call_label(x) for x in self.m.calls_of(mm) if self.interesting(x, c)]
                    self.facts.append(Fact("security", c.file, mm.line,
                                           f"로그인할 때 Spring Security가 사용자 조회에 {mm.qname} 사용"
                                           + (f" ({', '.join(dict.fromkeys(calls))})" if calls else "")))

    # ------------------------------------------------ 전역 처리

    def _global(self):
        for c in self.m.classes:
            if not c.has("ControllerAdvice", "RestControllerAdvice"):
                continue
            for mm in c.methods:
                if mm.has("ModelAttribute"):
                    names = [a["name"] for a in mm.model_attrs] + list(mm.ann("ModelAttribute").values)
                    if names:
                        self.facts.append(Fact("global", c.file, mm.line,
                                               f"모든 컨트롤러 화면에 모델 값 자동 추가: {', '.join(dict.fromkeys(names))} ({mm.qname})"))
                eh = mm.ann("ExceptionHandler")
                if eh is not None:
                    raw = " ".join([str(v) for v in eh.pairs.values()] + list(eh.values))
                    types = re.findall(r"(\w+)\.class", raw) or [p.type for p in mm.params if p.type.endswith("Exception")]
                    views = [x["value"] for x in mm.returns if x["kind"] == "view"]
                    attrs = [a["name"] for a in mm.model_attrs]
                    self.views_returned.update(v.strip("/") for v in views)
                    self.facts.append(Fact("global", c.file, mm.line,
                                           f"컨트롤러에서 잡지 않은 {', '.join(types) or '예외'} → "
                                           + (f"{', '.join(views)} 화면" if views else "처리")
                                           + (f" (모델 값 {', '.join(attrs)})" if attrs else "") + f" ({mm.qname})"))
        errs = sorted(t["file"] for t in self.m.templates.values() if t["view"].startswith("error/"))
        if errs:
            names = ", ".join(p.split("/")[-1] for p in errs)
            self.facts.append(Fact("global", errs[0], 1,
                                   f"templates/error/ 의 {names}: 컨트롤러 없이 오류 상태 코드에 맞춰 Spring Boot가 보여 주는 화면"
                                   " (403, 404, 500 등은 파일 이름으로 고름)"))

    # ------------------------------------------------ Spring Data

    def _spring_data(self):
        for c in self.m.classes:
            if not c.is_spring_data:
                continue
            declared = [mm.name for mm in c.methods if not mm.has_body]
            base = next(t for t in c.extends if t)
            msg = f"{c.name}: {base} 상속 (Spring Data 저장소). "
            if declared:
                msg += f"선언한 메서드 {', '.join(declared)}: 구현 코드 없이 메서드 이름 규칙으로 쿼리가 만들어진다. "
            msg += "save, findById, delete 등: 상속받은 기본 기능"
            self.facts.append(Fact("data", c.file, c.line, msg))

    # ------------------------------------------------ 서비스 호출

    def _services(self):
        for c in self.m.classes:
            if c.has("Controller", "RestController", "ControllerAdvice", "Configuration") or c.is_spring_data:
                continue
            if not (c.has("Service", "Component") or "UserDetailsService" in c.implements):
                continue
            for mm in c.methods:
                if not mm.has_body or mm.name == c.name:
                    continue
                calls = [self.call_label(x) for x in self.m.calls_of(mm)
                         if self.interesting(x, c) or (x.target is c and x.raw["name"] != mm.name and c.method(x.raw["name"]))]
                if calls:
                    self.facts.append(Fact("call", c.file, mm.line, f"{mm.qname} → {', '.join(dict.fromkeys(calls))}",
                                           anchors={f"method:{mm.qname}"}))

    # ------------------------------------------------ 예외 문구

    def _messages(self):
        for c in self.m.classes:
            for mm in c.methods:
                for t in mm.throws:
                    when = "" if t["context"] == "정상 흐름" else f"{t['context']} "
                    self.facts.append(Fact("message", c.file, t["line"], f"{mm.qname}: {when}{t['exception']}(\"{t['message']}\")",
                                           anchors={f"method:{mm.qname}"}))

    # ------------------------------------------------ 검증 애노테이션

    def _validation(self):
        users: dict[str, list[dict]] = {}
        for r in self.m.routes:
            for p in dict.fromkeys(r["form_params"]):
                users.setdefault(p, []).append(r)
        for c in self.m.classes:
            targets = [(f.name, [a for a in f.annotations if a.name in VALIDATION_ANNS]) for f in c.fields.values()]
            targets += [(mm.name, [a for a in mm.annotations if a.name in VALIDATION_ANNS]) for mm in c.methods]
            targets = [(n, anns) for n, anns in targets if anns]
            if not targets:
                continue
            us = users.get(c.name, [])
            valid = [r for r in us if c.name in r["valid_params"]]
            if valid:
                where = "제출 후 서버에서 검사: " + ", ".join(dict.fromkeys(route_label(r) for r in valid)) + " (@Valid)"
            elif us:
                where = "이 폼을 받는 경로(" + ", ".join(route_label(r) for r in us) + ")에 @Valid가 없어 검사가 실행되지 않음"
            else:
                where = "이 클래스를 @Valid로 받는 컨트롤러 경로 없음"
            for name, anns in targets:
                desc = ", ".join(self._ann_desc(a) for a in anns)
                self.facts.append(Fact("validation", c.file, anns[0].line, f"{c.name}.{name}: {desc} — {where}",
                                       anchors={f"class:{c.name}"}))

    @staticmethod
    def _ann_desc(a) -> str:
        bits = [f"{k}={v}" for k, v in a.pairs.items() if k not in ("message", "groups", "payload", "value")]
        if a.get("value") and a.name in ("Min", "Max", "Pattern", "DecimalMin", "DecimalMax"):
            bits.insert(0, a.get("value"))
        msg = a.get("message")
        if msg and not str(msg).startswith("{"):
            bits.append(f"\"{msg}\"")
        return f"@{a.name}" + (f"({', '.join(bits)})" if bits else "")

    # ------------------------------------------------ Controller → 템플릿 바인딩 (분석기 결과)

    def _bindings(self):
        for b in self.m.bindings:
            anchors = {f"route:{b['route']}"}
            tpl = b.get("target_template")
            related = {tpl} if tpl else set()
            frags = b.get("fragments") or []
            where = f"{b['view']} 템플릿" + (f"(포함 조각 {', '.join(frags)})" if frags else "")
            if b["kind"] == "template_missing":
                self.facts.append(Fact("template", b["file"], b["line"],
                                       f"{b['route']} {b['context']}: 반환하는 화면 {b['view']}의 템플릿 파일이 없음", anchors=anchors))
            elif b["kind"] == "model_attr":
                if b["status"] == "mismatch":
                    how = "(@ModelAttribute로 자동으로 넣는 값)" if b.get("implicit") else ""
                    self.facts.append(Fact("template", b["file"], b["line"],
                                           f"{b['route']} {b['context']}: 모델 값 {b['attr_name']}{how}을(를) {b['view']} 화면에 넘기지만 "
                                           f"{where} 어디에서도 출력하지 않음", related=related, anchors=anchors))
                elif MESSAGE_LIKE.search(b["attr_name"]) and not b.get("implicit") and b.get("ref"):
                    ref = b["ref"]
                    self.facts.append(Fact("template", ref["file"], ref["line"],
                                           f"{b['route']} {b['context']}: 모델 값 {b['attr_name']} 출력 위치 "
                                           f"{ref['file'].split('templates/')[-1]} {ref['line']}줄 ({short(ref['expr'], 60)})",
                                           related=related, anchors=anchors))
            elif b["kind"] == "validation_output":
                outs = b.get("error_outputs") or []
                forms = ", ".join(b["forms"])
                if not outs:
                    self.facts.append(Fact("template", b["file"], b["line"],
                                           f"{b['route']}: @Valid {forms} 검사에 실패하면 {b['view']} 화면을 다시 보여 주지만, 이 템플릿"
                                           f"{'과 포함 조각' if frags else ''}에 검증 오류를 출력하는 곳(th:errors, #fields.errors 등)이 없음. "
                                           f"애노테이션 메시지가 화면에 나오지 않음", related=related, anchors=anchors))
                else:
                    fields = [re.sub(r".*\*\{(\w+)\}.*", r"\1", o["expr"]) for o in outs if "th:errors" in o["expr"]]
                    desc = f"th:errors {len(fields)}곳({', '.join(fields)})" if fields else f"{len(outs)}곳"
                    self.facts.append(Fact("template", outs[0]["file"], outs[0]["line"],
                                           f"{b['route']}: @Valid {forms} 검사에 실패하면 {b['view']} 화면을 다시 보여 주고, "
                                           f"검증 오류를 {desc}에서 출력", related=related, anchors=anchors))
                if b.get("rejects") and not any("global" in o["expr"].lower() for o in outs):
                    self.facts.append(Fact("template", b["file"], b["rejects"][0],
                                           f"{b['route']}: 서비스 예외를 BindingResult 전역 오류(reject)로 넣지만 {b['view']} 템플릿에 "
                                           f"전역 오류를 출력하는 곳(#fields.globalErrors 등)이 없음", related=related, anchors=anchors))

    # ------------------------------------------------ HTML 구조

    def _html(self):
        for t in self.m.templates.values():
            for inp in t["inputs"]:
                a, line = inp["attrs"], inp["line"]
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
                                 "readonly": "readonly (수정할 수 없음)", "disabled": "disabled (처음부터 비활성)",
                                 "min": f"min={v}", "max": f"max={v}"}[k])
                self.facts.append(Fact("html", t["file"], line, f"입력란 {name}: {', '.join(bits)}"))
            for c in t["controls"]:
                at = c["attrs"]
                cond = next((at[k] for k in ("th:if", "th:unless", "sec:authorize", "data-th-if") if k in at), None)
                confirm = next((at[k] for k in ("onclick", "onsubmit") if "confirm(" in at.get(k, "")), None)
                if not cond and not confirm:
                    continue
                label = c["text"] or at.get("value") or at.get("id") or c["tag"]
                what = {"a": "링크", "button": "버튼", "form": "폼"}[c["tag"]]
                url = thymeleaf_url(at.get("th:action") or at.get("action") or at.get("th:href") or at.get("href"))
                bits = []
                if cond:
                    bits.append(f"{cond} {'아닐 때만' if 'th:unless' in at else '일 때만'} 보임")
                if confirm:
                    bits.append(f"누르면 확인 창({short(confirm, 40)})")
                self.facts.append(Fact("html", t["file"], c["line"],
                                       f"{what} '{short(label, 30)}'{f'({url})' if url else ''}: {', '.join(bits)}"))

    # ------------------------------------------------ JS

    def _has_element(self, template_path: str, target: str) -> bool:
        text = self.code.text(template_path)
        for sel in target.replace("의 각 요소", "").split(","):
            sel = sel.strip()
            if sel.startswith("#") and re.search(r'\bid\s*=\s*["\']' + re.escape(sel[1:]) + r'["\']', text):
                return True
            if sel.startswith(".") and re.search(r'class\s*=\s*["\'][^"\']*\b' + re.escape(sel[1:]) + r'\b', text):
                return True
            if re.fullmatch(r"[a-zA-Z][\w-]*", sel) and f"<{sel.lower()}" in text.lower():
                return True
            if sel and not re.fullmatch(r"[#.]?[\w-]+", sel):
                return True
        return False

    def _js(self):
        for path, jf in self.js.items():
            users = sorted(self.js_users.get(path, []))
            for b in user_bindings(jf):
                eff = "; ".join(b["effects"]) if b["effects"] else "효과를 정적으로 찾지 못함"
                having = [u for u in users if self._has_element(u, b["target"])
                          and (not b["effect_targets"] or any(self._has_element(u, x) for x in b["effect_targets"]))]
                where = ""
                if len(users) > 1 and having:
                    where = f" (대상 요소가 있는 템플릿: {', '.join(u.split('templates/')[-1] for u in having)})"
                elif len(users) > 1:
                    having = users
                handler = "(그 자리의 함수)" if b["handler"] == "<inline function>" else b["handler"]
                self.facts.append(Fact("js", path, b["line"],
                                       f"{b['target']} {b['event_type']} 이벤트 → {handler}: {eff}{where}",
                                       related=set(having) | {path}, anchor_self=not users))
            events = sorted({b["event_type"] for b in jf["event_bindings"]} - PAGE_EVENTS - {None})
            present = {b["event_type"] for b in jf["event_bindings"]}
            missing = [e for e in WATCHED_EVENTS if e not in present]
            summary = f"{path.split('/')[-1]}: 붙이는 이벤트 {', '.join(events) or '없음'}"
            if missing:
                summary += f" ({'·'.join(missing)} 이벤트 없음)"
            summary += ". 정규식 " + ("있음" if jf["regex_literals"] else "없음")
            calls = [f"{u['method']} {u['url']}" for u in jf["url_refs"]]
            if calls:
                summary += ". 서버 요청·이동: " + ", ".join(dict.fromkeys(calls))
            if users:
                summary += f". 이 파일을 불러오는 템플릿 {len(users)}개: {', '.join(u.split('templates/')[-1] for u in users)}"
            self.facts.append(Fact("js", path, 1, summary, related={path} | set(users)))

    # ------------------------------------------------ 미사용·처리하는 곳 없음

    def url_refs(self) -> list[tuple[str, str, str, int, str]]:
        refs = []
        for t in self.m.templates.values():
            refs += [(u["method"], u["url"], t["file"], u["line"], u["kind"]) for u in t["url_refs"]]
        for path, jf in self.js.items():
            refs += [(u["method"], u["url"], path, u["line"], u["kind"]) for u in jf["url_refs"]]
        for r in self.m.routes:
            refs += [("GET", js_norm_url(x["value"]), r["file"], x["line"], "redirect") for x in r["returns"]
                     if x["kind"] == "redirect" and js_norm_url(x["value"])]
        for s in self.m.security:
            if s["kind"] == "call" and s["name"] in ("loginPage", "defaultSuccessUrl", "failureUrl", "logoutSuccessUrl") and s["strings"]:
                refs.append(("GET", js_norm_url(s["strings"][0]), s["file"], s["line"], "보안 설정"))
        return [x for x in refs if x[1]]

    def _unused_and_unhandled(self):
        refs = self.url_refs()
        for r in self.m.routes:
            pats = [route_pattern(p) for p in r["paths"]]
            if not any(url_match(p, u) for p in pats for _, u, *_ in refs):
                label = route_label(r)
                self.facts.append(Fact("unused", r["file"], r["line"],
                                       f"{label}({r['controller']}.{r['method']}): 템플릿·JS·리다이렉트·보안 설정 어디에서도 "
                                       f"이 주소를 부르지 않음 (미사용 후보)", anchors={f"route:{label}"}))
        handled = [(r["http"], route_pattern(p)) for r in self.m.routes for p in r["paths"]] + list(self.security_urls)
        for method, url, path, line, kind in refs:
            if kind == "보안 설정" or url.startswith(STATIC_PREFIXES) or url == "/error":
                continue
            if url.startswith("/oauth2/") and self.oauth2_login:
                continue
            if not any(url_match(h[1], url) for h in handled):
                note = " (보안 설정에 oauth2Login 없음)" if url.startswith("/oauth2/") else ""
                self.facts.append(Fact("route" if path.endswith(".java") else "html", path, line,
                                       f"{kind} {method} {url}: 이 주소를 처리하는 컨트롤러나 보안 설정이 없음{note}"))
        included = {i["view"] for t in self.m.templates.values() for i in t["includes"]}
        for t in self.m.templates.values():
            v = t["view"]
            if v in self.views_returned or v in included or t["provides_fragment"] or v.startswith("error"):
                continue
            self.facts.append(Fact("unused", t["file"], 1,
                                   f"{v}: 어떤 컨트롤러도 이 화면을 반환하지 않고 다른 템플릿에 포함되지도 않음 (미사용 후보)"))

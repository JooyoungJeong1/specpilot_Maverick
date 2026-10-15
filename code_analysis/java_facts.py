"""Java 코드에서 사실 만들기: 보안 설정, 전역 처리, Spring Data, 컨트롤러 경로, 서비스 호출, 예외 문구, 입력값 검증."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .facts import Fact
from .java_index import (Call, ClassInfo, JavaIndex, MethodInfo, Param, ancestors, line_of, node_text,
                         string_value, walk)

MAPPINGS = {"GetMapping": "GET", "PostMapping": "POST", "PutMapping": "PUT", "DeleteMapping": "DELETE",
            "PatchMapping": "PATCH", "RequestMapping": None}
VALIDATION_ANNS = ["NotBlank", "NotNull", "NotEmpty", "Email", "Size", "Length", "Min", "Max", "Range",
                   "Pattern", "AssertTrue", "AssertFalse", "Past", "PastOrPresent", "Future", "FutureOrPresent",
                   "Positive", "PositiveOrZero", "Negative", "NegativeOrZero", "DecimalMin", "DecimalMax",
                   "Digits", "URL"]
# 모델 속성이 아닌 컨트롤러 매개변수 타입
FRAMEWORK_PARAM_TYPES = {"Model", "ModelMap", "BindingResult", "Errors", "RedirectAttributes", "Authentication",
                         "Principal", "HttpServletRequest", "HttpServletResponse", "HttpSession", "MultipartFile",
                         "String", "Long", "Integer", "int", "long", "boolean", "Boolean", "Locale", "SessionStatus",
                         "UserDetails", "Pageable", "UriComponentsBuilder"}
SECURITY_MATCHERS = {"requestMatchers", "antMatchers", "mvcMatchers", "regexMatchers"}
SECURITY_RULES = {"permitAll": "로그인 없이 접근", "authenticated": "로그인한 사용자만", "denyAll": "모두 차단",
                  "anonymous": "로그인하지 않은 사용자만", "fullyAuthenticated": "로그인한 사용자만(자동 로그인 제외)"}


def short(text: str, n: int = 90) -> str:
    t = re.sub(r"\s+", " ", text or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def same(a, b) -> bool:
    return a is not None and b is not None and a.start_byte == b.start_byte and a.end_byte == b.end_byte and a.type == b.type


def decap(name: str) -> str:
    return name[:1].lower() + name[1:] if name else name


# ---------------------------------------------------------------- 흐름 문맥

def context_of(node, body) -> str:
    """노드가 어떤 분기 안에 있는지: '입력값 검사 실패 시', '예외(IllegalArgumentException) 시', '조건 … 일 때'."""
    tags = []
    child = node
    for a in ancestors(node):
        if same(a, body):
            break
        if a.type == "catch_clause":
            param = next((c for c in a.children if c.type == "catch_formal_parameter"), None)
            ctype = next((c for c in param.children if c.type == "catch_type"), None) if param is not None else None
            tags.append(f"예외({node_text(ctype)}) 시" if ctype is not None else "예외 시")
        elif a.type == "if_statement":
            cond = node_text(a.child_by_field_name("condition")).strip()
            cond = cond[1:-1].strip() if cond.startswith("(") and cond.endswith(")") else cond
            alt = a.child_by_field_name("alternative")
            in_alt = alt is not None and alt.start_byte <= child.start_byte < alt.end_byte
            if "hasErrors" in cond:
                tags.append("입력값 검사 통과 시" if in_alt or cond.startswith("!") else "입력값 검사 실패 시")
            else:
                tags.append(f"{short(cond, 60)} 아닐 때" if in_alt else f"{short(cond, 60)} 일 때")
        child = a
    return ", ".join(reversed(tags)) if tags else "정상 흐름"


def render_concat(node) -> str:
    """"redirect:/notices/" + id → redirect:/notices/{id}"""
    if node.type == "string_literal":
        return string_value(node)
    if node.type == "binary_expression" and node_text(node.child_by_field_name("operator")) == "+":
        return render_concat(node.child_by_field_name("left")) + render_concat(node.child_by_field_name("right"))
    if node.type == "parenthesized_expression" and node.named_child_count == 1:
        return render_concat(node.named_children[0])
    return "{" + short(node_text(node), 30) + "}"


# ---------------------------------------------------------------- 경로 모양

@dataclass
class Return:
    kind: str          # view | redirect | forward | body
    value: str
    context: str
    line: int


@dataclass
class ModelAttr:
    name: str
    line: int
    context: str
    file: str
    via: str | None = None     # 헬퍼 메서드를 거쳤으면 그 이름
    flash: bool = False
    implicit: bool = False     # @ModelAttribute 매개변수로 자동으로 들어간 값


@dataclass
class Route:
    method: MethodInfo
    http: str
    paths: list[str]
    json: bool
    line: int
    form_params: list[Param] = field(default_factory=list)
    valid_params: list[Param] = field(default_factory=list)
    binding_result: bool = False
    hasErrors_line: int | None = None
    request_params: list[str] = field(default_factory=list)
    returns: list[Return] = field(default_factory=list)
    attrs: list[ModelAttr] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)
    rejects: list[int] = field(default_factory=list)          # bindingResult.reject(...) 줄

    @property
    def label(self) -> str:
        return f"{self.http} {', '.join(self.paths)}"

    def views(self) -> list[Return]:
        return [r for r in self.returns if r.kind in ("view", "forward")]


class JavaFacts:
    def __init__(self, index: JavaIndex):
        self.ix = index
        self.facts: list[Fact] = []
        self.routes: list[Route] = []
        self.security_urls: set[str] = set()        # Spring Security가 직접 처리하는 주소 (로그인 제출, 로그아웃)
        self.global_attrs: set[str] = set()         # @ControllerAdvice가 모든 화면에 넣는 모델 값
        self.views_returned: set[str] = set()       # 어떤 컨트롤러·전역 처리기가 반환하는 뷰 이름
        self.form_users: dict[str, list[Route]] = {}
        self.oauth2_login = False

    def run(self) -> "JavaFacts":
        self._routes()
        self._security()
        self._global()
        self._spring_data()
        self._services()
        self._messages()
        self._validation()
        return self

    # ------------------------------------------------ 분류

    def is_controller(self, c: ClassInfo) -> bool:
        return c.has("Controller", "RestController")

    def is_service_like(self, c: ClassInfo) -> bool:
        return c.has("Service", "Component", "Repository") or c.is_spring_data

    def _interesting_call(self, call: Call, owner: ClassInfo) -> bool:
        t = call.target
        if t is None or t is owner:
            return False
        if self.is_service_like(t):
            return True
        if t.kind == "interface" and any(self.is_service_like(c) for c in self.ix.implementations(t.name)):
            return True                          # 인터페이스로 주입받은 서비스 (MemberService ← MemberServiceImpl)
        return call.receiver == t.name           # 정적 호출 (PasswordValidator.isValid)

    def call_label(self, call: Call) -> str:
        t = call.target
        if t is not None and t.is_spring_data:
            declared = t.method(call.name)
            return f"{t.name}.{call.name}" + ("(이름 규칙 쿼리)" if declared else "(Spring Data 기본 기능)")
        if t is not None and t.kind == "interface":
            impls = [m.cls.name for m in self.ix.resolve_targets(call) if m.cls is not t]
            if not impls:
                impls = [c.name for c in self.ix.implementations(t.name) if c.method(call.name)]
            if impls:
                return f"{call.label}(구현: {', '.join(dict.fromkeys(impls))})"
        return call.label

    # ------------------------------------------------ 컨트롤러 경로

    def _routes(self):
        for c in self.ix.all_classes():
            if not self.is_controller(c):
                continue
            prefix_ann = c.ann("RequestMapping")
            prefixes = prefix_ann.values if prefix_ann and prefix_ann.values else [""]
            for m in c.methods:
                ann = next((a for a in m.annotations if a.name in MAPPINGS), None)
                if ann is None:
                    continue
                http = MAPPINGS[ann.name]
                if http is None:
                    mm = re.findall(r"RequestMethod\.(\w+)", ann.get("method") or "")
                    http = "/".join(mm) if mm else "ANY"
                subs = ann.values or [""]
                paths = [(p.rstrip("/") + "/" + s.lstrip("/")).rstrip("/") or "/" if s or p else "/"
                         for p in prefixes for s in subs]
                r = Route(method=m, http=http, paths=paths, line=ann.line,
                          json=c.has("RestController") or m.has("ResponseBody") or m.return_type == "ResponseEntity")
                self._route_details(r)
                self.routes.append(r)
                for rv in r.views():
                    self.views_returned.add(rv.value)
                for p in r.valid_params + r.form_params:
                    self.form_users.setdefault(p.type, []).append(r)
        for r in self.routes:
            self.facts.append(self._route_fact(r))

    def _route_details(self, r: Route):
        m = r.method
        for p in m.params:
            if p.type in ("BindingResult", "Errors"):
                r.binding_result = True
            elif p.has("RequestParam", "PathVariable"):
                a = p.ann("RequestParam") or p.ann("PathVariable")
                r.request_params.append((a.values[0] if a.values else (a.get("name") or p.name)))
            elif p.has("RequestBody"):
                continue
            elif p.type not in FRAMEWORK_PARAM_TYPES:
                r.form_params.append(p)
                if p.has("Valid", "Validated"):
                    r.valid_params.append(p)
                ma = p.ann("ModelAttribute")
                name = (ma.values[0] if ma and ma.values else None) or decap(p.type)
                r.attrs.append(ModelAttr(name, m.line, "요청마다", m.file, implicit=True))
        if m.body is None:
            return
        for n in walk(m.body):
            if n.type == "return_statement" and n.named_child_count:
                expr = n.named_children[0]
                ctx = context_of(n, m.body)
                if expr.type in ("string_literal", "binary_expression"):
                    v = render_concat(expr)
                    if v.startswith("redirect:"):
                        r.returns.append(Return("redirect", v[len("redirect:"):], ctx, line_of(n)))
                    elif v.startswith("forward:"):
                        r.returns.append(Return("forward", v[len("forward:"):], ctx, line_of(n)))
                    elif r.json:
                        r.returns.append(Return("body", short(v, 40), ctx, line_of(n)))
                    else:
                        r.returns.append(Return("view", v, ctx, line_of(n)))
                else:
                    r.returns.append(Return("body", short(node_text(expr), 50), ctx, line_of(n)))
            elif n.type == "if_statement" and "hasErrors" in node_text(n.child_by_field_name("condition")):
                r.hasErrors_line = r.hasErrors_line or line_of(n)
        self._collect_attrs(r, m, via=None, seen=set(), ctx_override=None)
        for call in self.ix.calls(m):
            if call.name in ("reject", "rejectValue") and call.receiver and \
                    any(p.name == call.receiver and p.type in ("BindingResult", "Errors") for p in m.params):
                r.rejects.append(call.line)
        r.calls = self._calls_through_helpers(m, set())

    def _collect_attrs(self, r: Route, m: MethodInfo, via: str | None, seen: set, ctx_override: str | None):
        """모델에 넣는 값. 헬퍼 메서드 안에서 넣은 값은 헬퍼를 부른 자리의 분기를 문맥으로 쓴다 (v5 분석기의 호출자 거슬러 오르기)."""
        if m.qname in seen or m.body is None:
            return
        seen.add(m.qname)
        for call in self.ix.calls(m):
            if call.name in ("addAttribute", "addFlashAttribute") and call.node is not None:
                args = call.node.child_by_field_name("arguments")
                first = args.named_children[0] if args is not None and args.named_child_count else None
                name = string_value(first)
                if name:
                    ctx = ctx_override or context_of(call.node, m.body)
                    r.attrs.append(ModelAttr(name, call.line, ctx, m.file, via=via, flash=call.name == "addFlashAttribute"))
            elif call.target is m.cls:                       # 같은 컨트롤러의 헬퍼 메서드를 따라간다
                helper = next(iter(m.cls.method(call.name)), None)
                if helper is not None and not helper.ann(*MAPPINGS):
                    self._collect_attrs(r, helper, via=helper.name, seen=seen,
                                        ctx_override=ctx_override or context_of(call.node, m.body))

    def _calls_through_helpers(self, m: MethodInfo, seen: set) -> list[Call]:
        if m.qname in seen:
            return []
        seen.add(m.qname)
        out = []
        for call in self.ix.calls(m):
            if self._interesting_call(call, m.cls):
                out.append(call)
            elif call.target is m.cls:
                helper = next(iter(m.cls.method(call.name)), None)
                if helper is not None:
                    out += self._calls_through_helpers(helper, seen)
        return out

    def _route_fact(self, r: Route) -> Fact:
        m = r.method
        parts = [f"{r.label} → {m.qname}"]
        if r.json:
            parts.append("응답은 JSON·데이터(화면 아님)")
        for p in r.valid_params:
            parts.append(f"@Valid {p.type} 입력값 검사")
        if r.request_params:
            parts.append("요청 값 " + ", ".join(r.request_params))
        calls = list(dict.fromkeys(self.call_label(c) for c in r.calls))
        if calls:
            parts.append("호출 " + ", ".join(calls))
        rets = []
        for x in r.returns:
            what = {"view": f"{x.value} 화면", "redirect": f"redirect:{x.value}", "forward": f"forward:{x.value}",
                    "body": f"응답 {x.value}"}[x.kind]
            rets.append(f"{x.context} {what}" if x.context != "정상 흐름" or len(r.returns) > 1 else what)
        if rets:
            parts.append("반환: " + " / ".join(dict.fromkeys(rets)))
        if r.rejects:
            parts.append("서비스 예외를 BindingResult 전역 오류로 추가")
        return Fact("route", m.file, r.line, ". ".join(parts), anchors={f"route:{r.label}"})

    # ------------------------------------------------ 보안 설정

    def _security(self):
        for path, jf in self.ix.files.items():
            text = self.ix.code.text(path)
            if not any(k in text for k in ("requestMatchers", "antMatchers", "formLogin", "authorizeHttpRequests",
                                          "authorizeRequests", "logout(")):
                continue
            calls = [n for n in walk(jf.tree.root_node) if n.type == "method_invocation"]
            names = {node_text(n.child_by_field_name("name")) for n in calls}
            for n in calls:
                name = node_text(n.child_by_field_name("name"))
                line = line_of(n.child_by_field_name("name"))
                args = n.child_by_field_name("arguments")
                strs = [string_value(a) for a in (args.named_children if args is not None else []) if a.type == "string_literal"]
                if name in SECURITY_MATCHERS or name == "anyRequest":
                    rule_node = n.parent if n.parent is not None and n.parent.type == "method_invocation" \
                        and same(n.parent.child_by_field_name("object"), n) else None
                    if rule_node is None:
                        continue
                    rule = node_text(rule_node.child_by_field_name("name"))
                    rargs = rule_node.child_by_field_name("arguments")
                    rstrs = [string_value(a) for a in (rargs.named_children if rargs is not None else [])
                             if a.type == "string_literal"]
                    methods = re.findall(r"HttpMethod\.(\w+)", node_text(args)) if args is not None else []
                    target = "그 밖의 모든 경로" if name == "anyRequest" else ((" ".join(methods) + " ") if methods else "") + ", ".join(strs)
                    if rule in ("hasRole", "hasAnyRole"):
                        who = ", ".join(rstrs) + " 역할만 (ROLE_ 접두사 자동)"
                    elif rule in ("hasAuthority", "hasAnyAuthority"):
                        who = ", ".join(rstrs) + " 권한만"
                    else:
                        who = SECURITY_RULES.get(rule, rule)
                    self.facts.append(Fact("security", path, line, f"{target} → {who}"))
                elif name == "loginPage" and strs:
                    proc = next((self._first_str(c) for c in calls
                                 if node_text(c.child_by_field_name("name")) == "loginProcessingUrl"), None) or strs[0]
                    user = next((self._first_str(c) for c in calls
                                 if node_text(c.child_by_field_name("name")) == "usernameParameter"), None) or "username"
                    self.security_urls.add(f"POST {proc}")
                    self.facts.append(Fact("security", path, line,
                                           f"로그인 화면 주소 {strs[0]}. 로그인 제출(POST {proc})은 컨트롤러가 아니라 "
                                           f"Spring Security가 처리한다 (아이디 입력 이름 '{user}')"))
                elif name == "defaultSuccessUrl" and strs:
                    always = args is not None and "true" in [node_text(a) for a in args.named_children]
                    msg = (f"로그인 성공 시 항상 {strs[0]} 화면으로 이동 (두 번째 인자 true: 로그인 전에 열려던 화면으로 돌려보내지 않음)"
                           if always else f"로그인 성공 시 로그인 전에 열려던 화면이 있으면 그 화면, 없으면 {strs[0]} 화면으로 이동")
                    self.facts.append(Fact("security", path, line, msg))
                elif name in ("failureUrl", "failureForwardUrl") and strs:
                    self.facts.append(Fact("security", path, line, f"로그인 실패 시 {strs[0]} 주소로 이동"))
                elif name == "logoutUrl" and strs:
                    self.security_urls.add(f"POST {strs[0]}")
                    succ = next((self._first_str(c) for c in calls
                                 if node_text(c.child_by_field_name("name")) == "logoutSuccessUrl"), None)
                    inv = "invalidateHttpSession" in names
                    self.facts.append(Fact("security", path, line,
                                           f"로그아웃 POST {strs[0]}: Spring Security가 처리"
                                           + (f" → {succ} 화면으로 이동" if succ else "") + (", 세션 무효화" if inv else "")))
                elif name == "ignoringRequestMatchers" and strs:
                    self.facts.append(Fact("security", path, line, "CSRF 검사 제외: " + ", ".join(strs)))
                elif name == "oauth2Login":
                    self.facts.append(Fact("security", path, line, "소셜 로그인(oauth2Login) 설정 있음"))
            if ("formLogin" in names or "authorizeHttpRequests" in names) and \
                    not ({"accessDeniedPage", "accessDeniedHandler"} & names):
                first = next((n for n in calls if node_text(n.child_by_field_name("name"))
                              in ("authorizeHttpRequests", "authorizeRequests")), None)
                if first is not None:
                    self.facts.append(Fact("security", path, line_of(first.child_by_field_name("name")),
                                           "권한이 없는 경로에 접근했을 때의 처리(accessDeniedPage, accessDeniedHandler)를 "
                                           "설정하지 않음 (기본 동작: 403 응답)"))
            if "oauth2Login" in names:
                self.oauth2_login = True
        for c in self.ix.all_classes():
            if "UserDetailsService" in c.implements:
                for m in c.method("loadUserByUsername"):
                    calls = [self.call_label(x) for x in self.ix.calls(m) if self._interesting_call(x, c)]
                    self.facts.append(Fact("security", c.file, m.line,
                                           f"로그인할 때 Spring Security가 사용자 조회에 {m.qname} 사용"
                                           + (f" ({', '.join(dict.fromkeys(calls))})" if calls else "")))

    @staticmethod
    def _first_str(call_node) -> str | None:
        args = call_node.child_by_field_name("arguments")
        for a in (args.named_children if args is not None else []):
            if a.type == "string_literal":
                return string_value(a)
        return None

    # ------------------------------------------------ 전역 처리 (@ControllerAdvice)

    def _global(self):
        for c in self.ix.all_classes():
            if not c.has("ControllerAdvice", "RestControllerAdvice"):
                continue
            for m in c.methods:
                if m.has("ModelAttribute"):
                    names = []
                    for call in self.ix.calls(m):
                        if call.name == "addAttribute":
                            args = call.node.child_by_field_name("arguments")
                            v = string_value(args.named_children[0]) if args is not None and args.named_child_count else None
                            if v:
                                names.append(v)
                    ma = m.ann("ModelAttribute")
                    if ma and ma.values:
                        names += ma.values
                    self.global_attrs.update(names)
                    if names:
                        self.facts.append(Fact("global", c.file, m.line,
                                               f"모든 컨트롤러 화면에 모델 값 자동 추가: {', '.join(dict.fromkeys(names))} ({m.qname})"))
                eh = m.ann("ExceptionHandler")
                if eh is not None:
                    types = re.findall(r"(\w+)\.class", eh.raw_args) or [p.type for p in m.params if p.type.endswith("Exception")]
                    views = []
                    attrs = []
                    if m.body is not None:
                        for n in walk(m.body):
                            if n.type == "return_statement" and n.named_child_count and n.named_children[0].type == "string_literal":
                                views.append(string_value(n.named_children[0]))
                    for call in self.ix.calls(m):
                        if call.name == "addAttribute":
                            args = call.node.child_by_field_name("arguments")
                            v = string_value(args.named_children[0]) if args is not None and args.named_child_count else None
                            if v:
                                attrs.append(v)
                    self.views_returned.update(views)
                    self.facts.append(Fact("global", c.file, m.line,
                                           f"컨트롤러에서 잡지 않은 {', '.join(types) or '예외'} → "
                                           + (f"{', '.join(views)} 화면" if views else "처리")
                                           + (f" (모델 값 {', '.join(attrs)})" if attrs else "") + f" ({m.qname})"))

    # ------------------------------------------------ Spring Data

    def _spring_data(self):
        for c in self.ix.all_classes():
            if not c.is_spring_data:
                continue
            declared = [m.name for m in c.methods if m.body is None]
            base = next(t for t in c.extends if t)
            msg = f"{c.name}: {base} 상속 (Spring Data 저장소). "
            if declared:
                msg += f"선언한 메서드 {', '.join(declared)}: 구현 코드 없이 메서드 이름 규칙으로 쿼리가 만들어진다. "
            msg += "save, findById, delete 등: 상속받은 기본 기능"
            self.facts.append(Fact("data", c.file, c.line, msg))

    # ------------------------------------------------ 서비스 호출

    def _services(self):
        for c in self.ix.all_classes():
            if self.is_controller(c) or c.has("ControllerAdvice", "Configuration") or c.is_spring_data:
                continue
            if not (c.has("Service", "Component") or "UserDetailsService" in c.implements):
                continue
            for m in c.methods:
                if m.body is None or m.name == c.name:
                    continue
                calls = []
                for call in self.ix.calls(m):
                    if self._interesting_call(call, c) or (call.target is c and call.name != m.name):
                        calls.append(self.call_label(call))
                if calls:
                    self.facts.append(Fact("call", c.file, m.line,
                                           f"{m.qname} → {', '.join(dict.fromkeys(calls))}", anchors={f"method:{m.qname}"}))

    # ------------------------------------------------ 예외 문구

    def _messages(self):
        for c in self.ix.all_classes():
            for m in c.methods:
                if m.body is None:
                    continue
                for n in walk(m.body):
                    if n.type != "throw_statement" or not n.named_child_count:
                        continue
                    expr = n.named_children[0]
                    if expr.type != "object_creation_expression":
                        continue
                    etype = node_text(expr.child_by_field_name("type"))
                    args = expr.child_by_field_name("arguments")
                    msgs = [string_value(a) for a in (args.named_children if args is not None else []) if a.type == "string_literal"]
                    if not msgs:
                        continue
                    ctx = context_of(n, m.body)
                    when = "" if ctx == "정상 흐름" else f"{ctx} "
                    self.facts.append(Fact("message", c.file, line_of(n),
                                           f"{m.qname}: {when}{etype}(\"{msgs[0]}\")", anchors={f"method:{m.qname}"}))

    # ------------------------------------------------ 입력값 검증 애노테이션

    def _validation(self):
        for c in self.ix.all_classes():
            fields = [(f, [a for a in f.annotations if a.name in VALIDATION_ANNS]) for f in c.fields.values()]
            fields = [(f, anns) for f, anns in fields if anns]
            methods = [(m, [a for a in m.annotations if a.name in VALIDATION_ANNS]) for m in c.methods]
            methods = [(m, anns) for m, anns in methods if anns]
            if not fields and not methods:
                continue
            users = self.form_users.get(c.name, [])
            valid = [r for r in users if any(p.type == c.name for p in r.valid_params)]
            if valid:
                where = "제출 후 서버에서 검사: " + ", ".join(dict.fromkeys(r.label for r in valid)) + " (@Valid)"
            elif users:
                where = "이 폼을 받는 경로(" + ", ".join(r.label for r in users) + ")에 @Valid가 없어 검사가 실행되지 않음"
            else:
                where = "이 클래스를 @Valid로 받는 컨트롤러 경로 없음"
            for target, anns in fields + methods:
                desc = ", ".join(self._ann_desc(a) for a in anns)
                self.facts.append(Fact("validation", c.file, anns[0].line,
                                       f"{c.name}.{target.name}: {desc} — {where}", anchors={f"class:{c.name}"}))

    @staticmethod
    def _ann_desc(a) -> str:
        bits = [f"{k}={v}" for k, v in a.pairs.items() if k not in ("message", "groups", "payload", "value")]
        if a.get("value") and a.name in ("Min", "Max", "Pattern", "DecimalMin", "DecimalMax"):
            bits.insert(0, a.get("value"))
        msg = a.get("message")
        if msg and not msg.startswith("{"):
            bits.append(f"\"{msg}\"")
        return f"@{a.name}" + (f"({', '.join(bits)})" if bits else "")

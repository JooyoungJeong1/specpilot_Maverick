"""화면 쪽 코드 읽기: Thymeleaf 템플릿(표준 HTML 파서)과 정적 JS(tree-sitter).

JS 부분은 3주차 analyze_frontend_js.py(선택자 → 변수, 변수 → 이벤트, 정규식 유무)를 옮기고,
이벤트 처리 함수가 실제로 무엇을 바꾸는지(버튼 disabled, 문구 표시, fetch 주소)까지 요약하도록 늘렸다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

import tree_sitter_javascript as tsjs
from tree_sitter import Language, Parser

from .codebase import Code

JS = Language(tsjs.language())

EXPR_VAR = re.compile(r"[$*]\{\s*([A-Za-z_]\w*)")
SKIP_VARS = {"param", "session", "application", "request", "response", "T", "true", "false", "null"}
NOTABLE_INPUT_ATTRS = ("required", "maxlength", "minlength", "pattern", "readonly", "disabled", "min", "max")
NOTABLE_INPUT_TYPES = {"email", "url", "number", "date", "tel", "datetime-local", "month", "time"}
CONTROL_TAGS = {"a", "button", "form"}
PAGE_EVENTS = {"DOMContentLoaded", "load", "readystatechange"}


def norm_url(raw: str | None) -> str | None:
    """@{/notices/{id}/edit(id=${notice.id})} → /notices/{}/edit, /login?error → /login. 경로가 아니면 None."""
    if not raw:
        return None
    u = raw.strip()
    if u.startswith("@{") and u.endswith("}"):
        u = u[2:-1]
    u = re.sub(r"\([^()]*\)$", "", u)                    # Thymeleaf 매개변수 부분
    u = re.sub(r"\$\{[^}]*\}", "{}", u)
    u = re.sub(r"\{[^}/]*\}", "{}", u)
    u = u.split("?")[0].split("#")[0]
    if not u.startswith("/"):
        return None
    return u.rstrip("/") or "/"


# ---------------------------------------------------------------- 템플릿

@dataclass
class Control:
    tag: str
    line: int
    attrs: dict
    text: str = ""


@dataclass
class Template:
    path: str
    view: str                                                   # templates/ 아래 경로, .html 뺀 이름
    refs: dict[str, list[tuple[int, str]]] = field(default_factory=dict)   # 모델 변수 → [(줄, 원문)]
    error_outputs: list[tuple[int, str]] = field(default_factory=list)     # th:errors, #fields...
    includes: list[tuple[str, int]] = field(default_factory=list)          # (조각 템플릿 뷰 이름, 줄)
    scripts: list[tuple[str, int]] = field(default_factory=list)           # (URL, 줄)
    url_refs: list[tuple[str, str, int, str]] = field(default_factory=list)  # (메서드, 경로, 줄, 종류)
    inputs: list[tuple[int, dict]] = field(default_factory=list)
    controls: list[Control] = field(default_factory=list)
    provides_fragment: bool = False
    title: str = ""
    headings: list[str] = field(default_factory=list)          # h1, h2 글자 (화면 이름 대조용)
    text: str = ""

    def refers(self, name: str) -> list[tuple[int, str]]:
        return self.refs.get(name, [])


class _TemplateParser(HTMLParser):
    def __init__(self, tpl: Template):
        super().__init__(convert_charrefs=True)
        self.t = tpl
        self.stack: list[Control] = []
        self.in_title = False
        self.in_heading = False

    def _expr(self, line: int, value: str):
        for m in EXPR_VAR.finditer(value or ""):
            name = m.group(1)
            if name not in SKIP_VARS:
                self.t.refs.setdefault(name, []).append((line, value.strip()[:80]))
        if "#fields" in (value or ""):
            self.t.error_outputs.append((line, value.strip()[:80]))

    def handle_starttag(self, tag, attrs):
        line = self.getpos()[0]
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        for k, v in a.items():
            if k.startswith(("th:", "data-th-", "sec:")) or "${" in v or "*{" in v:
                self._expr(line, v)
            if k in ("th:errors", "data-th-errors"):
                self.t.error_outputs.append((line, f'th:errors="{v}"'))
            if k in ("th:fragment",):
                self.t.provides_fragment = True
            if k in ("th:replace", "th:insert", "th:include"):
                m = re.search(r"~\{\s*([\w/\-.]+)\s*::", v) or re.search(r"^\s*([\w/\-.]+)\s*::", v)
                if m:
                    self.t.includes.append((m.group(1), line))
        if tag == "script":
            src = a.get("th:src") or a.get("src")
            if src:
                self.t.scripts.append((src, line))
        if tag == "form":
            url = norm_url(a.get("th:action") or a.get("action"))
            if url:
                self.t.url_refs.append(((a.get("method") or "get").upper(), url, line, "폼"))
        if tag == "a":
            url = norm_url(a.get("th:href") or a.get("href"))
            if url:
                self.t.url_refs.append(("GET", url, line, "링크"))
        if tag in ("input", "textarea", "select"):
            self.t.inputs.append((line, a))
        if tag == "title":
            self.in_title = True
        if tag in ("h1", "h2"):
            self.in_heading = True
            self.t.headings.append("")
        if tag in CONTROL_TAGS:
            if tag == "button":                       # 버튼이 속한 폼의 주소·메서드를 붙여 둔다 (화면 이동 따라가기용)
                form = next((c for c in reversed(self.stack) if c.tag == "form"), None)
                if form is not None and (a.get("type") or "submit").lower() == "submit":
                    a["_form_action"] = form.attrs.get("th:action") or form.attrs.get("action") or ""
                    a["_form_method"] = (form.attrs.get("method") or "get").upper()
            ctl = Control(tag, line, a)
            self.t.controls.append(ctl)
            self.stack.append(ctl)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in CONTROL_TAGS and self.stack and self.stack[-1].tag == tag:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in ("h1", "h2"):
            self.in_heading = False
        if tag in CONTROL_TAGS:
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i].tag == tag:
                    del self.stack[i:]
                    break

    def handle_data(self, data):
        line = self.getpos()[0]
        if "[[" in data or "[(" in data:
            self._expr(line, data)
        if self.in_title:
            self.t.title += data.strip()
        if self.in_heading and self.t.headings:
            self.t.headings[-1] += data.strip()
        for ctl in self.stack:
            ctl.text += " " + data.strip()


def parse_template(code: Code, path: str) -> Template:
    idx = path.find("templates/")
    view = path[idx + len("templates/"):] if idx >= 0 else path
    view = re.sub(r"\.html?$", "", view)
    t = Template(path=path, view=view, text=code.text(path))
    p = _TemplateParser(t)
    p.feed(t.text)
    p.close()
    for ctl in t.controls:
        ctl.text = re.sub(r"\s+", " ", ctl.text).strip()
    return t


def is_template(path: str) -> bool:
    return "/templates/" in f"/{path}" and path.lower().endswith((".html", ".htm"))


# ---------------------------------------------------------------- JS

def _t(node) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _short(s: str, n: int = 80) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _str_value(node) -> str | None:
    if node is None:
        return None
    if node.type == "string":
        frag = [c for c in node.children if c.type in ("string_fragment", "escape_sequence")]
        return "".join(_t(c) for c in frag)
    if node.type == "template_string":
        out = []
        for c in node.children:
            if c.type == "string_fragment":
                out.append(_t(c))
            elif c.type == "template_substitution":
                out.append("{}")
        return "".join(out)
    return None


@dataclass
class Binding:
    line: int
    target: str          # 선택자 또는 원문
    var: str | None
    event: str
    handler: str
    effects: list[str]
    effect_targets: list[str] = field(default_factory=list)   # 처리 함수가 바꾸는 요소의 선택자


@dataclass
class JsFile:
    path: str
    selectors: dict[str, str] = field(default_factory=dict)      # 변수 → 선택자
    bindings: list[Binding] = field(default_factory=list)
    has_regex: bool = False
    url_refs: list[tuple[str, str, int, str]] = field(default_factory=list)   # (메서드, 경로, 줄, 종류)

    @property
    def events(self) -> set[str]:
        return {b.event for b in self.bindings}

    def user_bindings(self) -> list["Binding"]:
        """페이지가 뜰 때 한 번 도는 감싸기(DOMContentLoaded, load)는 뺀 이벤트."""
        return [b for b in self.bindings if b.event not in PAGE_EVENTS]


class JsAnalyzer:
    def __init__(self, code: Code):
        self.code = code
        self.parser = Parser(JS)

    def analyze(self, path: str) -> JsFile:
        src = self.code.text(path).encode("utf-8")
        root = self.parser.parse(src).root_node
        jf = JsFile(path)
        functions: dict[str, object] = {}
        for n in _walk(root):
            if n.type == "function_declaration":
                functions[_t(n.child_by_field_name("name"))] = n
            elif n.type == "variable_declarator":
                name, value = _t(n.child_by_field_name("name")), n.child_by_field_name("value")
                if value is not None and value.type in ("arrow_function", "function_expression", "function"):
                    functions[name] = value
                sel = self._selector_call(value)
                if sel:
                    jf.selectors[name] = sel
            elif n.type == "regex":
                jf.has_regex = True
        for n in _walk(root):
            if n.type == "call_expression":
                fn = n.child_by_field_name("function")
                if fn is not None and fn.type == "member_expression" and _t(fn.child_by_field_name("property")) == "addEventListener":
                    self._binding(jf, n, fn, functions)
                elif fn is not None and _t(fn) == "fetch":
                    self._fetch(jf, n)
            elif n.type == "assignment_expression":
                left = n.child_by_field_name("left")
                if left is not None and left.type == "member_expression" and _t(left.child_by_field_name("property")) in ("href",) \
                        and "location" in _t(left):
                    url = _str_value(n.child_by_field_name("right"))
                    from_url = _norm_js_url(url)
                    if from_url:
                        jf.url_refs.append(("GET", from_url, n.start_point[0] + 1, "JS 이동"))
                elif left is not None and left.type == "member_expression" and _t(left.child_by_field_name("property")).startswith("on") \
                        and n.child_by_field_name("right") is not None \
                        and n.child_by_field_name("right").type in ("arrow_function", "function_expression", "function", "identifier"):
                    obj = left.child_by_field_name("object")
                    right = n.child_by_field_name("right")
                    handler, effects = self._handler(right, functions)
                    var = _t(obj)
                    jf.bindings.append(Binding(n.start_point[0] + 1, jf.selectors.get(var, var), var,
                                               _t(left.child_by_field_name("property"))[2:], handler, effects))
        return jf

    @staticmethod
    def _selector_call(node) -> str | None:
        if node is None or node.type != "call_expression":
            return None
        fn = node.child_by_field_name("function")
        if fn is None or fn.type != "member_expression":
            return None
        prop = _t(fn.child_by_field_name("property"))
        if prop not in ("querySelector", "getElementById", "querySelectorAll", "getElementsByClassName", "getElementsByName"):
            return None
        args = node.child_by_field_name("arguments")
        first = args.named_children[0] if args is not None and args.named_child_count else None
        v = _str_value(first)
        if v is None:
            return None
        return f"#{v}" if prop == "getElementById" else v

    def _binding(self, jf: JsFile, call, fn, functions):
        obj = fn.child_by_field_name("object")
        var = _t(obj).rstrip("?")
        args = call.child_by_field_name("arguments")
        named = args.named_children if args is not None else []
        if not named:
            return
        event = _str_value(named[0]) or _t(named[0])
        handler_node = named[1] if len(named) > 1 else None
        target = jf.selectors.get(var)
        if target is None:
            target = self._foreach_selector(call, var, jf.selectors) or var
        handler, effects = self._handler(handler_node, functions)
        changed = re.findall(r"(\w+)\.(?:disabled|hidden|textContent|innerText|innerHTML|value|type|checked|src|href|className)\s*=",
                             " ; ".join(effects))
        jf.bindings.append(Binding(fn.child_by_field_name("property").start_point[0] + 1, target,
                                   var if var in jf.selectors else None, event, handler, effects,
                                   [jf.selectors[c] for c in dict.fromkeys(changed) if c in jf.selectors]))

    def _foreach_selector(self, node, param: str, selectors: dict[str, str] | None = None) -> str | None:
        """forEach로 여러 요소에 같은 이벤트를 붙인 경우 대상 요소를 찾는다.
        document.querySelectorAll(".x").forEach((b) => b.addEventListener(...)) → .x의 각 요소
        [emailInput, nameInput].forEach((el) => el.addEventListener(...))      → #email, #name"""
        p = node.parent
        while p is not None:
            if p.type == "call_expression":
                fn = p.child_by_field_name("function")
                if fn is not None and fn.type == "member_expression" and _t(fn.child_by_field_name("property")) == "forEach":
                    obj = fn.child_by_field_name("object")
                    sel = self._selector_call(obj)
                    if sel:
                        return f"{sel}의 각 요소"
                    if obj is not None and obj.type == "array":
                        names = [_t(e) for e in obj.named_children]
                        return ", ".join((selectors or {}).get(x, x) for x in names)
            p = p.parent
        return None

    def _handler(self, node, functions) -> tuple[str, list[str]]:
        if node is None:
            return "(없음)", []
        if node.type == "identifier":
            name = _t(node)
            body = functions.get(name)
            return name, self._effects(body, functions, depth=1) if body is not None else []
        return "(그 자리의 함수)", self._effects(node, functions, depth=1)

    def _effects(self, node, functions, depth: int) -> list[str]:
        out: list[str] = []
        for n in _walk(node):
            if n.type == "assignment_expression":
                left = n.child_by_field_name("left")
                if left is not None and left.type == "member_expression" and _t(left.child_by_field_name("property")) in (
                        "disabled", "hidden", "textContent", "innerText", "innerHTML", "value", "type", "checked",
                        "src", "href", "className"):
                    out.append(f"{_short(_t(left), 40)} = {_short(_t(n.child_by_field_name('right')), 70)}")
            elif n.type == "call_expression":
                fn = n.child_by_field_name("function")
                ft = _t(fn)
                if ft == "fetch":
                    args = n.child_by_field_name("arguments")
                    first = args.named_children[0] if args is not None and args.named_child_count else None
                    out.append(f"fetch {_str_value(first) or _short(_t(first), 50)}")
                elif ft.endswith((".add", ".remove", ".toggle")) and "classList" in ft:
                    out.append(_short(_t(n), 60))
                elif ft in ("alert", "confirm", "window.alert", "window.confirm"):
                    out.append(_short(_t(n), 60))
                elif ft.endswith(".preventDefault"):
                    out.append("기본 동작 막음(preventDefault)")
                elif ft in ("setTimeout", "window.setTimeout"):
                    out.append("setTimeout으로 지연 실행")
                elif ft.endswith(".test") or ft.endswith(".match"):
                    out.append(f"정규식 검사 {_short(ft, 40)}")
                elif depth > 0 and fn is not None and fn.type == "identifier" and _t(fn) in functions:
                    inner = self._effects(functions[_t(fn)], functions, depth - 1)
                    if inner:
                        out.append(f"{_t(fn)}() 호출: " + "; ".join(inner[:2]))
        return list(dict.fromkeys(out))[:4]

    def _fetch(self, jf: JsFile, call):
        args = call.child_by_field_name("arguments")
        named = args.named_children if args is not None else []
        if not named:
            return
        url = _norm_js_url(_str_value(named[0]))
        method = "GET"
        if len(named) > 1 and named[1].type == "object":
            m = re.search(r"method\s*:\s*['\"](\w+)['\"]", _t(named[1]))
            if m:
                method = m.group(1).upper()
        if url:
            jf.url_refs.append((method, url, call.start_point[0] + 1, "JS fetch"))


def _norm_js_url(url: str | None) -> str | None:
    if not url:
        return None
    return norm_url(url)

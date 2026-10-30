"""analyze_frontend_js.py — 프론트엔드(.js)를 tree-sitter로 파싱해 구조적 사실을 뽑는다.

다음 네 가지를 뽑는다.
  - selectors        어떤 DOM 요소(선택자)가 어떤 변수에 담겼는가
  - event_bindings   그 변수에 어떤 이벤트(input/blur/click 등) 리스너가 붙어 있는가
  - regex_literals   파일 안에 정규식 리터럴이 있는가
  - string_literals  파일 안의 문자열 리터럴 (문구 대조용)
이번에 더한 것
  - 이벤트 처리 함수가 실제로 무엇을 바꾸는지 (effects: 버튼 disabled, 문구, fetch, classList …)
  - forEach로 여러 요소에 한꺼번에 붙인 이벤트의 대상 요소 (target)
  - 서버 요청·이동 주소 (url_refs: fetch, location.href)
  - 경로를 파일 이름이 아니라 ③과 같은 상대 경로로, 줄 번호를 ③의 줄 목록 기준으로 낸다
  - 라이브러리에 넘기는 설정 객체 (lib_configs: AG Grid 옵션처럼 이벤트가 아니라 설정으로 동작하는 기능)
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import tree_sitter_javascript as tsjs
from tree_sitter import Language, Parser

JS_LANGUAGE = Language(tsjs.language())
PAGE_EVENTS = {"DOMContentLoaded", "load", "readystatechange"}
# 설정 객체로 보지 않는 호출 (이벤트·요청·배열 순회 등은 따로 다루거나 사실과 관계없음)
NOT_CONFIG_CALLS = ("addEventListener", "removeEventListener", "fetch", "then", "catch", "finally", "forEach", "map",
                    "filter", "reduce", "find", "some", "every", "push", "assign", "stringify", "parse", "log", "warn",
                    "error", "setTimeout", "setInterval", "querySelector", "querySelectorAll", "getElementById")
EFFECT_PROPS = ("disabled", "hidden", "textContent", "innerText", "innerHTML", "value", "type", "checked", "src", "href",
                "className")


def _t(node) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def _line(node) -> int:
    return node.start_point[0] + 1


def _iter_nodes(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def _short(s: str, n: int = 80) -> str:
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _string_value(node) -> str | None:
    """'string'·'template_string' 노드의 값. 템플릿 문자열의 ${…}는 {}로 둔다."""
    if node is None:
        return None
    if node.type == "string":
        return "".join(_t(c) for c in node.children if c.type in ("string_fragment", "escape_sequence"))
    if node.type == "template_string":
        return "".join(_t(c) if c.type == "string_fragment" else "{}" for c in node.children
                       if c.type in ("string_fragment", "template_substitution"))
    return None


def norm_url(url: str | None) -> str | None:
    if not url:
        return None
    u = re.sub(r"\{[^}/]*\}", "{}", url.split("?")[0].split("#")[0])
    if not u.startswith("/"):
        return None
    return u.rstrip("/") or "/"


def _selector_call(node) -> str | None:
    """document.querySelector("#x") / getElementById("x") / querySelectorAll(".x") → 선택자"""
    if node is None or node.type != "call_expression":
        return None
    fn = node.child_by_field_name("function")
    if fn is None or fn.type != "member_expression":
        return None
    prop = _t(fn.child_by_field_name("property"))
    if prop not in ("querySelector", "getElementById", "querySelectorAll", "getElementsByClassName", "getElementsByName"):
        return None
    args = node.child_by_field_name("arguments")
    v = _string_value(args.named_children[0]) if args is not None and args.named_child_count else None
    if v is None:
        return None
    return f"#{v}" if prop == "getElementById" else v


def parse_js_source(file: str, text: str) -> dict:
    root = Parser(JS_LANGUAGE).parse(text.encode("utf-8")).root_node
    selectors, event_bindings, regex_literals, string_literals, url_refs = [], [], [], [], []
    functions: dict[str, object] = {}
    sel_by_var: dict[str, str] = {}

    for node in _iter_nodes(root):
        if node.type == "function_declaration":
            functions[_t(node.child_by_field_name("name"))] = node
        elif node.type == "variable_declarator":
            name, value = _t(node.child_by_field_name("name")), node.child_by_field_name("value")
            if value is not None and value.type in ("arrow_function", "function_expression", "function"):
                functions[name] = value
            sel = _selector_call(value)
            if sel is not None:
                sel_by_var[name] = sel
                selectors.append({"var_name": name, "selector": sel, "line": _line(node)})
        elif node.type == "regex":
            pat = node.child_by_field_name("pattern")
            regex_literals.append({"pattern": _t(pat) if pat is not None else _t(node), "line": _line(node)})
        elif node.type == "string":
            string_literals.append({"value": _string_value(node), "line": _line(node)})

    def effects(body, depth: int) -> list[str]:
        out = []
        for n in _iter_nodes(body):
            if n.type == "assignment_expression":
                left = n.child_by_field_name("left")
                if left is not None and left.type == "member_expression" and _t(left.child_by_field_name("property")) in EFFECT_PROPS:
                    out.append(f"{_short(_t(left), 40)} = {_short(_t(n.child_by_field_name('right')), 70)}")
            elif n.type == "call_expression":
                fn = n.child_by_field_name("function")
                ft = _t(fn)
                args = n.child_by_field_name("arguments")
                first = args.named_children[0] if args is not None and args.named_child_count else None
                if ft == "fetch":
                    out.append(f"fetch {_string_value(first) or _short(_t(first), 50)}")
                elif "classList" in ft and ft.endswith((".add", ".remove", ".toggle")):
                    out.append(_short(_t(n), 60))
                elif ft in ("alert", "confirm", "window.alert", "window.confirm"):
                    out.append(_short(_t(n), 60))
                elif ft.endswith(".preventDefault"):
                    out.append("기본 동작 막음(preventDefault)")
                elif ft in ("setTimeout", "window.setTimeout"):
                    out.append("setTimeout으로 지연 실행")
                elif ft.endswith((".test", ".match")):
                    out.append(f"정규식 검사 {_short(ft, 40)}")
                elif depth > 0 and fn is not None and fn.type == "identifier" and ft in functions:
                    inner = effects(functions[ft], depth - 1)
                    if inner:
                        out.append(f"{ft}() 호출: " + "; ".join(inner[:2]))
        return list(dict.fromkeys(out))[:4]

    def handler_of(node) -> tuple[str, list[str]]:
        if node is None:
            return "(없음)", []
        if node.type == "identifier":
            body = functions.get(_t(node))
            return _t(node), effects(body, 1) if body is not None else []
        return "<inline function>", effects(node, 1)

    def foreach_target(node) -> str | None:
        p = node.parent
        while p is not None:
            if p.type == "call_expression":
                fn = p.child_by_field_name("function")
                if fn is not None and fn.type == "member_expression" and _t(fn.child_by_field_name("property")) == "forEach":
                    obj = fn.child_by_field_name("object")
                    sel = _selector_call(obj)
                    if sel:
                        return f"{sel}의 각 요소"
                    if obj is not None and obj.type == "array":
                        return ", ".join(sel_by_var.get(_t(e), _t(e)) for e in obj.named_children)
            p = p.parent
        return None

    for node in _iter_nodes(root):
        if node.type == "call_expression":
            fn = node.child_by_field_name("function")
            if fn is not None and fn.type == "member_expression" and _t(fn.child_by_field_name("property")) == "addEventListener":
                obj_expr = _t(fn.child_by_field_name("object")).rstrip("?")
                args = node.child_by_field_name("arguments")
                named = args.named_children if args is not None else []
                if not named:
                    continue
                event = _string_value(named[0]) or _t(named[0])
                handler, eff = handler_of(named[1] if len(named) > 1 else None)
                changed = re.findall(r"(\w+)\.(?:%s)\s*=" % "|".join(EFFECT_PROPS), " ; ".join(eff))
                event_bindings.append({
                    "object_expr": obj_expr,
                    "target": sel_by_var.get(obj_expr) or foreach_target(node) or obj_expr,
                    "event_type": event,
                    "handler": handler,
                    "effects": eff,
                    "effect_targets": [sel_by_var[c] for c in dict.fromkeys(changed) if c in sel_by_var],
                    "line": _line(fn.child_by_field_name("property")),
                })
            elif fn is not None and _t(fn) == "fetch":
                args = node.child_by_field_name("arguments")
                named = args.named_children if args is not None else []
                url = norm_url(_string_value(named[0])) if named else None
                method = "GET"
                if len(named) > 1 and named[1].type == "object":
                    m = re.search(r"method\s*:\s*['\"](\w+)['\"]", _t(named[1]))
                    method = m.group(1).upper() if m else "GET"
                if url:
                    url_refs.append({"method": method, "url": url, "line": _line(node), "kind": "JS fetch"})
        elif node.type == "assignment_expression":
            left = node.child_by_field_name("left")
            if left is not None and left.type == "member_expression" and _t(left.child_by_field_name("property")) == "href" \
                    and "location" in _t(left):
                url = norm_url(_string_value(node.child_by_field_name("right")))
                if url:
                    url_refs.append({"method": "GET", "url": url, "line": _line(node), "kind": "JS 이동"})

    # ---- 라이브러리 설정 객체: 호출·생성자에 넘기는 객체 리터럴 (직접 또는 변수로)
    objects_by_var: dict[str, object] = {}
    arrays_by_var: dict[str, object] = {}
    for node in _iter_nodes(root):
        if node.type == "variable_declarator":
            v = node.child_by_field_name("value")
            if v is not None and v.type == "object":
                objects_by_var[_t(node.child_by_field_name("name"))] = v
            elif v is not None and v.type == "array":
                arrays_by_var[_t(node.child_by_field_name("name"))] = v

    def value_text(v) -> str:
        if v is None:
            return "?"
        if v.type in ("string", "template_string"):
            return f"\"{_string_value(v)}\""
        if v.type in ("number", "true", "false", "null"):
            return _t(v)
        if v.type == "array":
            if all(e.type in ("number", "string", "true", "false") for e in v.named_children):
                return "[" + ", ".join(value_text(e) for e in v.named_children) + "]"
            return array_summary(v)
        if v.type in ("arrow_function", "function_expression", "function"):
            eff = effects(v, 1)
            return "함수" + (f"({'; '.join(eff)})" if eff else "")
        if v.type == "identifier" and _t(v) in arrays_by_var:
            return array_summary(arrays_by_var[_t(v)])
        return _short(_t(v), 40)

    def array_summary(arr) -> str:
        """[{headerName: "번호", ...}, ...] → 객체 N개 (headerName: 번호, 제목, …)"""
        objs = [e for e in arr.named_children if e.type == "object"]
        if not objs:
            return _short(_t(arr), 50)
        first_key = None
        vals = []
        for o in objs:
            for pair in o.named_children:
                if pair.type == "pair" and pair.child_by_field_name("value") is not None \
                        and pair.child_by_field_name("value").type == "string":
                    k = _t(pair.child_by_field_name("key")).strip("\"'")
                    if first_key in (None, k):
                        first_key = k
                        vals.append(_string_value(pair.child_by_field_name("value")))
                        break
        return f"객체 {len(objs)}개" + (f" ({first_key}: {', '.join(vals)})" if first_key else "")

    def props_of(obj, prefix: str = "", depth: int = 0) -> list[str]:
        out = []
        for pair in obj.named_children:
            if pair.type == "shorthand_property_identifier":
                name = _t(pair)
                out.append(f"{prefix}{name}={value_text_ident(name)}")
            elif pair.type == "pair":
                key = _t(pair.child_by_field_name("key")).strip("\"'")
                val = pair.child_by_field_name("value")
                if val is not None and val.type == "object" and depth < 1:
                    out += props_of(val, f"{prefix}{key}.", depth + 1)
                else:
                    out.append(f"{prefix}{key}={value_text(val)}")
        return out

    def value_text_ident(name: str) -> str:
        if name in arrays_by_var:
            return array_summary(arrays_by_var[name])
        if name in objects_by_var:
            return "{" + ", ".join(props_of(objects_by_var[name])[:6]) + "}"
        return name

    lib_configs = []
    seen_objects = set()
    for node in _iter_nodes(root):
        if node.type not in ("call_expression", "new_expression"):
            continue
        callee = node.child_by_field_name("function") if node.type == "call_expression" else node.child_by_field_name("constructor")
        callee_text = _t(callee)
        if not callee_text or callee_text.split(".")[-1] in NOT_CONFIG_CALLS:
            continue
        args = node.child_by_field_name("arguments")
        for a in (args.named_children if args is not None else []):
            obj, var = None, None
            if a.type == "object":
                obj = a
            elif a.type == "identifier" and _t(a) in objects_by_var:
                obj, var = objects_by_var[_t(a)], _t(a)
            if obj is None or obj.start_byte in seen_objects:
                continue
            props = props_of(obj)
            if len(props) < 2:
                continue
            seen_objects.add(obj.start_byte)
            lib_configs.append({"callee": callee_text, "var": var, "line": _line(obj), "call_line": _line(node),
                                "props": props[:16]})

    return {"file": file, "selectors": selectors, "event_bindings": event_bindings, "regex_literals": regex_literals,
            "string_literals": string_literals, "url_refs": url_refs, "lib_configs": lib_configs}


def user_bindings(result: dict) -> list[dict]:
    """페이지가 뜰 때 한 번 도는 감싸기(DOMContentLoaded 등)는 뺀 이벤트."""
    return [b for b in result["event_bindings"] if b["event_type"] not in PAGE_EVENTS]


def analyze(code) -> dict[str, dict]:
    """③의 코드 묶음(codebase.Code)에 있는 .js 파일마다 분석한다 (경로·줄 번호가 ③과 같다)."""
    return {p: parse_js_source(p, code.text(p)) for p in code.by_suffix(".js")}


def parse_js_file(path: Path) -> dict:
    """파일 하나 (verification2와 같은 사용법). file에는 파일 이름이 들어간다."""
    return parse_js_source(path.name, path.read_text(encoding="utf-8"))


def analyze_js_directory(js_root: Path) -> dict:
    """폴더 전체 (verification2와 같은 모양으로 합친다)."""
    aggregated = {"files": [], "selectors": [], "event_bindings": [], "regex_literals": [], "string_literals": [], "url_refs": [],
                  "lib_configs": []}
    for js_file in sorted(js_root.rglob("*.js")):
        result = parse_js_file(js_file)
        aggregated["files"].append(result["file"])
        for key in ("selectors", "event_bindings", "regex_literals", "string_literals", "url_refs", "lib_configs"):
            aggregated[key] += [{"file": result["file"], **item} for item in result[key]]
    return aggregated


if __name__ == "__main__":
    import sys
    print(json.dumps(analyze_js_directory(Path(sys.argv[1] if len(sys.argv) > 1 else ".")), ensure_ascii=False, indent=2))

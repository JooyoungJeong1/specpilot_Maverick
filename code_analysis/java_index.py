"""Java 소스를 tree-sitter로 읽어 클래스·필드·메서드·애노테이션 색인을 만든다.

2주차 JavaParser 분석기(specpilot-analyzer)가 하던 일 가운데 사실을 만드는 데 필요한 부분을 옮겼다.
- 타입 해석: 메서드 안의 `memberRepository.existsByEmail(...)`에서 `memberRepository`의 타입을
  매개변수 → 지역 변수 → 필드 순서로 찾아 `MemberRepository.existsByEmail`로 잇는다.
  스프링의 필드 주입·생성자 주입 코드는 이 방식으로 대부분 풀린다 (JavaParser Symbol Solver보다 단순한 대신
  빌드나 classpath, Lombok 처리가 필요 없고, ③과 같은 줄 번호를 그대로 쓴다).
- Spring Data: JpaRepository 등을 상속한 인터페이스의 메서드는 "구현 코드 없이 이름 규칙으로 동작"으로 표시한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import tree_sitter_java as tsjava
from tree_sitter import Language, Parser

from .codebase import Code

JAVA = Language(tsjava.language())

SPRING_DATA_BASES = {"JpaRepository", "CrudRepository", "PagingAndSortingRepository", "Repository",
                     "ListCrudRepository", "ListPagingAndSortingRepository", "MongoRepository",
                     "ReactiveCrudRepository", "JpaSpecificationExecutor"}


def node_text(node) -> str:
    return node.text.decode("utf-8", errors="replace") if node is not None else ""


def line_of(node) -> int:
    return node.start_point[0] + 1


def string_value(node) -> str | None:
    """"..." 문자열 리터럴의 값. 리터럴이 아니면 None."""
    if node is None or node.type != "string_literal":
        return None
    raw = node_text(node)
    if raw.startswith('"""'):
        return raw[3:-3]
    body = raw[1:-1]
    return (body.replace('\\"', '"').replace("\\n", "\n").replace("\\t", "\t").replace("\\\\", "\\"))


def simple_type(text: str) -> str:
    """List<Member> → List, java.util.Map → Map, Member[] → Member"""
    t = re.sub(r"<.*>", "", text or "").replace("[]", "").strip()
    return t.split(".")[-1]


def walk(node):
    stack = [node]
    while stack:
        n = stack.pop()
        yield n
        stack.extend(reversed(n.children))


def ancestors(node):
    p = node.parent
    while p is not None:
        yield p
        p = p.parent


# ---------------------------------------------------------------- 모양

@dataclass
class Annotation:
    name: str
    line: int
    values: list[str] = field(default_factory=list)          # 이름 없는 값 또는 value=/path= 의 문자열
    pairs: dict[str, str] = field(default_factory=dict)       # 이름=값 (원문 그대로, 문자열이면 따옴표 뺀 값)
    raw_args: str = ""

    def get(self, key: str) -> str | None:
        return self.pairs.get(key)


@dataclass
class Param:
    name: str
    type: str
    annotations: list[Annotation]

    def has(self, *names: str) -> bool:
        return any(a.name in names for a in self.annotations)

    def ann(self, name: str) -> Annotation | None:
        return next((a for a in self.annotations if a.name == name), None)


@dataclass
class FieldInfo:
    name: str
    type: str
    line: int
    annotations: list[Annotation]


@dataclass
class MethodInfo:
    name: str
    cls: "ClassInfo"
    line: int                      # 메서드 이름이 있는 줄
    ann_line: int                  # 선언 시작 줄 (애노테이션 포함)
    annotations: list[Annotation]
    params: list[Param]
    return_type: str
    node: object
    body: object | None

    @property
    def file(self) -> str:
        return self.cls.file

    @property
    def qname(self) -> str:
        return f"{self.cls.name}.{self.name}"

    def ann(self, *names: str) -> Annotation | None:
        return next((a for a in self.annotations if a.name in names), None)

    def has(self, *names: str) -> bool:
        return self.ann(*names) is not None


@dataclass
class ClassInfo:
    name: str
    kind: str                      # class | interface | enum | record
    file: str
    line: int
    annotations: list[Annotation]
    extends: list[str]
    implements: list[str]
    fields: dict[str, FieldInfo] = field(default_factory=dict)
    methods: list[MethodInfo] = field(default_factory=list)

    def ann(self, *names: str) -> Annotation | None:
        return next((a for a in self.annotations if a.name in names), None)

    def has(self, *names: str) -> bool:
        return self.ann(*names) is not None

    def method(self, name: str) -> list[MethodInfo]:
        return [m for m in self.methods if m.name == name]

    @property
    def is_spring_data(self) -> bool:
        return self.kind == "interface" and any(t in SPRING_DATA_BASES for t in self.extends)


@dataclass
class Call:
    """메서드 안의 호출 하나."""
    node: object
    name: str
    receiver: str | None           # 받는 쪽 원문 (예: memberRepository), 없으면 None
    target: ClassInfo | None       # 색인 안의 클래스로 풀렸으면 그 클래스
    line: int
    source: str = "heuristic"      # javaparser | javaparser-library | heuristic
    decl: tuple[str, int] | None = None          # JavaParser가 알려 준 선언 위치 (파일, 메서드 이름 줄)
    impls: list[tuple[str, int]] = field(default_factory=list)   # 인터페이스 메서드면 구현 메서드 위치

    @property
    def label(self) -> str:
        return f"{self.target.name}.{self.name}" if self.target else (f"{self.receiver}.{self.name}" if self.receiver else self.name)


# ---------------------------------------------------------------- 파싱

def parse_annotations(modifiers) -> list[Annotation]:
    out = []
    if modifiers is None:
        return out
    for child in modifiers.children:
        if child.type not in ("annotation", "marker_annotation"):
            continue
        name = node_text(child.child_by_field_name("name")).split(".")[-1]
        ann = Annotation(name=name, line=line_of(child))
        args = child.child_by_field_name("arguments")
        if args is not None:
            ann.raw_args = node_text(args)
            for a in args.named_children:
                if a.type == "element_value_pair":
                    key = node_text(a.child_by_field_name("key"))
                    val = a.child_by_field_name("value")
                    strs = _strings_in(val)
                    ann.pairs[key] = strs[0] if len(strs) == 1 and val.type == "string_literal" else node_text(val)
                    if key in ("value", "path"):
                        ann.values.extend(strs)
                else:
                    ann.values.extend(_strings_in(a))
                    if a.type not in ("string_literal", "element_value_array_initializer"):
                        ann.pairs.setdefault("value", node_text(a))
        out.append(ann)
    return out


def _strings_in(node) -> list[str]:
    if node is None:
        return []
    if node.type == "string_literal":
        return [string_value(node)]
    return [string_value(n) for n in walk(node) if n.type == "string_literal"]


def _modifiers(node):
    return next((c for c in node.children if c.type == "modifiers"), None)


def _type_list(node) -> list[str]:
    if node is None:
        return []
    out = []
    for n in walk(node):
        if n.type in ("type_identifier", "scoped_type_identifier") and n.parent is not None \
                and n.parent.type in ("type_list", "superclass", "generic_type") \
                and not (n.parent.type == "generic_type" and n.parent.parent is not None
                         and n.parent.parent.type == "type_arguments"):
            if n.parent.type == "generic_type" and n.parent.children[0].start_byte != n.start_byte:
                continue
            out.append(simple_type(node_text(n)))
    return out


@dataclass
class JavaFile:
    path: str
    tree: object
    classes: list[ClassInfo]


class JavaIndex:
    """resolver를 주면(javaparser_bridge.Resolver) 호출의 타입 해석을 JavaParser 결과로 하고,
    JavaParser가 풀지 못한 호출만 아래의 간이 해석으로 채운다."""

    def __init__(self, code: Code, resolver=None):
        self.code = code
        self.resolver = resolver
        self.parser = Parser(JAVA)
        self.files: dict[str, JavaFile] = {}
        self.classes: dict[str, ClassInfo] = {}
        self._occ: dict[str, dict[int, int]] = {}            # 파일 → 호출 시작 바이트 → 같은 줄·같은 이름 안 순번
        self._stats: dict[str, int] = {}
        self.disagreements: list[str] = []
        self._calls_cache: dict[int, list] = {}
        for path in code.by_suffix(".java"):
            tree = self.parser.parse(code.text(path).encode("utf-8"))
            classes = []
            groups: dict[tuple[int, str], list[int]] = {}
            for n in walk(tree.root_node):
                if n.type in ("class_declaration", "interface_declaration", "enum_declaration", "record_declaration"):
                    classes.append(self._class(path, n))
                elif n.type == "method_invocation":
                    nm = n.child_by_field_name("name")
                    groups.setdefault((line_of(nm), node_text(nm)), []).append(nm.start_byte)
            self._occ[path] = {b: i for starts in groups.values() for i, b in enumerate(sorted(starts))}
            self.files[path] = JavaFile(path, tree, classes)
            for c in classes:
                self.classes.setdefault(c.name, c)

    def _class(self, path: str, n) -> ClassInfo:
        kind = n.type.replace("_declaration", "")
        extends = _type_list(n.child_by_field_name("superclass"))
        implements = _type_list(n.child_by_field_name("interfaces"))
        if kind == "interface":
            ext = next((c for c in n.children if c.type == "extends_interfaces"), None)
            extends = _type_list(ext)
        info = ClassInfo(name=node_text(n.child_by_field_name("name")), kind=kind, file=path, line=line_of(n),
                         annotations=parse_annotations(_modifiers(n)), extends=extends, implements=implements)
        body = n.child_by_field_name("body")
        if body is None:
            return info
        for m in body.named_children:
            if m.type == "field_declaration":
                ftype = simple_type(node_text(m.child_by_field_name("type")))
                anns = parse_annotations(_modifiers(m))
                for d in m.children_by_field_name("declarator"):
                    name = node_text(d.child_by_field_name("name"))
                    info.fields[name] = FieldInfo(name, ftype, line_of(d), anns)
            elif m.type in ("method_declaration", "constructor_declaration"):
                params = []
                ps = m.child_by_field_name("parameters")
                for p in (ps.named_children if ps is not None else []):
                    if p.type in ("formal_parameter", "spread_parameter"):
                        params.append(Param(node_text(p.child_by_field_name("name")),
                                            simple_type(node_text(p.child_by_field_name("type"))),
                                            parse_annotations(_modifiers(p))))
                name_node = m.child_by_field_name("name")
                info.methods.append(MethodInfo(
                    name=node_text(name_node), cls=info, line=line_of(name_node), ann_line=line_of(m),
                    annotations=parse_annotations(_modifiers(m)), params=params,
                    return_type=simple_type(node_text(m.child_by_field_name("type"))) if m.type == "method_declaration" else "",
                    node=m, body=m.child_by_field_name("body")))
        return info

    # ---------------- 조회

    def all_classes(self) -> list[ClassInfo]:
        return [c for f in self.files.values() for c in f.classes]

    def find_class(self, name: str) -> ClassInfo | None:
        return self.classes.get(simple_type(name))

    def field_type(self, cls: ClassInfo, name: str) -> str | None:
        """필드 타입. 이 클래스에 없으면 부모 클래스(이 코드 안에 있는 것)를 따라 올라가며 찾는다."""
        seen = set()
        c = cls
        while c is not None and c.name not in seen:
            seen.add(c.name)
            if name in c.fields:
                return c.fields[name].type
            c = self.find_class(c.extends[0]) if c.extends and c.kind == "class" else None
        return None

    def implementations(self, iface: str) -> list[ClassInfo]:
        return [c for c in self.all_classes() if iface in c.implements]

    # ---------------- 메서드 안의 호출 풀기

    def local_types(self, m: MethodInfo) -> dict[str, str]:
        types = {p.name: p.type for p in m.params}
        if m.body is not None:
            for n in walk(m.body):
                if n.type == "local_variable_declaration":
                    t = simple_type(node_text(n.child_by_field_name("type")))
                    for d in n.children_by_field_name("declarator"):
                        types[node_text(d.child_by_field_name("name"))] = t
                elif n.type in ("catch_formal_parameter",):
                    ct = next((c for c in n.children if c.type == "catch_type"), None)
                    nm = n.child_by_field_name("name")
                    if ct is not None and nm is not None:
                        types[node_text(nm)] = simple_type(node_text(ct).split("|")[0])
        return types

    def calls(self, m: MethodInfo) -> list[Call]:
        key = id(m)
        if key not in self._calls_cache:
            self._calls_cache[key] = self._calls(m)
        return self._calls_cache[key]

    def _calls(self, m: MethodInfo) -> list[Call]:
        if m.body is None:
            return []
        local = self.local_types(m)
        out = []
        for n in walk(m.body):
            if n.type != "method_invocation":
                continue
            name = node_text(n.child_by_field_name("name"))
            obj = n.child_by_field_name("object")
            receiver = node_text(obj) if obj is not None else None
            target = None
            if obj is None or receiver == "this":
                target = m.cls
            elif obj.type == "identifier":
                t = local.get(receiver) or self.field_type(m.cls, receiver)
                target = self.find_class(t) if t else self.find_class(receiver)     # 정적 호출: PasswordValidator.isValid
            elif obj.type == "field_access" and node_text(obj).startswith("this."):
                ftype = self.field_type(m.cls, node_text(obj)[5:])
                if ftype:
                    target = self.find_class(ftype)
            call = Call(n, name, receiver, target, line_of(n.child_by_field_name("name")))
            if self.resolver is not None:
                self._apply_resolver(m, call)
            self._stats[call.source] = self._stats.get(call.source, 0) + 1
            out.append(call)
        return out

    def _class_at(self, file: str | None, name: str | None) -> ClassInfo | None:
        if not file or file not in self.files:
            return None
        return next((c for c in self.files[file].classes if c.name == name), None)

    def _apply_resolver(self, m: MethodInfo, call: Call):
        """JavaParser 결과로 호출 대상을 정한다. 간이 해석과 다르면 기록해 둔다."""
        name_node = call.node.child_by_field_name("name")
        idx = self._occ.get(m.file, {}).get(name_node.start_byte, 0)
        r = self.resolver.lookup(m.file, call.line, call.name, idx)
        heuristic = call.target
        if r is None or not r.resolved:
            call.source = "heuristic"                # JavaParser가 못 푼 호출 → 간이 해석 결과를 그대로 쓴다
            return
        decl_cls = self._class_at(r.decl_file, r.declaring_type)
        if decl_cls is not None:                    # 이 프로젝트 코드의 선언으로 풀림
            call.target = decl_cls
            call.decl = (r.decl_file, r.decl_line)
            call.impls = list(r.impls)
            call.source = "javaparser"
            if heuristic is not None and heuristic is not decl_cls and heuristic.name != decl_cls.name \
                    and decl_cls.name not in heuristic.extends + heuristic.implements:
                self.disagreements.append(f"{m.file}:{call.line} {call.label}: 간이 해석은 {heuristic.name}, JavaParser는 {decl_cls.name}")
            elif heuristic is None:
                self.disagreements.append(f"{m.file}:{call.line} {call.name}: 간이 해석은 못 풂, JavaParser는 {decl_cls.name}")
        else:                                       # 라이브러리 선언으로 풀림 (Model.addAttribute, JpaRepository.save …)
            call.source = "javaparser-library"
            if heuristic is not None and heuristic.is_spring_data:
                return                              # 저장소 상속 메서드는 저장소 이름으로 남긴다 (MemberRepository.save)
            if heuristic is not None and heuristic is not m.cls:
                self.disagreements.append(f"{m.file}:{call.line} {call.label}: 간이 해석은 {heuristic.name}, "
                                          f"JavaParser는 라이브러리 {r.declaring_type}")
            call.target = None if heuristic is not m.cls else heuristic

    def resolution_stats(self) -> dict:
        for c in self.all_classes():                # 아직 안 본 메서드까지 한 번씩 돌려 숫자를 채운다
            for m in c.methods:
                self.calls(m)
        return {"by_source": dict(sorted(self._stats.items())), "disagreements": len(self.disagreements)}

    def method_at(self, file: str, line: int) -> MethodInfo | None:
        for c in (self.files[file].classes if file in self.files else []):
            for m in c.methods:
                if m.line == line:
                    return m
        return None

    def resolve_targets(self, call: Call) -> list[MethodInfo]:
        """호출이 실제로 실행할 수 있는 메서드들. 인터페이스 메서드면 구현 메서드까지 (구현이 여럿이면 모두)."""
        if call.decl is not None:
            out = []
            decl = self.method_at(*call.decl)
            if decl is not None:
                out.append(decl)
            out += [m for m in (self.method_at(f, l) for f, l in call.impls) if m is not None]
            return out
        m = self.resolve_method(call)
        return [m] if m is not None else []

    def resolve_method(self, call: Call) -> MethodInfo | None:
        if call.decl is not None:
            decl = self.method_at(*call.decl)
            if decl is not None and decl.body is None and call.impls:
                impl = self.method_at(*call.impls[0])
                return impl or decl
            return decl
        if call.target is None:
            return None
        ms = call.target.method(call.name)
        if ms:
            return ms[0]
        if call.target.kind == "interface":          # 인터페이스로 받은 경우 구현 클래스에서 찾는다
            for impl in self.implementations(call.target.name):
                ms = impl.method(call.name)
                if ms:
                    return ms[0]
        return None

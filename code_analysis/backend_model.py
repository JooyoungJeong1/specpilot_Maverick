"""백엔드 분석기 JSON(backend-analysis.json)을 사실 만들기 쉬운 모양으로 읽는다.

호출 대상 정하기 (분석기가 못 푼 호출을 어떻게 채우는지)
1. 분석기(Symbol Solver)가 이 코드 안의 선언으로 풀었으면 그대로 쓴다. 인터페이스면 구현 메서드까지 받는다.
2. 라이브러리 선언으로 풀었으면 화면 사실에서는 뺀다. 다만 Spring Data 저장소의 상속 메서드(save 등)는 저장소 이름으로 남긴다.
3. 메서드는 못 풀었어도 받는 쪽의 타입(receiver_type)은 분석기가 푸는 경우가 많다
   (인자가 Lombok getter라서 메서드 고르기만 실패한 경우). 그 타입의 같은 이름·같은 인자 수 메서드로 잇는다.
4. 받는 쪽이 없거나 this면 같은 클래스, 받는 쪽이 클래스 이름이면 정적 호출로 본다.
"""
from __future__ import annotations

from dataclasses import dataclass, field

SPRING_DATA_BASES = {"JpaRepository", "CrudRepository", "PagingAndSortingRepository", "Repository",
                     "ListCrudRepository", "ListPagingAndSortingRepository", "MongoRepository",
                     "ReactiveCrudRepository", "JpaSpecificationExecutor"}


@dataclass
class Ann:
    name: str
    line: int
    values: list
    pairs: dict

    def get(self, key):
        return self.pairs.get(key)


def _anns(items) -> list[Ann]:
    return [Ann(a["name"], a["line"], a.get("values", []), a.get("pairs", {})) for a in items or []]


@dataclass
class Param:
    name: str
    type: str
    annotations: list[Ann]

    def has(self, *names) -> bool:
        return any(a.name in names for a in self.annotations)


@dataclass
class Field:
    name: str
    type: str
    line: int
    annotations: list[Ann]


@dataclass
class Meth:
    name: str
    cls: "Cls"
    line: int
    ann_line: int
    annotations: list[Ann]
    params: list[Param]
    return_type: str
    has_body: bool
    returns: list[dict]
    model_attrs: list[dict]
    throws: list[dict]

    @property
    def file(self) -> str:
        return self.cls.file

    @property
    def qname(self) -> str:
        return f"{self.cls.name}.{self.name}"

    def ann(self, *names) -> Ann | None:
        return next((a for a in self.annotations if a.name in names), None)

    def has(self, *names) -> bool:
        return self.ann(*names) is not None


@dataclass
class Cls:
    name: str
    qualified: str
    kind: str
    file: str
    line: int
    annotations: list[Ann]
    extends: list[str]
    implements: list[str]
    fields: dict[str, Field] = field(default_factory=dict)
    methods: list[Meth] = field(default_factory=list)

    def ann(self, *names) -> Ann | None:
        return next((a for a in self.annotations if a.name in names), None)

    def has(self, *names) -> bool:
        return self.ann(*names) is not None

    def method(self, name: str) -> list[Meth]:
        return [m for m in self.methods if m.name == name]

    @property
    def is_spring_data(self) -> bool:
        return self.kind == "interface" and any(t in SPRING_DATA_BASES for t in self.extends)


@dataclass
class Call:
    raw: dict
    target: Cls | None = None
    source: str = "none"          # javaparser | javaparser-library | receiver_type | same_class | static | none
    decl: tuple[str, int] | None = None
    impls: list[tuple[str, int]] = field(default_factory=list)

    def __getattr__(self, key):
        try:
            return self.raw[key]
        except KeyError:
            raise AttributeError(key)

    @property
    def label(self) -> str:
        if self.target is not None:
            return f"{self.target.name}.{self.raw['name']}"
        r = self.raw.get("receiver")
        return f"{r}.{self.raw['name']}" if r else self.raw["name"]


class BackendModel:
    def __init__(self, data: dict):
        self.data = data
        self.classes: list[Cls] = []
        self.by_name: dict[str, Cls] = {}
        self.by_file_name: dict[tuple[str, str], Cls] = {}
        self.methods_at: dict[tuple[str, int], Meth] = {}
        for c in data.get("classes", []):
            cls = Cls(c["name"], c.get("qualified", c["name"]), c["kind"], c["file"], c["line"], _anns(c.get("annotations")),
                      c.get("extends", []), c.get("implements", []))
            for f in c.get("fields", []):
                cls.fields[f["name"]] = Field(f["name"], f["type"], f["line"], _anns(f.get("annotations")))
            for m in c.get("methods", []):
                meth = Meth(m["name"], cls, m["line"], m.get("ann_line", m["line"]), _anns(m.get("annotations")),
                            [Param(p["name"], p["type"], _anns(p.get("annotations"))) for p in m.get("params", [])],
                            m.get("return_type", ""), m.get("has_body", True), m.get("returns", []),
                            m.get("model_attrs", []), m.get("throws", []))
                cls.methods.append(meth)
                self.methods_at[(cls.file, meth.line)] = meth
            self.classes.append(cls)
            self.by_name.setdefault(cls.name, cls)
            self.by_file_name[(cls.file, cls.name)] = cls
        self.routes: list[dict] = data.get("routes", [])
        self.bindings: list[dict] = data.get("bindings", [])
        self.security: list[dict] = data.get("security", [])
        self.templates: dict[str, dict] = {t["view"]: t for t in data.get("templates", [])}
        self.calls: list[Call] = [self._resolve(c) for c in data.get("calls", [])]
        self.calls_by_method: dict[tuple[str, int], list[Call]] = {}
        for c in self.calls:
            if c.raw.get("caller_line") is not None:
                self.calls_by_method.setdefault((c.raw["file"], c.raw["caller_line"]), []).append(c)

    # ------------------------------------------------ 조회

    def find(self, name: str | None) -> Cls | None:
        return self.by_name.get(name) if name else None

    def implementations(self, iface: str) -> list[Cls]:
        return [c for c in self.classes if iface in c.implements]

    def calls_of(self, m: Meth) -> list[Call]:
        return self.calls_by_method.get((m.file, m.line), [])

    def route_method(self, r: dict) -> Meth | None:
        return self.methods_at.get((r["file"], r["method_line"]))

    # ------------------------------------------------ 호출 대상

    def _resolve(self, raw: dict) -> Call:
        c = Call(raw)
        caller = self.by_file_name.get((raw["file"], raw.get("caller_class") or ""))
        if raw.get("resolved") and raw.get("decl_file"):
            target = self.by_file_name.get((raw["decl_file"], raw.get("declaring_type")))
            if target is not None:
                c.target, c.source = target, "javaparser"
                c.decl = (raw["decl_file"], raw["decl_line"])
                c.impls = [(i["file"], i["line"]) for i in raw.get("impls", []) if i.get("file")]
                return c
        rtype = self.find(raw.get("receiver_type"))
        if raw.get("resolved"):
            c.source = "javaparser-library"
            if rtype is not None and rtype.is_spring_data:
                c.target = rtype                    # MemberRepository.save (Spring Data 기본 기능)
            return c
        if rtype is not None:
            c.target, c.source = rtype, "receiver_type"
            return c
        receiver = raw.get("receiver")
        if receiver in (None, "this") and caller is not None:
            c.target, c.source = caller, "same_class"
        elif receiver and receiver in self.by_name:
            c.target, c.source = self.by_name[receiver], "static"
        return c

    def resolve_targets(self, call: Call) -> list[Meth]:
        """호출이 실제로 실행할 수 있는 메서드들 (인터페이스면 구현 메서드 모두)."""
        if call.decl is not None:
            out = [m for m in (self.methods_at.get(call.decl),) + tuple(self.methods_at.get(i) for i in call.impls) if m]
            return out
        t = call.target
        if t is None:
            return []
        argc = call.raw.get("args")
        cands = [m for m in t.method(call.raw["name"]) if argc is None or len(m.params) == argc] or t.method(call.raw["name"])
        out = cands[:1]
        if t.kind == "interface":
            for impl in self.implementations(t.name):
                ims = [m for m in impl.method(call.raw["name"]) if argc is None or len(m.params) == argc]
                out += ims[:1]
        return out

    def resolution_stats(self) -> dict:
        stats: dict[str, int] = {}
        for c in self.calls:
            stats[c.source] = stats.get(c.source, 0) + 1
        return {"analyzer": self.data.get("tool"), "library_jars": self.data.get("library_jars", 0),
                "analyzer_notes": self.data.get("call_stats", {}), "target_by": dict(sorted(stats.items()))}

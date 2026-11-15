"""사실 하나의 모양과 code_facts.json 쓰기.

출력 형식은 backend/docs/code_facts.example.json 과 같다.
  {"common": [사실...], "screens": {"화면ID": [사실...]}}
사실 하나는 {"kind", "file", "line", "fact"} 네 칸만 쓴다. ③ 프롬프트에 그대로 들어가므로 짧게 둔다.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from .codebase import Code

# ③에서 읽기 좋은 순서
KIND_ORDER = ["security", "global", "config", "data", "route", "template", "validation",
              "call", "message", "js", "html", "unused"]
# 화면과 관계없이 모든 화면에 줄 사실
COMMON_KINDS = {"security", "global", "config", "data"}


@dataclass
class Fact:
    kind: str
    file: str
    line: int
    fact: str
    # 화면 나누기에만 쓰는 정보 (출력하지 않음)
    related: set[str] = field(default_factory=set)   # 이 사실과 관련된 파일 (file 포함)
    anchors: set[str] = field(default_factory=set)   # 화면에 붙일 때 쓰는 고리: route:POST /x, view:auth/login, method:A.b, class:Form
    common: bool = False                              # True면 화면과 관계없이 common
    anchor_self: bool = True                          # False면 자기 파일(file)로는 화면에 붙이지 않는다

    def __post_init__(self):
        self.related.add(self.file)
        if self.kind in COMMON_KINDS:
            self.common = True

    def all_anchors(self) -> set[str]:
        files = self.related if self.anchor_self else self.related - {self.file}
        return set(self.anchors) | {f"file:{p}" for p in files}

    def out(self) -> dict:
        return {"kind": self.kind, "file": self.file, "line": self.line, "fact": self.fact}

    def sort_key(self):
        k = KIND_ORDER.index(self.kind) if self.kind in KIND_ORDER else len(KIND_ORDER)
        return (k, self.file, self.line, self.fact)


def check(facts: list[Fact], code: Code) -> tuple[list[Fact], list[str]]:
    """③의 코드 묶음에 있는 파일·줄인지 확인한다. 아니면 빼고 이유를 남긴다. 같은 사실은 하나만 남긴다."""
    kept, problems, seen = [], [], set()
    for f in facts:
        if f.file not in code.files:
            problems.append(f"{f.file}: ③ 코드 묶음에 없는 파일이라 뺌 ({f.kind})")
            continue
        if not 1 <= f.line <= len(code.files[f.file]):
            problems.append(f"{f.file}:{f.line}: 줄 번호가 범위 밖이라 뺌 ({f.kind})")
            continue
        key = (f.kind, f.file, f.line, f.fact)
        if key in seen:
            continue
        seen.add(key)
        f.related = {r for r in f.related if r in code.files}
        kept.append(f)
    return sorted(kept, key=Fact.sort_key), problems


def write(path: Path, common: list[Fact], screens: dict[str, list[Fact]], meta: dict, reach: dict | None = None) -> dict:
    obj = {
        "_설명": "code_analysis가 만든 코드 분석 결과. judge --facts 로 넘긴다. common은 모든 화면에, "
                "screens의 목록은 그 화면 ③에만 들어간다. 파일 경로는 judge --code 로 준 폴더 기준 상대 경로이고 "
                "줄 번호는 ③ 코드 묶음의 \"줄번호|\"와 같다. reach는 프롬프트에 넣지 않고, ③이 판정한 뒤 프로그램이 "
                "근거가 그 화면의 처리 과정에서 닿는 코드인지 다시 확인하는 데 쓴다.",
        "_meta": meta,
        "common": [f.out() for f in sorted(common, key=Fact.sort_key)],
        "screens": {sid: [f.out() for f in sorted(fs, key=Fact.sort_key)] for sid, fs in sorted(screens.items())},
    }
    if reach is not None:
        obj["reach"] = reach
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return obj

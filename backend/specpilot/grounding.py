"""③ 근거 재확인: AI가 낸 판정을 프로그램이 다시 확인하고, 사람이 볼 항목을 따로 모은다.

LLM을 쓰지 않는다. 근거 줄 대조(code_prep.verify_evidence: 파일이 있는가, 그 줄에 그 코드가 있는가)에 더해
기업 피드백의 "최종 판정 전 확인 사항"을 프로그램으로 확인한다.

| 확인 | 함수 | 결과 |
| --- | --- | --- |
| AI가 note·mismatch에 적은 파일·클래스·메서드가 실제로 있는가 | unknown_refs | 사람 확인 목록 |
| 근거 메서드가 그 화면의 처리 과정에서 호출되는가 (화면 → 경로 → Controller → Service → Repository) | check_reach | 미사용 코드만 근거면 확인필요로 내림, 다른 화면의 처리 코드면 사람 확인 목록 |
| 요구사항의 모든 조건을 확인했는가 | condition_gaps | 사람 확인 목록 |
| "설계서에 없는 구현"(extras)의 근거 줄이 실제로 있는가 | verify_extras | 근거가 틀린 것은 evidence_ok: false |

도달 정보(reach)는 code_analysis가 code_facts.json에 넣어 준다 (judge --facts). 없으면 도달 확인은 건너뛴다.
화면 ↔ 템플릿 대응이 추정이라, "다른 화면의 처리 코드"는 판정을 바꾸지 않고 사람 확인 목록에만 올린다.
"""
from __future__ import annotations

import os
import re
from bisect import bisect_right
from pathlib import PurePosixPath

from . import code_prep
from .code_prep import Codebase

TAG_UNUSED = "[미사용 코드만 근거로 대 확인필요 처리]"

# 한글이 바로 붙어도("login.html에서") 잡히게 경계는 ASCII 글자로만 본다 (\b는 한글도 글자로 본다)
FILE_REF = re.compile(r"(?<![A-Za-z0-9_.-])(?:[A-Za-z0-9_.-]+/)*([A-Za-z_][A-Za-z0-9_-]*\.(?:java|kt|html|htm|js|jsx|ts|tsx|vue|css|yml|yaml|properties|xml|sql))(?![A-Za-z0-9_])")
# 이 코드의 클래스로 보이는 이름 (라이브러리 클래스 Model.addAttribute, String.format 같은 것은 건너뛴다)
CLASS_SUFFIX = ("Controller", "Service", "ServiceImpl", "Repository", "Form", "Dto", "DTO", "Request", "Response",
                "Config", "Configuration", "Validator", "Handler", "Advice", "Entity", "Mapper", "Util", "Utils")
# 기술 이름이라 파일로 보지 않는 것 (Vue.js, Node.js 등)
TECH_NAMES = {"vue.js", "node.js", "next.js", "nuxt.js", "react.js", "express.js", "chart.js", "three.js", "d3.js",
              "angular.js", "ember.js", "backbone.js", "alpine.js", "htmx.js"}
CLASS_METHOD = re.compile(r"(?<![A-Za-z0-9_])([A-Z][A-Za-z0-9_]*)\.([a-z][A-Za-z0-9_]*)(?![A-Za-z0-9_])")


# ---------- 파일·클래스·메서드가 실제로 있는가 ----------

class SymbolIndex:
    def __init__(self, cb: Codebase):
        self.cb = cb
        # 판정 코드 묶음에서 빠지는 파일(.min.js 라이브러리 등)도 언급할 수 있으므로 폴더 전체의 파일 이름을 본다
        self.names = {PurePosixPath(p).name for p in cb.files}
        root = getattr(cb, "root", None)
        if root and os.path.isdir(root):
            for _, dirs, files in os.walk(root):
                dirs[:] = [d for d in dirs if d not in (".git", "node_modules", ".gradle", ".idea", "__pycache__")]
                self.names.update(files)
        self.java = {}                      # 클래스 이름 → 파일 (파일 이름 기준)
        for p in cb.files:
            if p.endswith((".java", ".kt")):
                self.java.setdefault(PurePosixPath(p).stem, p)

    def has_method(self, cls: str, method: str) -> bool:
        path = self.java.get(cls)
        if path is None:
            return False
        pat = re.compile(rf"\b{re.escape(method)}\s*\(")
        return any(pat.search(line) for line in self.cb.files[path])


def unknown_refs(idx: SymbolIndex, text: str | None) -> list[str]:
    """글(note, mismatch)에 적힌 파일·클래스·메서드 가운데 코드에 없는 것."""
    if not text:
        return []
    out = []
    for m in FILE_REF.finditer(text):
        name = m.group(1)
        if name.lower() in TECH_NAMES:
            continue
        if name not in idx.names:
            out.append(f"없는 파일 {name}")
    for m in CLASS_METHOD.finditer(text):
        cls, meth = m.group(1), m.group(2)
        if f"{cls}.{meth}" in text and FILE_REF.fullmatch(f"{cls}.{meth}"):
            continue                        # login.html 같은 파일 이름은 위에서 봤다
        if not cls.endswith(CLASS_SUFFIX):
            continue
        if cls not in idx.java:
            out.append(f"없는 클래스 {cls}")
        elif not idx.has_method(cls, meth):
            out.append(f"{cls}에 없는 메서드 {meth}")
    return list(dict.fromkeys(out))


def _text_of(r: dict) -> str:
    parts = [r.get("note") or "", r.get("split_issue") or ""]
    for mm in r.get("mismatch") or []:
        if isinstance(mm, dict):
            parts += [str(mm.get("code") or "")]
    return "\n".join(parts)


# ---------- 근거가 그 화면의 처리 과정에서 닿는 코드인가 ----------

class Reach:
    """code_facts.json의 reach. 근거 줄 → 감싸는 메서드, 화면별로 닿는 메서드·파일, 미사용 코드 범위."""

    def __init__(self, data: dict | None):
        data = data or {}
        self.ok = bool(data.get("methods") or data.get("unused"))
        self.by_file: dict[str, list[dict]] = {}
        for m in data.get("methods") or []:
            self.by_file.setdefault(m["file"], []).append(m)
        for ms in self.by_file.values():
            ms.sort(key=lambda m: m["start"])
        self.screens: dict[str, dict] = {sid: {"methods": set(v.get("methods") or []), "files": set(v.get("files") or [])}
                                         for sid, v in (data.get("screens") or {}).items()}
        self.unused = data.get("unused") or []
        # 메서드 → 그 메서드에 닿는 화면들
        self.owner: dict[str, set[str]] = {}
        for sid, v in self.screens.items():
            for name in v["methods"]:
                self.owner.setdefault(name, set()).add(sid)

    def method_at(self, file: str, line: int) -> dict | None:
        ms = self.by_file.get(file) or []
        i = bisect_right([m["start"] for m in ms], line) - 1
        while i >= 0:                          # 안쪽(늦게 시작한) 메서드부터
            if ms[i]["start"] <= line <= ms[i]["end"]:
                return ms[i]
            i -= 1
        return None

    def unused_at(self, file: str, line: int) -> dict | None:
        return next((u for u in self.unused if u["file"] == file and u["start"] <= line <= u["end"]), None)


def check_reach(reach: Reach, sid: str, evidence: list[dict]) -> tuple[list[str], bool]:
    """반환: (사람이 볼 이유 목록, 모든 근거가 미사용 코드인가)."""
    if not reach.ok or not evidence:
        return [], False
    reasons, unused_n, checked = [], 0, 0
    mine = reach.screens.get(sid)
    for ev in evidence:
        if not isinstance(ev, dict) or not isinstance(ev.get("line"), int):
            continue
        f, line = ev.get("file"), ev["line"]
        checked += 1
        u = reach.unused_at(f, line)
        if u is not None:
            unused_n += 1
            reasons.append(f"미사용 코드 근거 {f}:{line} ({u['label'][:60]})")
            continue
        if mine is None:                       # 이 화면의 템플릿을 못 찾았으면 도달 확인을 하지 않는다
            continue
        m = reach.method_at(f, line)
        if m is not None:
            owners = reach.owner.get(m["name"], set())
            if owners and m["name"] not in mine["methods"]:
                reasons.append(f"이 화면에서 닿지 않는 메서드 {m['name']} ({', '.join(sorted(owners))} 화면의 처리 코드)")
            continue
        other = sorted(s for s, v in reach.screens.items() if s != sid and f in v["files"])
        if f.endswith((".html", ".htm", ".js")) and other and f not in mine["files"]:
            reasons.append(f"다른 화면의 파일 {f} ({', '.join(other)} 화면)")
    return list(dict.fromkeys(reasons)), checked > 0 and unused_n == checked


# ---------- 요구사항의 모든 조건을 확인했는가 ----------

def condition_gaps(unit: dict, r: dict) -> list[int]:
    """구현으로 판정한 단위에서, 근거의 for에 번호가 없는 조건 (1부터). 조건이 없거나 구현이 아니면 빈 목록."""
    conds = unit.get("conditions") or []
    if r.get("status") != "구현" or not conds:
        return []
    covered: set[int] = set()
    for ev in r.get("evidence") or []:
        if not isinstance(ev, dict):
            continue
        v = ev.get("for")
        for x in (v if isinstance(v, list) else [v]):
            if isinstance(x, int):
                covered.add(x)
            elif isinstance(x, str):
                covered |= {int(n) for n in re.findall(r"\d+", x)}
    return [i for i in range(1, len(conds) + 1) if i not in covered]


# ---------- 설계서에 없는 구현(extras)의 근거 ----------

def verify_extras(cb: Codebase, extras: list) -> int:
    """extras 하나하나의 file·line·code를 대조한다. 틀린 것은 evidence_ok: false. 틀린 수를 돌려준다."""
    bad = 0
    for e in extras or []:
        if not isinstance(e, dict):
            continue
        if not e.get("file"):
            continue
        ev = {"file": e.get("file"), "line": e.get("line"), "code": e.get("code")}
        problems = code_prep.verify_evidence(cb, [ev])
        if ev.get("line_reported") is not None:
            e["line_reported"], e["line"] = ev["line_reported"], ev["line"]
        e["evidence_ok"] = not problems
        if problems:
            e["evidence_problems"] = problems
            bad += 1
    return bad


# ---------- 한 화면 결과에 모두 적용 ----------

def recheck(cb: Codebase, reach: Reach, sid: str, units: list[dict], results: dict[str, dict],
            idx: SymbolIndex | None = None) -> dict:
    """근거 줄 대조 뒤에 부른다. 결과마다 review(사람이 볼 이유)를 채우고, 미사용 코드만 근거인 구현·불일치는 확인필요로 내린다.
    여러 번 불러도 같은 결과가 되게 한다 (재사용한 판정에도 다시 적용)."""
    idx = idx or SymbolIndex(cb)
    by_id = {u["id"]: u for u in units}
    counts = {"unused_evidence": 0, "reach_other_screen": 0, "condition_gaps": 0, "unknown_refs": 0}
    for uid, r in results.items():
        reasons: list[str] = []
        if not r.get("evidence_ok", True):
            reasons.append("근거 코드를 실제 코드에서 찾지 못함" + (" (확인필요로 내림)" if r.get("original_status") else ""))

        reach_reasons, all_unused = check_reach(reach, sid, r.get("evidence") or [])
        if by_id.get(uid, {}).get("screen_id") == "APP":   # 앱 전체 단위는 원래 여러 화면에 걸치므로 미사용 코드만 본다
            reach_reasons = [x for x in reach_reasons if x.startswith("미사용")]
        if all_unused and r.get("status") in ("구현", "불일치"):
            r["original_status"] = r["status"]
            r["status"] = "확인필요"
            r["note"] = ((r.get("note") or "") + " " + TAG_UNUSED).strip()
        if any(x.startswith("미사용") for x in reach_reasons):
            counts["unused_evidence"] += 1
        if any(not x.startswith("미사용") for x in reach_reasons):
            counts["reach_other_screen"] += 1
        r["reach_problems"] = reach_reasons
        reasons += reach_reasons

        gaps = condition_gaps(by_id.get(uid, {}), r)
        r["condition_gaps"] = gaps
        if gaps:
            counts["condition_gaps"] += 1
            conds = by_id[uid].get("conditions") or []
            reasons.append("근거가 없는 조건: " + ", ".join(f"{i}) {conds[i - 1]}" for i in gaps))

        unknown = unknown_refs(idx, _text_of(r))
        r["unknown_refs"] = unknown
        if unknown:
            counts["unknown_refs"] += 1
            reasons.append("설명에 적힌 코드가 없음: " + ", ".join(unknown))

        if r.get("status") == "확인필요" and not reasons:
            reasons.append("AI가 코드만으로 판단하지 못함" + (f": {r['note']}" if r.get("note") else ""))
        r["review"] = reasons
    return counts

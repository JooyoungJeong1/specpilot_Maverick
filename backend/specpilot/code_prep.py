"""소스 코드 준비: 파일 모으기, 줄 번호 붙이기, 크기 재기, 화면별 묶음, 근거 줄 대조.

LLM을 쓰지 않는다. ③ 정합성 판정 전후에 프로그램이 하는 일이다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

CODE_EXTS = {
    ".java", ".kt", ".py", ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte",
    ".html", ".htm", ".jsp", ".css", ".xml", ".yml", ".yaml", ".properties", ".sql",
}
EXCLUDE_DIRS = {
    ".git", ".idea", ".vscode", ".gradle", "node_modules", "build", "target", "dist", "out",
    "bin", "gradle", "__pycache__", ".venv", "venv", "test", "tests", "__tests__", "coverage",
}
MAX_FILE_BYTES = 300_000          # 이보다 큰 파일은 생성물이나 묶은 라이브러리일 가능성이 높아 뺀다
MIN_FILE_NAME = re.compile(r"\.min\.(js|css)$")

ROUTE_PATTERNS = [
    re.compile(r"@(?:Get|Post|Put|Delete|Patch|Request)Mapping\s*\(([^)]*)\)"),      # Spring
    re.compile(r"\b(?:app|router)\.(?:get|post|put|delete|patch)\(\s*['\"]([^'\"]+)"),  # Express
    re.compile(r"\bpath\(\s*['\"]([^'\"]*)['\"]"),                                     # Django
    re.compile(r"\bpath:\s*['\"](/[^'\"]*)['\"]"),                                     # Vue/React 라우터
    re.compile(r"\b(?:redirect:|return\s+\")([\w/\-{}.:]+)"),                          # Spring 반환 템플릿·이동
]
LABEL_PATTERN = re.compile(r"<(?:title|h1|h2|h3|button|label|a)\b[^>]*>([^<{}$]{2,40})<")


@dataclass
class Codebase:
    root: Path
    files: dict[str, list[str]] = field(default_factory=dict)   # 상대 경로(/) → 줄 목록

    def text(self, paths: list[str] | None = None) -> str:
        """파일마다 "=== 파일경로 ===" 머리글을 달고 각 줄 앞에 "줄번호|"를 붙인 코드.

        줄마다 파일 경로를 붙이면 경로가 긴 Java 프로젝트에서 토큰이 세 배 가까이 늘어서
        (샘플 기준 약 8.5만 → 3.4만) 경로는 머리글에 한 번만 쓴다.
        """
        out = []
        for p in sorted(paths if paths is not None else self.files):
            if p not in self.files:
                continue
            out.append(f"=== {p} ===")
            out.extend(f"{i}|{line}" for i, line in enumerate(self.files[p], 1))
        return "\n".join(out)

    def tokens(self, paths: list[str] | None = None) -> int:
        return estimate_tokens(self.text(paths))


def load_codebase(root: Path) -> Codebase:
    root = Path(root)
    cb = Codebase(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in CODE_EXTS:
            continue
        rel = path.relative_to(root)
        if any(part in EXCLUDE_DIRS for part in rel.parts[:-1]):
            continue
        if MIN_FILE_NAME.search(path.name) or path.stat().st_size > MAX_FILE_BYTES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        cb.files[rel.as_posix()] = text.splitlines()
    return cb


def estimate_tokens(text: str) -> int:
    """대략적인 토큰 수. 영문·기호는 4글자에 1토큰, 한글 등은 1글자에 1토큰으로 넉넉히 잡는다."""
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    return ascii_chars // 4 + (len(text) - ascii_chars)


# ---------- 화면별 묶음 ----------

def file_index(cb: Codebase, max_signals: int = 12) -> list[dict]:
    """LLM이 화면별 파일을 고를 때 볼 단서: 경로, 줄 수, 경로 매핑과 화면 라벨."""
    index = []
    for path, lines in cb.files.items():
        signals: list[str] = []
        for line in lines:
            for pat in ROUTE_PATTERNS:
                for m in pat.finditer(line):
                    signals.append(m.group(0).strip()[:80])
            for m in LABEL_PATTERN.finditer(line):
                signals.append(m.group(1).strip())
            if len(signals) >= max_signals:
                break
        index.append({"path": path, "lines": len(lines), "signals": list(dict.fromkeys(signals))[:max_signals]})
    return index


def _key(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", text)


def files_mentioning(cb: Codebase, phrases: list[str], prefix_len: int = 6) -> set[str]:
    """문구의 앞부분(공백·기호 제외 6글자)이 들어 있는 파일. 문구가 조금 달라도(=불일치) 찾게 앞부분만 본다."""
    keys = {_key(p)[:prefix_len] for p in phrases if p and len(_key(p)) >= prefix_len}
    if not keys:
        return set()
    hits = set()
    for path, lines in cb.files.items():
        joined = _key("".join(lines))
        if any(k in joined for k in keys):
            hits.add(path)
    return hits


# ---------- 근거 줄 대조 ----------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


EVIDENCE_LINE_TOLERANCE = 2      # 적은 줄에 없을 때 위아래로 찾아볼 줄 수


def _quote_matches(lines: list[str], line: int, quoted: list[str]) -> bool:
    """line번째 줄부터 인용한 줄들이 차례로 들어 있는지 (공백 차이는 무시)."""
    if not 1 <= line <= len(lines):
        return False
    actual = lines[line - 1: line - 1 + len(quoted)]
    return len(actual) == len(quoted) and all(q in _norm(a) for q, a in zip(quoted, actual))


def verify_evidence(cb: Codebase, evidence: list[dict], fixes: list[str] | None = None,
                    tolerance: int = EVIDENCE_LINE_TOLERANCE) -> list[str]:
    """LLM이 근거로 댄 "파일:줄"에 정말 그 코드가 있는지 본다. 문제 목록을 돌려준다(없으면 빈 목록).

    적은 줄에는 없지만 위아래 tolerance줄 안에 같은 코드가 있으면 지어낸 근거가 아니라 줄 번호를 잘못 센 것으로 본다
    (애노테이션 줄과 메서드 선언 줄을 헷갈리는 경우가 대부분이었다). 이때는 문제로 치지 않고 근거의 line을 고친다.
    원래 적은 번호는 line_reported에 남기고, fixes를 주면 고친 내용을 거기에 적는다.
    """
    problems = []
    for ev in evidence or []:
        if not isinstance(ev, dict):
            problems.append("근거 형식 오류")
            continue
        f, line, code = ev.get("file"), ev.get("line"), ev.get("code")
        if f not in cb.files:
            problems.append(f"{f}: 없는 파일")
            continue
        lines = cb.files[f]
        if not isinstance(line, int) or not 1 - tolerance <= line <= len(lines) + tolerance:
            problems.append(f"{f}:{line}: 줄 번호가 범위 밖")
            continue
        if not code:
            problems.append(f"{f}:{line}: 인용한 코드가 없음")
            continue
        quoted = [q for q in (_norm(x) for x in str(code).splitlines()) if q]
        if _quote_matches(lines, line, quoted):
            continue
        near = [n for d in range(1, tolerance + 1) for n in (line - d, line + d) if _quote_matches(lines, n, quoted)]
        if near:
            ev["line_reported"], ev["line"] = line, near[0]
            if fixes is not None:
                fixes.append(f"{f}:{line} → {near[0]}줄 (줄 번호 보정)")
            continue
        problems.append(f"{f}:{line}: 인용한 코드가 실제 줄과 다름")
    return problems


def snippet(cb: Codebase, path: str, line: int, around: int = 2) -> str:
    lines = cb.files.get(path, [])
    lo, hi = max(1, line - around), min(len(lines), line + around)
    return "\n".join(f"{'>' if i == line else ' '} {i:>4} | {lines[i - 1]}" for i in range(lo, hi + 1))

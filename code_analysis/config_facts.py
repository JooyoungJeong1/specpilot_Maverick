"""설정 파일(application.yml / .properties)에서 화면 동작에 영향을 주는 값만 사실로 만든다."""
from __future__ import annotations

import re

from .codebase import Code
from .facts import Fact

INTERESTING = ("spring.servlet.multipart.", "server.servlet.session.", "server.port", "server.error.",
               "spring.security.", "spring.h2.console.", "spring.mvc.", "spring.web.", "app.")
EXPLAIN = {
    "spring.servlet.multipart.max-file-size": "업로드 파일 하나의 최대 크기. 넘으면 컨트롤러 코드에 닿기 전에 요청이 거부된다",
    "spring.servlet.multipart.max-request-size": "요청 전체(파일과 다른 입력값을 합친 크기)의 최대 크기. 넘으면 컨트롤러 코드에 닿기 전에 요청이 거부된다",
    "server.servlet.session.timeout": "로그인 세션 유지 시간",
    "spring.h2.console.enabled": "H2 데이터베이스 관리 화면 사용 여부",
}


def parse_yaml(lines: list[str]) -> list[tuple[str, str, int]]:
    """들여쓰기로 키 경로를 이어 붙이는 간단한 YAML 읽기 (스칼라 값만, 목록·여러 줄 값은 건너뜀)."""
    out, stack = [], []          # stack: [(들여쓰기, 키)]
    for no, raw in enumerate(lines, 1):
        if not raw.strip() or raw.lstrip().startswith(("#", "-", "---")):
            continue
        m = re.match(r"^(\s*)([\w.\-\[\]\"']+)\s*:\s*(.*)$", raw)
        if not m:
            continue
        indent, key, value = len(m.group(1)), m.group(2).strip("\"'"), m.group(3).split(" #")[0].strip()
        while stack and stack[-1][0] >= indent:
            stack.pop()
        path = ".".join([k for _, k in stack] + [key])
        if value and value not in ("|", ">"):
            out.append((path, value.strip("\"'"), no))
        else:
            stack.append((indent, key))
    return out


def parse_properties(lines: list[str]) -> list[tuple[str, str, int]]:
    out = []
    for no, raw in enumerate(lines, 1):
        s = raw.strip()
        if not s or s.startswith(("#", "!")):
            continue
        m = re.match(r"^([\w.\-\[\]]+)\s*[=:]\s*(.*)$", s)
        if m:
            out.append((m.group(1), m.group(2).strip(), no))
    return out


def config_facts(code: Code) -> list[Fact]:
    facts = []
    java_text = {p: code.text(p) for p in code.by_suffix(".java")}
    for path, lines in code.files.items():
        low = path.lower()
        if low.endswith((".yml", ".yaml")):
            entries = parse_yaml(lines)
        elif low.endswith(".properties"):
            entries = parse_properties(lines)
        else:
            continue
        for key, value, no in entries:
            if not key.startswith(INTERESTING):
                continue
            text = f"{key} = {value}"
            if key in EXPLAIN:
                text += f" ({EXPLAIN[key]})"
            users = [p.split("/")[-1].removesuffix(".java") for p, t in java_text.items() if "${" + key in t]
            if users:
                text += f". 코드에서 읽는 곳: {', '.join(users)}"
            facts.append(Fact("config", path, no, text))
    return facts

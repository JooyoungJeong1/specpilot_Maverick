"""JavaParser 호출 해석기(code_analysis/javaparser)를 돌리고 결과를 읽는다.

1. ③의 파일 목록(load_codebase)에 있는 .java 파일을 그 줄 그대로 임시 폴더에 다시 쓴다.
   → JavaParser가 내는 경로·줄 번호가 ③과 같다. 테스트·빌드 폴더처럼 ③이 빼는 파일도 똑같이 빠진다.
2. java -jar 로 해석기를 돌린다. 해석기는 호출마다 "어느 클래스의 어느 선언으로 가는지"만 낸다.
3. (파일, 줄, 메서드 이름, 같은 줄 안 순번)으로 tree-sitter가 찾은 호출과 맞춘다.
   열 번호는 tree-sitter(바이트)와 JavaParser(글자)가 달라서 쓰지 않는다.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .codebase import Code

HERE = Path(__file__).resolve().parent
JAR_DIR = HERE / "javaparser" / "target"
WORK_DIR = HERE / "out" / ".javaparser"


def find_jar(explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.is_file() else None
    jars = sorted((j for j in JAR_DIR.glob("specpilot-javaparser-*.jar") if not j.name.startswith("original-")),
                  key=lambda j: j.stat().st_mtime, reverse=True)
    return jars[0] if jars else None


def java_available() -> bool:
    return shutil.which("java") is not None


@dataclass
class Resolution:
    resolved: bool
    declaring_type: str | None = None
    declaring_kind: str | None = None
    decl_file: str | None = None
    decl_line: int | None = None
    impls: list[tuple[str, int]] = field(default_factory=list)
    error: str | None = None


class Resolver:
    """해석기 결과를 (파일, 줄, 이름, 순번)으로 찾는 표."""

    def __init__(self, data: dict):
        self.data = data
        self.table: dict[tuple[str, int, str, int], Resolution] = {}
        for c in data.get("calls", []):
            self.table[(c["file"], c["line"], c["name"], c.get("index", 0))] = Resolution(
                resolved=bool(c.get("resolved")), declaring_type=c.get("declaring_type"),
                declaring_kind=c.get("declaring_kind"), decl_file=c.get("decl_file"), decl_line=c.get("decl_line"),
                impls=[(i["file"], i["line"]) for i in c.get("impls", []) if i.get("file")], error=c.get("error"))

    def lookup(self, file: str, line: int, name: str, index: int) -> Resolution | None:
        return self.table.get((file, line, name, index))

    @property
    def stats(self) -> dict:
        return self.data.get("stats", {})


def run(code: Code, jar: Path, classpath: str | None = None, gradle_root: Path | None = None,
        timeout: int = 900, keep_sources: bool = False) -> Resolver:
    src = WORK_DIR / "src"
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    src.mkdir(parents=True)
    n = 0
    for path in code.by_suffix(".java"):
        target = src / path
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8", newline="\n") as f:
            f.write(code.text(path) + "\n")
        n += 1
    if n == 0:
        raise RuntimeError("Java 파일이 없습니다")
    out = WORK_DIR / "calls.json"
    cmd = ["java", "-jar", str(jar), "--src", str(src), "--out", str(out)]
    if classpath:
        cmd += ["--classpath", str(Path(classpath).resolve())]
    elif gradle_root:
        cmd += ["--gradle-root", str(Path(gradle_root).resolve())]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"JavaParser 해석기가 {timeout}초 안에 끝나지 않았습니다")
    if proc.returncode != 0 or not out.is_file():
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()[-15:]
        raise RuntimeError("JavaParser 해석기 실행 실패 (종료 코드 %s)\n%s" % (proc.returncode, "\n".join(err)))
    data = json.loads(out.read_text(encoding="utf-8"))
    if not keep_sources:                      # 기업 코드 사본은 남기지 않는다 (결과 JSON만 남김)
        shutil.rmtree(src, ignore_errors=True)
    return Resolver(data)

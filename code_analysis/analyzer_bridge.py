"""백엔드 분석기(code_analysis/analyzer, Java)를 돌리고 결과 JSON을 읽는다.

1. ③의 파일 목록(load_codebase)에 있는 .java와 템플릿(.html)을 그 줄 그대로 임시 폴더에 다시 쓴다.
   → 분석기가 내는 경로·줄 번호가 ③과 같고, ③이 빼는 테스트·빌드 폴더의 파일도 똑같이 빠진다.
2. java -jar 로 분석기를 돌린다 (JavaParser + Symbol Solver + Jsoup).
3. 끝나면 사본을 지우고, 결과 JSON만 남긴다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from .codebase import Code

HERE = Path(__file__).resolve().parent
JAR_DIR = HERE / "analyzer" / "target"
WORK_DIR = HERE / "out" / ".analyzer"
BUILD_HINT = "cd code_analysis/analyzer && mvn -q clean package"


def find_jar(explicit: str | None = None) -> Path | None:
    """--analyzer-jar > 환경 변수 SPECPILOT_ANALYZER_JAR > code_analysis/analyzer/target/ 의 최신 jar."""
    for cand in (explicit, os.environ.get("SPECPILOT_ANALYZER_JAR")):
        if cand:
            p = Path(cand)
            return p if p.is_file() else None
    jars = sorted((j for j in JAR_DIR.glob("specpilot-analyzer-*.jar") if not j.name.startswith("original-")),
                  key=lambda j: j.stat().st_mtime, reverse=True)
    return jars[0] if jars else None


def java_available() -> bool:
    return shutil.which("java") is not None


def is_template(path: str) -> bool:
    return "/templates/" in f"/{path}" and path.lower().endswith((".html", ".htm"))


def run(code: Code, jar: Path, classpath: str | None = None, gradle_root: Path | None = None,
        timeout: int = 1200) -> dict:
    src = WORK_DIR / "src"
    if WORK_DIR.exists():
        shutil.rmtree(WORK_DIR)
    src.mkdir(parents=True)
    copied = 0
    for path in code.files:
        if path.endswith(".java") or is_template(path):
            target = src / path
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(target, "w", encoding="utf-8", newline="\n") as f:
                f.write(code.text(path) + "\n")
            copied += 1
    if copied == 0:
        raise RuntimeError("Java·템플릿 파일이 없습니다")
    out = WORK_DIR / "backend-analysis.json"
    cmd = ["java", "-jar", str(jar), "--src", str(src), "--out", str(out)]
    if classpath:
        cmd += ["--classpath", str(Path(classpath).resolve())]
    elif gradle_root:
        cmd += ["--gradle-root", str(Path(gradle_root).resolve())]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"백엔드 분석기가 {timeout}초 안에 끝나지 않았습니다")
    finally:
        shutil.rmtree(src, ignore_errors=True)      # 기업 코드 사본은 남기지 않는다
    if proc.returncode != 0 or not out.is_file():
        err = (proc.stderr or b"").decode("utf-8", errors="replace").strip().splitlines()[-15:]
        raise RuntimeError("백엔드 분석기 실행 실패 (종료 코드 %s)\n%s" % (proc.returncode, "\n".join(err)))
    return json.loads(out.read_text(encoding="utf-8"))

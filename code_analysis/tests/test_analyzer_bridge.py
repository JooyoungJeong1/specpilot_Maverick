"""백엔드 분석기(Java) 연결 테스트.

JDK 없이도 돌도록 subprocess를 가짜로 바꿔, 분석기에 넘기는 사본과 정리 동작을 확인한다.
분석기 jar가 있으면(빌드했거나 SPECPILOT_ANALYZER_JAR) 실제 분석기 결과가 저장된 fixture와 같은지도 확인한다.
"""
import json
import subprocess
from pathlib import Path

import pytest

from code_analysis import analyzer_bridge as ab
from code_analysis import cli, codebase

HERE = Path(__file__).resolve().parent
APP = HERE / "fixtures" / "qna-app"
FIXTURE = HERE / "fixtures" / "qna-backend-analysis.json"


def test_run_passes_exact_copy_and_cleans_up(monkeypatch, tmp_path):
    code = codebase.load(APP)
    seen = {}

    def fake_run(cmd, capture_output, timeout):
        src = Path(cmd[cmd.index("--src") + 1])
        out = Path(cmd[cmd.index("--out") + 1])
        seen["files"] = sorted(p.relative_to(src).as_posix() for p in src.rglob("*") if p.is_file())
        seen["same"] = all((src / p).read_text(encoding="utf-8") == code.text(p) + "\n" for p in seen["files"])
        seen["src"] = src
        out.write_text(json.dumps({"tool": "fake"}), encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(ab.subprocess, "run", fake_run)
    monkeypatch.setattr(ab, "WORK_DIR", tmp_path / ".analyzer")
    assert ab.run(code, Path("fake.jar")) == {"tool": "fake"}
    expected = sorted(p for p in code.files if p.endswith(".java") or ab.is_template(p))
    assert seen["files"] == expected                         # .java + 템플릿만, test·build 폴더는 ③처럼 빠짐
    assert any(p.endswith(".html") for p in seen["files"])
    assert seen["same"]                                      # ③의 줄 그대로
    assert not seen["src"].exists()                          # 기업 코드 사본은 남기지 않는다


def test_missing_jar_message(monkeypatch):
    monkeypatch.setattr(ab, "find_jar", lambda explicit=None: None)
    with pytest.raises(SystemExit) as e:
        cli.build(APP, log=lambda *a: None)
    assert "mvn -q clean package" in str(e.value)


def test_find_jar_env(monkeypatch, tmp_path):
    jar = tmp_path / "specpilot-analyzer-9.9.9.jar"
    jar.write_bytes(b"x")
    monkeypatch.setenv("SPECPILOT_ANALYZER_JAR", str(jar))
    assert ab.find_jar() == jar


def _comparable(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in ("src", "millis")}


@pytest.mark.skipif(ab.find_jar() is None or not ab.java_available(),
                    reason="백엔드 분석기 jar가 없음 (cd code_analysis/analyzer && mvn -q clean package)")
def test_real_analyzer_matches_fixture():
    """실제 분석기로 가상의 앱을 분석한 결과가 저장된 fixture와 같아야 한다 (분석기를 고치면 fixture도 다시 만든다)."""
    data = ab.run(codebase.load(APP), ab.find_jar())
    stored = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert _comparable(data) == _comparable(stored), \
        "분석기 결과가 fixture와 다릅니다. 의도한 변경이면 README의 'fixture 다시 만들기'대로 갱신하세요."

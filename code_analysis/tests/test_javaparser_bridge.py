"""JavaParser 연결 테스트.

JDK·Maven 없이도 돌도록, 해석기 결과(JSON)를 손으로 만들어 Python 쪽 연결을 확인한다.
해석기 jar가 빌드돼 있고 java가 있으면 실제 해석기로도 한 번 돌린다 (test_real_javaparser).
"""
import json
import subprocess
from pathlib import Path

import pytest

from code_analysis import cli, codebase, javaparser_bridge as jpb
from code_analysis.java_index import JavaIndex

APP = Path(__file__).resolve().parent / "fixtures" / "qna-app"
J = "src/main/java/demo/"
QNA_SERVICE = J + "service/QnaService.java"
NOTIFY = J + "service/NotifyService.java"
MAIL = J + "service/MailNotifyService.java"
SMS = J + "service/SmsNotifyService.java"
CTRL = J + "controller/QnaController.java"


def line_of(code, path, text, nth=0):
    hits = [i for i, l in enumerate(code.files[path], 1) if text in l]
    return hits[nth]


def fake_result(code):
    """해석기가 냈을 법한 결과: 인터페이스 호출(구현 둘), 라이브러리 호출, 저장소 상속 메서드, 못 푼 호출."""
    send_call = line_of(code, QNA_SERVICE, "notifyService.send")
    calls = [
        {"file": QNA_SERVICE, "line": send_call, "col": 23, "name": "send", "index": 0, "receiver": "notifyService",
         "resolved": True, "declaring_type": "NotifyService", "declaring_qualified": "demo.service.NotifyService",
         "declaring_kind": "interface", "signature": "demo.service.NotifyService.send(java.lang.String)", "params": 1,
         "decl_file": NOTIFY, "decl_line": line_of(code, NOTIFY, "void send"),
         "impls": [{"file": MAIL, "line": line_of(code, MAIL, "public void send"), "type": "MailNotifyService"},
                   {"file": SMS, "line": line_of(code, SMS, "public void send"), "type": "SmsNotifyService"}]},
        {"file": QNA_SERVICE, "line": line_of(code, QNA_SERVICE, "qnaRepository.save"), "col": 30, "name": "save",
         "index": 0, "receiver": "qnaRepository", "resolved": True, "declaring_type": "CrudRepository",
         "declaring_qualified": "org.springframework.data.repository.CrudRepository", "declaring_kind": "interface",
         "signature": "save(S)", "params": 1, "decl_file": None, "decl_line": None, "impls": []},
        {"file": CTRL, "line": line_of(code, CTRL, 'model.addAttribute("errorMessage"'), "col": 19, "name": "addAttribute",
         "index": 0, "receiver": "model", "resolved": True, "declaring_type": "Model",
         "declaring_qualified": "org.springframework.ui.Model", "declaring_kind": "interface",
         "signature": "addAttribute(String, Object)", "params": 2, "decl_file": None, "decl_line": None, "impls": []},
        {"file": CTRL, "line": line_of(code, CTRL, "qnaService.create"), "col": 24, "name": "create", "index": 0,
         "receiver": "qnaService", "resolved": False, "error": "UnsolvedSymbolException"},
    ]
    return {"tool": "specpilot-javaparser (테스트용 가짜)", "library_jars": 0, "calls": calls,
            "stats": {"calls": len(calls), "resolved": 3, "resolved_to_source": 1}}


def calls_in(ix, path, method):
    cls = ix.files[path].classes[0]
    return {c.name: c for c in ix.calls(cls.method(method)[0])}


def test_interface_call_reaches_all_implementations():
    code = codebase.load(APP)
    heuristic = calls_in(JavaIndex(code), QNA_SERVICE, "create")["send"]
    jp_ix = JavaIndex(code, jpb.Resolver(fake_result(code)))
    jp = calls_in(jp_ix, QNA_SERVICE, "create")["send"]
    assert jp.source == "javaparser" and jp.target.name == "NotifyService"
    reached = {m.qname for m in jp_ix.resolve_targets(jp)}
    assert reached == {"NotifyService.send", "MailNotifyService.send", "SmsNotifyService.send"}
    # 간이 해석은 구현이 여럿이어도 첫 번째 구현 하나만 따라간다
    assert len(JavaIndex(code).resolve_targets(heuristic)) == 1


def test_library_and_spring_data_and_fallback():
    code = codebase.load(APP)
    ix = JavaIndex(code, jpb.Resolver(fake_result(code)))
    svc = calls_in(ix, QNA_SERVICE, "create")
    assert svc["save"].source == "javaparser-library" and svc["save"].target.name == "QnaRepository"   # 저장소 이름으로 남김
    ctrl = calls_in(ix, CTRL, "create")
    assert ctrl["addAttribute"].source == "javaparser-library" and ctrl["addAttribute"].target is None
    assert ctrl["create"].source == "heuristic" and ctrl["create"].target.name == "QnaService"        # 못 푼 호출은 간이 해석
    stats = ix.resolution_stats()["by_source"]
    assert stats["javaparser"] == 1 and stats["javaparser-library"] == 2 and stats["heuristic"] > 0


def test_disagreement_is_recorded():
    code = codebase.load(APP)
    data = fake_result(code)
    data["calls"][0].update(declaring_type="MailNotifyService", decl_file=MAIL,
                            decl_line=line_of(code, MAIL, "public void send"), impls=[])
    ix = JavaIndex(code, jpb.Resolver(data))
    ix.resolution_stats()
    assert any("간이 해석은 NotifyService, JavaParser는 MailNotifyService" in d for d in ix.disagreements)


def test_build_with_resolver_meta_and_label():
    code = codebase.load(APP)
    res, problems = cli.build(APP, resolver=jpb.Resolver(fake_result(code)), log=lambda *a: None)
    assert problems == []
    assert res["meta"]["java_engine"].startswith("javaparser")
    assert res["meta"]["call_resolution"]["by_source"]["javaparser"] == 1
    call = next(f for f in res["common"] if f.kind == "call" and f.fact.startswith("QnaService.create"))
    assert "NotifyService.send(구현: MailNotifyService, SmsNotifyService)" in call.fact


def test_run_writes_exact_copy_and_cleans_up(monkeypatch, tmp_path):
    """해석기에 넘기는 사본이 ③의 파일 목록·줄과 같고, 실행 뒤 사본을 지우는지."""
    code = codebase.load(APP)
    seen = {}

    def fake_run(cmd, capture_output, timeout):
        src = Path(cmd[cmd.index("--src") + 1])
        out = Path(cmd[cmd.index("--out") + 1])
        seen["files"] = sorted(p.relative_to(src).as_posix() for p in src.rglob("*.java"))
        seen["same"] = all((src / p).read_text(encoding="utf-8") == code.text(p) + "\n" for p in seen["files"])
        out.write_text(json.dumps(fake_result(code)), encoding="utf-8")
        seen["src"] = src
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    monkeypatch.setattr(jpb.subprocess, "run", fake_run)
    monkeypatch.setattr(jpb, "WORK_DIR", tmp_path / ".javaparser")
    resolver = jpb.run(code, Path("fake.jar"))
    assert seen["files"] == sorted(code.by_suffix(".java"))          # test·build 폴더의 .java는 ③처럼 빠진다
    assert seen["same"]
    assert not seen["src"].exists()                                   # 기업 코드 사본은 남기지 않는다
    assert resolver.lookup(QNA_SERVICE, line_of(code, QNA_SERVICE, "notifyService.send"), "send", 0).resolved


def test_auto_falls_back_without_jar(monkeypatch):
    monkeypatch.setattr(jpb, "find_jar", lambda explicit=None: None)
    res, _ = cli.build(APP, engine="auto", log=lambda *a: None)
    assert res["meta"]["java_engine"].startswith("treesitter (JavaParser를 쓰지 못함")
    with pytest.raises(SystemExit):
        cli.build(APP, engine="javaparser", log=lambda *a: None)


@pytest.mark.skipif(jpb.find_jar() is None or not jpb.java_available(),
                    reason="JavaParser 해석기 jar가 없음 (cd code_analysis/javaparser && mvn -q package)")
def test_real_javaparser():
    res, problems = cli.build(APP, engine="javaparser", log=lambda *a: None)
    assert problems == []
    assert res["meta"]["java_engine"].startswith("javaparser")
    by = res["meta"]["call_resolution"]["by_source"]
    assert by.get("javaparser", 0) + by.get("javaparser-library", 0) > 0

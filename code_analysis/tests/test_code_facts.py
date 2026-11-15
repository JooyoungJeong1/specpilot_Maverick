"""code_analysis 테스트. 기업 샘플 코드 대신 tests/fixtures/qna-app(가상의 앱)으로 확인한다.

백엔드 분석기(Java) 결과는 tests/fixtures/qna-backend-analysis.json에 저장해 둔 것을 쓴다
(그 앱에 실제 분석기를 돌린 결과. JDK 없이도 테스트가 돌게 하려는 것).
분석기 jar가 있으면 test_analyzer_bridge.py의 test_real_analyzer_matches_fixture가 이 파일이 최신인지 확인한다.

실행 (저장소 폴더에서): python -m pytest code_analysis/tests -q
"""
import json
import sys
from pathlib import Path

import pytest

from code_analysis import cli, codebase
from code_analysis.facts import Fact, check

HERE = Path(__file__).resolve().parent
APP = HERE / "fixtures" / "qna-app"
REQ = HERE / "fixtures" / "qna-requirements.json"
ANALYSIS = json.loads((HERE / "fixtures" / "qna-backend-analysis.json").read_text(encoding="utf-8"))
BACKEND = Path(__file__).resolve().parents[2] / "backend"

CTRL = "src/main/java/demo/controller/QnaController.java"
WRITE = "src/main/resources/templates/qna/write.html"
JS = "src/main/resources/static/js/qna.js"


@pytest.fixture(scope="module")
def result():
    res, problems = cli.build(APP, log=lambda *a: None, analysis=ANALYSIS)
    return res, problems


@pytest.fixture(scope="module")
def split():
    res, _ = cli.build(APP, requirements=REQ, log=lambda *a: None, analysis=ANALYSIS)
    return res


def all_facts(res):
    return res["common"] + [f for fs in res["screens"].values() for f in fs]


def find(res, kind, *words):
    return [f for f in all_facts(res) if f.kind == kind and all(w in f.fact for w in words)]


# ---------------------------------------------------------------- ③과 같은 파일 목록·줄 번호

def test_file_list_same_as_backend():
    """③(backend/specpilot/code_prep.load_codebase)과 같은 파일·같은 줄 목록이어야 경로와 줄 번호가 맞는다."""
    if not (BACKEND / "specpilot" / "code_prep.py").is_file():
        pytest.skip("backend 폴더가 없음")
    sys.path.insert(0, str(BACKEND))
    from specpilot.code_prep import load_codebase
    expected = load_codebase(APP).files
    assert codebase.load(APP).files == expected
    assert codebase.load(APP, prefer_backend=False).files == expected      # 백엔드를 못 불러올 때 쓰는 사본도 같아야 한다


def test_excluded_files():
    files = codebase.load(APP, prefer_backend=False).files
    assert CTRL in files and WRITE in files
    assert not any("/test/" in f or f.startswith("build/") or f.endswith(".min.js") for f in files)
    assert all("\\" not in f for f in files)                                # 경로 구분자는 /


def test_every_fact_points_inside_code(result):
    res, problems = result
    code = codebase.load(APP)
    assert problems == []
    for f in all_facts(res):
        assert f.file in code.files, f.file
        assert 1 <= f.line <= len(code.files[f.file])


def test_check_drops_unknown_files():
    code = codebase.load(APP)
    kept, problems = check([Fact("route", "없는/파일.java", 1, "x"), Fact("route", CTRL, 9999, "y"),
                            Fact("route", CTRL, 1, "z")], code)
    assert [f.fact for f in kept] == ["z"] and len(problems) == 2


# ---------------------------------------------------------------- 사실 내용

def test_route_and_flow(result):
    res, _ = result
    f = find(res, "route", "POST /qna →", "QnaController.create")[0]
    assert f.file == CTRL and codebase.load(APP).line(CTRL, f.line).strip().startswith("@PostMapping")
    assert "@Valid QnaForm" in f.fact and "QnaService.create" in f.fact
    assert "입력값 검사 실패 시 qna/write 화면" in f.fact and "redirect:/qna" in f.fact
    assert "예외(IllegalArgumentException) 시 qna/write 화면" in f.fact


def test_model_value_not_rendered(result):
    res, _ = result
    f = find(res, "template", "errorMessage", "출력하지 않음")[0]
    assert f.file == CTRL and "addAttribute" in codebase.load(APP).line(CTRL, f.line)


def test_validation_errors_not_rendered(result):
    res, _ = result
    assert find(res, "template", "@Valid QnaForm", "검증 오류를 출력하는 곳", "없음")


def test_security(result):
    res, _ = result
    code = codebase.load(APP)
    f = find(res, "security", "/qna/*/delete", "ADMIN")[0]
    assert ".requestMatchers" in code.line(f.file, f.line)            # 두 줄로 나뉜 체이닝도 첫 줄을 가리킨다
    assert find(res, "security", "로그인 제출(POST /login)", "Spring Security")
    assert find(res, "security", "항상 /qna", "true")


def test_spring_data_service_message_validation(result):
    res, _ = result
    assert find(res, "data", "QnaRepository", "existsByTitle", "이름 규칙")
    assert find(res, "call", "QnaService.create", "QnaRepository.existsByTitle(이름 규칙 쿼리)",
                "NotifyService.send(구현: MailNotifyService, SmsNotifyService)", "QnaRepository.save(Spring Data 기본 기능)")
    assert find(res, "message", "이미 있는 제목입니다.")
    v = find(res, "validation", "QnaForm.title")[0]
    assert '@NotBlank("제목을 입력하세요")' in v.fact and "max=30" in v.fact and "POST /qna (@Valid)" in v.fact


def test_js(result):
    res, _ = result
    b = find(res, "js", "#title input 이벤트", "saveButton.disabled")[0]
    assert b.file == JS and "addEventListener" in codebase.load(APP).line(JS, b.line)
    assert find(res, "js", "qna.js: addEventListener로 붙이는 이벤트 input", "blur·focusout·submit 이벤트 없음", "qna/write.html")


def test_unused_and_unhandled(result):
    res, _ = result
    assert find(res, "unused", "POST /qna/check")
    assert find(res, "unused", "qna/old")
    assert find(res, "html", "/oauth2/authorization/kakao", "처리하는 컨트롤러나 보안 설정이 없음")
    assert find(res, "html", "입력란 title", "maxlength=30")


# ---------------------------------------------------------------- 화면 나누기

def test_all_common_without_requirements(result):
    res, _ = result
    assert res["screens"] == {} and res["meta"]["screen_split"].startswith("none")


def test_split_by_requirements(split):
    assert split["meta"]["screen_templates"]["QNA-002"] == [WRITE]
    assert split["meta"]["screen_templates"]["QNA-003"] == []           # 팝업은 이름으로 부모 템플릿을 고르지 않는다
    q2 = {f.fact for f in split["screens"]["QNA-002"]}
    assert any("errorMessage" in x for x in q2) and any("QnaForm.title" in x for x in q2)
    assert any("#title input" in x for x in q2)
    commons = split["common"]
    assert not any("errorMessage" in f.fact or "#title input" in f.fact for f in commons)   # 작성 화면 사실은 common에 섞이지 않는다


def test_split_by_code_map(tmp_path):
    cmap = tmp_path / "code_map.json"
    cmap.write_text(json.dumps({"mapping": [{"screen_id": "QNA-001", "files": ["src/main/resources/templates/qna/list.html"]}],
                                "common_files": []}), encoding="utf-8")
    res, _ = cli.build(APP, code_map=cmap, log=lambda *a: None, analysis=ANALYSIS)
    q1 = res["screens"]["QNA-001"]
    assert any("GET /qna →" in f.fact for f in q1)
    assert not any("errorMessage" in f.fact for f in q1)


# ---------------------------------------------------------------- 출력 파일

def test_output_matches_backend_format(tmp_path):
    out = tmp_path / "code_facts.json"
    saved = tmp_path / "backend-analysis.json"
    saved.write_text(json.dumps(ANALYSIS, ensure_ascii=False), encoding="utf-8")
    assert cli.main(["--code", str(APP), "--requirements", str(REQ), "--out", str(out), "--analysis", str(saved)]) == 0
    assert (tmp_path / "frontend-js.json").is_file()
    obj = json.loads(out.read_text(encoding="utf-8"))
    assert isinstance(obj["common"], list) and isinstance(obj["screens"], dict)
    for f in obj["common"] + [x for xs in obj["screens"].values() for x in xs]:
        assert set(f) == {"kind", "file", "line", "fact"} and isinstance(f["line"], int)
    try:
        sys.path.insert(0, str(BACKEND))
        from specpilot.judge import facts_for, load_facts
    except Exception:
        pytest.skip("backend의 judge를 불러올 수 없음 (패키지 미설치)")
    facts = load_facts(out)
    assert len(facts_for(facts, "QNA-002")) == len(obj["common"]) + len(obj["screens"]["QNA-002"])


# ---------------------------------------------------------------- 호출 대상 (분석기 결과 + 채우기)

def test_call_targets_from_analyzer():
    from code_analysis.backend_model import BackendModel
    m = BackendModel(ANALYSIS)
    by = {(c.raw["caller_class"], c.raw["name"]): c for c in m.calls}
    send = by[("QnaService", "send")]                       # 인터페이스 → 구현 둘 다 (분석기가 구현 위치를 줌)
    assert send.source == "javaparser"
    assert {x.qname for x in m.resolve_targets(send)} == {"NotifyService.send", "MailNotifyService.send", "SmsNotifyService.send"}
    close = by[("AdminQnaController", "close")]             # 부모 클래스(BaseController)의 필드로 받은 서비스
    assert close.source == "javaparser" and close.target.name == "QnaService"
    exists = by[("QnaService", "existsByTitle")]            # 라이브러리 classpath 없이: 메서드는 못 풀어도 받는 쪽 타입으로 잇는다
    assert exists.source == "receiver_type" and exists.target.name == "QnaRepository"
    assert by[("QnaController", "addAttribute")].target is None    # 라이브러리(Model) 호출은 사실에 쓰지 않는다


def test_inherited_field_route_calls(result):
    res, _ = result
    assert find(res, "route", "POST /admin/qna/{id}/close", "호출 QnaService.close")


# ---------------------------------------------------------------- v0.2.1: 라이브러리 설정 · 조건부 문구 · 인라인 이벤트 · 버튼·링크

def test_library_config_fact(result):
    res, _ = result
    f = find(res, "js", "gridOptions을(를) agGrid.createGrid에 넘기는 설정", "pagination=true", "paginationPageSize=10",
             "columnDefs=객체 2개 (headerName: 번호, 제목)")[0]
    assert f.file.endswith("qna-list.js") and "const gridOptions" in codebase.load(APP).line(f.file, f.line)
    # 이벤트가 없다는 요약은 범위를 밝힌다 (라이브러리 설정을 "없음"으로 읽지 않게)
    assert find(res, "js", "qna-list.js: addEventListener로 붙이는 이벤트", "라이브러리 설정 1개")


def test_conditional_text_and_placeholder(result):
    res, _ = result
    t = find(res, "html", "문구 '등록된 질문이 없습니다.'", 'th:unless="${hasQna}" 아닐 때만 보임')[0]
    assert "등록된 질문이 없습니다." in codebase.load(APP).line(t.file, t.line)
    # th:text가 있는 링크의 문구는 자리표시라고 밝힌다
    assert find(res, "html", "링크 (th:text=${latestTitle} 값, 자리표시 '최근 질문 제목')", 'th:if="${hasQna}" 일 때만 보임')
    assert not find(res, "html", "링크 '최근 질문 제목'")


def test_inline_event_and_every_link(result):
    res, _ = result
    assert find(res, "html", "입력란 dueDate: type=text", "포커스를 받으면 type=date로 바뀜")
    assert find(res, "html", "링크 '취소': 누르면 GET /qna로 이동, 확인 창 없음")
    assert find(res, "html", "버튼 '등록': 누르면 POST /qna 폼 제출, 확인 창 없음")


# ---------------------------------------------------------------- ③ 근거 재확인용 도달 정보 (reach)

def test_reach_for_evidence_recheck(split, tmp_path):
    from code_analysis.facts import write
    from code_analysis.reach import method_end
    reach = split["reach"]
    m = {x["name"]: x for x in reach["methods"]}
    assert (m["QnaController.create"]["start"], m["QnaController.create"]["end"]) == (21, 33)   # 애노테이션 줄부터 닫는 중괄호까지
    assert m["QnaController.check"]["start"] == 40 and m["QnaController.check"]["end"] == 44
    s2 = reach["screens"]["QNA-002"]
    # 작성 화면: 폼 제출 경로 → 컨트롤러 → 서비스 → (인터페이스면 구현 모두) → 저장소
    assert {"QnaController.create", "QnaService.create", "MailNotifyService.send", "SmsNotifyService.send"} <= set(s2["methods"])
    assert "src/main/java/demo/repository/QnaRepository.java" in s2["files"] and WRITE in s2["files"]
    assert "QnaService.create" not in reach["screens"]["QNA-001"]["methods"]                  # 목록 화면에서는 닿지 않음
    unused = {(u["file"], u["start"]) for u in reach["unused"]}
    assert (CTRL, 40) in unused                                                               # POST /qna/check
    assert ("src/main/resources/templates/qna/old.html", 1) in unused
    obj = write(tmp_path / "cf.json", split["common"], split["screens"], split["meta"], reach)
    assert obj["reach"] is reach and split["meta"]["reach"]["unused"] == len(reach["unused"])
    # 문자열·주석 안의 중괄호는 세지 않는다
    assert method_end(['void a() {', '  String s = "}";  // }', '  /* { */', '}', 'x'], 1) == 4
    assert method_end(['abstract void b();'], 1) == 1

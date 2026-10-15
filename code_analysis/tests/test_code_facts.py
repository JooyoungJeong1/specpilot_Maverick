"""code_analysis 테스트. 기업 샘플 코드 대신 tests/fixtures/qna-app(가상의 앱)으로 확인한다.

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
BACKEND = Path(__file__).resolve().parents[2] / "backend"

CTRL = "src/main/java/demo/controller/QnaController.java"
WRITE = "src/main/resources/templates/qna/write.html"
JS = "src/main/resources/static/js/qna.js"


@pytest.fixture(scope="module")
def result():
    res, problems = cli.build(APP, log=lambda *a: None)
    return res, problems


@pytest.fixture(scope="module")
def split():
    res, _ = cli.build(APP, requirements=REQ, log=lambda *a: None)
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
                "QnaRepository.save(Spring Data 기본 기능)")
    assert find(res, "message", "이미 있는 제목입니다.")
    v = find(res, "validation", "QnaForm.title")[0]
    assert '@NotBlank("제목을 입력하세요")' in v.fact and "max=30" in v.fact and "POST /qna (@Valid)" in v.fact


def test_js(result):
    res, _ = result
    b = find(res, "js", "#title input 이벤트", "saveButton.disabled")[0]
    assert b.file == JS and "addEventListener" in codebase.load(APP).line(JS, b.line)
    assert find(res, "js", "qna.js: 붙이는 이벤트 input", "blur·focusout·submit 이벤트 없음", "qna/write.html")


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
    res, _ = cli.build(APP, code_map=cmap, log=lambda *a: None)
    q1 = res["screens"]["QNA-001"]
    assert any("GET /qna →" in f.fact for f in q1)
    assert not any("errorMessage" in f.fact for f in q1)


# ---------------------------------------------------------------- 출력 파일

def test_output_matches_backend_format(tmp_path):
    out = tmp_path / "code_facts.json"
    assert cli.main(["--code", str(APP), "--requirements", str(REQ), "--out", str(out)]) == 0
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

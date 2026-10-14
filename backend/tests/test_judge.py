"""③ 정합성 판정, 코드 준비, trace, 채점 테스트 (API 키 필요 없음).

테스트용 코드와 문구는 모두 지어낸 것이다. 실제 샘플 코드의 결함을 넣지 않는다 (블라인드 평가).
"""
import json
from pathlib import Path

import pytest

from specpilot import code_prep, schema
from specpilot.config import Settings
from specpilot.judge import choose_mode, judge_screen, merge_judgments, units_by_screen
from specpilot.llm import ScriptedLLM
from specpilot.pdf_utils import item_block
from specpilot.prompts import PromptSet
from specpilot.stages import RunContext, write_json
from specpilot.trace import trace

CONTROLLER = """package demo;
public class AuthController {
    @GetMapping("/login")
    public String login() { return "auth/login"; }
    String fail = "회원 정보를 찾을 수 없습니다. 다시 시도해주세요.";
}"""
TEMPLATE = """<html><title>로그인</title>
<button id="google">Google로 계속하기</button>
<button id="login" disabled>로그인</button>
</html>"""


def unit(i, **kw):
    base = {"id": f"REQ-LOGIN-001-{i:02d}", "screen_id": "LOGIN-001", "source": [f"Action {chr(64 + i)}"],
            "quote": "q", "origin": "명시", "reason": None, "kind": "표시", "given": None,
            "when": "로그인 화면에 들어간다", "conditions": [], "then": f"결과 {i}",
            "exact": {"message": None, "values": [], "target": None}, "issue": None}
    base.update(kw)
    return base


@pytest.fixture
def code_root(tmp_path):
    root = tmp_path / "code"
    (root / "src/main/java/demo").mkdir(parents=True)
    (root / "src/main/resources/templates/auth").mkdir(parents=True)
    (root / "src/test/java").mkdir(parents=True)
    (root / "node_modules/lib").mkdir(parents=True)
    (root / "src/main/java/demo/AuthController.java").write_text(CONTROLLER, encoding="utf-8")
    (root / "src/main/resources/templates/auth/login.html").write_text(TEMPLATE, encoding="utf-8")
    (root / "src/test/java/AuthTest.java").write_text("class AuthTest {}", encoding="utf-8")
    (root / "node_modules/lib/x.js").write_text("var x;", encoding="utf-8")
    return root


@pytest.fixture
def run_dir(tmp_path):
    rd = tmp_path / "run"
    units = [
        unit(1, then="Google 로그인 버튼이 표시된다", exact={"message": None, "values": ["Google로 계속하기"], "target": None}),
        unit(2, kind="실패", then="오류 메시지가 표시된다",
             exact={"message": "회원 정보를 찾을 수 없습니다. 다시 확인해 주세요.", "values": [], "target": None}),
        {**unit(1), "id": "REQ-APP-01", "screen_id": "APP", "source": ["LOGIN-001 Description 0"], "kind": "접근"},
        {**unit(1), "id": "REQ-APP-02", "screen_id": "APP", "source": ["화면 이미지"], "quote": "어디에도 없음", "kind": "접근"},
    ]
    write_json(rd / "requirements.json", {
        "app_profile": {"screens": [{"screen_id": "LOGIN-001", "name": "로그인", "pages": [1]}]},
        "units": units, "questions": [],
    })
    return rd


def ctx_for(run_dir, responses):
    s = Settings()
    s.max_retries = 1
    return RunContext(run_dir, run_dir / "input.pdf", s, PromptSet(s.prompts_dir), ScriptedLLM(responses))


# ---------- 코드 준비 ----------

def test_load_codebase_skips_tests_and_libraries(code_root):
    cb = code_prep.load_codebase(code_root)
    assert sorted(cb.files) == ["src/main/java/demo/AuthController.java",
                                "src/main/resources/templates/auth/login.html"]
    text = cb.text()
    assert "=== src/main/java/demo/AuthController.java ===\n1|package demo;" in text
    assert '3|    @GetMapping("/login")' in text


def test_verify_evidence(code_root):
    cb = code_prep.load_codebase(code_root)
    f = "src/main/java/demo/AuthController.java"
    assert code_prep.verify_evidence(cb, [{"file": f, "line": 3, "code": '@GetMapping("/login")'}]) == []
    assert code_prep.verify_evidence(cb, [{"file": f, "line": 3, "code": '  @GetMapping("/login")  '}]) == []  # 공백 차이는 허용
    assert "실제 줄과 다름" in code_prep.verify_evidence(cb, [{"file": f, "line": 2, "code": '@GetMapping("/login")'}])[0]
    assert "없는 파일" in code_prep.verify_evidence(cb, [{"file": "Nope.java", "line": 1, "code": "x"}])[0]
    assert "범위 밖" in code_prep.verify_evidence(cb, [{"file": f, "line": 99, "code": "x"}])[0]


def test_files_mentioning_finds_slightly_different_message(code_root):
    cb = code_prep.load_codebase(code_root)
    hits = code_prep.files_mentioning(cb, ["회원 정보를 찾을 수 없습니다. 다시 확인해 주세요."])
    assert hits == {"src/main/java/demo/AuthController.java"}


def test_file_index_has_routes_and_labels(code_root):
    idx = {i["path"]: i for i in code_prep.file_index(code_prep.load_codebase(code_root))}
    assert any("/login" in s for s in idx["src/main/java/demo/AuthController.java"]["signals"])
    assert "Google로 계속하기" in idx["src/main/resources/templates/auth/login.html"]["signals"]


def test_choose_mode_by_size(code_root):
    cb = code_prep.load_codebase(code_root)
    s = Settings()
    s.code_token_limit = 10_000
    assert choose_mode(s, cb, None) == "whole"
    s.code_token_limit = 10
    assert choose_mode(s, cb, None) == "screen"
    assert choose_mode(s, cb, "whole") == "whole"


# ---------- 단위 배분과 집계 ----------

def test_units_by_screen_routes_app_units(run_dir):
    req = json.loads((run_dir / "requirements.json").read_text(encoding="utf-8"))
    groups = units_by_screen(req)
    assert [u["id"] for u in groups["LOGIN-001"]] == ["REQ-LOGIN-001-01", "REQ-LOGIN-001-02", "REQ-APP-01"]
    assert [u["id"] for u in groups["APP"]] == ["REQ-APP-02"]


def test_aggregate_items_partial():
    units = [unit(1, source=["Description 3-(3)-1)"]), unit(2, source=["Description 3-(3)-2)"]), unit(3, source=["Action E"])]
    items = schema.aggregate_items(units, {"REQ-LOGIN-001-01": "불일치", "REQ-LOGIN-001-02": "미구현", "REQ-LOGIN-001-03": "구현"})
    assert items["LOGIN-001 Description 3"]["status"] == "부분구현"
    assert items["LOGIN-001 Action E"]["status"] == "구현"


# ---------- 판정: 근거 대조, 빠진 단위, 쪼개기 신호 ----------

def test_judge_screen_downgrades_fake_evidence(run_dir, code_root):
    cb = code_prep.load_codebase(code_root)
    req = json.loads((run_dir / "requirements.json").read_text(encoding="utf-8"))
    us = units_by_screen(req)["LOGIN-001"]
    tpl = "src/main/resources/templates/auth/login.html"
    response = {
        "screen_id": "LOGIN-001",
        "results": [
            {"unit_id": "REQ-LOGIN-001-01", "status": "구현", "mismatch": [], "note": None, "split_issue": None,
             "evidence": [{"file": tpl, "line": 2, "code": '<button id="google">Google로 계속하기</button>'}]},
            {"unit_id": "REQ-LOGIN-001-02", "status": "불일치", "note": None,
             "mismatch": [{"field": "message", "spec": "다시 확인해 주세요.", "code": "다시 시도해주세요."}],
             "split_issue": "문구는 불일치, 표시 위치는 확인필요",
             "evidence": [{"file": "src/main/java/demo/AuthController.java", "line": 1, "code": "지어낸 코드"}]},
        ],
        "extras": [],
    }
    # 첫 응답은 REQ-APP-01 판정이 빠져 재시도, 두 번째도 같으면 빠진 단위를 확인필요로 채움
    c = ctx_for(run_dir, [json.dumps(response, ensure_ascii=False)] * 2)
    meta = judge_screen(c, cb, "LOGIN-001", us, None)
    assert meta["attempts"] == 2 and meta["evidence_failures"] == 1
    saved = {r["unit_id"]: r for r in json.loads((run_dir / "judge/LOGIN-001.json").read_text(encoding="utf-8"))["results"]}
    assert saved["REQ-LOGIN-001-01"]["status"] == "구현"
    assert saved["REQ-LOGIN-001-02"]["status"] == "확인필요" and saved["REQ-LOGIN-001-02"]["original_status"] == "불일치"
    assert saved["REQ-APP-01"]["status"] == "확인필요" and "판정 누락" in saved["REQ-APP-01"]["note"]
    # 코드 묶음은 캐시 블록으로 먼저 들어간다
    first = c.llm.calls[0]["messages"][0]["content"][0]
    assert first["text"].startswith("# 코드 묶음") and "cache_control" in first

    report = merge_judgments(run_dir)
    assert report["summary"]["split_issues"] == 1
    assert report["summary"]["evidence_failures"] == 1


def test_merge_candidates_flags_too_fine_split():
    ev = [{"file": "a.html", "line": 3, "code": "x"}]
    units = [unit(1), unit(2)]
    results = {"REQ-LOGIN-001-01": {"status": "구현", "evidence": ev}, "REQ-LOGIN-001-02": {"status": "구현", "evidence": ev}}
    assert schema.merge_candidates(units, results)[0]["units"] == ["REQ-LOGIN-001-01", "REQ-LOGIN-001-02"]


# ---------- trace ----------

def test_trace_shows_chain(run_dir, code_root):
    write_json(run_dir / "judge" / "run.json", {"code_root": str(code_root)})
    tpl = "src/main/resources/templates/auth/login.html"
    write_json(run_dir / "judgments.json", {"results": {"REQ-LOGIN-001-01": {
        "unit_id": "REQ-LOGIN-001-01", "screen_id": "LOGIN-001", "status": "구현", "mismatch": [], "note": None,
        "split_issue": "버튼은 있음, 로고는 확인필요",
        "evidence": [{"file": tpl, "line": 2, "code": "x"}]}}, "items": {}, "extras": []})
    out = trace(run_dir, unit="REQ-LOGIN-001-01")
    for part in ("[1. 기획서 원문]", "[2. ② 단위]", "[3. ③ 판정]", "판정 갈림", "Google로 계속하기", "[원인 가려내기]"):
        assert part in out
    assert "해당하는 단위가 없습니다" in trace(run_dir, item="LOGIN-001 Description 9")


def test_item_block_cuts_one_item():
    text = "\n".join([
        "                    0   로그인 화면 개요",
        "                    1   SNS 로그인은 버튼으로 표시한다.",
        "     1   (이미지 마커)",
        "                        (1) Google (2) Naver",
        "                    A   Google 새창",
        "                    B   Naver 새창",
    ])
    assert item_block(text, "Description 1") == "1   SNS 로그인은 버튼으로 표시한다.\n(1) Google (2) Naver"
    assert item_block(text, "Action B") == "B   Naver 새창"


# ---------- 채점 ----------

def test_score_counts_detected_missed_false_alarm(tmp_path):
    from specpilot.score import format_report, score
    write_json(tmp_path / "judgments.json", {"results": {}, "extras": [], "items": {
        "QNA-002 Description 1": {"status": "불일치", "units": ["REQ-QNA-002-03"]},
        "QNA-002 Description 2": {"status": "불일치", "units": ["REQ-QNA-002-04"]},
        "QNA-002 Action A": {"status": "구현", "units": ["REQ-QNA-002-09"]},
    }})
    key = Path(__file__).resolve().parent.parent / "docs" / "answer_key.example.json"
    report = score(tmp_path, key)
    s = report["summary"]
    # 결함 3개(D1 불일치, A 부분구현, B 미구현) 중 D1만 탐지. D2는 정답이 구현인데 불일치로 판정 → 오탐. B는 판정 없음.
    assert (s["defects_in_key"], s["detected"], s["false_alarms"], s["not_judged"]) == (3, 1, 1, 1)
    assert s["recall"] == 0.333 and s["precision"] == 0.5
    text = format_report(report)
    assert "결함 탐지율 33%" in text and "오탐  QNA-002 Description 2" in text


def test_score_uses_explicit_units_only_and_explains_missing(tmp_path):
    from specpilot.score import format_report, score

    def unit(uid, origin, source):
        return {"id": uid, "screen_id": "QNA-002", "origin": origin, "source": source,
                "quote": "q", "reason": None if origin == "명시" else "A이고 B이므로 C", "then": "t"}

    write_json(tmp_path / "requirements.json", {
        "units": [unit("U1", "명시", ["Description 1"]),
                  unit("U2", "명시", ["Description 2"]),
                  unit("U3", "함의", ["Description 2", "Action A"]),        # 함의: 채점에 넣으면 D2, A를 오탐으로 만든다
                  unit("U4", "함의", ["Action B"])],                        # Action B는 함의로만 나옴
        "questions": [], "skipped": {"QNA-002": []}, "rejected_units": {}, "rejected_screens": {},
        "screen_status": {"QNA-002": {"status": "완료"}}})
    write_json(tmp_path / "judgments.json", {"items": {}, "extras": [], "results": {
        "U1": {"status": "불일치"}, "U2": {"status": "구현"}, "U3": {"status": "미구현"}, "U4": {"status": "미구현"}}})
    key = Path(__file__).resolve().parent.parent / "docs" / "answer_key.example.json"
    report = score(tmp_path, key)
    rows = {r["item"]: r for r in report["rows"]}
    assert rows["QNA-002 Description 2"]["outcome"] == "정상"          # 함의 U3의 미구현이 섞이지 않음
    assert rows["QNA-002 Description 1"]["outcome"] == "탐지"
    assert rows["QNA-002 Action A"]["predicted"] is None
    assert "함의 단위로만 나옴 (U3)" in rows["QNA-002 Action A"]["why_not_judged"]
    assert "함의 단위로만 나옴 (U4)" in rows["QNA-002 Action B"]["why_not_judged"]
    assert [i["unit_id"] for i in report["implied_review"]] == ["U3", "U4"]
    assert report["summary"]["basis"] == "명시 단위만"
    review = (tmp_path / "score_review.md").read_text(encoding="utf-8")
    assert "정답" in review and "AI" in review
    implied_md = (tmp_path / "implied_review.md").read_text(encoding="utf-8")
    assert "U3" in implied_md and "(O / X)" in implied_md
    assert "함의 단위 2개는 채점하지 않음" in format_report(report)


# ---------- 문구 띄어쓰기 ----------

def test_spacing_only_mismatch_becomes_implemented():
    from specpilot.judge import relax_spacing
    r = {"status": "불일치", "note": None,
         "mismatch": [{"field": "message", "spec": "형식이 올바르지 않습니다.", "code": "형식이 올바르지않습니다."}]}
    assert relax_spacing(r) and r["status"] == "구현" and r["original_status"] == "불일치"
    assert "띄어쓰기" in r["note"]
    r2 = {"status": "불일치", "mismatch": [{"field": "message", "spec": "다시 확인해 주세요.", "code": "다시 시도해주세요."}]}
    assert not relax_spacing(r2) and r2["status"] == "불일치"                 # 글자가 다르면 그대로 불일치
    r3 = {"status": "불일치", "mismatch": [{"field": "message", "spec": "a b", "code": "ab"},
                                         {"field": "target", "spec": "QNA-001", "code": "QNA-002"}]}
    assert not relax_spacing(r3)                                                 # 다른 차이가 같이 있으면 그대로


def test_units_sent_to_judge_without_response_keys(run_dir, code_root):
    cb = code_prep.load_codebase(code_root)
    req = json.loads((run_dir / "requirements.json").read_text(encoding="utf-8"))
    us = [{**u, "key": "u01"} for u in units_by_screen(req)["LOGIN-001"][:1]]
    c = ctx_for(run_dir, [json.dumps({"screen_id": "LOGIN-001", "extras": [], "results": [
        {"unit_id": us[0]["id"], "status": "미구현", "mismatch": [], "evidence": [], "note": "없음", "split_issue": None}]})])
    judge_screen(c, cb, "LOGIN-001", us, None)
    sent = c.llm.calls[0]["messages"][0]["content"][1]["text"]
    assert '"key"' not in sent and us[0]["id"] in sent


# ---------- 코드 분석 결과 (--facts) ----------

def test_code_facts_go_into_judge_prompt(run_dir, code_root):
    from specpilot.judge import facts_for, load_facts, NO_FACTS
    example = load_facts(Path(__file__).resolve().parent.parent / "docs" / "code_facts.example.json")
    assert facts_for(example, "QNA-002")[0]["kind"] == "security"          # 공통이 먼저, 그 화면 것이 뒤에
    assert len(facts_for(example, "QNA-002")) == 5 and len(facts_for(example, "QNA-001")) == 1

    cb = code_prep.load_codebase(code_root)
    req = json.loads((run_dir / "requirements.json").read_text(encoding="utf-8"))
    us = units_by_screen(req)["LOGIN-001"][:1]
    answer = json.dumps({"screen_id": "LOGIN-001", "extras": [], "results": [
        {"unit_id": us[0]["id"], "status": "미구현", "mismatch": [], "evidence": [], "note": "없음", "split_issue": None}]})

    c = ctx_for(run_dir, [answer])
    meta = judge_screen(c, cb, "LOGIN-001", us, None, [{"fact": "AuthController.login → AuthService.login"}])
    sent = c.llm.calls[0]["messages"][0]["content"][1]["text"]
    assert "AuthController.login → AuthService.login" in sent and meta["facts"] == 1

    c2 = ctx_for(run_dir, [answer])                                        # --facts 없이: 자리에 (없음)
    judge_screen(c2, cb, "LOGIN-001", us, None)
    assert f"코드 분석 결과: {NO_FACTS}" in c2.llm.calls[0]["messages"][0]["content"][1]["text"]

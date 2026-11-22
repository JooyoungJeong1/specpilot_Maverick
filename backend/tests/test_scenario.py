"""④ 시나리오 합성과 테스트 사양서 엑셀 테스트 (API 키 필요 없음).

가상의 문의 게시판 앱(QNA)으로 확인한다. 실제 기획서 내용은 넣지 않는다.
"""
import json

import pytest

openpyxl = pytest.importorskip("openpyxl")

from specpilot import cli  # noqa: E402
from specpilot.config import Settings  # noqa: E402
from specpilot.llm import LLMResult, ScriptedLLM  # noqa: E402
from specpilot.prompts import PromptSet  # noqa: E402
from specpilot.scenario import (SPEC_FILE, TRACE_FILE, build_groups, merge_scenarios, popup_parent,  # noqa: E402
                                post_checks, run_scenario, validate_scenarios)
from specpilot.stages import RunContext, read_json, write_json  # noqa: E402

QUOTE = "이 문장은 사양서 프롬프트에 들어가면 안 된다"


def unit(uid, sid, kind="표시", **kw):
    base = {"id": uid, "key": "u01", "screen_id": sid, "source": ["Description 1"], "quote": QUOTE,
            "origin": "명시", "reason": None, "kind": kind, "given": None, "when": "화면에 들어간다",
            "conditions": [], "then": f"{uid} 결과가 표시된다", "exact": {"message": None, "values": [], "target": None},
            "issue": None, "ref_hint": {"screen_id": "QNA-001", "source": "Description 9", "value": "다른 화면 값"}}
    base.update(kw)
    return base


UNITS = [
    unit("REQ-QNA-001-01", "QNA-001", then="문의 목록이 표시된다"),
    unit("REQ-QNA-002-01", "QNA-002", then="제목과 내용 입력란이 표시된다"),
    unit("REQ-QNA-002-02", "QNA-002", kind="검증", when="제목을 비우고 다른 곳을 누른다", then="오류 메시지가 표시된다",
         exact={"message": "제목을 입력해주세요.", "values": [], "target": None}),
    unit("REQ-QNA-002-03", "QNA-002", kind="제약", when="제목을 검사할 때", then="서버 확인 없이 검사한다"),
    unit("REQ-QNA-002-04", "QNA-002", kind="처리", origin="함의", reason="등록하면 저장되고 목록으로 가므로 목록에 보여야 한다",
         then="등록한 문의가 목록에 표시된다"),
    unit("REQ-QNA-005-01", "QNA-005", kind="이동", when="삭제하기를 누른다", then="삭제 확인 팝업이 표시된다",
         issue="팝업 문구가 설계서에 없음"),
    unit("REQ-QNA-006-01", "QNA-006", kind="이동", when="확인을 누른다", then="문의 목록 화면으로 이동한다",
         exact={"message": None, "values": [], "target": "QNA-001"}),
    unit("REQ-APP-01", "APP", kind="접근", origin="함의", reason="상단 로그아웃 버튼이 있어 로그인을 전제로 한다",
         given="로그아웃 상태", when="문의 목록 주소로 들어간다", then="문의 목록을 볼 수 없다"),
]
SCREENS = [
    {"screen_id": "QNA-001", "name": "문의 목록", "depth": "고객센터", "type": "화면", "repeats_from": None},
    {"screen_id": "QNA-002", "name": "문의 작성", "depth": "고객센터", "type": "화면", "repeats_from": None},
    {"screen_id": "QNA-006", "name": "문의 삭제 확인", "depth": "고객센터", "type": "팝업", "repeats_from": None},
    {"screen_id": "QNA-005", "name": "문의 수정", "depth": "고객센터", "type": "화면", "repeats_from": None},
]
FLOWS = [{"from": "QNA-002", "trigger": "등록", "to": "QNA-001", "source": "QNA-002 Action A"},
         {"from": "QNA-005", "trigger": "삭제하기", "to": "QNA-006", "source": "QNA-005 Action B"}]
QUESTIONS = [{"id": "Q-APP-01", "topic": "로그인 후 이동", "question": "로그인 뒤 어느 화면으로 가나요?", "why": "설계서에 없음",
              "priority": "하", "related_units": []},
             {"id": "Q-QNA-002-01", "topic": "역할", "question": "답변은 누가 쓰나요?", "why": "역할 이름 없음",
              "priority": "상", "related_units": ["REQ-QNA-002-01"]}]


def step(action, expected, ids, **kw):
    s = {"action": action, "expected": expected, "account": None, "input": None, "data_source": None,
         "note": None, "unit_ids": ids, "setup": False}
    s.update(kw)
    return s


def answer(*scenarios):
    return json.dumps({"scenarios": list(scenarios)}, ensure_ascii=False)


def sc(title, steps, category=None):
    return {"title": title, "category": category, "steps": steps}


R_001 = answer(sc("문의 목록 표시", [
    step("일반 사용자로 로그인한다.", "로그인된다.", [], setup=True, account="일반 사용자 / user1@example.com", data_source="더미"),
    step("문의 목록 화면에 들어간다.", "문의 목록이 표시된다.", ["REQ-QNA-001-01"]),
]))
R_002_BAD = answer(sc("문의 작성", [step("문의 작성 화면에 들어간다.", "입력란이 표시된다.", ["REQ-QNA-009-01"])]))
R_002_MISSING = answer(sc("문의 작성 화면 표시와 제목 검사", [
    step("문의 작성 화면에 들어간다.", "제목과 내용 입력란이 표시된다.", ["REQ-QNA-002-01"]),
    step("제목을 비우고 다른 곳을 누른다.", "\"제목을 입력해주세요.\" 오류 메시지가 표시된다.", ["REQ-QNA-002-02"]),
    step("제목을 입력하고 다른 곳을 누른다.", "오류 메시지가 표시되지 않는다.", ["REQ-QNA-002-02"], note="정상 짝"),
]))
R_002_GAP = answer(sc("문의 등록 뒤 목록 반영", [
    step("문의를 등록한다.", "문의 목록 화면이 표시된다.", [], setup=True),
    step("목록에서 등록한 문의를 찾는다.", "등록한 문의가 목록에 표시된다.", ["REQ-QNA-002-04"]),
]))
R_005 = answer(sc("문의 삭제", [
    step("문의 수정 화면에서 삭제하기를 누른다.", "삭제 확인 팝업이 표시된다.", ["REQ-QNA-005-01"]),
    step("팝업에서 확인을 누른다.", "문의 목록 화면으로 이동한다.", ["REQ-QNA-006-01"], note="테스트용 문의만 삭제"),
]))
R_APP = answer(sc("로그아웃 상태 접근 제한", [
    step("로그아웃 상태에서 문의 목록 주소로 들어간다.", "문의 목록을 볼 수 없다.", ["REQ-APP-01"]),
], category="접근 권한"))


@pytest.fixture
def run_dir(tmp_path):
    rd = tmp_path / "run"
    write_json(rd / "requirements.json", {
        "app_profile": {"screens": SCREENS, "flows": FLOWS, "login_required": [], "roles": [], "role_limited": None,
                        "common_areas": [], "reading_notes": []},
        "units": UNITS, "questions": QUESTIONS,
    })
    write_json(rd / "run.json", {"run_id": "t", "source_pdf": "inputs\\가상기획서.pdf"})
    return rd


def ctx_for(run_dir, responses):
    s = Settings()
    s.max_retries = 1
    llm = None if responses is None else ScriptedLLM(responses)
    return RunContext(run_dir, run_dir / "input.pdf", s, PromptSet(s.prompts_dir), llm)


def req(run_dir):
    return read_json(run_dir / "requirements.json")


# ---------- 묶음 ----------

def test_groups_follow_screens_put_popup_with_parent_and_skip_constraints(run_dir):
    groups, excluded = build_groups(req(run_dir))
    assert [g["id"] for g in groups] == ["QNA-001", "QNA-002", "QNA-005", "APP"]
    g005 = groups[2]
    assert g005["screens"] == ["QNA-005", "QNA-006"]
    assert [u["id"] for u in g005["units"]] == ["REQ-QNA-005-01", "REQ-QNA-006-01"]
    assert "팝업 QNA-006 문의 삭제 확인 포함" in g005["label"]
    assert [u["id"] for u in excluded] == ["REQ-QNA-002-03"]
    assert all(u["kind"] != "제약" for g in groups for u in g["units"])


def test_popup_parent_falls_back_to_repeats_from():
    screens = {"A-001": {"screen_id": "A-001", "type": "화면"},
               "A-002": {"screen_id": "A-002", "type": "팝업", "repeats_from": {"screen_id": "A-001", "items": []}}}
    assert popup_parent(screens["A-002"], screens, []) == "A-001"
    assert popup_parent({"screen_id": "A-009", "type": "팝업"}, screens, []) is None


def test_prompt_renders_with_example_and_keeps_units_in_input_part(run_dir):
    p = PromptSet(Settings().prompts_dir).render("scenario", GROUP="QNA-001 문의 목록", UNITS="[]", APP_PROFILE="{}", NOTE="없음")
    assert "TC-" not in p.system                      # 시나리오 ID는 프로그램이 붙인다
    assert '"title": "문의 작성 화면 표시와 입력 검사"' in p.system
    assert p.user_input.startswith("# 입력") and "QNA-001 문의 목록" in p.user_input


# ---------- 검사 ----------

def test_validate_rejects_unknown_ids_and_blank_steps():
    obj = {"scenarios": [{"title": "t", "steps": [
        {"action": "", "expected": "x", "unit_ids": ["REQ-X"]},
        {"action": "a", "expected": "b", "unit_ids": "REQ-A"},
    ]}]}
    msgs = [i.message for i in validate_scenarios(obj, ["REQ-A"])]
    assert any("action가 비어" in m for m in msgs)
    assert any("이 묶음에 없는 단위 ID: REQ-X" in m for m in msgs)
    assert any("목록이어야" in m for m in msgs)
    assert validate_scenarios({"scenarios": []}, ["REQ-A"])[0].message == "시나리오가 하나도 없습니다"


def test_post_checks_message_and_unit_less_steps():
    by_id = {"REQ-A": {"exact": {"message": "제목을 입력해주세요."}}}
    scs = [{"scenario_id": "TC-X-01", "steps": [
        {"no": 1, "expected": "오류 메시지가 표시된다.", "unit_ids": ["REQ-A"], "note": None, "setup": False},
        {"no": 2, "expected": "오류 메시지가 표시되지 않는다.", "unit_ids": ["REQ-A"], "note": "정상 짝", "setup": False},
        {"no": 3, "expected": "\"제목을 입력해 주세요.\"가 표시된다.", "unit_ids": ["REQ-A"], "note": None, "setup": False},
        {"no": 4, "expected": "화면이 표시된다.", "unit_ids": [], "note": None, "setup": False},
        {"no": 5, "expected": "로그인된다.", "unit_ids": [], "note": None, "setup": True},
    ]}]
    where = [i.where for i in post_checks(scs, by_id)]
    assert where == ["TC-X-01 단계 1", "TC-X-01 단계 4"]    # 3은 띄어쓰기만 달라 통과, 2는 정상 짝, 5는 준비 단계


# ---------- 전체 실행 ----------

def test_run_scenario_end_to_end(run_dir):
    ctx = ctx_for(run_dir, [R_001, R_002_BAD, R_002_MISSING, R_002_GAP, R_005, R_APP])
    report = run_scenario(ctx, log=lambda *_: None)

    s = report["summary"]
    assert (s["units_target"], s["units_covered"], s["units_uncovered"], s["units_excluded"]) == (7, 7, 0, 1)
    assert report["group_status"] == {"QNA-001": "완료", "QNA-002": "완료", "QNA-005": "완료", "APP": "완료"}

    # ④에는 quote·ref_hint를 보내지 않는다 (예상결과를 then·exact로만 쓰게)
    sent = ctx.llm.calls[0]["messages"][0]["content"][0]["text"]
    assert QUOTE not in sent and "다른 화면 값" not in sent and "REQ-QNA-001-01" in sent
    # 빠진 단위만 다시 요청했다
    gap = ctx.llm.calls[3]["messages"][0]["content"][0]["text"]
    assert "REQ-QNA-002-04" in gap and "REQ-QNA-002-01" not in gap and "빠졌다" in gap
    meta = read_json(run_dir / "scenario" / "QNA-002.meta.json")
    assert meta["attempts"] == 2 and meta["gap"]["units"] == ["REQ-QNA-002-04"]

    data = read_json(run_dir / "scenarios.json")
    ids = [x["scenario_id"] for x in data["scenarios"]]
    assert ids == ["TC-QNA-001-01", "TC-QNA-002-01", "TC-QNA-002-02", "TC-QNA-005-01", "TC-APP-01"]
    first = data["scenarios"][0]
    assert (first["depth1"], first["depth2"], first["title"]) == ("고객센터", "문의 목록", "문의 목록 표시")
    assert [st["no"] for st in first["steps"]] == [1, 2] and first["steps"][0]["setup"] is True
    app = data["scenarios"][-1]
    assert (app["depth1"], app["depth2"]) == ("앱 전체", "접근 권한")
    assert app["steps"][0]["note"].startswith("함의: ")          # 프로그램이 붙인 비고
    delete = data["scenarios"][3]
    assert "확인 필요: 팝업 문구가 설계서에 없음" in delete["steps"][0]["note"]
    assert delete["steps"][1]["note"] == "테스트용 문의만 삭제"
    assert data["excluded"] == ["REQ-QNA-002-03"]
    # 화면(frontend)이 읽는 칸
    assert set(first["steps"][0]) >= {"no", "action", "expected", "account", "input", "data_source", "note", "unit_ids", "setup"}


def test_spec_excel_follows_company_layout(run_dir):
    run_scenario(ctx_for(run_dir, [R_001, R_002_MISSING, R_002_GAP, R_005, R_APP]), log=lambda *_: None)
    wb = openpyxl.load_workbook(run_dir / SPEC_FILE)
    assert wb.sheetnames == ["개정이력", "00. 목차", "01. 고객센터", "02. 앱 전체"]      # 기업 샘플처럼 시나리오 시트만

    ws = wb["01. 고객센터"]
    assert (ws["A1"].value, ws["B1"].value, ws["A2"].value, ws["B2"].value) == ("프로젝트명", "가상기획서", "시험대상 메뉴명", "고객센터")
    assert [ws[c].value for c in ("A4", "B4", "D4", "E4", "F4", "G4", "J4", "K4")] == \
        ["시험번호", "시험구분", "No", "시험절차", "예상결과", "시험데이터", "확인결과", "근거 요구사항"]
    assert [ws[c].value for c in ("A5", "B5", "C5", "G5", "H5", "I5")] == ["시나리오명", "DEPTH(1)", "DEPTH(2)", "계정", "입력값", "비고"]
    assert ws["A6"].value == "TC-QNA-001-01\n문의 목록 표시" and ws["A7"].value == "TC-QNA-001-01"
    assert (ws["D6"].value, ws["G6"].value, ws["I6"].value, ws["J6"].value, ws["K6"].value, ws["L6"].value) == \
        (1, "일반 사용자 / user1@example.com", "준비 단계", None, "-", "더미")
    assert ws["K7"].value == "REQ-QNA-001-01"
    assert ws.freeze_panes == "A6"

    toc = wb["00. 목차"]
    assert toc["A4"].value == "01. 고객센터" and toc["C4"].value == "문의 목록 (01)" and toc["F4"].value == 10101



def trace_rows(run_dir):
    """추적표.xlsx: 요구사항 ID → (판정, 근거 코드, 시나리오·단계, 비고)"""
    t = openpyxl.load_workbook(run_dir / TRACE_FILE)["추적표"]
    assert [c.value for c in t[1]][6:] == ["판정(③)", "근거 코드(③)", "시나리오·단계(④)", "비고"]
    return {r[0].value: tuple(c.value for c in r[6:10]) for r in t.iter_rows(min_row=2)}


def test_trace_table_is_a_separate_file(run_dir):
    run_scenario(ctx_for(run_dir, [R_001, R_002_MISSING, R_002_GAP, R_005, R_APP]), log=lambda *_: None)
    rows = trace_rows(run_dir)
    assert len(rows) == len(UNITS)                                  # 제약 단위까지 요구사항 전체
    assert rows["REQ-QNA-002-03"][3].startswith("사양서 대상 아님 (제약")
    assert rows["REQ-QNA-002-02"][2] == "TC-QNA-002-01 #2, TC-QNA-002-01 #3"
    assert rows["REQ-QNA-002-02"][0] == "③ 전"                      # ③을 아직 안 돌림


def test_trace_table_joins_judge_results_when_present(run_dir):
    run_scenario(ctx_for(run_dir, [R_001, R_002_MISSING, R_002_GAP, R_005, R_APP]), log=lambda *_: None)
    write_json(run_dir / "judgments.json", {"results": {"REQ-QNA-002-02": {
        "status": "불일치", "evidence": [{"file": "src/qna.js", "line": 8, "code": "x"}]}}, "items": {}, "extras": []})
    merge_scenarios(run_dir, log=lambda *_: None)
    rows = trace_rows(run_dir)
    assert rows["REQ-QNA-002-02"][:2] == ("불일치", "src/qna.js:8")
    assert rows["REQ-QNA-001-01"][0] == "-"                         # ③ 결과가 없는 단위
    spec = openpyxl.load_workbook(run_dir / SPEC_FILE)
    assert all("불일치" not in str(c.value) for ws in spec for row in ws.iter_rows() for c in row)   # 사양서에는 판정을 넣지 않는다


class UsageLLM(ScriptedLLM):
    """토큰 사용량을 같이 돌려주는 가짜 LLM."""

    def complete(self, system, messages, max_tokens):
        r = super().complete(system, messages, max_tokens)
        return LLMResult(r.text, r.stop_reason, {"input_tokens": 1000, "output_tokens": 500})


def test_gap_request_is_recorded_in_group_meta(run_dir):
    # 빠진 단위를 다시 요청한 호출도 묶음 메타의 호출별 기록 · 처리시간 · 예상 비용 합계에 들어간다
    ctx = ctx_for(run_dir, None)
    ctx.settings.model = "claude-sonnet-5"
    ctx.llm = UsageLLM([R_001, R_002_BAD, R_002_MISSING, R_002_GAP, R_005, R_APP])
    run_scenario(ctx, log=lambda *_: None)

    meta = read_json(run_dir / "scenario" / "QNA-002.meta.json")
    assert [c.get("gap", False) for c in meta["calls"]] == [False, False, True]   # 처음 요청 2번 + 다시 요청 1번
    assert meta["usage"]["input_tokens"] == 3000 == sum(c["usage"]["input_tokens"] for c in meta["calls"])
    assert meta["cost_usd"] == round(sum(c["cost_usd"] for c in meta["calls"]), 6) == 0.021
    assert meta["elapsed_sec"] == round(sum(c["elapsed_sec"] for c in meta["calls"]), 2)


def test_unit_still_missing_after_gap_is_reported(run_dir):
    missing_again = answer(sc("다시", [step("문의 작성 화면에 들어간다.", "제목과 내용 입력란이 표시된다.", [], setup=True)]))
    ctx = ctx_for(run_dir, [R_002_MISSING, missing_again])
    report = run_scenario(ctx, only={"QNA-002"}, log=lambda *_: None)
    assert report["group_status"]["QNA-002"] == "확인필요"
    assert [u["id"] for u in report["uncovered"]] == ["REQ-QNA-002-04"]
    assert report["summary"]["units_not_run"] == 4                 # 돌리지 않은 다른 묶음의 단위
    rows = {k: v[3] for k, v in trace_rows(run_dir).items()}
    assert rows["REQ-QNA-002-04"].startswith("사양서에 없음")
    assert rows["REQ-QNA-001-01"].startswith("아직 사양서를 만들지 않은 화면")   # 돌리지 않은 묶음은 따로 표시
    assert rows["REQ-QNA-002-01"] is None                                      # 사양서에 들어간 단위는 비고 칸이 비어 있음


def test_screens_option_picks_group_by_member_screen(run_dir):
    ctx = ctx_for(run_dir, [R_005])
    run_scenario(ctx, only={"QNA-006"}, log=lambda *_: None)      # 팝업 ID로 골라도 부모 묶음이 돈다
    assert (run_dir / "scenario" / "QNA-005.json").exists() and len(ctx.llm.calls) == 1


def test_dry_run_writes_prompts_only(run_dir):
    assert run_scenario(ctx_for(run_dir, None), log=lambda *_: None) == {}
    preview = run_dir / "prompts_preview" / "scenario_QNA-002.txt"
    assert preview.exists() and "REQ-QNA-002-04" in preview.read_text(encoding="utf-8")
    assert not (run_dir / "scenario").exists() and not (run_dir / SPEC_FILE).exists() and not (run_dir / TRACE_FILE).exists()


def test_excel_only_rebuilds_without_llm(run_dir):
    run_scenario(ctx_for(run_dir, [R_001, R_002_MISSING, R_002_GAP, R_005, R_APP]), log=lambda *_: None)
    (run_dir / SPEC_FILE).unlink()
    report = merge_scenarios(run_dir, project="다른 이름", log=lambda *_: None)
    assert report["spec_file"] == SPEC_FILE
    assert openpyxl.load_workbook(run_dir / SPEC_FILE)["01. 고객센터"]["B1"].value == "다른 이름"
    assert cli.main(["scenario", "--run", str(run_dir), "--excel-only"]) == 0

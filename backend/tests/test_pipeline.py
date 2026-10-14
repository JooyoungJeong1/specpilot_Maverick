"""API 키 없이 돌아가는 테스트 (① ② 검사, 후처리, 재시도, 합치기).

프롬프트 문서의 가상 예시(QNA 앱)를 정상 입력으로 쓴다. 실제 기획서 내용은 넣지 않는다.
"""
import copy
import json

import pytest
from pypdf import PdfWriter

from specpilot import schema
from specpilot.cli import _run_screens
from specpilot.config import ROOT, Settings
from specpilot.llm import JSONParseError, ScriptedLLM, parse_json
from specpilot.merge import merge
from specpilot.pdf_utils import detect_items
from specpilot.prompts import PromptSet
from specpilot.stages import (STATUS_DONE, STATUS_FAILED, STATUS_REJECTED, STATUS_REVIEW, RunContext,
                              run_app_profile, run_screen)
from tests.helpers import FakeTexts, example_input

EXAMPLES = ROOT / "prompts" / "examples"
APP = json.loads((EXAMPLES / "app_example.json").read_text(encoding="utf-8"))
SCREEN = json.loads((EXAMPLES / "screen_example.json").read_text(encoding="utf-8"))
SCREEN2 = json.loads((EXAMPLES / "screen_example_2.json").read_text(encoding="utf-8"))
TEXT1 = FakeTexts(example_input("5. 예시 1"))        # 예시 1의 입력 화면 글자 = QNA-002의 "원문"
TEXT2 = FakeTexts(example_input("6. 예시 2"))
QNA002_ITEMS = {f"Description {i}" for i in range(6)} | {"Action A", "Action B"}


def screen_of(profile, sid):
    return next(s for s in profile["screens"] if s["screen_id"] == sid)


@pytest.fixture
def ctx(tmp_path):
    pdf = tmp_path / "input.pdf"
    w = PdfWriter()
    for _ in range(9):
        w.add_blank_page(width=200, height=200)
    with open(pdf, "wb") as f:
        w.write(f)
    settings = Settings()
    settings.max_retries = 2

    def make(responses, texts=TEXT1):
        return RunContext(tmp_path, pdf, settings, PromptSet(settings.prompts_dir), ScriptedLLM(responses), _texts=texts)
    return make


# ---------- 프롬프트 ----------

def test_prompts_render_without_leftover_placeholders():
    ps = PromptSet(ROOT / "prompts")
    a = ps.render("app_profile")
    s = ps.render("screen_decompose", APP_PROFILE="{}", SCREEN_ID="LOGIN-001", SCREEN_PAGES="p.1, p.2")
    for r in (a, s):
        assert "{{" not in r.system + r.user_input
        assert r.user_input.startswith("# 입력")
    assert "LOGIN-001" in s.user_input and "LOGIN-001" not in s.system  # 화면마다 달라지는 값은 캐시 부분에 없어야 함
    assert "QNA-005" in s.system                                        # 예시 2가 들어감
    assert "같은 내용을 질문으로도" not in a.system + s.system            # 단위·질문 동시 생성 규칙은 뺐다


# ---------- 예시는 검사를 통과해야 한다 (quote가 예시 입력 글자에 그대로 있는지까지) ----------

def test_examples_are_valid():
    assert schema.errors(schema.validate_app_profile(APP)) == []
    issues = schema.validate_screen(SCREEN, "QNA-002", QNA002_ITEMS, texts=TEXT1)
    assert [i for i in issues if i.level != "fix"] == []
    issues = schema.validate_screen(SCREEN2, "QNA-005", texts=TEXT2)
    assert [i for i in issues if i.level != "fix"] == []


# ---------- 깨진 출력은 잡아야 한다 ----------

def test_missing_field_and_bad_values():
    bad = copy.deepcopy(SCREEN)
    del bad["units"][0]["then"]
    bad["units"][1]["kind"] = "기능"
    bad["units"][2]["key"] = "x3"
    issues = schema.validate_screen(bad, "QNA-002")
    msgs = [i.message for i in schema.errors(issues)]
    assert any("then" in m for m in msgs)
    assert any("kind" in m for m in msgs)
    assert any("key 형식" in i.message for i in issues if i.level == "warning")   # key 모양은 경고만


def test_duplicate_keys_and_missing_items_seen():
    bad = copy.deepcopy(SCREEN)
    bad["units"][1]["key"] = bad["units"][0]["key"]
    assert any("중복" in i.message for i in schema.errors(schema.validate_screen(bad, "QNA-002")))
    del bad["items_seen"]
    assert any("items_seen" in i.message for i in schema.errors(schema.validate_screen(bad, "QNA-002")))


# ---------- 원문 대조 ----------

def test_quote_check_exact_typo_fixed_and_invented():
    good = copy.deepcopy(SCREEN["units"][2])
    assert schema.check_quotes([good], TEXT1, None) == []
    fixed = copy.deepcopy(good)
    fixed["quote"] = fixed["quote"].replace("포커스", "포커쓰")                   # 한 글자를 바꿈 (오타를 고친 것과 같은 꼴)
    assert [i.level for i in schema.check_quotes([fixed], TEXT1, None)] == ["warning"]
    invented = copy.deepcopy(good)
    invented["quote"] = "제목 입력란 옆에 글자 수가 표시된다."                    # 원문에 없는 문장
    issues = schema.check_quotes([invented], TEXT1, None)
    assert [i.level for i in issues] == ["error"] and "원문에 없습니다" in issues[0].message
    assert [i.level for i in schema.check_quotes([invented], TEXT1, None, strict=False)] == ["warning"]
    from_image = copy.deepcopy(invented)
    from_image["source"] = ["화면 이미지"]                                      # 그림 글자는 대조가 부정확해 경고만
    assert [i.level for i in schema.check_quotes([from_image], TEXT1, None)] == ["warning"]
    weak = FakeTexts(example_input("5. 예시 1"), strong=False)                 # pdftotext 없이 읽었으면 경고만
    assert [i.level for i in schema.check_quotes([invented], weak, None)] == ["warning"]


def test_typo_in_prose_stays_in_quote_only():
    # 예시 2: 설명 문장의 "상셰"(오타)는 quote에 그대로, then은 바른 뜻, issue 없음
    u07 = next(u for u in SCREEN2["units"] if u["key"] == "u07")
    assert "상셰" in u07["quote"] and "상세" in u07["then"] and "오타" not in str(u07["issue"])
    assert schema.check_quotes([u07], TEXT2, None) == []


# ---------- 커버리지: 체크리스트 / items_seen / units·skipped ----------

def test_coverage_three_way():
    assert schema.check_coverage(SCREEN, QNA002_ITEMS, strict=True) == []   # Description 5는 skipped에 있음
    issues = schema.check_coverage(SCREEN, QNA002_ITEMS | {"Description 6"}, strict=True)
    assert issues and "Description 6" in issues[0].message

    obj = copy.deepcopy(SCREEN)
    obj["items_seen"].append("Description 7")                               # 모델이 봤다고 했는데 다루지 않음
    issues = schema.check_items_seen(obj, QNA002_ITEMS, True, "QNA-002")
    assert any(i.level == "error" and "Description 7" in i.message for i in issues)
    assert any(i.level == "warning" and "체크리스트에 없는" in i.message for i in issues)

    obj = copy.deepcopy(SCREEN)
    obj["items_seen"].remove("Action B")                                     # 다뤘지만 items_seen에는 안 적음
    issues = schema.check_items_seen(obj, QNA002_ITEMS, True, "QNA-002")
    assert [i.level for i in issues] == ["warning"]


def test_other_screen_sources_do_not_count_as_coverage():
    obj = {"units": [{"source": ["LOGIN-004 Description 3"]}, {"source": ["Description 1"]}], "skipped": []}
    assert schema.covered_items(obj, "LOGIN-001") == {"Description 1"}


def test_detect_items_uses_description_column():
    text = "\n".join([
        "                    0   로그인 화면 개요",
        "     1                 (이미지 마커)",
        "                    1   SNS 로그인",
        "     E  로그인",
        "                    A   Google 새창",
        "                    E   로그인 버튼",
    ])
    assert detect_items(text) == {"Description 0", "Description 1", "Action A", "Action E"}


def test_parse_json_with_fence_and_chatter():
    assert parse_json('설명입니다\n```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(JSONParseError):
        parse_json("JSON이 없음")


# ---------- 후처리: ID, 함의 거르기, 마커 표시 ----------

def test_assign_ids_maps_related_units():
    units, questions = schema.assign_ids(copy.deepcopy(SCREEN["units"]), copy.deepcopy(SCREEN["questions"]), "QNA-002")
    assert [u["id"] for u in units][:2] == ["REQ-QNA-002-01", "REQ-QNA-002-02"]
    assert list(units[0])[0] == "id" and units[0]["key"] == "u01"
    assert questions[0]["id"] == "Q-QNA-002-01" and questions[0]["related_units"] == ["REQ-QNA-002-03"]


def _ids(obj, scope):
    return schema.assign_ids(copy.deepcopy(obj["units"]), copy.deepcopy(obj["questions"]), scope)


def test_implied_gate_keeps_supported_and_demotes_weak():
    units, questions = _ids(SCREEN, "QNA-002")
    kept, qs, fixes = schema.gate_implied(units, questions, "QNA-002", TEXT1)
    assert len(kept) == len(units) and not fixes                     # 예시의 함의(u13)는 원문 2개가 실제로 있음

    units, questions = _ids(SCREEN, "QNA-002")
    units[-1]["quote"] = "문의가 저장되고"                              # 근거 원문이 하나뿐
    kept, qs, fixes = schema.gate_implied(units, questions, "QNA-002", TEXT1)
    assert len(kept) == len(units) - 1
    assert qs[-1]["id"] == "Q-QNA-002-03" and qs[-1]["draft_unit"]["id"] == "REQ-QNA-002-13"
    assert fixes[0].level == "fix" and "하나뿐" in fixes[0].message

    units, questions = _ids(SCREEN, "QNA-002")
    units[-1]["quote"] = "문의가 저장되고 / 목록 맨 위에 새 글 표시가 붙는다"   # 원문에 없는 근거
    kept, qs, fixes = schema.gate_implied(units, questions, "QNA-002", TEXT1)
    assert len(kept) == len(units) - 1 and "찾지 못함" in fixes[0].message


def test_low_confidence_implied_joins_existing_question():
    # v3.1 방식(확신 낮음 단위 + 같은 내용 질문)으로 나와도 한 곳(질문)에만 남긴다
    units, questions = _ids(SCREEN, "QNA-002")
    units[-1]["issue"] = "확신 낮음: 목록 정렬 기준이 없음"
    questions[0]["related_units"] = [units[-1]["id"]]
    kept, qs, fixes = schema.gate_implied(units, questions, "QNA-002", TEXT1)
    assert len(kept) == len(units) - 1 and len(qs) == len(questions)   # 새 질문을 만들지 않음
    assert qs[0]["draft_unit"]["id"] == units[-1]["id"] and qs[0]["related_units"] == []


def test_tag_missing_markers():
    units, _ = _ids(SCREEN, "QNA-002")
    fixes = schema.tag_missing_markers(units, {"Description 4", "Action B"}, "QNA-002")
    tagged = [u["id"] for u in units if "입력 점검" in str(u.get("issue"))]
    assert tagged == ["REQ-QNA-002-08", "REQ-QNA-002-12"] and len(fixes) == 2


def test_normalize_app_profile_assigns_missing_screen_ids():
    p = copy.deepcopy(APP)
    p["screens"][0]["screen_id"] = None
    fixes = schema.normalize_app_profile(p)
    assert p["screens"][0]["screen_id"] == "SCR-001" and p["screens"][0]["id_assigned"]
    assert fixes[0].level == "fix"


# ---------- 재시도와 합치기 ----------

def test_screen_retry_then_success(ctx):
    c = ctx(["이건 JSON이 아님", json.dumps(SCREEN, ensure_ascii=False)])
    meta = run_screen(c, screen_of(APP, "QNA-002"), APP)
    assert meta["status"] == STATUS_DONE and meta["attempts"] == 2
    assert meta["retry_reasons"][0]["attempt"] == 1 and "JSON" in meta["retry_reasons"][0]["errors"][0]
    # 두 번째 호출에는 첫 응답과 문제 목록이 붙어 있어야 한다
    second = c.llm.calls[1]["messages"]
    assert second[1]["role"] == "assistant" and "직전 출력에 아래 문제" in second[2]["content"]
    saved = json.loads((c.run_dir / "screens" / "QNA-002.json").read_text(encoding="utf-8"))
    assert saved["units"][0]["id"] == "REQ-QNA-002-01"


def test_invented_quote_triggers_retry(ctx):
    bad = copy.deepcopy(SCREEN)
    bad["units"][3]["quote"] = "내용 입력란 아래에 남은 글자 수가 표시된다."
    c = ctx([json.dumps(bad, ensure_ascii=False), json.dumps(SCREEN, ensure_ascii=False)])
    meta = run_screen(c, screen_of(APP, "QNA-002"), APP)
    assert meta["status"] == STATUS_DONE and meta["attempts"] == 2
    assert "원문에 없습니다" in meta["retry_reasons"][0]["errors"][0]


def test_screen_keeps_rejected_units_when_retries_run_out(ctx):
    bad = copy.deepcopy(SCREEN)
    bad["units"][0]["kind"] = "기능"
    c = ctx([json.dumps(bad, ensure_ascii=False)] * 3)
    meta = run_screen(c, screen_of(APP, "QNA-002"), APP)
    assert meta["status"] == STATUS_REVIEW and meta["attempts"] == 3
    saved = json.loads((c.run_dir / "screens" / "QNA-002.json").read_text(encoding="utf-8"))
    assert len(saved["units"]) == len(SCREEN["units"]) - 1
    assert saved["rejected"]["units"][0]["unit"]["key"] == "u01"           # 버리지 않고 남긴다
    assert "kind" in saved["rejected"]["units"][0]["errors"][0]


def test_screen_failed_when_never_json(ctx):
    c = ctx(["아니요"] * 3)
    meta = run_screen(c, screen_of(APP, "QNA-002"), APP)
    assert meta["status"] == STATUS_FAILED
    assert not (c.run_dir / "screens" / "QNA-002.json").exists()


def test_model_rejects_unreadable_screen(ctx):
    out = {"screen_id": "QNA-002", "reject_reason": "그림 아래쪽이 잘려 항목 대부분의 대상 요소를 찾을 수 없음",
           "items_seen": [], "units": [], "questions": [], "skipped": []}
    c = ctx([json.dumps(out, ensure_ascii=False)])
    meta = run_screen(c, screen_of(APP, "QNA-002"), APP)
    assert meta["status"] == STATUS_REJECTED and "잘려" in meta["reject_reason"]


def test_gate_rejected_screen_is_not_sent(ctx, capsys):
    c = ctx([])                                                               # 응답이 없으니 부르면 실패한다
    gate = {"screens": {"QNA-002": {"verdict": "반려", "reasons": ["그림에서 찾을 수 없는 설명 번호가 많습니다"]}}}
    _run_screens(c, APP, {"QNA-002"}, workers=1, gate=gate)
    meta = json.loads((c.run_dir / "screens" / "QNA-002.meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == STATUS_REJECTED and meta["rejected_by"].startswith("게이트")
    assert c.llm.calls == [] and "반려 (게이트)" in capsys.readouterr().out


def test_app_profile_keeps_going_when_only_an_app_unit_is_bad(ctx):
    corpus = FakeTexts(" ".join(u["quote"].replace(" / ", " ") for u in APP["units"]))   # 예시 단위의 근거만 있는 원문
    bad = copy.deepcopy(APP)
    bad["units"][1]["quote"] = "회원은 하루에 다섯 번까지 문의할 수 있다 / 문의는 상담원이 확인한다"   # 원문에 없는 근거
    c = ctx([json.dumps(bad, ensure_ascii=False)] * 3, texts=corpus)
    got = run_app_profile(c)                                               # 화면 목록은 멀쩡하므로 멈추지 않는다
    meta = json.loads((c.run_dir / "app_profile.meta.json").read_text(encoding="utf-8"))
    assert meta["status"] == STATUS_REVIEW and meta["attempts"] == 3
    assert [r["unit"]["key"] for r in got["rejected"]["units"]] == ["a02"]
    assert [u["id"] for u in got["units"]] == ["REQ-APP-01", "REQ-APP-02"]
    assert len(got["screens"]) == len(APP["screens"])


def test_app_profile_stops_when_screens_are_broken(ctx):
    from specpilot.stages import StageFailed
    bad = copy.deepcopy(APP)
    bad["screens"][0]["pages"] = [99]                                     # PDF에 없는 쪽
    c = ctx([json.dumps(bad, ensure_ascii=False)] * 3, texts=FakeTexts())
    with pytest.raises(StageFailed):
        run_app_profile(c)


def test_end_to_end_merge(ctx):
    c = ctx([json.dumps(APP, ensure_ascii=False), json.dumps(SCREEN, ensure_ascii=False),
             json.dumps({"screen_id": "QNA-003", "reject_reason": "글자가 깨져 읽을 수 없음", "items_seen": [],
                         "units": [], "questions": [], "skipped": []}, ensure_ascii=False)],
            texts=FakeTexts())                                                # ①의 가상 앱은 원문이 없어 대조를 건너뜀
    got = run_app_profile(c)
    assert [u["id"] for u in got["units"]] == ["REQ-APP-01", "REQ-APP-02", "REQ-APP-03"]
    run_screen(c, screen_of(got, "QNA-002"), got)
    run_screen(c, screen_of(got, "QNA-003"), got)
    report = merge(c.run_dir)
    req = json.loads((c.run_dir / "requirements.json").read_text(encoding="utf-8"))
    assert len(req["units"]) == len(APP["units"]) + len(SCREEN["units"])
    assert req["screen_status"]["QNA-002"]["status"] == STATUS_DONE
    assert req["rejected_screens"] == {"QNA-003": "글자가 깨져 읽을 수 없음"}
    assert req["questions"][0]["priority"] == "상"                           # 우선순위 상이 먼저
    # 나머지 6개 화면은 실행하지 않았으므로 결과 없음 오류, 반려는 오류가 아니라 경고
    assert report["summary"]["errors"] == len(APP["screens"]) - 2
    assert report["summary"]["screens_rejected"] == 1
    assert "units" not in req["app_profile"]

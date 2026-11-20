"""③ 근거 재확인(grounding.py), 비용 기록(cost.py), 판정 재사용(--reuse-from) 테스트.

API 키 필요 없음. 코드와 문구는 모두 지어낸 것이다 (실제 샘플 코드의 결함을 넣지 않는다).
"""
import json

import pytest

from specpilot import code_prep, cost, grounding
from specpilot.config import Settings
from specpilot.judge import judge_screen, merge_judgments, units_by_screen
from specpilot.llm import LLMResult, ScriptedLLM
from specpilot.prompts import PromptSet
from specpilot.stages import RunContext, write_json

CTRL = "src/main/java/demo/NoteController.java"
SVC = "src/main/java/demo/NoteService.java"
FORM = "src/main/resources/templates/note/form.html"
EDIT = "src/main/resources/templates/note/edit.html"

CONTROLLER = """package demo;
public class NoteController {
    @PostMapping("/notes")
    public String create(NoteForm form) {
        noteService.create(form);
        return "redirect:/notes";
    }

    @PostMapping("/notes/{id}")
    public String update(Long id, NoteForm form) {
        noteService.update(id, form);
        return "redirect:/notes/" + id;
    }

    @PostMapping("/notes/check")
    public boolean check(String title) {
        return true;
    }
}"""
SERVICE = """package demo;
public class NoteService {
    public void create(NoteForm form) {
        if (form.getTitle().isBlank()) throw new IllegalArgumentException("제목을 입력하세요");
    }

    public void update(Long id, NoteForm form) {
        repo.save(form);
    }
}"""
FORM_HTML = """<form th:action="@{/notes}" method="post">
<input name="title" maxlength="30">
<button>저장</button>
</form>"""
EDIT_HTML = """<form th:action="@{/notes/{id}(id=${id})}" method="post">
<button>수정</button>
</form>"""

REACH = {
    "methods": [
        {"name": "NoteController.create", "file": CTRL, "start": 3, "end": 7},
        {"name": "NoteController.update", "file": CTRL, "start": 9, "end": 13},
        {"name": "NoteController.check", "file": CTRL, "start": 15, "end": 18},
        {"name": "NoteService.create", "file": SVC, "start": 3, "end": 5},
        {"name": "NoteService.update", "file": SVC, "start": 7, "end": 9},
    ],
    "screens": {
        "NOTE-002": {"methods": ["NoteController.create", "NoteService.create"], "files": [CTRL, SVC, FORM]},
        "NOTE-004": {"methods": ["NoteController.update", "NoteService.update"], "files": [CTRL, SVC, EDIT]},
    },
    "unused": [{"file": CTRL, "start": 15, "end": 18, "label": "POST /notes/check(NoteController.check): 미사용 후보"}],
}


def unit(i, **kw):
    base = {"id": f"REQ-NOTE-002-{i:02d}", "screen_id": "NOTE-002", "source": [f"Action {chr(64 + i)}"],
            "quote": "q", "origin": "명시", "reason": None, "kind": "처리", "given": None,
            "when": "저장을 누른다", "conditions": [], "then": f"결과 {i}",
            "exact": {"message": None, "values": [], "target": None}, "issue": None}
    base.update(kw)
    return base


UNITS = [
    unit(1, then="입력값이 저장된다"),
    unit(2, then="제목 중복을 확인한다"),
    unit(3, kind="검증", conditions=["제목이 비어 있음", "제목이 30자를 넘음"], then="오류 문구가 표시된다"),
    unit(4, kind="표시", then="안내 문구가 표시된다"),
]


@pytest.fixture
def code_root(tmp_path):
    root = tmp_path / "code"
    for rel, text in [(CTRL, CONTROLLER), (SVC, SERVICE), (FORM, FORM_HTML), (EDIT, EDIT_HTML),
                      ("src/main/resources/static/js/vendor.min.js", "/* lib */")]:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def make_run(tmp_path, name="run"):
    rd = tmp_path / name
    write_json(rd / "requirements.json", {
        "app_profile": {"screens": [{"screen_id": "NOTE-002", "name": "노트 등록", "pages": [1]}]},
        "units": UNITS, "questions": []})
    return rd


ANSWER = {
    "screen_id": "NOTE-002",
    "results": [
        # 등록 단위인데 수정 메서드를 근거로 댐 → 다른 화면의 처리 코드 (판정 유지, 사람 확인)
        {"unit_id": "REQ-NOTE-002-01", "status": "구현", "mismatch": [], "note": None, "split_issue": None,
         "evidence": [{"file": SVC, "line": 8, "code": "repo.save(form);"}]},
        # 미사용 경로만 근거 → 확인필요로 내림
        {"unit_id": "REQ-NOTE-002-02", "status": "구현", "mismatch": [], "note": None, "split_issue": None,
         "evidence": [{"file": CTRL, "line": 16, "code": "public boolean check(String title) {"}]},
        # 조건 2개 중 1번만 근거 + 없는 파일을 설명에 적음
        {"unit_id": "REQ-NOTE-002-03", "status": "구현", "mismatch": [], "split_issue": None,
         "note": "SocialLoginService.java 42줄과 NoteService.validate에서도 검사",
         "evidence": [{"file": SVC, "line": 4, "code": 'if (form.getTitle().isBlank()) throw new IllegalArgumentException("제목을 입력하세요");',
                       "for": [1]}]},
        {"unit_id": "REQ-NOTE-002-04", "status": "확인필요", "mismatch": [], "evidence": [], "split_issue": None,
         "note": "실행해야 알 수 있음"},
    ],
    "extras": [
        {"file": FORM, "line": 2, "code": '<input name="title" maxlength="30">', "description": "제목 30자 제한"},
        {"file": "src/main/java/demo/SocialLoginService.java", "line": 42, "code": "login()", "description": "지어낸 기능"},
    ],
}


class UsageLLM(ScriptedLLM):
    """토큰 사용량을 같이 돌려주는 가짜 LLM."""

    def complete(self, system, messages, max_tokens):
        r = super().complete(system, messages, max_tokens)
        return LLMResult(r.text, r.stop_reason, {"input_tokens": 1000, "output_tokens": 500, "thinking_tokens": 100,
                                                 "cache_creation_input_tokens": 20000, "cache_read_input_tokens": 0})


def ctx_for(run_dir, llm):
    s = Settings()
    s.max_retries = 0
    s.model = "claude-sonnet-5"
    return RunContext(run_dir, run_dir / "input.pdf", s, PromptSet(s.prompts_dir), llm)


# ---------- 하나씩 ----------

def test_unknown_refs(code_root):
    idx = grounding.SymbolIndex(code_prep.load_codebase(code_root))
    found = grounding.unknown_refs(idx, "SocialLoginService.java 42줄, NoteService.validate, NoteService.create, "
                                        "form.html 2줄, vendor.min.js, Vue.js, Model.addAttribute, AuthService.login")
    assert "없는 파일 SocialLoginService.java" in found
    assert "NoteService에 없는 메서드 validate" in found
    assert "없는 클래스 AuthService" in found
    assert not any("form.html" in x or "vendor.min.js" in x or "Vue" in x or "Model" in x or "create" in x for x in found)


def test_reach_method_and_unused():
    r = grounding.Reach(REACH)
    assert r.method_at(SVC, 8)["name"] == "NoteService.update"
    assert r.method_at(SVC, 6) is None                                # 메서드 사이 빈 줄
    reasons, all_unused = grounding.check_reach(r, "NOTE-002", [{"file": SVC, "line": 8, "code": "x"}])
    assert not all_unused and "NoteService.update" in reasons[0] and "NOTE-004" in reasons[0]
    reasons, all_unused = grounding.check_reach(r, "NOTE-002", [{"file": CTRL, "line": 16, "code": "x"}])
    assert all_unused and reasons[0].startswith("미사용")
    assert grounding.check_reach(r, "NOTE-002", [{"file": SVC, "line": 4, "code": "x"}]) == ([], False)
    assert grounding.check_reach(grounding.Reach(None), "NOTE-002", [{"file": CTRL, "line": 16}]) == ([], False)


def test_condition_gaps():
    u = UNITS[2]
    assert grounding.condition_gaps(u, {"status": "구현", "evidence": [{"for": [1]}]}) == [2]
    assert grounding.condition_gaps(u, {"status": "구현", "evidence": [{"for": [1, 2]}]}) == []
    assert grounding.condition_gaps(u, {"status": "구현", "evidence": [{"for": "조건 1"}, {"for": 2}]}) == []
    assert grounding.condition_gaps(u, {"status": "불일치", "evidence": []}) == []


def test_cost_estimate(monkeypatch):
    monkeypatch.delenv("SPECPILOT_PRICE", raising=False)
    assert cost.estimate("claude-sonnet-5", {"input_tokens": 1_000_000}) == 2.0
    assert cost.estimate("claude-sonnet-5-5", {"cache_read_input_tokens": 1_000_000}) == 0.1
    assert cost.estimate("claude-haiku-5-5", {"input_tokens": 1_000_000}) == 0.5            # 10만 넘으면 비싼 가격
    assert cost.estimate("claude-haiku-5-5", {"input_tokens": 50_000, "output_tokens": 1000}) == 0.0055
    assert cost.estimate("unknown-model", {"input_tokens": 10}) is None
    monkeypatch.setenv("SPECPILOT_PRICE", "1,2,3,4")
    assert cost.estimate("unknown-model", {"output_tokens": 1_000_000}) == 2.0


# ---------- 판정 한 화면 전체 ----------

def test_judge_screen_rechecks_and_reports(tmp_path, code_root):
    cb = code_prep.load_codebase(code_root)
    rd = make_run(tmp_path)
    us = units_by_screen(json.loads((rd / "requirements.json").read_text(encoding="utf-8")))["NOTE-002"]
    c = ctx_for(rd, UsageLLM([json.dumps(ANSWER, ensure_ascii=False)]))
    meta = judge_screen(c, cb, "NOTE-002", us, None, reach=grounding.Reach(REACH))
    assert meta["unused_evidence"] == 1 and meta["reach_other_screen"] == 1 and meta["condition_gaps"] == 1
    assert meta["unknown_refs"] == 1 and meta["extras_unverified"] == 1
    assert meta["elapsed_sec"] >= 0 and meta["calls"][0]["usage"]["input_tokens"] == 1000
    assert meta["cost_usd"] == pytest.approx((1000 * 2 + 500 * 10 + 20000 * 2.5) / 1e6)
    assert len(meta["input_hash"]) == 16

    saved = {r["unit_id"]: r for r in json.loads((rd / "judge/NOTE-002.json").read_text(encoding="utf-8"))["results"]}
    r1, r2, r3, r4 = (saved[f"REQ-NOTE-002-0{i}"] for i in range(1, 5))
    assert r1["status"] == "구현" and "NOTE-004" in r1["review"][0]                       # 판정은 유지
    assert r2["status"] == "확인필요" and r2["original_status"] == "구현" and grounding.TAG_UNUSED in r2["note"]
    assert r2["evidence_ok"]                                                               # 근거 줄 자체는 맞다
    assert r3["condition_gaps"] == [2] and any("30자" in x for x in r3["review"])
    assert any("SocialLoginService.java" in x for x in r3["review"]) and any("validate" in x for x in r3["review"])
    assert r4["review"][0].startswith("AI가 코드만으로 판단하지 못함")
    ex = json.loads((rd / "judge/NOTE-002.json").read_text(encoding="utf-8"))["extras"]
    assert ex[0]["evidence_ok"] and not ex[1]["evidence_ok"]

    report = merge_judgments(rd)
    s = report["summary"]
    assert s["needs_review"] == 4 and s["unused_evidence"] == 1 and s["extras_unverified"] == 1
    assert s["usage"]["calls"] == 1 and s["usage"]["cost_usd"] == pytest.approx(meta["cost_usd"])
    assert {x["unit_id"] for x in report["review"]} == {u["id"] for u in UNITS}
    md = (rd / "judge_review.md").read_text(encoding="utf-8")
    assert "REQ-NOTE-002-02" in md and "확인필요 (원래 구현)" in md and "예상 $" in md


def test_reuse_from_previous_run_skips_llm(tmp_path, code_root):
    cb = code_prep.load_codebase(code_root)
    reach = grounding.Reach(REACH)
    first = make_run(tmp_path, "first")
    us = units_by_screen(json.loads((first / "requirements.json").read_text(encoding="utf-8")))["NOTE-002"]
    m1 = judge_screen(ctx_for(first, UsageLLM([json.dumps(ANSWER, ensure_ascii=False)])), cb, "NOTE-002", us, None, reach=reach)

    second = make_run(tmp_path, "second")
    c = ctx_for(second, ScriptedLLM([]))                     # 부르면 "준비된 응답이 더 없습니다"로 실패한다
    m2 = judge_screen(c, cb, "NOTE-002", us, None, reach=reach, reuse_dir=first)
    assert c.llm.calls == [] and m2["reused_from"] and m2["cost_usd"] == 0
    assert m2["reused_usage"]["cost_usd"] == m1["cost_usd"] and m2["input_hash"] == m1["input_hash"]
    a = json.loads((first / "judge/NOTE-002.json").read_text(encoding="utf-8"))
    b = json.loads((second / "judge/NOTE-002.json").read_text(encoding="utf-8"))
    assert a == b
    t = merge_judgments(second)["usage"]["total"]
    assert t["screens_reused"] == 1 and t["cost_usd"] == 0 and t["saved_cost_usd"] == pytest.approx(m1["cost_usd"])

    # 단위가 바뀌면 해시가 달라져 다시 부른다
    changed = [dict(us[0], then="바뀐 결과")] + us[1:]
    c3 = ctx_for(make_run(tmp_path, "third"), ScriptedLLM([json.dumps(ANSWER, ensure_ascii=False)]))
    m3 = judge_screen(c3, cb, "NOTE-002", changed, None, reach=reach, reuse_dir=first)
    assert len(c3.llm.calls) == 1 and not m3.get("reused_from")


def test_bundle_adds_reached_files(code_root):
    from specpilot.judge import bundle_for
    cb = code_prep.load_codebase(code_root)
    files = bundle_for("NOTE-002", UNITS, cb, {"mapping": [{"screen_id": "NOTE-002", "files": [FORM]}], "common_files": []},
                       grounding.Reach(REACH))
    assert files == sorted([CTRL, SVC, FORM])


def test_app_units_skip_other_screen_check(code_root):
    cb = code_prep.load_codebase(code_root)
    app = dict(UNITS[0], id="REQ-APP-01", screen_id="APP")
    res = {"REQ-APP-01": {"unit_id": "REQ-APP-01", "status": "구현", "evidence_ok": True,
                          "evidence": [{"file": SVC, "line": 8, "code": "repo.save(form);"}]}}
    grounding.recheck(cb, grounding.Reach(REACH), "NOTE-002", [app], res)
    assert res["REQ-APP-01"]["review"] == [] and res["REQ-APP-01"]["status"] == "구현"

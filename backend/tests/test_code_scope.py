"""③ 화면별 코드 묶음을 프로그램이 고르는지 (code_scope.py). LLM을 부르지 않는다. 코드는 지어낸 것이다."""
import json

import pytest

from specpilot import code_prep, code_scope
from specpilot.config import Settings
from specpilot.judge import build_code_map
from specpilot.llm import ScriptedLLM
from specpilot.prompts import PromptSet
from specpilot.stages import RunContext, write_json

J = "src/main/java/demo/"
T = "src/main/resources/templates/"
S = "src/main/resources/static/"
FILES = {
    J + "web/NoteController.java": """package demo.web;
import demo.service.NoteService;
public class NoteController {
    private final NoteService noteService;
    public String form() { return "note/form"; }
    public String save(NoteForm form) { noteService.create(form); return "redirect:/notes"; }
}""",
    J + "web/NoteForm.java": "public class NoteForm { String title; }",
    J + "service/NoteService.java": """public class NoteService {
    private final NoteRepository repo;
    private final Notifier notifier;
    public void create(NoteForm f) { if (f.title.isBlank()) throw new IllegalArgumentException("제목을 입력해 주세요"); }
}""",
    J + "service/Notifier.java": "public interface Notifier { void send(); }",
    J + "service/MailNotifier.java": "public class MailNotifier implements Notifier { public void send() {} }",
    J + "repo/NoteRepository.java": "public interface NoteRepository extends JpaRepository<Note, Long> {}",
    J + "repo/Note.java": "public class Note {}",
    J + "web/OtherController.java": """public class OtherController {
    public String page() { return "other/page"; }
}""",
    J + "config/SecurityConfig.java": "@Configuration\npublic class SecurityConfig { SecurityFilterChain chain() { return null; } }",
    "src/main/resources/application.yml": "server:\n  port: 8080",
    T + "note/form.html": """<html layout:decorate="~{layout/base}">
<script th:src="@{/js/note.js}"></script>
<h2>노트 작성하기</h2>
<form th:action="@{/notes}"><button>저장</button></form>
</html>""",
    T + "layout/base.html": '<link rel="stylesheet" th:href="@{/css/site.css}">',
    T + "other/page.html": "<h2>다른 화면</h2>",
    S + "js/note.js": "document.querySelector('form');",
    S + "css/site.css": "body { margin: 0; }",
}


@pytest.fixture
def cb(tmp_path):
    for rel, text in FILES.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return code_prep.load_codebase(tmp_path)


def req(units, screens=None):
    screens = screens or [{"screen_id": "NOTE-001", "name": "노트 작성하기", "depth": "노트", "type": "화면"}]
    return {"app_profile": {"screens": screens}, "units": units, "questions": []}


def unit(sid, msg=None):
    return {"id": f"REQ-{sid}-01", "screen_id": sid, "exact": {"message": msg, "values": [], "target": None}}


def test_follows_references_from_message_without_llm(cb):
    units = {"NOTE-001": [unit("NOTE-001", "제목을 입력해 주세요")]}
    m = code_scope.select(cb, req(units["NOTE-001"]), units)
    files = set(m["mapping"][0]["files"])
    why = m["mapping"][0]["why"]
    # 문구는 서비스에만 있다 → 쓰는 컨트롤러로 올라가 → 반환하는 템플릿 → JS·레이아웃 → 레이아웃의 CSS
    assert why[J + "service/NoteService.java"].startswith("문구 검색")
    assert why[J + "web/NoteController.java"].startswith("사용처")
    assert {T + "note/form.html", S + "js/note.js", T + "layout/base.html", S + "css/site.css"} <= files
    assert {J + "repo/NoteRepository.java", J + "service/Notifier.java", J + "service/MailNotifier.java", J + "web/NoteForm.java"} <= files
    assert J + "web/OtherController.java" not in files and T + "other/page.html" not in files
    assert m["common_files"] == sorted([J + "config/SecurityConfig.java", "src/main/resources/application.yml"])
    assert m["source"] == "program" and m["unmapped_screens"] == []


def test_screen_name_and_popup_parent(cb):
    screens = [{"screen_id": "NOTE-001", "name": "노트 작성하기", "depth": "노트", "type": "화면"},
               {"screen_id": "NOTE-002", "name": "노트 작성하기(취소)", "depth": "노트", "type": "팝업"},
               {"screen_id": "NOTE-003", "name": "취소 확인", "depth": "노트", "type": "팝업"}]
    units = {"NOTE-001": [unit("NOTE-001")], "NOTE-002": [unit("NOTE-002", "작성을 취소하시겠습니까?")],
             "NOTE-003": [unit("NOTE-003")]}
    m = {x["screen_id"]: x for x in code_scope.select(cb, req([], screens), units)["mapping"]}
    assert m["NOTE-001"]["why"][T + "note/form.html"].startswith("문구 검색: 화면 이름")
    assert T + "note/form.html" in m["NOTE-002"]["files"]          # 팝업 코드가 없어도 부모 화면 템플릿은 들어간다
    assert m["NOTE-003"]["why"][T + "note/form.html"] == "부모 화면 NOTE-001"     # 같은 depth의 앞 화면
    assert code_scope.parent_of(screens[1], screens) == "NOTE-001"


def test_token_limit_drops_far_references_first(cb):
    units = {"NOTE-001": [unit("NOTE-001", "제목을 입력해 주세요")]}
    common = cb.tokens(code_scope.common_files(cb))
    seeds = [J + "service/NoteService.java", T + "note/form.html"]       # 단위 문구, 화면 이름
    m = code_scope.select(cb, req(units["NOTE-001"]), units,
                          token_limit=common + cb.tokens([seeds[0]]) + cb.tokens([seeds[1]]) + 1)
    assert m["mapping"][0]["files"] == sorted(seeds)                       # 씨앗은 남김
    assert len(m["dropped_over_limit"]["NOTE-001"]) >= 8


def test_build_code_map_calls_no_llm(cb, tmp_path):
    rd = tmp_path / "run"
    units = [unit("NOTE-001", "제목을 입력해 주세요")]
    write_json(rd / "requirements.json", req(units))
    s = Settings()
    ctx = RunContext(rd, rd / "input.pdf", s, PromptSet(s.prompts_dir), ScriptedLLM([]))
    cmap = build_code_map(ctx, cb, req(units), {"NOTE-001": units})
    assert ctx.llm.calls == [] and cmap["mapping"][0]["screen_id"] == "NOTE-001"
    saved = json.loads((rd / "judge/code_map.json").read_text(encoding="utf-8"))
    assert saved["source"] == "program"
    saved["mapping"][0]["files"] = [T + "note/form.html"]               # 사람이 고친 대응표는 그대로 쓴다
    write_json(rd / "judge/code_map.json", saved)
    assert build_code_map(ctx, cb, req(units), {"NOTE-001": units})["mapping"][0]["files"] == [T + "note/form.html"]

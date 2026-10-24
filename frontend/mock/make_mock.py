"""가짜 결과 폴더(mock/qna-example/)를 만든다. 커밋해도 되는 가상 앱(QNA) 데이터만 쓴다.

backend/prompts/examples/의 예시(app_example, screen_example, screen_example_2, judge_example)를 바탕으로
①② 결과 파일과 ③ 화면별 판정을 임시 실행 폴더에 쓰고, 합치기는 백엔드 함수를 그대로 부른다.
그래서 requirements.json, judgments.json, judge_report.json은 실제 실행과 같은 형식·같은 집계 규칙이다.
  - ID 붙이기, 근거가 약한 함의를 질문으로 옮기기: schema.assign_ids, schema.gate_implied
  - 합치기: merge.merge, judge.merge_judgments (부분구현 집계 포함)
  - 근거 줄 대조, 띄어쓰기 완화: code_prep.verify_evidence, judge.relax_spacing (mock/code/ 기준)

판정·근거 코드는 모두 지어낸 것이다. 실제 결과처럼 쓰지 않는다.

실행 (저장소 폴더에서, API 키·pypdf 필요 없음):
    python frontend/mock/make_mock.py
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
BACKEND = REPO / "backend"
EXAMPLES = BACKEND / "prompts" / "examples"
OUT = HERE / "qna-example"
CODE_DIR = HERE / "code"          # 가짜 코드 (코드 앞뒤 보기용, 모든 mock 실행이 같이 씀)

# 합치기 함수만 쓰므로 PDF 라이브러리는 필요 없다. 설치돼 있지 않으면 빈 모듈로 대신한다.
try:
    import pypdf  # noqa: F401
except ImportError:
    sys.modules["pypdf"] = types.SimpleNamespace(PdfReader=None, PdfWriter=None)
sys.path.insert(0, str(BACKEND))

from specpilot import code_prep, judge, merge, schema  # noqa: E402
from specpilot.stages import write_json  # noqa: E402


def load(name: str) -> dict:
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def unit(key, sid, source, quote, kind, when, then, *, origin="명시", reason=None, given=None,
         conditions=(), message=None, values=(), target=None, issue=None):
    return {"key": key, "screen_id": sid, "source": list(source), "quote": quote, "origin": origin,
            "reason": reason, "kind": kind, "given": given, "when": when, "conditions": list(conditions),
            "then": then, "exact": {"message": message, "values": list(values), "target": target},
            "issue": issue, "ref_hint": None}


# ---------- 가짜 코드 (근거 줄 대조에 쓴다) ----------

MOCK_HEADER = "가상 문의 앱 (mock). 실제 코드가 아니다."
CODE = {
    "src/main/java/demo/config/SecurityConfig.java": f"""package demo.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;

// {MOCK_HEADER}
@Configuration
public class SecurityConfig {{

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {{
        http.authorizeHttpRequests(auth -> auth
                .requestMatchers("/login", "/signup", "/css/**", "/js/**").permitAll()
                .requestMatchers("/qna", "/qna/new").authenticated()
                .anyRequest().permitAll())
            .formLogin(form -> form
                .loginPage("/login")
                .usernameParameter("email")
                .defaultSuccessUrl("/qna")
                .failureUrl("/login?error"));
        return http.build();
    }}
}}
""",
    "src/main/java/demo/controller/MemberController.java": f"""package demo.controller;

import demo.service.MemberService;
import org.springframework.stereotype.Controller;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;

// {MOCK_HEADER}
@Controller
public class MemberController {{

    private final MemberService memberService;

    public MemberController(MemberService memberService) {{
        this.memberService = memberService;
    }}

    @GetMapping("/login")
    public String loginForm() {{
        return "member/login";
    }}

    @GetMapping("/signup")
    public String signupForm() {{
        return "member/signup";
    }}

    @PostMapping("/signup")
    public String signup(SignupForm form) {{
        memberService.join(form);
        return "redirect:/";
    }}
}}
""",
    "src/main/java/demo/controller/QnaController.java": f"""package demo.controller;

import demo.service.QnaService;
import java.security.Principal;
import org.springframework.stereotype.Controller;
import org.springframework.ui.Model;
import org.springframework.web.bind.annotation.*;

// {MOCK_HEADER}
@Controller
@RequestMapping("/qna")
public class QnaController {{

    private final QnaService qnaService;

    public QnaController(QnaService qnaService) {{
        this.qnaService = qnaService;
    }}

    @GetMapping
    public String list(Model model, Principal principal) {{
        model.addAttribute("items", qnaService.visibleTo(principal.getName()));
        return "qna/list";
    }}

    @GetMapping("/new")
    public String writeForm() {{
        return "qna/write";
    }}

    @PostMapping
    public String create(QnaForm form, Principal principal) {{
        qnaService.create(form, principal.getName());
        return "redirect:/qna";
    }}

    @GetMapping("/{{id}}")
    public String detail(@PathVariable Long id, Model model) {{
        model.addAttribute("qna", qnaService.get(id));
        return "qna/detail";
    }}

    @PostMapping("/{{id}}/delete")
    public String delete(@PathVariable Long id) {{
        qnaService.delete(id);
        return "redirect:/qna";
    }}
}}
""",
    "src/main/resources/templates/member/login.html": f"""<!DOCTYPE html>
<!-- {MOCK_HEADER} -->
<html xmlns:th="http://www.thymeleaf.org">
<head>
  <title>로그인</title>
  <script src="/js/member.js" defer></script>
</head>
<body>
<form id="loginForm" method="post" action="/login">
  <input type="email" id="email" name="email" placeholder="이메일">
  <input type="password" id="password" name="password" placeholder="비밀번호">
  <p class="error" th:if="${{param.error}}">이메일 또는 비밀번호를 확인해주세요.</p>
  <button type="submit" id="loginBtn">로그인</button>
</form>
<a href="/signup">회원가입</a>
</body>
</html>
""",
    "src/main/resources/templates/member/signup.html": f"""<!DOCTYPE html>
<!-- {MOCK_HEADER} -->
<html xmlns:th="http://www.thymeleaf.org">
<head>
  <title>회원가입</title>
  <script src="/js/member.js" defer></script>
</head>
<body>
<form id="signupForm" method="post" action="/signup">
  <input type="email" id="email" name="email" placeholder="이메일">
  <p class="error" id="emailError"></p>
  <input type="password" id="password" name="password" placeholder="비밀번호">
  <p class="error" id="passwordError"></p>
  <input type="password" id="passwordConfirm" name="passwordConfirm" placeholder="비밀번호 확인">
  <button type="submit" id="joinBtn">가입하기</button>
</form>
</body>
</html>
""",
    "src/main/resources/templates/qna/list.html": f"""<!DOCTYPE html>
<!-- {MOCK_HEADER} -->
<html xmlns:th="http://www.thymeleaf.org">
<body>
<header th:replace="~{{fragments/header :: header}}"></header>
<a href="/qna/new" class="btn">문의하기</a>
<table>
  <tr th:each="q : ${{items}}">
    <td><a th:href="@{{/qna/{{id}}(id=${{q.id}})}}" th:text="${{q.title}}">제목</a></td>
    <td th:text="${{q.createdAt}}">작성일</td>
  </tr>
</table>
</body>
</html>
""",
    "src/main/resources/templates/qna/write.html": f"""<!DOCTYPE html>
<!-- {MOCK_HEADER} -->
<html xmlns:th="http://www.thymeleaf.org">
<body>
<header th:replace="~{{fragments/header :: header}}"></header>
<form id="qnaForm" method="post" action="/qna">
  <select id="type" name="type">
    <option value="">문의 유형</option>
    <option value="account">계정</option>
    <option value="etc">기타</option>
  </select>
  <input type="text" id="title" name="title" maxlength="30" placeholder="제목">
  <p class="error" id="titleError"></p>
  <textarea id="content" name="content" placeholder="내용"></textarea>
  <p class="error" id="contentError"></p>
  <button type="submit" id="submitBtn">등록</button>
</form>
<script src="/js/qna.js"></script>
</body>
</html>
""",
    "src/main/resources/templates/qna/detail.html": f"""<!DOCTYPE html>
<!-- {MOCK_HEADER} -->
<html xmlns:th="http://www.thymeleaf.org">
<body>
<header th:replace="~{{fragments/header :: header}}"></header>
<h1 th:text="${{qna.title}}">제목</h1>
<p th:text="${{qna.createdAt}}">작성일</p>
<div th:text="${{qna.content}}">내용</div>
<div th:if="${{qna.answer}}" th:text="${{qna.answer}}">답변</div>
<a th:href="@{{/qna/{{id}}/answer(id=${{qna.id}})}}" class="btn">답변하기</a>
<a th:href="@{{/qna/{{id}}/edit(id=${{qna.id}})}}" class="btn">수정하기</a>
</body>
</html>
""",
    "src/main/resources/templates/qna/delete.html": f"""<!-- {MOCK_HEADER} -->
<div class="popup" id="deletePopup">
  <p>문의를 삭제하시겠습니까?</p>
  <form method="post" th:action="@{{/qna/{{id}}/delete(id=${{qna.id}})}}">
    <button type="submit">예</button>
  </form>
  <button type="button" onclick="document.getElementById('deletePopup').hidden = true">아니오</button>
</div>
""",
    "src/main/resources/static/js/member.js": f"""// {MOCK_HEADER}
const email = document.getElementById("email");
const password = document.getElementById("password");

function showError(input, message) {{
  const box = document.getElementById(input.id + "Error");
  if (box) box.textContent = message;
}}

email?.addEventListener("blur", () => {{
  if (!/^[^@\\s]+@[^@\\s]+$/.test(email.value)) showError(email, "올바른 이메일 형식이 아닙니다.");
}});

password?.addEventListener("blur", () => {{
  if (password.value.length < 8) showError(password, "비밀번호는 8자 이상 입력해 주세요.");
}});
""",
    "src/main/resources/static/js/qna.js": f"""// {MOCK_HEADER}
const title = document.getElementById("title");
const content = document.getElementById("content");
const type = document.getElementById("type");

function showError(input, message) {{
  document.getElementById(input.id + "Error").textContent = message;
}}

title.addEventListener("blur", () => {{
  if (!title.value.trim()) showError(title, "제목을 입력하세요");
}});

content.addEventListener("blur", () => {{
  if (content.value.length < 10) showError(content, "내용을 10자 이상 입력해주세요.");
}});

type.addEventListener("change", () => type.classList.add("selected"));

function saveDraft() {{
  localStorage.setItem("qnaDraft", JSON.stringify({{ title: title.value, content: content.value }}));
}}
setInterval(saveDraft, 30000);
""",
    "src/main/resources/static/css/qna.css": f"""/* {MOCK_HEADER} */
select {{ border: 1px solid #ccc; }}
select.selected {{ background: #eee; }}
""",
}


def ev(path: str, needle: str, shift: int = 0) -> dict:
    """그 파일에서 needle이 처음 나오는 줄을 근거로 댄다. shift를 주면 일부러 틀린 줄(근거 불일치)을 댄다."""
    if path not in CODE:                       # 없는 파일을 대는 경우 (근거 불일치)
        return {"file": path, "line": 1, "code": needle}
    lines = CODE[path].splitlines()
    n = next(i for i, line in enumerate(lines, 1) if needle in line)
    return {"file": path, "line": n + shift, "code": lines[n - 1].strip()}


SEC = "src/main/java/demo/config/SecurityConfig.java"
MEMC = "src/main/java/demo/controller/MemberController.java"
QNAC = "src/main/java/demo/controller/QnaController.java"
LOGIN = "src/main/resources/templates/member/login.html"
SIGNUP = "src/main/resources/templates/member/signup.html"
LIST = "src/main/resources/templates/qna/list.html"
WRITE = "src/main/resources/templates/qna/write.html"
DETAIL = "src/main/resources/templates/qna/detail.html"
DELETE = "src/main/resources/templates/qna/delete.html"
MEMJS = "src/main/resources/static/js/member.js"
QNAJS = "src/main/resources/static/js/qna.js"
QNACSS = "src/main/resources/static/css/qna.css"


# ---------- ② 화면별 결과 (LLM 응답 모양, key만 있음) ----------

def screens() -> dict[str, dict]:
    out = {}
    out["MEM-001"] = {
        "screen_id": "MEM-001", "reject_reason": None,
        "items_seen": ["Description 0", "Description 1", "Description 2", "Action E", "Action F"],
        "units": [
            unit("u01", "MEM-001", ["Description 0"], "이메일, 비밀번호 입력란과 로그인 버튼이 있다.", "표시",
                 "로그인 화면에 들어간다", "이메일, 비밀번호 입력란과 로그인 버튼이 표시된다",
                 values=["이메일", "비밀번호", "로그인"]),
            unit("u02", "MEM-001", ["Description 2"], "회원가입 시 설정한 이메일(ID)와 비밀번호로 로그인한다", "처리",
                 "이메일과 비밀번호를 입력하고 로그인 버튼을 누른다", "로그인된다",
                 conditions=["가입된 이메일과 비밀번호"], issue="로그인 성공 뒤 이동하는 화면이 설계서에 없음"),
            unit("u03", "MEM-001", ["Action E"], "* error-msg: 이메일 또는 비밀번호가 올바르지 않습니다.", "실패",
                 "로그인 버튼을 누른다", "로그인 실패 안내 문구가 표시된다",
                 conditions=["이메일 또는 비밀번호가 틀림"], message="이메일 또는 비밀번호가 올바르지 않습니다."),
            unit("u04", "MEM-001", ["Action F"], "회원가입: 회원가입 화면(MEM-002)으로 이동한다.", "이동",
                 "회원가입 링크를 누른다", "회원가입 화면으로 이동한다", target="MEM-002"),
            unit("u05", "MEM-001", ["상태 화면 p.2"], "로그인에 실패하면 입력한 이메일은 지우지 않는다.", "상태",
                 "로그인에 실패한다", "입력한 이메일이 입력란에 남아 있다"),
        ],
        "questions": [],
        "skipped": [{"source": "Description 1", "reason": "로고 배치(디자인)"}],
    }
    out["MEM-002"] = {
        "screen_id": "MEM-002", "reject_reason": None,
        "items_seen": ["Description 0", "Description 1", "Description 2", "Action A"],
        "units": [
            unit("u01", "MEM-002", ["Description 0"], "이메일, 비밀번호, 비밀번호 확인 입력란과 가입하기 버튼이 있다.", "표시",
                 "회원가입 화면에 들어간다", "이메일, 비밀번호, 비밀번호 확인 입력란과 가입하기 버튼이 표시된다",
                 values=["이메일", "비밀번호", "비밀번호 확인", "가입하기"]),
            unit("u02", "MEM-002", ["Description 1"], "포커스 아웃 시 이메일 형식이 아니면 에러 메시지를 표시한다.", "검증",
                 "이메일 입력란에서 다른 곳으로 이동한다", "이메일 입력란 아래에 오류 메시지가 표시된다",
                 conditions=["이메일 형식이 아님"], message="이메일 형식이 올바르지 않습니다."),
            unit("u03", "MEM-002", ["Description 2"], "비밀번호가 8자 미만이면 에러 메시지를 표시한다.", "검증",
                 "비밀번호 입력란에서 다른 곳으로 이동한다", "오류 메시지가 표시된다",
                 conditions=["비밀번호가 8자 미만"], message="비밀번호는 8자 이상 입력해주세요.", values=["8자 이상"]),
            unit("u04", "MEM-002", ["Action A"], "가입하기: 회원 정보를 저장하고", "처리",
                 "가입하기 버튼을 누른다", "회원 정보가 저장된다"),
            unit("u05", "MEM-002", ["Action A"], "로그인 화면으로 이동한다", "이동",
                 "가입하기 버튼을 누른다", "로그인 화면으로 이동한다", target="MEM-001"),
        ],
        "questions": [
            {"key": "q01", "topic": "비밀번호 확인 검사", "question": "비밀번호 확인이 비밀번호와 다르면 어떤 문구를 보여 주나요?",
             "why": "MEM-002 그림에 비밀번호 확인 입력란은 있으나 설명에 일치 검사 규칙과 문구가 없어 결과를 정할 수 없음",
             "priority": "상", "related_units": ["u01"]},
        ],
        "skipped": [],
    }
    out["QNA-001"] = {
        "screen_id": "QNA-001", "reject_reason": None,
        "items_seen": ["Description 0", "Description 2", "Description 4", "Action B", "Action C"],
        "units": [
            unit("u01", "QNA-001", ["Description 2"], "목록에는 작성자 본인의 문의와 비공개가 아닌 문의가 표시된다", "표시",
                 "문의 목록 화면에 들어간다", "본인의 문의와 공개 문의가 목록에 표시된다"),
            unit("u02", "QNA-001", ["Description 4"], "문의 게시물은 목록 화면에서 삭제할 수 없다", "접근",
                 "문의 목록 화면을 본다", "목록에 삭제 버튼이 보이지 않는다"),
            unit("u03", "QNA-001", ["Action C"], "문의하기: 문의 작성(QNA-002)으로 이동한다.", "이동",
                 "문의하기 버튼을 누른다", "문의 작성 화면으로 이동한다", target="QNA-002"),
            # 근거 원문이 하나뿐인 함의 → gate_implied가 질문으로 옮기고 draft_unit에 남긴다
            unit("u04", "QNA-001", ["Description 2"], "목록에는 작성자 본인의 문의와 비공개가 아닌 문의가 표시된다", "표시",
                 "문의 목록 화면에 들어간다", "문의가 최신순으로 표시된다", origin="함의",
                 reason="목록에 본인 문의와 공개 문의가 함께 표시되므로, 최근 문의를 찾기 쉽게 최신순으로 표시되어야 한다"),
        ],
        "questions": [],
        "skipped": [{"source": "Description 0", "reason": "화면 개요"},
                    {"source": "Action B", "reason": "좌측 메뉴 (공통 영역)"}],
    }
    ex = load("screen_example.json")                  # QNA-002 (예시 1)
    out["QNA-002"] = ex
    out["QNA-003"] = {
        "screen_id": "QNA-003", "reject_reason": None,
        "items_seen": ["Description 1", "Description 3", "Action C", "Action D"],
        "units": [
            unit("u01", "QNA-003", ["Description 1"], "문의 제목, 작성일, 내용과 답변이 표시된다.", "표시",
                 "문의 상세 화면에 들어간다", "문의 제목, 작성일, 내용과 답변이 표시된다",
                 values=["제목", "작성일", "내용", "답변"]),
            unit("u02", "QNA-003", ["Description 3"], "답변은 상담원만 작성한다", "접근",
                 "문의 상세 화면을 본다", "답변하기 버튼이 보이지 않는다", given="상담원이 아닌 계정으로 로그인한 상태"),
            unit("u03", "QNA-003", ["Action C"], "답변하기: 답변 작성(QNA-004)으로 이동한다.", "이동",
                 "답변하기 버튼을 누른다", "답변 작성 화면으로 이동한다", given="상담원 계정으로 로그인한 상태",
                 target="QNA-004"),
            unit("u04", "QNA-003", ["Action D"], "수정하기: 문의 수정(QNA-005)으로 이동한다.", "이동",
                 "수정하기 버튼을 누른다", "문의 수정 화면으로 이동한다", target="QNA-005"),
        ],
        "questions": [],
        "skipped": [],
        # 재시도 후에도 검사를 통과하지 못해 뺀 단위 (stages._split_invalid 모양). 이 화면 상태는 확인필요
        "rejected": {"units": [{"unit": unit("u05", "QNA-003", ["Action E"], "목록: 문의 목록으로 돌아간다.", "알림",
                                             "목록 버튼을 누른다", "문의 목록 화면으로 이동한다"),
                                "errors": ["kind 값이 허용 목록에 없습니다: 알림"]}],
                     "questions": []},
    }
    out["QNA-005"] = load("screen_example_2.json")   # 예시 2. ③이 실패해 판정 전으로 남는다
    out["QNA-006"] = {
        "screen_id": "QNA-006", "reject_reason": None,
        "items_seen": ["Action A", "Action B"],
        "units": [
            unit("u01", "QNA-006", ["Action A"], "예: 문의를 삭제하고 문의 목록(QNA-001)으로 이동한다.", "처리",
                 "예 버튼을 누른다", "문의가 삭제된다"),
            unit("u02", "QNA-006", ["Action B"], "아니오: 팝업을 닫는다.", "이동",
                 "아니오 버튼을 누른다", "삭제 확인 팝업이 닫힌다"),
        ],
        "questions": [],
        "skipped": [],
    }
    return out


SCREEN_STATUS = {"QNA-003": "확인필요"}              # 나머지는 완료
GATE_REJECTED = {"QNA-004": "그림 마커와 설명 번호가 절반 넘게 맞지 않음 (그림 A~D, 설명 A~F)"}


# ---------- ③ 화면별 판정 (LLM 응답 모양) ----------

def r(uid, status, evidence=(), note=None, mismatch=(), split_issue=None):
    return {"unit_id": uid, "status": status, "mismatch": list(mismatch), "evidence": list(evidence),
            "note": note, "split_issue": split_issue}


def mm(field, spec, code):
    return {"field": field, "spec": spec, "code": code}


def verdicts() -> dict[str, dict]:
    """화면 ID → {results, extras}. 앱 전체 단위(REQ-APP-…)는 언급된 화면마다 따로 판정된다 (judge.units_by_screen)."""
    jx = {x["unit_id"]: x for x in load("judge_example.json")["results"]}
    app01 = "REQ-APP-01"   # 로그아웃 상태로 문의 화면에 들어갈 수 없다
    app02 = "REQ-APP-02"   # 가입한 계정으로 로그인된다
    app03 = "REQ-APP-03"   # 수정한 제목이 목록에 보인다
    a02_note = "가입 저장(MemberService.join)과 로그인(Spring Security)은 있으나 비밀번호 암호화 설정이 묶음에 없어 가입한 계정으로 로그인되는지 코드만으로 확인할 수 없음"
    return {
        "MEM-001": {"results": [
            r(app01, "구현", [ev(SEC, '.requestMatchers("/qna", "/qna/new").authenticated()')], "문의 목록·작성 주소는 로그인해야 들어갈 수 있음"),
            r(app02, "확인필요", [], a02_note),
            r("REQ-MEM-001-01", "구현", [ev(LOGIN, 'id="loginBtn"')]),
            r("REQ-MEM-001-02", "구현", [ev(SEC, '.usernameParameter("email")')], "로그인 성공 뒤 /qna로 이동 (설계서에는 이동 화면 없음)"),
            # 근거로 댄 줄이 실제 문구 줄과 2줄 어긋남 → 프로그램이 확인필요로 내림 (원래 불일치)
            r("REQ-MEM-001-03", "불일치", [ev(LOGIN, "이메일 또는 비밀번호를 확인해주세요.", shift=2)], None,
              [mm("message", "이메일 또는 비밀번호가 올바르지 않습니다.", "이메일 또는 비밀번호를 확인해주세요.")]),
            r("REQ-MEM-001-04", "구현", [ev(LOGIN, 'href="/signup"')]),
            r("REQ-MEM-001-05", "미구현", [ev(LOGIN, 'id="email" name="email"')],
              "login.html의 이메일 입력란에 이전 입력값을 채우는 코드가 없음. MemberController, SecurityConfig의 failureUrl도 확인함"),
        ], "extras": []},
        "MEM-002": {"results": [
            r(app02, "확인필요", [], a02_note),
            r("REQ-MEM-002-01", "구현", [ev(SIGNUP, 'id="joinBtn"')]),
            r("REQ-MEM-002-02", "불일치", [ev(MEMJS, "올바른 이메일 형식이 아닙니다.")], None,
              [mm("message", "이메일 형식이 올바르지 않습니다.", "올바른 이메일 형식이 아닙니다.")]),
            # 띄어쓰기만 다름 → relax_spacing이 구현으로 바꾼다 (원래 불일치)
            r("REQ-MEM-002-03", "불일치", [ev(MEMJS, "비밀번호는 8자 이상")], "띄어쓰기 차이",
              [mm("message", "비밀번호는 8자 이상 입력해주세요.", "비밀번호는 8자 이상 입력해 주세요.")]),
            r("REQ-MEM-002-04", "구현", [ev(MEMC, "memberService.join(form);")]),
            r("REQ-MEM-002-05", "불일치", [ev(MEMC, 'return "redirect:/";')], "가입 후 로그인 화면이 아니라 첫 화면(/)으로 이동함",
              [mm("target", "MEM-001", "/")]),
        ], "extras": []},
        "QNA-001": {"results": [
            r(app01, "구현", [ev(SEC, '.requestMatchers("/qna", "/qna/new").authenticated()')]),
            r(app03, "구현", [ev(QNAC, "qnaService.visibleTo(principal.getName())")], "목록을 열 때마다 저장된 제목을 다시 읽음"),
            r("REQ-QNA-001-01", "구현", [ev(QNAC, "qnaService.visibleTo(principal.getName())")]),
            r("REQ-QNA-001-02", "구현", [ev(LIST, 'th:each="q : ${items}"')], "목록 행에 삭제 버튼이 없음"),
            r("REQ-QNA-001-03", "구현", [ev(LIST, 'href="/qna/new"')]),
        ], "extras": [
            {"file": LIST, "line": ev(LIST, "fragments/header")["line"], "code": ev(LIST, "fragments/header")["code"],
             "description": "목록 위에 공통 머리글 조각을 넣음 (설계서에 머리글 설명 없음)"},
        ]},
        "QNA-002": {"results": [
            r(app01, "구현", [ev(SEC, '.requestMatchers("/qna", "/qna/new").authenticated()')]),
            r("REQ-QNA-002-01", "미구현", [ev(WRITE, '<select id="type" name="type">')], jx["REQ-QNA-002-01"]["note"],
              split_issue=jx["REQ-QNA-002-01"]["split_issue"]),
            r("REQ-QNA-002-02", "구현", [ev(WRITE, 'maxlength="30"')]),
            r("REQ-QNA-002-03", "불일치", [ev(QNAJS, '"제목을 입력하세요"')], None, jx["REQ-QNA-002-03"]["mismatch"]),
            r("REQ-QNA-002-04", "구현", [ev(QNAJS, "content.value.length < 10")]),
            r("REQ-QNA-002-05", "구현", [ev(QNAJS, "content.value.length < 10")], jx["REQ-QNA-002-05"]["note"]),
            r("REQ-QNA-002-06", "구현", [ev(QNAJS, "content.value.length < 10")], "금지어 검사 코드 없음"),
            r("REQ-QNA-002-07", "확인필요", [ev(WRITE, 'id="submitBtn"')],
              "등록 버튼에 활성화·비활성화 처리가 없고 브라우저 기본 동작만 있음. 처음부터 눌리는지 화면에서 확인 필요"),
            r("REQ-QNA-002-08", "불일치", [ev(QNACSS, "select.selected")], None,
              [mm("values", ["파란색 테두리"], ["회색 배경"])]),
            r("REQ-QNA-002-09", "구현", [ev(QNAC, "qnaService.create(form, principal.getName());")]),
            r("REQ-QNA-002-10", "미구현", [], jx["REQ-QNA-002-10"]["note"]),
            r("REQ-QNA-002-11", "구현", [ev(QNAC, 'return "redirect:/qna";')]),
            r("REQ-QNA-002-12", "미구현", [ev(QNAC, 'model.addAttribute("qna", qnaService.get(id));')],
              "상세 조회에 작성자·비공개 확인이 없음. 비공개 체크박스도 작성 화면에 없음"),
            r("REQ-QNA-002-13", "구현", [ev(QNAC, 'return "redirect:/qna";')], "등록 후 목록으로 이동하고 목록은 본인 문의를 다시 읽음"),
        ], "extras": [
            {**e, **ev(QNAJS, "setInterval(saveDraft, 30000);")} for e in load("judge_example.json")["extras"]
        ]},
        "QNA-003": {"results": [
            # 로그인 없이 상세 주소에 들어갈 수 있음 → 앱 전체 단위의 가장 나쁜 판정이 이 화면에서 나온다
            r(app01, "미구현", [ev(SEC, ".anyRequest().permitAll())")], "/qna/{id}(문의 상세)는 로그인 확인 없이 열림"),
            r(app03, "구현", [ev(DETAIL, '<h1 th:text="${qna.title}">')], "상세 화면도 저장된 제목을 다시 읽음"),
            r("REQ-QNA-003-01", "구현", [ev(DETAIL, '<h1 th:text="${qna.title}">')]),
            # 없는 파일을 근거로 댐. 미구현은 그대로 두고 evidence_ok만 false가 된다 (original_status 없음)
            r("REQ-QNA-003-02", "미구현", [ev("src/main/resources/templates/qna/answer-button.html", 'th:if="${isAgent}"')],
              "답변하기 버튼이 역할과 상관없이 보임"),
            r("REQ-QNA-003-03", "구현", [ev(DETAIL, "답변하기")]),
            r("REQ-QNA-003-04", "구현", [ev(DETAIL, "수정하기")]),
        ], "extras": []},
        # QNA-005: ③ 실패 → 결과 파일 없음. 그 화면 단위는 판정 전
        "QNA-006": {"results": [
            # REQ-QNA-006-01은 LLM이 빠뜨림 → 프로그램이 "판정 누락"으로 채운다
            r("REQ-QNA-006-02", "구현", [ev(DELETE, "아니오")]),
        ], "extras": []},
    }


JUDGE_FAILED = {"QNA-005"}


# ---------- 사양서 (④는 아직 없음. CLAUDE.md 3장 v3 형식) ----------

def step(no, action, expected, unit_ids, account=None, input=None, note=None, setup=None, data_source=None):
    return {"no": no, "action": action, "expected": expected, "account": account, "input": input,
            "data_source": data_source, "note": note, "unit_ids": unit_ids, "setup": setup}


SCENARIOS = {"scenarios": [
    {"scenario_id": "TC-MEM-001-01", "depth1": "회원", "depth2": "로그인", "steps": [
        step(1, "로그인 화면에 들어간다.", "이메일, 비밀번호 입력란과 로그인 버튼이 표시된다.", ["REQ-MEM-001-01"]),
        step(2, "가입된 이메일과 틀린 비밀번호로 로그인한다.", "\"이메일 또는 비밀번호가 올바르지 않습니다.\"가 표시되고 입력한 이메일은 남아 있다.",
             ["REQ-MEM-001-03", "REQ-MEM-001-05"], account="user1@example.com", input="비밀번호: wrong-pass"),
        step(3, "가입된 이메일과 비밀번호로 로그인한다.", "로그인된다.", ["REQ-MEM-001-02", "REQ-APP-02"],
             account="user1@example.com", note="로그인 후 이동 화면은 질문 Q-APP-02 답변에 따름"),
        step(4, "회원가입 링크를 누른다.", "회원가입 화면으로 이동한다.", ["REQ-MEM-001-04"]),
    ]},
    {"scenario_id": "TC-QNA-002-01", "depth1": "고객센터", "depth2": "문의 작성", "steps": [
        step(1, "문의 작성 화면에 들어간다.", "문의 유형, 제목, 내용 입력란과 비공개 체크박스가 표시된다.", ["REQ-QNA-002-01"],
             account="user1@example.com", setup="user1@example.com으로 로그인"),
        step(2, "제목을 비운 채 다른 입력란을 누른다.", "\"제목을 입력해주세요.\"가 표시된다.", ["REQ-QNA-002-03"]),
        step(3, "내용에 5자를 입력하고 다른 곳을 누른다.", "\"내용을 10자 이상 입력해주세요.\"가 표시된다.",
             ["REQ-QNA-002-04", "REQ-QNA-002-05"], input="내용: 안녕하세요"),
        step(4, "문의 유형, 제목, 내용을 모두 채운다.", "등록 버튼이 활성화된다.", ["REQ-QNA-002-07"],
             input="유형: 계정 / 제목: 로그인 문의 / 내용: 로그인이 되지 않습니다. 확인 부탁드립니다."),
        step(5, "등록 버튼을 누른다.", "\"문의가 등록되었습니다.\" 팝업이 표시된 뒤 문의 목록으로 이동한다.",
             ["REQ-QNA-002-09", "REQ-QNA-002-10", "REQ-QNA-002-11"]),
        step(6, "문의 목록을 본다.", "방금 등록한 문의가 목록에 표시된다.", ["REQ-QNA-002-13"]),
    ]},
    {"scenario_id": "TC-QNA-002-02", "depth1": "고객센터", "depth2": "문의 작성", "steps": [
        step(1, "비공개를 체크하고 문의를 등록한다.", "문의가 등록된다.", ["REQ-QNA-002-12"],
             account="user1@example.com", setup="user1@example.com으로 로그인"),
        step(2, "다른 계정으로 로그인해 그 문의를 연다.", "문의 내용을 볼 수 없다.", ["REQ-QNA-002-12"],
             account="user2@example.com", data_source="1단계에서 등록한 문의"),
    ]},
    {"scenario_id": "TC-QNA-005-01", "depth1": "고객센터", "depth2": "문의 수정", "steps": [
        step(1, "제목을 바꾸고 저장 버튼을 누른다.", "수정한 내용이 저장되고 문의 상세 화면으로 이동한다.",
             ["REQ-QNA-005-05", "REQ-QNA-005-06"], account="user1@example.com", input="제목: 로그인 문의(수정)",
             setup="user1@example.com으로 로그인해 본인 문의의 수정 화면을 연다"),
        step(2, "문의 목록을 본다.", "바뀐 제목이 목록에 표시된다.", ["REQ-APP-03"]),
    ]},
]}


# ---------- 실행 ----------

def build(run: Path) -> None:
    profile = load("app_example.json")
    schema.normalize_app_profile(profile)
    units, questions = schema.assign_ids(profile["units"], profile["questions"], "APP")
    profile["units"], profile["questions"], _ = schema.gate_implied(units, questions, "APP")
    write_json(run / "app_profile.json", profile)

    for s in profile["screens"]:
        sid = s["screen_id"]
        if sid in GATE_REJECTED:            # stages.mark_rejected 모양
            write_json(run / "screens" / f"{sid}.meta.json",
                       {"screen_id": sid, "status": "반려", "attempts": 0, "reject_reason": GATE_REJECTED[sid],
                        "rejected_by": "게이트(입력 점검)", "issues": []})
    for sid, obj in screens().items():
        units, questions = schema.assign_ids(obj["units"], obj["questions"], sid)
        obj["units"], obj["questions"], _ = schema.gate_implied(units, questions, sid)
        obj.setdefault("rejected", {"units": [], "questions": []})
        write_json(run / "screens" / f"{sid}.json", obj)
        write_json(run / "screens" / f"{sid}.meta.json",
                   {"screen_id": sid, "status": SCREEN_STATUS.get(sid, "완료"), "attempts": 1, "prompt_version": "mock"})
    merge.merge(run)

    # ③: judge.judge_screen이 LLM 응답을 받은 뒤 하는 일을 그대로 한다
    code_dir = CODE_DIR
    cb = code_prep.load_codebase(code_dir)
    requirements = json.loads((run / "requirements.json").read_text(encoding="utf-8"))
    by_screen = judge.units_by_screen(requirements)
    all_verdicts = verdicts()
    for sid, us in by_screen.items():
        if sid in JUDGE_FAILED:
            write_json(run / "judge" / f"{sid}.meta.json", {"screen_id": sid, "status": "실패", "issues": []})
            continue
        given = all_verdicts[sid]
        unit_ids = [u["id"] for u in us]
        extra_ids = {x["unit_id"] for x in given["results"]} - set(unit_ids)
        assert not extra_ids, f"{sid}: 이 화면으로 가지 않는 단위를 판정함 {extra_ids}"
        results = {x["unit_id"]: dict(x) for x in given["results"]}
        for x in results.values():
            problems = code_prep.verify_evidence(cb, x.get("evidence", []))
            x["evidence_ok"] = not problems
            if problems:
                x["evidence_problems"] = problems
                if x["status"] in ("구현", "불일치"):
                    x["original_status"] = x["status"]
                    x["status"] = "확인필요"
                    x["note"] = ((x.get("note") or "") + " [근거 불일치로 확인필요 처리]").strip()
        for x in results.values():
            judge.relax_spacing(x)
        for uid in unit_ids:
            if uid not in results:
                results[uid] = {"unit_id": uid, "status": "확인필요", "mismatch": [], "evidence": [],
                                "note": "판정 누락 (LLM이 결과를 내지 않음)", "split_issue": None, "evidence_ok": True}
        extras = [{k: e[k] for k in ("file", "line", "code", "description")} for e in given["extras"]]
        write_json(run / "judge" / f"{sid}.json",
                   {"screen_id": sid, "results": [results[u] for u in unit_ids], "extras": extras})
        write_json(run / "judge" / f"{sid}.meta.json", {"screen_id": sid, "status": "완료"})
    judge.merge_judgments(run)


def main() -> None:
    OUT.mkdir(exist_ok=True)
    code_dir = CODE_DIR
    if code_dir.exists():
        shutil.rmtree(code_dir)
    for rel, text in CODE.items():
        p = code_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    with tempfile.TemporaryDirectory() as tmp:
        run = Path(tmp) / "qna-example"
        build(run)
        for name in ("requirements.json", "judgments.json", "judge_report.json"):
            shutil.copyfile(run / name, OUT / name)
    write_json(OUT / "scenarios.json", SCENARIOS)
    report = json.loads((OUT / "judge_report.json").read_text(encoding="utf-8"))
    print(json.dumps(report["summary"], ensure_ascii=False))


if __name__ == "__main__":
    main()

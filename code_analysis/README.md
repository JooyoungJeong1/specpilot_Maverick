# code_analysis — 소스 코드 정적 분석 (코드팀)

샘플 코드를 읽어서, ③ 정합성 판정 때 AI에게 같이 줄 "사실"을 만든다. LLM을 부르지 않는다(API 키 필요 없음, 무료).
백엔드 코드는 고치지 않는다. 이 폴더의 도구가 JSON 파일 하나를 만들면 끝이다.

구성은 2주차 검증용 저장소(specpilot-verification2, 이 저장소에는 없음)와 같다.

| 부분 | 도구 | 하는 일 |
| --- | --- | --- |
| `analyzer/` (Java) | JavaParser + Symbol Solver + Jsoup | 백엔드(.java + Thymeleaf) 콜그래프·바인딩 분석 → `backend-analysis.json` |
| `analyze_frontend_js.py` | tree-sitter | 프론트엔드(.js) 구조 분석 → `frontend-js.json` |
| 나머지 Python | — | 두 결과와 설정 파일로 사실 문장을 만들고, ③과 경로·줄을 맞추고, 화면별로 나눠 `code_facts.json`을 쓴다 |

## 입력과 출력

- 입력: 샘플 코드 폴더 경로. 기업 자료라 저장소에 넣지 않고 각자 PC에 둔다 (예: `backend/inputs/sample-code`)
- 출력: `code_analysis/out/` (기업 코드에서 뽑은 내용이라 커밋하지 않는다. 저장소 루트 `.gitignore`의 `code_analysis/out/`이 막음)
  - `code_facts.json`: ③에 넘기는 파일. 형식은 `backend/docs/code_facts.example.json`과 같다
    (`common`: 모든 화면 / `screens`: 화면 ID → 그 화면 사실 목록, 사실 하나는 `{"kind", "file", "line", "fact"}`)
  - `backend-analysis.json`, `frontend-js.json`: 중간 결과. 사실이 이상할 때 원인을 찾는 용도
- `code_facts.json`의 `_설명`, `_meta`(실행 정보, 호출 해석 통계, 화면별로 고른 템플릿, 뺀 사실)는 사람이 보는 칸이다. ③ 프롬프트에는 `common`과 그 화면의 `screens` 목록만 들어간다
- `reach`(근거 재확인용 도달 정보)는 프롬프트에 넣지 않는다. ③이 판정한 뒤 프로그램이 근거를 다시 확인하는 데 쓴다 (아래 "③ 근거 재확인에 쓰는 도달 정보")

## 설치

처음 한 번만 (저장소 폴더에서):

```bash
pip install -r code_analysis/requirements.txt          # tree-sitter (Python 3.10 이상, Windows 3.14용도 있음)

cd code_analysis/analyzer                              # 백엔드 분석기 빌드 (JDK 17 이상, Maven)
mvn -q clean package                                   # → target/specpilot-analyzer-0.8.1.jar
cd ../..
```

pom.xml은 2주차 v7과 같은 의존성(JavaParser 3.26.1, Jsoup 1.18.1)이라 v7을 빌드했던 PC면 그대로 된다. 분석기 코드를 고쳤으면 다시 빌드한다.

## 실행

명령은 **저장소 폴더**(code_analysis와 backend가 있는 곳)에서 한다.

```bash
# 1) 기본: 모든 사실을 common에 넣는다
python -m code_analysis --code backend/inputs/sample-code

# 2) 화면별로 나누기: ②까지 돈 실행의 requirements.json을 준다 (권장)
python -m code_analysis --code backend/inputs/sample-code --requirements backend/output/<실행ID>/requirements.json

# 3) 화면별로 나누기: ③을 화면별 묶음으로 돌린 실행의 code_map.json을 준다 (2와 같이 줘도 된다)
python -m code_analysis --code backend/inputs/sample-code --code-map backend/output/<실행ID>/judge/code_map.json
```

| 옵션 | 뜻 |
| --- | --- |
| `--gradle` | 샘플 코드의 `gradlew`로 라이브러리 classpath를 뽑아 분석기에 준다 (v6/v7의 자동 추출과 같음). Spring·JPA에서 상속받은 메서드까지 풀린다. 몇 분 걸릴 수 있고 Gradle이 의존성을 받을 수 있어야 한다 |
| `--classpath 파일` | 라이브러리 jar 목록 파일을 직접 준다 (한 줄에 하나) |
| `--analyzer-jar 경로` | 분석기 jar 위치 (기본: `analyzer/target/`에서 가장 최근 것, 또는 환경 변수 `SPECPILOT_ANALYZER_JAR`) |
| `--analysis out/backend-analysis.json` | Java 분석을 건너뛰고 지난 결과를 다시 쓴다. 화면 나누기나 사실 문장만 바꿔 볼 때 |

실행하면 호출 해석 통계, 화면마다 붙은 사실 수, 그 화면에 대응시킨 템플릿이 출력된다. 대응이 이상하면 `_meta.screen_templates`를 보고 알려 준다.

**`--code`에는 `judge --code`에 줄 폴더와 같은 폴더를 준다.** 사실의 파일 경로가 그 폴더 기준 상대 경로라서, 다른 폴더를 주면 ③의 경로와 어긋난다.

## 백엔드에서 쓰는 법 (조장)

```bash
cd backend
python -m specpilot judge --run output/<실행> --code inputs/<샘플코드> --facts ../code_analysis/out/code_facts.json
```

`--facts`를 넣은 판정과 뺀 판정을 각각 채점해서 효과를 비교한다. 들어가는 모습은 `--dry-run`의 `prompts_preview/judge_화면ID.txt` 맨 아래 "코드 분석 결과"에서 볼 수 있다.

## 백엔드 분석기 (`analyzer/`, v8)

2주차 v7(`specpilot-verification2/analyzer`)을 이어받았다. v7이 내던 콜그래프와 Controller-템플릿 바인딩을 그대로 내되, ③에 쓰려고 다음을 바꿨다.

| | v7 | v8 |
| --- | --- | --- |
| 입력 | 소스 폴더 경로 (위치 인자) | Python이 ③의 파일 목록·줄 그대로 다시 쓴 폴더 (`--src`) |
| 파일 경로 | 파일 이름만 (`AuthController.java`) | ③과 같은 상대 경로 (`src/main/java/.../AuthController.java`) |
| 줄 번호 | delombok한 코드 기준이라 원본과 어긋날 수 있음 | 원본 기준 (delombok하지 않음) |
| 템플릿 위치 | 소스 경로에서 짐작. 틀리면 `template_refs`가 비고 바인딩이 전부 `mismatch`가 됐다 (실제로 v7 결과가 그랬음) | 넘겨받은 폴더 안의 `templates/`에서 찾음 |
| 바인딩 | 메서드가 반환하는 뷰가 하나일 때만 판단 | 분기별로 판단 ("예외 시 errorMessage를 넘기고 같은 화면을 반환"), 헬퍼 메서드 안에서 넣은 값은 부른 자리의 분기로 |
| 콜그래프 | 해석 결과와 `spring_data_derived` 등 표시 | 같음 + 호출한 메서드, 분기 문맥, 받는 쪽 타입, 선언 위치, 인터페이스면 모든 구현 메서드 위치 |
| 더한 것 | — | 컨트롤러 경로(HTTP 메서드, 경로, @Valid, 분기별 반환), 보안 설정 체이닝, 검증 애노테이션, 예외 문구(`orElseThrow` 포함), 템플릿 구조(검증 오류 출력, 포함 조각, 스크립트, 폼·링크, 입력란, 버튼, v8.1부터 조건이 붙은 문구 `texts`) |

**delombok을 하지 않는 이유**: delombok한 코드를 파싱하면 줄 번호가 원본과 달라져 ③의 근거 줄과 맞지 않는다. 대신 Lombok이 만든 getter를 인자로 넘기는 호출은 메서드 고르기에 실패할 수 있는데, 그때도 분석기는 **받는 쪽의 타입**(예: `noticeRepository`의 타입 `NoticeRepository`)은 대개 풀어 낸다. Python이 그 타입의 같은 이름·같은 인자 수 메서드로 이어 준다 (`backend_model.py`). 어느 쪽으로 정했는지는 `_meta.call_resolution.target_by`에 남는다.

| `target_by` | 뜻 |
| --- | --- |
| `javaparser` | 분석기가 이 코드 안의 선언으로 풂 (인터페이스면 구현 메서드까지) |
| `javaparser-library` | 라이브러리 선언으로 풂 (Model.addAttribute 등). 사실에는 쓰지 않음. Spring Data 저장소의 상속 메서드는 저장소 이름으로 남김 |
| `receiver_type` | 메서드는 못 풀었지만 받는 쪽 타입으로 이음 |
| `same_class`, `static` | 받는 쪽이 없거나 this / 클래스 이름 |
| `none` | 라이브러리 객체나 지역 값 (사실과 관계없음) |

`--gradle`로 라이브러리 classpath를 주면 `javaparser`·`javaparser-library`가 늘고 `receiver_type`이 준다.

## 프론트엔드 분석 (`analyze_frontend_js.py`)

verification2의 같은 파일을 이어받았다. 그때 뽑던 `selectors`, `event_bindings`, `regex_literals`, `string_literals`는 그대로이고(`analyze_js_directory`도 같은 모양으로 쓸 수 있음), 다음을 더했다.

- 이벤트 처리 함수가 실제로 무엇을 바꾸는지 (`effects`: 버튼 disabled, 문구, fetch, classList …)
- forEach로 여러 요소에 한꺼번에 붙인 이벤트의 대상 요소 (`target`)
- 서버 요청·이동 주소 (`url_refs`)
- 파일 이름 대신 ③과 같은 상대 경로, ③의 줄 목록 기준 줄 번호
- 라이브러리에 넘기는 설정 객체 (`lib_configs`: `agGrid.createGrid(el, gridOptions)`의 `pagination`처럼 이벤트가 아니라 설정으로 동작하는 기능)

verification2의 `check_frontend_requirement`(요구사항 하나를 규칙으로 판정)는 빼고, 판정은 ③에 맡긴다.

## 뽑는 사실

예시는 `tests/fixtures/qna-app`(가상의 앱)에서 나온 것이다.

| kind | 내용 | 예 | 들어가는 곳 |
| --- | --- | --- | --- |
| `security` | 경로별 접근 범위, 로그인·로그아웃 처리, 로그인 성공·실패 후 이동, 접근 거부 처리 유무 | `/qna/*/delete → ADMIN 역할만`, `로그인 제출(POST /login)은 컨트롤러가 아니라 Spring Security가 처리한다` | common |
| `global` | @ControllerAdvice, Spring Boot가 자동으로 고르는 오류 화면 | `모든 컨트롤러 화면에 모델 값 자동 추가: loginMember` | common |
| `config` | 업로드 한도, 세션 시간, `app.*` 값과 그 값을 읽는 클래스 | `spring.servlet.multipart.max-file-size = 50MB (…컨트롤러 코드에 닿기 전에 요청이 거부된다)` | common |
| `data` | Spring Data 저장소: 구현 코드 없이 이름 규칙으로 동작하는 메서드 | `QnaRepository: JpaRepository 상속. 선언한 메서드 existsByTitle: 구현 코드 없이 …` | common |
| `route` | 컨트롤러 경로 → 처리 메서드, @Valid, 서비스 호출, 분기별 반환 | `POST /qna → QnaController.create. @Valid QnaForm 입력값 검사. 호출 QnaService.create. 반환: 입력값 검사 실패 시 qna/write 화면 / 정상 흐름 redirect:/qna / 예외(IllegalArgumentException) 시 qna/write 화면` | 화면 |
| `template` | 넘긴 모델 값을 템플릿(과 포함 조각)이 출력하는지, @Valid 실패 시 다시 보여 주는 화면에 검증 오류 출력이 있는지 | `모델 값 errorMessage을(를) qna/write 화면에 넘기지만 qna/write 템플릿 어디에서도 출력하지 않음` | 화면 |
| `validation` | 폼 클래스의 검증 애노테이션과 메시지, 그 검사가 언제 어느 경로에서 도는지 | `QnaForm.title: @NotBlank("제목을 입력하세요"), @Size(max=30, …) — 제출 후 서버에서 검사: POST /qna (@Valid)` | 화면 |
| `call` | 서비스 메서드 → 저장소·다른 서비스 호출 | `QnaService.create → QnaRepository.existsByTitle(이름 규칙 쿼리), NotifyService.send(구현: MailNotifyService, SmsNotifyService), QnaRepository.save(Spring Data 기본 기능)` | 화면 |
| `message` | 예외로 던지는 문구와 그 조건 (`orElseThrow` 포함) | `QnaService.create: qnaRepository.existsByTitle(…) 일 때 IllegalArgumentException("이미 있는 제목입니다.")` | 화면 |
| `js` | 요소별 이벤트와 처리 함수가 바꾸는 것, 파일이 addEventListener로 붙이는 이벤트 종류(blur·focusout·submit이 없으면 명시), 라이브러리에 넘기는 설정 객체(AG Grid 옵션 등), 그 JS를 불러오는 템플릿 | `#title input 이벤트 → update: saveButton.disabled = !titleInput.value.trim()`, `gridOptions을(를) agGrid.createGrid에 넘기는 설정: pagination=true, paginationPageSize=10, …` | 화면 |
| `html` | 입력란 제약과 인라인 이벤트 속성(onfocus 등), 모든 버튼·링크(라벨 → 이동·폼 제출, 표시 조건, 확인 창 유무, th:text면 "자리표시"), 조건이 붙은 문구(th:if·th:unless), 처리하는 곳이 없는 링크 | `입력란 dueDate: type=text, 포커스를 받으면 type=date로 바뀜`, `링크 '취소': 누르면 GET /qna로 이동, 확인 창 없음`, `문구 '등록된 질문이 없습니다.': th:unless="${hasQna}" 아닐 때만 보임` | 화면 |
| `unused` | 어디서도 부르지 않는 경로, 어떤 컨트롤러도 반환하지 않는 템플릿 | `POST /qna/check: … 어디에서도 이 주소를 부르지 않음 (미사용 후보)` | 화면 (못 붙으면 common) |

사실은 "어느 코드를 봐야 하는지"를 알려 주는 용도다. ③ 프롬프트는 근거를 반드시 실제 코드 줄로 인용하고, 분석 결과와 코드가 다르면 코드를 따르게 되어 있다.

## ③ 근거 재확인에 쓰는 도달 정보 (`reach`)

AI가 댄 근거 줄이 실제로 있어도, 그 코드가 **그 화면의 기능 처리 과정에서 호출되는지**는 따로 봐야 한다
(예: 등록 화면 단위의 근거로 같은 서비스의 수정 메서드를 댐, 어디서도 부르지 않는 경로를 근거로 댐).
그래서 화면별 사실 나누기에 쓰는 고리(화면 → 템플릿·JS → 폼·링크·JS가 부르는 경로 → Controller → Service → Repository, 인터페이스면 구현 모두)를 그대로 `code_facts.json`의 `reach`에 내보낸다 (`reach.py`).

| 칸 | 내용 |
| --- | --- |
| `methods` | 모든 메서드와 줄 범위 (애노테이션 줄 ~ 닫는 중괄호. 범위는 Python이 중괄호 짝을 세어 정한다. 문자열·주석 안의 중괄호는 세지 않음) |
| `screens` | 화면 → 그 화면에서 닿는 메서드 이름(`methods`)과 파일(`files`: 템플릿, 포함 조각, JS, 컨트롤러, 서비스, 저장소, 폼 클래스) |
| `unused` | `unused` 사실의 위치: 어디서도 부르지 않는 경로의 처리 메서드 범위, 어떤 컨트롤러도 반환하지 않는 템플릿 전체 |

③(`backend/specpilot/grounding.py`)은 근거 줄을 감싸는 메서드를 찾아
- 근거가 모두 `unused` 안이면 구현·불일치를 확인필요로 내리고,
- 다른 화면에서만 닿는 메서드면 판정은 두고 사람 확인 목록(`judge_review.md`)에 올린다.
- 화면별 묶음(`--mode screen`)일 때는 `screens[화면].files`를 그 화면 코드 묶음에 더한다.

화면 ↔ 템플릿 대응이 추정이라(아래 "화면별로 나누는 방법") 다른 화면 판단은 판정을 바꾸지 않는다. 대응을 못 찾은 화면은 `screens`에 없고 도달 확인을 건너뛴다.

## ③과 경로·줄 번호를 맞춘 방법

1. **파일 목록**: `backend/specpilot/code_prep.py`의 `load_codebase`를 그대로 불러 쓴다(수정하지 않음). 확장자, 제외 폴더(test, build, gradle 등), `.min.js`, 300KB 기준이 ③과 같다. 백엔드를 불러올 수 없을 때만 같은 규칙을 옮겨 둔 사본(`codebase.py`)을 쓰고, 두 결과가 같은지는 테스트가 확인한다.
2. **분석기 입력**: `load_codebase`가 만든 줄 목록을 그대로 `out/.analyzer/src/`에 다시 써서 분석기에 넘기고, 끝나면 지운다. JS는 같은 줄 목록을 바로 파싱한다. 그래서 모든 줄 번호가 ③의 `줄번호|`와 같다.
3. **마지막 검사**: 출력 전에 모든 사실이 ③ 코드 묶음 안의 파일·줄인지 다시 확인하고, 아니면 빼고 `_meta.dropped`에 이유를 남긴다.

`load_codebase`의 규칙이 바뀌면 `codebase.py`의 사본도 같이 바꾼다 (테스트 `test_file_list_same_as_backend`가 알려 준다).

## 화면별로 나누는 방법

③은 화면마다 `common` + `screens[화면ID]`를 넣는다. 보안·전역 처리·설정·Spring Data는 항상 `common`이고, 나머지는 그 화면의 템플릿과 이어진 사실만 그 화면으로 간다.

**화면 ↔ 템플릿 (`--requirements`)**
- 화면 이름과 템플릿의 `<title>`, `h1`, `h2`를 맞대 본다. 팝업 화면(`type: "팝업"`)은 부모 화면 템플릿과 이름이 겹쳐서 이름으로 고르지 않는다.
- 그 화면 단위의 원문 문구(`exact.message`), 값, 이동 대상, 따옴표 안 라벨이 템플릿(과 그 템플릿이 불러오는 JS) 글자에 있는지 본다. 백엔드의 `files_mentioning`처럼 공백·기호를 뺀 앞 6글자로 비교해서, 문구가 조금 달라도(=불일치) 찾는다.
- 이미 찾은 화면의 버튼·링크 가운데 설계서의 화면 이동(`flows`, 이동 단위의 target)과 라벨이 맞는 것을 따라가, 그 주소가 정상 흐름에서 보여 주는 템플릿을 이동 대상 화면의 후보로 올린다.

**템플릿 → 사실**: 그 템플릿과 불러오는 JS, 그 템플릿을 보여 주거나 그 템플릿의 폼·링크·JS가 부르는 경로, 그 경로에서 이어지는 서비스 메서드(인터페이스면 구현 메서드 모두), 그 경로의 폼 클래스에 걸린 사실을 붙인다.

여러 화면이 같이 쓰는 JS는 **이벤트 대상 요소와 처리 함수가 바꾸는 요소가 실제로 있는 템플릿에만** 그 이벤트를 붙이고, 사실에 "(대상 요소가 있는 템플릿: …)"을 적는다.

어느 화면에도 붙지 않은 사실은 버리지 않고 `common`에 넣는다 (`_meta.unplaced_to_common`).

## 한계

- **라이브러리 classpath 없이 돌리면** Spring·JPA에서 상속받은 메서드(`save` 등)는 분석기가 못 풀고 받는 쪽 타입으로 잇는다. 정확한 해석이 필요하면 `--gradle`.
- **Lombok getter를 인자로 쓰는 호출**은 메서드 고르기가 실패할 수 있어, 같은 이름이 여럿(오버로딩)이면 인자 수로만 고른다.
- **Spring MVC + Thymeleaf + 정적 JS 기준이다.** JSP, React·Vue 같은 SPA, Kotlin, 함수형으로 등록한 경로는 아직 읽지 않는다.
- **정적으로만 본다.** 실행해야 알 수 있는 동작(브라우저 기본 동작, 프레임워크 기본값)은 "기본 동작"이라고만 적는다.
- **화면 ↔ 템플릿 대응은 추정이다.** 제목이 같은 템플릿이 둘이면 둘 다 붙는다. 틀리면 `--code-map`으로 사람이 고친 대응표를 준다.
- 사실 문장은 사람이 정한 틀에 코드의 값을 채운 것이다. 문장을 바꾸려면 `facts_builder.py`를 고친다.

## 파일

| 파일 | 내용 |
| --- | --- |
| `analyzer/` | 백엔드 분석기 (Java, Maven). `Main.java` 실행·classpath, `Backend.java` 구조·콜그래프·경로·보안·바인딩, `Templates.java` Thymeleaf(Jsoup), `Json.java` 출력 |
| `analyzer_bridge.py` | 분석기 실행: ③과 같은 파일 사본 만들기, `java -jar`, 사본 지우기 |
| `analyze_frontend_js.py` | 프론트엔드 JS 분석 (tree-sitter) |
| `backend_model.py` | 분석기 JSON 읽기, 못 푼 호출의 대상 채우기 |
| `facts_builder.py` | 사실 문장 만들기 |
| `config_facts.py` | 설정 파일 사실 |
| `screens.py` | 화면별로 나누기 |
| `reach.py` | ③ 근거 재확인용 도달 정보 (메서드 줄 범위, 화면별로 닿는 메서드·파일, 미사용 코드 위치) |
| `codebase.py` | ③과 같은 파일 목록 읽기 |
| `facts.py` | 사실 모양, ③ 코드 묶음 안인지 검사, 파일 쓰기 |
| `cli.py`, `__main__.py` | 실행 (`python -m code_analysis`) |
| `tests/` | 테스트와 가상의 앱(`fixtures/qna-app`, 기업 코드 아님), 그 앱의 분석기 결과(`fixtures/qna-backend-analysis.json`), 화면 나누기용 가상 requirements(`fixtures/qna-requirements.json`) |

## 테스트

```bash
python -m pytest code_analysis/tests -q        # 27 passed, 1 skipped (분석기 jar를 빌드하면 28 passed)
```

API 키도 기업 코드도 JDK도 필요 없다. 백엔드 분석 결과는 가상의 앱에 실제 분석기를 돌려 저장해 둔 `fixtures/qna-backend-analysis.json`을 쓴다.
분석기 jar가 있으면 `test_real_analyzer_matches_fixture`가 지금 분석기의 결과와 이 파일이 같은지 확인한다.

**fixture 다시 만들기** (분석기 출력을 일부러 바꿨을 때, 저장소 폴더에서):

```bash
python -c "import json; from pathlib import Path; from code_analysis import codebase, analyzer_bridge as ab; d = ab.run(codebase.load(Path('code_analysis/tests/fixtures/qna-app')), ab.find_jar()); [d.pop(k, None) for k in ('src', 'millis')]; Path('code_analysis/tests/fixtures/qna-backend-analysis.json').write_text(json.dumps(d, ensure_ascii=False, indent=1) + '\n', encoding='utf-8')"
```

새 사실 종류를 더할 때는 `fixtures/qna-app`에 그 패턴을 가진 코드를 조금 넣고, fixture를 다시 만든 뒤 `tests/`에 확인을 더해 PR을 올린다. 사실 문장은 ③ 프롬프트에 그대로 들어가므로, 바꾸면 PR 설명에 바꾸기 전후 문장을 적는다.

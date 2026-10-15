# code_analysis — 소스 코드 정적 분석 (코드팀)

샘플 코드를 읽어서, ③ 정합성 판정 때 AI에게 같이 줄 "사실"을 만든다.
Java 메서드 호출의 타입 해석은 **JavaParser + Symbol Solver**(`javaparser/`, Java)가 하고, 문법 읽기·템플릿·JS·화면 나누기·출력은 Python이 한다.
LLM을 부르지 않는다(API 키 필요 없음, 무료). 백엔드 코드는 고치지 않는다. 이 폴더의 도구가 JSON 파일 하나를 만들면 끝이다.

## 입력과 출력

- 입력: 샘플 코드 폴더 경로. 기업 자료라 저장소에 넣지 않고 각자 PC에 둔다 (예: `backend/inputs/sample-code`)
- 출력: `code_analysis/out/code_facts.json`. 기업 코드에서 뽑은 내용이라 커밋하지 않는다 (`out/.gitignore`가 막음)
- 형식: `backend/docs/code_facts.example.json`과 같다
  - `common`: 모든 화면에 줄 사실 / `screens`: 화면 ID → 그 화면 사실 목록
  - 사실 하나는 `{"kind", "file", "line", "fact"}`
  - `_설명`, `_meta`(실행 정보, 화면별로 고른 템플릿, 뺀 사실)는 사람이 보는 칸이다. ③ 프롬프트에는 `common`과 그 화면의 `screens` 목록만 들어간다

## 설치

처음 한 번만 (저장소 폴더에서):

```bash
pip install -r code_analysis/requirements.txt          # tree-sitter (Python 3.10 이상, Windows 3.14용도 있음)

cd code_analysis/javaparser                            # JavaParser 해석기 jar 빌드 (JDK 17 이상, Maven 필요)
mvn -q package                                         # → target/specpilot-javaparser-0.1.0.jar
cd ../..
```

jar가 없거나 `java`를 찾지 못하면 자동으로 tree-sitter 간이 해석으로 돌고, 그 사실이 실행 화면과 `_meta.java_engine`에 남는다.
조장 PC처럼 채점에 쓰는 결과는 jar를 빌드해서 만든다.

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

실행하면 쓴 Java 해석 엔진, 화면마다 붙은 사실 수, 그 화면에 대응시킨 템플릿이 출력된다. 대응이 이상하면 `out/code_facts.json`의 `_meta.screen_templates`를 보고 알려 준다.

| 옵션 | 뜻 |
| --- | --- |
| `--java-engine auto` (기본) | JavaParser 해석기 jar와 java가 있으면 JavaParser, 없으면 tree-sitter |
| `--java-engine javaparser` / `treesitter` | 엔진 강제. javaparser인데 jar가 없으면 멈춘다 |
| `--gradle` | 샘플 코드의 `gradlew`로 라이브러리 classpath를 뽑아 JavaParser에 준다. Spring·JPA 라이브러리에서 상속받은 메서드까지 풀린다 (몇 분 걸릴 수 있고 Gradle이 의존성을 받아야 함) |
| `--classpath 파일` | 라이브러리 jar 목록 파일을 직접 준다 (한 줄에 하나) |
| `--compare-engines` | tree-sitter와 JavaParser 결과를 비교해 `out/engine_compare.json`에 남긴다 (아래 참고) |

**`--code`에는 `judge --code`에 줄 폴더와 같은 폴더를 준다.** 사실의 파일 경로가 그 폴더 기준 상대 경로라서, 다른 폴더를 주면 ③의 경로와 어긋난다.

## 백엔드에서 쓰는 법 (조장)

```bash
cd backend
python -m specpilot judge --run output/<실행> --code inputs/<샘플코드> --facts ../code_analysis/out/code_facts.json
```

`--facts`를 넣은 판정과 뺀 판정을 각각 채점해서 효과를 비교한다. 들어가는 모습은 `--dry-run`의 `prompts_preview/judge_화면ID.txt` 맨 아래 "코드 분석 결과"에서 볼 수 있다.

## 뽑는 사실

예시는 `tests/fixtures/qna-app`(가상의 앱)에서 나온 것이다.

| kind | 내용 | 예 | 들어가는 곳 |
| --- | --- | --- | --- |
| `security` | 보안 설정: 경로별 접근 범위, 로그인·로그아웃 처리, 로그인 성공·실패 후 이동, 접근 거부 처리 유무 | `/qna/*/delete → ADMIN 역할만`, `로그인 제출(POST /login)은 컨트롤러가 아니라 Spring Security가 처리한다` | common |
| `global` | 모든 컨트롤러에 걸리는 처리(@ControllerAdvice), Spring Boot가 자동으로 고르는 오류 화면 | `모든 컨트롤러 화면에 모델 값 자동 추가: loginMember` | common |
| `config` | 설정 파일의 업로드 한도, 세션 시간, `app.*` 값과 그 값을 읽는 클래스 | `spring.servlet.multipart.max-file-size = 50MB (…컨트롤러 코드에 닿기 전에 요청이 거부된다)` | common |
| `data` | Spring Data 저장소: 구현 코드 없이 이름 규칙으로 동작하는 메서드 | `QnaRepository: JpaRepository 상속. 선언한 메서드 existsByTitle: 구현 코드 없이 …` | common |
| `route` | 컨트롤러 경로 → 처리 메서드, @Valid 검사, 서비스 호출, 분기별 반환 화면·이동 | `POST /qna → QnaController.create. @Valid QnaForm 입력값 검사. 호출 QnaService.create. 반환: 입력값 검사 실패 시 qna/write 화면 / 정상 흐름 redirect:/qna / 예외(IllegalArgumentException) 시 qna/write 화면` | 화면 |
| `template` | 컨트롤러가 넘긴 모델 값을 템플릿(과 포함 조각)이 실제로 출력하는지, @Valid 실패 시 다시 보여 주는 화면에 검증 오류 출력이 있는지 | `모델 값 errorMessage을(를) qna/write 화면에 넘기지만 qna/write 템플릿 어디에서도 출력하지 않음` | 화면 |
| `validation` | 폼 클래스의 검증 애노테이션과 메시지, 그 검사가 언제(제출 후 서버) 어느 경로에서 도는지 | `QnaForm.title: @NotBlank("제목을 입력하세요"), @Size(max=30, …) — 제출 후 서버에서 검사: POST /qna (@Valid)` | 화면 |
| `call` | 서비스 메서드 → 저장소·다른 서비스 호출 | `QnaService.create → QnaRepository.existsByTitle(이름 규칙 쿼리), QnaRepository.save(Spring Data 기본 기능)` | 화면 |
| `message` | 예외로 던지는 문구와 그 조건 | `QnaService.create: qnaRepository.existsByTitle(…) 일 때 IllegalArgumentException("이미 있는 제목입니다.")` | 화면 |
| `js` | 요소별 이벤트와 처리 함수가 바꾸는 것, 파일이 쓰는 이벤트 종류(blur·focusout·submit이 없으면 명시), 그 JS를 불러오는 템플릿 | `#title input 이벤트 → update: saveButton.disabled = !titleInput.value.trim()` | 화면 |
| `html` | 입력란 제약(type=email, maxlength 등)과 브라우저가 대신 하는 일, 조건부로만 보이는 버튼·링크, 처리하는 곳이 없는 링크 | `입력란 title: maxlength=30 (그 이상은 입력되지 않음)` | 화면 |
| `unused` | 어디서도 부르지 않는 경로, 어떤 컨트롤러도 반환하지 않는 템플릿 | `POST /qna/check: 템플릿·JS·리다이렉트·보안 설정 어디에서도 이 주소를 부르지 않음 (미사용 후보)` | 화면 (못 붙으면 common) |

사실은 "어느 코드를 봐야 하는지"를 알려 주는 용도다. ③ 프롬프트는 근거를 반드시 실제 코드 줄로 인용하고, 분석 결과와 코드가 다르면 코드를 따르게 되어 있다.

## ③과 경로·줄 번호를 맞춘 방법

1. **파일 목록**: `backend/specpilot/code_prep.py`의 `load_codebase`를 그대로 불러 쓴다(수정하지 않음). 확장자, 제외 폴더(test, build, gradle 등), `.min.js`, 300KB 기준이 ③과 같다. 백엔드를 불러올 수 없을 때만 같은 규칙을 옮겨 둔 사본(`codebase.py`)을 쓰고, 두 결과가 같은지는 테스트가 확인한다.
2. **줄 번호**: 파일을 디스크에서 다시 읽지 않고, `load_codebase`가 만든 줄 목록을 이어 붙인 글자를 파싱한다. 그래서 사실의 줄 번호가 ③의 `줄번호|`와 같다.
3. **마지막 검사**: 출력 전에 모든 사실이 ③ 코드 묶음 안의 파일·줄인지 다시 확인하고, 아니면 빼고 `_meta.dropped`에 이유를 남긴다.

`load_codebase`의 규칙이 바뀌면 `codebase.py`의 사본도 같이 바꾼다 (테스트 `test_file_list_same_as_backend`가 알려 준다).

## 화면별로 나누는 방법

③은 화면마다 `common` + `screens[화면ID]`를 넣는다. 보안·전역 처리·설정·Spring Data는 항상 `common`이고, 나머지는 그 화면의 템플릿과 이어진 사실만 그 화면으로 간다.

**화면 ↔ 템플릿 (`--requirements`)**
- 화면 이름과 템플릿의 `<title>`, `h1`, `h2`를 맞대 본다. 팝업 화면(`type: "팝업"`)은 부모 화면 템플릿과 이름이 겹쳐서 이름으로 고르지 않는다.
- 그 화면 단위의 원문 문구(`exact.message`), 값, 이동 대상, 따옴표 안 라벨이 템플릿(과 그 템플릿이 불러오는 JS) 글자에 있는지 본다. 백엔드의 `files_mentioning`처럼 공백·기호를 뺀 앞 6글자로 비교해서, 문구가 조금 달라도(=불일치) 찾는다.
- 이미 찾은 화면의 버튼·링크 가운데 설계서의 화면 이동(`flows`, 이동 단위의 target)과 라벨이 맞는 것을 따라가, 그 주소가 정상 흐름에서 보여 주는 템플릿을 이동 대상 화면의 후보로 올린다. 예: 목록 화면의 "질문하기" 링크 → `GET /qna/new` → `qna/write` → 작성 화면.

**템플릿 → 사실**: 그 템플릿과 그 템플릿이 불러오는 JS, 그 템플릿을 보여 주거나 그 템플릿의 폼·링크·JS가 부르는 경로, 그 경로에서 이어지는 서비스 메서드, 그 경로의 폼 클래스에 걸린 사실을 붙인다.

여러 화면이 같이 쓰는 JS는 **이벤트 대상 요소와 처리 함수가 바꾸는 요소가 실제로 있는 템플릿에만** 그 이벤트를 붙이고, 사실에 "(대상 요소가 있는 템플릿: …)"을 적는다. 다른 화면용 코드를 근거로 끌어오는 것을 막기 위해서다.

어느 화면에도 붙지 않은 사실은 버리지 않고 `common`에 넣는다 (`_meta.unplaced_to_common`).

## 한계

- **JavaParser 없이 돌리면 타입 해석이 간이 방식이다.** 오버로딩, 구현이 여럿인 인터페이스, `a.b().c()`, `var`에서 틀리거나 놓칠 수 있다 (위 표). 채점용 결과는 jar를 빌드해서 만든다.
- **라이브러리 classpath 없이 JavaParser를 돌리면** Spring·JPA에서 상속받은 메서드는 풀지 못하고 간이 해석으로 채운다. 필요하면 `--gradle`.
- **Spring MVC + Thymeleaf + 정적 JS 기준이다.** JSP, React·Vue 같은 SPA, Kotlin, 애노테이션 대신 함수형으로 등록한 경로는 아직 읽지 않는다.
- **정적으로만 본다.** 실행해야 알 수 있는 동작(브라우저 기본 동작, 프레임워크 기본값)은 "기본 동작"이라고만 적는다.
- **화면 ↔ 템플릿 대응은 추정이다.** 제목이 같은 템플릿이 둘이면 둘 다 붙는다. 틀리면 `--code-map`으로 사람이 고친 대응표를 주면 된다.
- 사실 문장(`fact`)은 사람이 정한 틀에 코드의 값을 채운 것이다. 문장을 바꾸고 싶으면 `java_facts.py`, `link.py`의 해당 부분을 고친다.

## Java 호출 해석: JavaParser가 기본, tree-sitter는 대신

사실 대부분(경로 애노테이션, 보안 설정 체이닝, 검증 애노테이션, 예외 문구, 템플릿, JS, 설정)은 문법만 보면 나와서 어느 도구로 읽어도 같다.
도구에 따라 달라지는 곳은 **메서드 호출이 어느 클래스의 어느 선언으로 가는지**(타입 해석) 하나다. 서비스 → 저장소 호출, 경로 → 서비스 연결, 화면에 붙일 서비스 메서드가 여기서 정해진다.

| | JavaParser + Symbol Solver | tree-sitter 간이 해석 |
| --- | --- | --- |
| 방식 | 컴파일러처럼 타입을 푼다 | 변수 타입을 매개변수 → 지역 변수 → 필드(부모 클래스 포함) 선언에서 찾는다 |
| 오버로딩 | 인자 타입으로 정확한 선언을 고른다 | 같은 이름의 첫 번째 선언 |
| 구현이 여럿인 인터페이스 | 모든 구현 메서드를 따라간다 | 첫 번째 구현만 |
| `a.b().c()`, `var`, 제네릭 반환, 정적 import | 푼다 | 못 푼다 |
| 라이브러리 메서드 (`--gradle`) | 어느 라이브러리 선언인지까지 푼다 | 구분하지 못한다 |
| 필요한 것 | JDK 17, Maven으로 jar 한 번 빌드 | pip만 |

**어떻게 잇는가** (`javaparser_bridge.py`)
1. ③의 파일 목록(`load_codebase`)에 있는 `.java` 파일을 **그 줄 그대로** `out/.javaparser/src/`에 다시 쓴다. 그래서 해석기가 내는 경로·줄 번호가 ③과 같고, ③이 빼는 테스트·빌드 폴더의 파일도 똑같이 빠진다. 실행이 끝나면 이 사본은 지운다.
2. `java -jar specpilot-javaparser.jar`가 호출마다 "선언한 클래스, 선언 위치, (인터페이스면) 구현 메서드 위치"를 `out/.javaparser/calls.json`에 쓴다. 사실 문장은 만들지 않는다.
3. Python이 tree-sitter로 찾은 호출과 **(파일, 줄, 메서드 이름, 같은 줄 안 순번)**으로 맞춘다. 열 번호는 tree-sitter(바이트)와 JavaParser(글자)가 달라서 쓰지 않는다.
4. JavaParser가 이 코드 안의 선언으로 풀면 그 결과를 쓴다. 라이브러리 선언으로 풀면 화면 사실에서 빼되, Spring Data 저장소의 상속 메서드(`save` 등)는 저장소 이름으로 남긴다. 못 푼 호출(예: Lombok이 만든 getter)만 tree-sitter 간이 해석으로 채운다. 어느 쪽으로 풀었는지 개수가 `_meta.call_resolution`에 남는다.

**엔진 비교** (`--compare-engines`): 같은 코드를 두 엔진으로 분석해서 한쪽에만 있는 사실, 같은 호출을 다른 클래스로 푼 곳을 `out/engine_compare.json`에 남긴다. `--facts`로 각각 판정·채점하면 어느 엔진이 ③ 정확도를 실제로 올리는지 숫자로 볼 수 있다.

**왜 전부 Java로 하지 않는가.** 2주차 `specpilot-analyzer`(JavaParser + Jsoup)를 키워 전부 Java로 만들 수도 있다. 하지만 타입 해석 말고는 Java로 옮겨서 정확해지는 부분이 없다.
- JS는 JavaParser가 읽지 못해 Java용 JS 파서를 따로 들여야 한다.
- ③과 같은 파일 목록을 쓰려면 `load_codebase`를 Java로 다시 짜야 해서, 백엔드가 바뀔 때마다 어긋날 수 있다.
- 테스트도 백엔드와 다른 도구(JUnit)로 따로 돌려야 한다.

그래서 정확도가 갈리는 곳만 JavaParser로 하고, 나머지는 백엔드와 같은 Python에 둔다.

## 파일

| 파일 | 내용 |
| --- | --- |
| `cli.py`, `__main__.py` | 실행 (`python -m code_analysis`) |
| `codebase.py` | ③과 같은 파일 목록 읽기 (`load_codebase` 불러오기, 안 되면 사본) |
| `java_index.py` | Java 파싱(tree-sitter): 클래스·필드·메서드·애노테이션 색인. 호출 대상은 JavaParser 결과를 쓰고 못 푼 것만 간이 해석 |
| `javaparser/` | JavaParser + Symbol Solver 호출 해석기 (Java, Maven). `mvn -q package`로 jar를 만든다 |
| `javaparser_bridge.py` | 해석기 실행: ③과 같은 파일 사본 만들기, `java -jar` 실행, 결과를 호출과 맞추기 |
| `java_facts.py` | `route`, `security`, `global`, `data`, `call`, `message`, `validation` |
| `web_facts.py` | 템플릿 파싱(모델 변수, 검증 오류 출력, 포함 조각, 스크립트, 폼·링크, 입력란), JS 파싱(선택자, 이벤트, 처리 함수가 바꾸는 것, fetch) |
| `link.py` | 파일을 맞대 봐야 나오는 사실: `template`, `js`, `html`, `unused` |
| `config_facts.py` | `config` |
| `screens.py` | 화면별로 나누기 |
| `facts.py` | 사실 모양, ③ 코드 묶음 안인지 검사, 파일 쓰기 |
| `tests/` | 테스트와 가상의 앱(`fixtures/qna-app`, 기업 코드 아님) |

## 테스트

```bash
python -m pytest code_analysis/tests -q        # 21 passed, 1 skipped (jar를 빌드하면 22 passed)
```

API 키도 기업 코드도 필요 없다. JavaParser 연결은 해석기 결과를 손으로 만든 JSON으로 확인하고(`test_javaparser_bridge.py`), jar가 빌드돼 있으면 실제 해석기로도 한 번 돈다. 저장소 폴더에서 `python -m pytest -q`로 돌리면 백엔드 테스트와 함께 돈다.

새 사실 종류를 더할 때는 `tests/fixtures/qna-app`에 그 패턴을 가진 코드를 조금 넣고 `tests/test_code_facts.py`에 확인을 더한 뒤 PR을 올린다. 사실 문장은 ③ 프롬프트에 그대로 들어가므로, 바꾸면 PR 설명에 바꾸기 전후 문장을 적는다.

# SpecPilot 백엔드 가이드 — 구조 설명과 테스트 방법

> 팀원 공유용 문서다. 조장이 가진 정답 세트의 내용은 이 문서에 넣지 않는다.

---

## 1. 한눈에 보기

### 1-1. 파이프라인과 구현 상태

| 단계 | 하는 일 | 쓰는 것 | 상태 |
| --- | --- | --- | --- |
| 입력 점검 | 기획서를 돌려도 되는지 본다. PDF가 열리는지, 글자층이 있는지, 설명표 번호를 찾을 수 있는지, 그림 속 마커와 설명 번호가 맞는지 | 프로그램 (무료) | 완료 |
| ① 앱 프로필 | 기획서 전체를 한 번 읽고 화면 목록, 화면 이동, 공통 영역, 로그인 필요 여부, 역할 같은 **여러 화면에 걸친 정보**를 정리 | LLM 1회 | 완료 |
| 게이트 | ①의 화면↔쪽 대응으로 입력 점검 결과를 화면 단위로 묶어, 문제가 큰 화면은 ②를 돌리지 않음 | 프로그램 (무료) | 완료 |
| ② 화면별 분해 | 화면 하나씩 요구사항을 **최소 단위**로 쪼갬 | LLM 화면 수만큼 | 완료 |
| (합치기·검사) | ①②의 결과를 `requirements.json` 하나로 합치고 검사 | 프로그램 | 완료 |
| ③ 정합성 판정 | 단위마다 소스 코드에 어떻게 구현됐는지 판정 | LLM 화면 수만큼 | 완료 |
| ④ 시나리오 합성 | 단위를 묶어 테스트 시나리오(사양서)를 만듦. ③ 결과와 코드는 쓰지 않음 | LLM 묶음 수만큼 | 완료 (실제 API 실행 전) |

프롬프트는 v3.1을 반영했다. v3.1과 다른 곳은 [`PROMPT_CHANGES.md`](PROMPT_CHANGES.md)에 있다.

### 1-2. 명령과 단계

| 명령 | 하는 단계 | 언제 쓰나 |
| --- | --- | --- |
| `check` | 입력 점검 (+ `--app-profile`을 주면 게이트까지) | 돈 들이기 전에 기획서 상태를 볼 때 |
| `run` | 입력 점검 → ① → 게이트 → ② → 합치기 | 처음 실행할 때 |
| `screen` | (입력 점검) → 게이트 → ② (지정한 화면만) → 합치기 | 프롬프트를 고치고 화면 하나만 다시 볼 때, 기획서를 고친 뒤 그 화면만 다시 돌릴 때(`--pdf`) |
| `merge` | 합치기 | 화면 결과 파일을 직접 고쳤을 때 |
| `judge` | ③ | `requirements.json`이 나온 뒤 코드와 비교할 때 |
| `scenario` | ④ | `requirements.json`이 나온 뒤 테스트 사양서를 만들 때. `--excel-only`는 엑셀만 다시 |
| `trace` | 단계를 거꾸로 | ③ 결과가 이상할 때 원인 단계를 찾을 때 |
| `score` | ③ 채점 | 정답 세트와 비교해 점수를 낼 때 (조장용) |
| `validate` | 검사만 | JSON 파일 하나가 형식에 맞는지 볼 때 |
| `serve` | 웹에서 올린 기획서·코드로 `run` → `judge` → `scenario` | 웹 화면으로 시연할 때 (README "웹으로 시연") |

입력 점검이나 게이트에서 **기획서 전체를 반려하면** 명령이 종료 코드 3으로 멈춘다. 점검 결과를 무시하고 돌리려면 `--force`를 붙인다.

### 1-3. 데이터 흐름

```
기획서.pdf ─(run)─▶ 입력 점검 preflight.json ─▶ ① app_profile.json ─▶ 게이트 gate.json
                                                                        │ 반려 아닌 화면만
                                                   ② screens/화면ID.json ┴─(합치기)─▶ requirements.json
                                                                                         │
                     소스 코드 폴더 ─(judge)──────────────────────────────────────────────┴─▶ ③ judge/화면ID.json
                                                                                                └─(합치기)─▶ judgments.json
                                                                                                             judge_report.json
                                                                   정답 세트 ─(score)─▶ score_report.json, score_review.md, implied_review.md
requirements.json ─(scenario)─▶ ④ scenario/묶음ID.json ─(합치기)─▶ scenarios.json, scenario_report.json, 테스트사양서.xlsx, 추적표.xlsx
                   (③ 결과와 코드는 쓰지 않는다. 둘은 단위 ID로만 이어진다)
```

모든 결과는 `output/<실행ID>/` 폴더 하나에 쌓인다. 단계마다 결과가 파일로 남기 때문에, 어느 단계에서 틀렸는지 거슬러 올라가 볼 수 있다.

### 1-4. 기획서에 문제가 있을 때의 처리 기준

| 문제 | 어디서 | 처리 |
| --- | --- | --- |
| PDF가 안 열림, 암호, 글자층 없음(스캔본), 설명표를 못 찾음(다른 양식), 그림 마커와 번호가 대부분 안 맞음 | 입력 점검 | **전체 반려** (①도 부르지 않음) |
| 한 화면의 그림 마커와 설명 번호가 절반 넘게 안 맞음 | 게이트 | **그 화면만 반려**, 나머지는 진행. 반려 화면이 절반 이상이면 전체 반려 |
| 그림이 조금 잘림(마커 1~2개 없음), 번호가 비어 있음, 어느 화면에도 속하지 않은 쪽, 설계서에 없는 화면으로 가는 이동 | 입력 점검·게이트 | **경고**만 남기고 진행. 그림에 마커가 없던 항목의 단위에는 프로그램이 issue를 붙인다 |
| 화면 항목의 절반 넘게 읽을 수 없음 | ② | ②가 `reject_reason`을 내고 그 화면만 반려 |
| 가벼운 오타(문맥상 뜻이 하나), 이름이 조금 다름 | ② | 바른 뜻으로 읽고 넘어감. 코드와 대조하는 값(문구, 라벨)의 오타·명칭 차이만 issue |
| 설계서가 정하지 않은 것(빈 화면, 활성화 조건, 이동 대상), 서로 맞지 않는 서술 | ② | 지어내지 않고 issue나 질문으로 |

오류가 적은 기획서가 보통이라고 보고, 비용이 드는 LLM 검사를 앞에 따로 두지 않았다. 앞단 검사는 무료인 프로그램 검사만 하고, 화면 단위 문제는 ②가 읽으면서 처리한다. 반려된 화면은 기획서를 고친 뒤 `screen --pdf`로 그 화면만 다시 돌린다(① 결과를 다시 쓰므로 화면 하나 값만 든다).

---

## 2. 파일별 역할 — 단계 순서대로

```
specpilot-backend/
  prompts/          프롬프트 문장 (코드 아님. 프롬프트 담당이 고치는 곳)
  specpilot/        파이썬 코드
  tests/            API 키 없이 돌아가는 테스트 73개
  docs/             이 문서, 프롬프트 변경 정리, 정답 세트 형식 예시
```

### 2-1. 모든 단계가 함께 쓰는 도구

| 파일 | 역할 |
| --- | --- |
| `cli.py` | 명령(run, judge …)을 받아서 아래 파일들을 순서대로 부르는 **지휘자**. 진행 상황을 화면에 찍는다 |
| `__main__.py` | `python -m specpilot`으로 실행되게 하는 입구. `cli.py`를 부르기만 한다 |
| `config.py` | `.env`에서 설정(모델, 재시도 횟수, 반려 기준 등)을 읽는다 |
| `prompts.py` | `prompts/` 폴더의 프롬프트 파일을 읽어 `{{자리표시자}}`를 채운다. 프롬프트를 **고정 부분**(지침·예시, 캐시됨)과 **입력 부분**(`# 입력` 뒤, 실행마다 바뀜)으로 나누고, 고정 부분의 해시를 `prompt_version`으로 남긴다 |
| `llm.py` | Claude API 호출. 고정 부분에 캐시를 걸고, 과부하·네트워크 오류는 SDK가 4번까지 다시 보낸다. 응답에서 JSON을 꺼내는 `parse_json`, 테스트용 가짜 LLM `ScriptedLLM`도 여기 있다 |
| `pdf_utils.py` | PDF 자르기, 글자 읽기. pdftotext가 있으면 **글자마다 좌표**를 받아(`-bbox`) 오른쪽 설명표의 번호 칸과 왼쪽 화면 그림을 나눠 읽는다. 원문 대조(`TextIndex`)도 여기 있다 |
| `stages.py`의 `_call_with_retry` | 모든 LLM 단계가 쓰는 **호출 → JSON 꺼내기 → 검사 → 재시도** 반복. 검사에 걸리면 "직전 출력에 아래 문제가 있다"며 문제 목록을 붙여 같은 대화에서 다시 부른다. 출력이 길이 한도에서 잘린 경우는 다시 불러도 같으므로 재시도하지 않는다 |
| `schema.py` | **검사 규칙과 후처리 전부**. 단계별 검사 함수, ID 붙이기, 함의 검사가 다 여기 있다 |
| `preflight.py` | 입력 점검과 게이트 판정 |

검사 결과는 세 수준으로 나뉜다.
- **error**: 형식이 틀려 다음 단계에서 쓸 수 없거나 근거를 지어냄 → 재시도 사유
- **warning**: 기록만 남김
- **fix**: 프로그램이 직접 고침 (예: 근거가 약한 함의를 질문으로 옮김, 화면 ID를 붙임)

### 2-2. 입력 점검 — `preflight.run_preflight`

| | |
| --- | --- |
| 입력 | 기획서 PDF |
| 출력 | `preflight.json` |

LLM을 부르지 않는다. 순서대로 보고, 기획서가 통째로 깨졌으면 여기서 멈춘다.
1. **PDF 열림**: 깨진 파일, 암호가 걸린 파일 → 전체 반려
2. **글자층**: 쪽마다 글자 수를 센다. 절반 이상이 0이면 스캔 이미지 PDF로 보고 전체 반려. 일부만 0이면 경고
3. **설명표 번호 찾기**: 쪽마다 오른쪽의 한두 글자짜리 숫자·알파벳 중 x 위치가 가장 많이 겹치는 칸을 번호 칸으로 본다. 그 칸의 번호가 그 쪽의 기획서 항목(Description 3, Action E …)이고, **②의 누락 검사 기준(체크리스트)**이 된다. 한 곳도 못 찾으면 지원하지 않는 양식으로 보고 전체 반려
4. **번호 연속성**: 설명 번호가 0부터 빈틈없이 이어지는지, 같은 번호가 두 번 나오지 않는지 → 경고
5. **그림 마커 대조**: 설명표의 번호(0번 제외)가 왼쪽 그림 속 마커로도 있는지 본다. 일치율이 `SPECPILOT_MARKER_MATCH_MIN`(기본 0.5)보다 낮으면 그 쪽을 반려 후보로, 일부만 없으면 경고로 둔다. 그림에 마커 글자가 하나도 없으면(마커가 그림 픽셀로만 들어간 문서) 이 대조는 건너뛴다
6. **전체 판정**: 반려 후보 쪽이 `SPECPILOT_REJECT_RATIO`(기본 0.5) 이상이면 전체 반려

pdftotext가 없으면 좌표를 못 읽어서 3번은 예전 방식(배치 글자의 들여쓰기)으로 하고 4·5번은 건너뛴다. 이때는 반려하지 않고 "poppler 설치 필요" 경고만 남긴다.

샘플 기획서(15쪽)에서는 설명·Action 번호 103개가 모두 나오고, 마커 대조에서는 MYPAGE-001(p.14)의 Description 12·13과 Action B만 걸린다(그림이 잘린 부분). 예전 방식은 같은 문서에서 57~73개만 찾았다.

### 2-3. ① 앱 프로필 — `stages.run_app_profile`

| | |
| --- | --- |
| 입력 | 기획서 PDF 전체 |
| 출력 | `app_profile.json`, `app_profile.meta.json`, `raw/app_profile.attempt1.txt` |
| 프롬프트 | `prompts/app_profile.txt` + 공통 블록(`blocks/`) + 예시(`examples/app_example.json`) + `hints.txt` |

**처리 순서**
1. 프롬프트를 완성한다 (`prompts.py`).
2. PDF 전체를 그대로 붙여 Claude를 부른다. Claude는 페이지마다 **이미지와 글자를 함께** 받으므로, 글자로는 안 뽑히는 머리글의 값도 읽는다 (`pdf_utils.document_block`).
3. 응답에서 JSON을 꺼내고, 화면 ID가 없는 화면에 `SCR-001`…을 붙인다 (`schema.normalize_app_profile`).
4. 검사한다 (`schema.validate_app_profile`).
   - 필수 필드 8개(screens, flows, common_areas, login_required, roles, role_limited, units, questions)
   - 화면마다 screen_id, name, pages가 있는지, pages가 PDF 쪽수 범위 안인지, 화면 ID가 겹치지 않는지
   - 앱 전체 단위와 질문의 형식, key 중복
   - 앱 전체 단위의 quote가 설계서 원문에 있는지
5. 걸리면 문제 목록을 붙여 다시 부른다 (기본 2번 더).
6. key(a01, q01) 대신 최종 ID(`REQ-APP-01`, `Q-APP-01`)를 붙인다 (`schema.assign_ids`).
7. **함의 검사** (`schema.gate_implied`): 근거 원문이 둘 이상이고 원문에 실제로 있고 "확신 낮음" 표시가 없어야 단위로 남긴다. 못 채우면 질문으로 옮기고 원래 단위는 질문의 `draft_unit`에 둔다. 같은 내용의 질문이 이미 있으면 새로 만들지 않고 그 질문에 붙인다.
8. 저장한다. **①이 실패하면 전체를 멈춘다.** 뒤 단계가 모두 ①의 화면 목록을 기준으로 돌기 때문이다.

### 2-4. 게이트 판정 — `preflight.gate_screens`

| | |
| --- | --- |
| 입력 | `preflight.json` + `app_profile.json` |
| 출력 | `gate.json` |

입력 점검은 쪽 단위로만 볼 수 있다. ①이 알려 준 화면↔쪽 대응으로 화면 단위로 묶는다.
- 화면의 그림 마커 일치율이 기준보다 낮으면 **그 화면은 반려**하고 ②를 부르지 않는다 (`screens/화면ID.meta.json`에 상태 "반려"와 이유가 남는다).
- 팝업이 부모 화면의 항목을 되풀이하면(`repeats_from`) 그 항목은 그림에 마커가 없어도 문제로 보지 않는다.
- 반려된 화면이 절반 이상이면 전체 반려.
- 경고: 그림에 없는 번호, 어느 화면에도 속하지 않은 쪽(①이 페이지를 빠뜨렸는지), 이동 대상에 화면 ID가 없거나 설계서에 없는 화면 ID로 가는 이동, ①이 적은 `reading_notes`.

### 2-5. ② 화면별 분해 — `stages.run_screen`

| | |
| --- | --- |
| 입력 | 그 화면의 페이지(잘라 낸 PDF) + ①의 앱 프로필 전체 |
| 출력 | `screens/화면ID.json`, `screens/화면ID.meta.json`, `raw/screen_화면ID.attemptN.txt` |
| 프롬프트 | `prompts/screen_decompose.txt` + 공통 블록 + 예시 두 개(`examples/screen_example.json`, `screen_example_2.json`) |

**처리 순서** (게이트를 통과한 화면마다)
1. 그 화면의 페이지(`pages` + `state_pages`)만 잘라 새 PDF를 만든다 (`pdf_utils.subset_pdf`). `.env`에서 `SPECPILOT_FULL_PDF=true`로 하면 PDF 전체를 보낸다.
2. 프롬프트의 입력 부분에 앱 프로필 전체, 화면 ID, **원본 페이지 번호**를 넣는다. 잘라 붙이면 페이지 번호가 1부터 다시 세어지므로, "상태 화면 p.N"의 N이 원본과 맞도록 알려 주는 것이다.
3. **체크리스트**를 가져온다. 입력 점검에서 찾은 그 화면 페이지의 항목 번호다 (`meta`의 `expected_items`, `checklist_from`).
4. Claude를 부르고 검사한다 (`schema.validate_screen`).
   - 단위마다 필드, kind 8종, origin(명시/함의), source·then이 비어 있지 않은지, exact의 3개 칸, key 중복
   - 질문과 제외 목록(skipped)의 형식
   - **세 군데 대조** (`schema.check_items_seen`): 프로그램 체크리스트 / 모델이 본 항목(`items_seen`) / 실제로 다룬 항목(units·skipped). 체크리스트나 items_seen에 있는데 다루지 않은 항목은 error라서 재시도한다(`SPECPILOT_COVERAGE_STRICT=false`면 경고만). 다룬 항목인데 items_seen에 없거나, 체크리스트에 없는 항목은 경고
   - **원문 대조** (`schema.check_quotes`): quote와 exact.message가 그 화면 페이지(없으면 문서 전체) 글자에 있는지 본다. 띄어쓰기와 따옴표 모양은 무시한다. 원문에 없으면 지어낸 근거로 보고 error(재시도), 한두 글자만 다르면(오타를 고쳐 쓴 정도) 경고. 그림이나 상태 화면이 근거인 단위, pdftotext 없이 읽은 경우는 경고만
5. 모델이 `reject_reason`을 냈으면(화면 항목 절반 이상을 읽을 수 없음) 그 화면은 **반려**로 저장하고 끝낸다.
6. 재시도 후에도 오류가 남으면, 단위·질문을 하나씩 검사해서 오류가 있는 것을 `rejected`로 옮기고(**버리지 않는다**) 상태를 "확인필요"로 둔다. JSON 자체가 안 나오면 "실패"다.
7. 최종 ID(`REQ-LOGIN-001-07`, `Q-LOGIN-001-01`)를 붙이고, 함의 검사를 하고, 입력 점검에서 그림에 마커가 없던 항목의 단위에 issue("입력 점검: 그림에서 … 마커를 찾지 못함")를 붙여 저장한다.

**화면 상태**: 완료 / 확인필요(결과는 있지만 검사를 다 통과하지 못함) / 실패(쓸 수 있는 결과 없음) / 반려(게이트나 ②가 읽을 수 없다고 판단)

### 2-6. 합치기·검사 — `merge.py`

LLM을 쓰지 않는다. 이어 붙이고 검사하는 일이라 프로그램이 더 정확하고 비용도 들지 않는다.

| 출력 | 내용 |
| --- | --- |
| `requirements.json` | 앱 프로필(단위·질문 제외), **단위 전체**(앱 전체 + 화면별), 질문 전체(우선순위 상 먼저), 화면별 제외 목록, 화면별 상태, 반려된 화면과 이유, 검사에서 빠진 단위(`rejected_units`). **③④가 쓰는 파일** |
| `validation_report.json` | 화면 수와 완료·반려 수, 단위·질문 수(우선순위별), kind별·출처별 개수, 입력 점검·게이트 요약, 오류·경고 목록 |

전체 기준으로 한 번 더 보는 것: 결과가 없는 화면(오류), 완료가 아닌 화면(경고), 반려된 화면(경고, 단위에서 뺌), 화면을 넘어 겹치는 ID, 질문이 없는 단위를 가리키는 경우(경고).

### 2-7. ③ 정합성 판정 — `judge.py`, `code_prep.py`

| | |
| --- | --- |
| 입력 | `requirements.json` + 소스 코드 폴더 |
| 출력 | `judge/화면ID.json`(+ meta), `judge/run.json`, `judge/code_map.json`(화면별 묶음일 때), `judgments.json`, `judge_report.json` |
| 프롬프트 | `prompts/judge.txt` + 예시(`examples/judge_example.json`), 화면별 묶음일 때 `prompts/code_select.txt` |

**처리 순서**
1. **코드 모으기** (`code_prep.load_codebase`). 코드 확장자(.java .js .html .yml 등)만 모으고, 테스트·빌드 산출물·라이브러리 폴더(test, build, target, node_modules, gradle 등), `.min.js`, 300KB 넘는 파일은 뺀다.
2. **줄 번호 붙이기.** 파일마다 `=== 파일경로 ===` 머리글을 달고 줄마다 `줄번호|`를 붙인다. 줄마다 경로를 붙이면 경로가 긴 Java 프로젝트에서 토큰이 세 배 가까이 늘어서(샘플 기준 약 8.5만 → 3.4만), 경로는 머리글에 한 번만 쓴다.
3. **크기 재기 → 넣는 방식 고르기** (`judge.choose_mode`). 코드 전체가 `SPECPILOT_CODE_TOKEN_LIMIT`(기본 10만) 이하면 **통째로**(whole), 넘으면 **화면별 묶음**(screen). `--mode`로 강제할 수 있다.
4. **단위 나누기** (`judge.units_by_screen`). 화면 단위는 그 화면으로 보낸다. 앱 전체 단위(REQ-APP-…)는 근거에 화면 ID가 나오는 화면마다 보내고, 어느 화면도 언급하지 않으면 `APP` 묶음으로 모은다(`--screens APP`으로 따로 돌릴 수 있음).
5. (screen 방식일 때만) **화면-코드 대응표** (`judge.build_code_map`). LLM이 파일 목록을 보고 화면마다 파일을 고른다. 목록에 없는 경로는 버리고 `judge/code_map.json`에 저장한다. **이 파일은 사람이 고쳐도 되고, 있으면 다시 만들지 않는다.** 여기에 프로그램이 단위의 문구(앞 6글자)가 들어 있는 파일을 더한다.
6. **판정 호출.** 코드 묶음을 첫 블록(캐시)으로, 화면 ID와 단위 목록을 그다음에 넣는다. 화면별 묶음이면 "필요한 코드가 묶음에 없어 보이면 미구현이 아니라 확인필요로 하라"고 알려 준다.
7. **검사** (`schema.validate_judge`). 받은 단위마다 결과가 하나씩 있는지, status가 구현/불일치/미구현/확인필요 중 하나인지, 구현·불일치에 근거 코드가 있는지. 빠진 단위가 있으면 재시도한다.
8. **근거 줄 대조** (`code_prep.verify_evidence`). LLM이 댄 `파일:줄`에 인용한 코드가 정말 있는지 본다(공백 차이는 무시). 틀리면 구현·불일치를 **확인필요로 내리고** 원래 판정을 `original_status`에 남긴다.
9. **띄어쓰기만 다른 문구** (`judge.relax_spacing`). 불일치 이유가 문구의 띄어쓰기뿐이면 구현으로 바꾸고 원래 판정을 남긴다. 띄어쓰기는 추출 도구마다 달라서 비교하지 않기로 했다.
10. 재시도 후에도 판정이 빠진 단위는 확인필요("판정 누락")로 채운다.
11. **합치기** (`judge.merge_judgments`).
    - 단위별 결과. 앱 전체 단위가 여러 화면에서 판정되면 더 나쁜 쪽을 남긴다.
    - **기획서 항목별 집계** (`schema.aggregate_items`). 같은 항목(예: LOGIN-001 Description 3)에서 나온 단위들의 판정이 모두 같으면 그 판정, 섞이면 **부분구현**.
    - **쪼개기 신호**: 덜 쪼갬(`split_issues`), 너무 쪼갬(`merge_candidates`).
    - 기획서에 없는 구현(`extras`).


**코드 분석 결과 넣기 (`--facts`)**: 코드팀 정적 분석(JavaParser, tree-sitter 등)이 뽑은 사실을 `judge --facts 파일.json`으로 넘기면 화면마다 ③ 프롬프트의 `{{CODE_FACTS}}` 자리에 들어간다. 형식은 `docs/code_facts.example.json`(`common`: 모든 화면, `screens`: 화면ID → 그 화면 사실 목록). 없으면 "(없음)"이 들어가고 지금과 똑같이 돈다. 같은 실행에 `--facts`를 넣은 것과 뺀 것을 각각 채점하면 효과를 숫자로 볼 수 있다.

### 2-8. ④ 시나리오 합성 — `scenario.py`, `excel.py`

| | |
| --- | --- |
| 입력 | `requirements.json`만 (③의 판정 결과와 코드는 쓰지 않는다. 사양서의 예상결과가 코드 동작에 끌려가지 않게) |
| 출력 | `scenario/묶음ID.json`(+ meta), `scenarios.json`, `scenario_report.json`, `테스트사양서.xlsx`, `추적표.xlsx` |
| 프롬프트 | `prompts/scenario.txt` + 예시(`examples/scenario_example.json`) |

**처리 순서**
1. **묶기** (`scenario.build_groups`). 화면마다 한 묶음. 팝업(`type: 팝업`)은 그 팝업을 여는 화면의 묶음에 넣는다(화면 이동 `flows`로 찾고, 없으면 `repeats_from`). 앱 전체 단위는 APP 묶음. kind "제약" 단위는 화면에서 확인할 수 없는 처리 방식이라 빼고(정합성 판정에만 씀) 추적표에 표시한다.
2. **합성 호출.** 단위는 판단에 필요한 칸만 보낸다(`quote`·`source`·`ref_hint`는 뺌. 예상결과를 then·exact로만 쓰게 하고, 다른 화면 값이 기준으로 들어가지 않게). 앱 프로필은 화면 목록·화면 이동·로그인 필요 여부·역할만 넣는다. 시험데이터는 더미로 만든다.
3. **검사** (`scenario.validate_scenarios`). 형식(시험절차·예상결과가 있는지, unit_ids가 목록인지), 묶음에 없는 단위 ID. 걸리면 재시도한다.
4. **커버리지.** 어느 단계에도 들어가지 않은 단위가 있으면 **그 단위만 넣어 한 번 더 요청**한다(`*_gap` 호출). 그래도 없으면 `uncovered`로 남기고 그 묶음은 확인필요.
5. **마무리** (`scenario.finish`). 시나리오 ID(`TC-<묶음>-NN`), 단계 번호, DEPTH(1)(묶음 주 화면의 Depth)·DEPTH(2)(시나리오가 가장 많이 확인하는 화면 이름, APP은 LLM이 적은 기능 이름)는 프로그램이 붙인다. 함의 단위와 issue가 있는 단위를 확인하는 단계에는 비고("함의: …", "확인 필요: …")를 붙인다.
6. **경고** (`scenario.post_checks`). 근거 단위가 없는데 준비 단계도 아닌 단계(지어낸 단계일 수 있음), 단위의 문구(exact.message)가 예상결과에 없는 단계(정상 짝은 제외, 띄어쓰기는 비교하지 않음).
7. **합치기·엑셀** (`scenario.merge_scenarios`, `excel.write_spec`). LLM을 부르지 않는다(`--excel-only`로 따로 돌릴 수 있음). 사양서 엑셀은 기업 샘플 양식 그대로 개정이력, 00. 목차, 메뉴(Depth)별 시나리오 시트만 둔다(정보 칸 + 두 줄 머리글: 시험번호/시나리오명, 시험구분 DEPTH(1)·(2), No, 시험절차, 예상결과, 시험데이터 계정·입력값·비고, 확인결과 O/X). 우리가 더한 열은 근거 요구사항, 데이터 출처다. 판정 결과는 넣지 않는다. 추적표(`excel.write_trace`)는 따로 낸다: 요구사항 단위 전체를 한 줄씩, ③을 돌렸으면 판정·근거 코드, ④ 시나리오·단계, 제약·빠진 단위·아직 안 돌린 화면 표시. 확인 질문은 결과 화면의 "질문 시트" 내보내기로 받는다.

### 2-9. 단계를 가로지르는 도구

| 파일 | 명령 | 하는 일 |
| --- | --- | --- |
| `trace.py` | `trace` | 단위 하나(또는 기획서 항목 하나)를 **기획서 원문**(PDF에서 그 항목만 잘라 냄) → **② 단위** → **③ 판정과 근거 코드**(앞뒤 2줄 포함) → ④ 순서로 한 번에 보여 주고, 원인을 가리는 질문 5개를 붙인다 |
| `score.py` | `score` | ③ 판정을 정답 세트와 **기획서 항목 단위**로 비교해 점수를 낸다. `score_review.md`(전체 비교표 + 틀린 항목의 정답 근거와 AI 판정·근거 코드, 조장 전용)와 `implied_review.md`(함의 단위 O/X 검토지, 공유 가능)도 만든다 |
| `schema.py` | `validate` | JSON 파일 하나만 검사 |
| `server.py` | `serve` | 웹 시연 서버. 올린 PDF(여러 개면 이어 붙임)·코드 zip을 `output/_uploads/<실행ID>/`에 두고 `run`·`judge`·`scenario`를 따로 프로세스로 차례로 부른다. 진행 상태는 실행 폴더의 meta 파일로 만들어 웹(`frontend/src/types/progress.ts` 모양)에 준다 |

---

## 3. 실행 준비

1. **파이썬 3.10 이상**
2. 설치
   ```bash
   pip install -r requirements.txt
   ```
3. **pdftotext 설치 (강력 권장)**: 입력 점검의 그림 마커 대조, 정확한 체크리스트, 원문 대조에 쓴다. 없어도 돌아가지만 이 검사들이 약해진다(경고로만 남음).
   - Windows (PowerShell): `winget install poppler` → 약관 질문에 `Y` → **터미널(VS Code 포함)을 완전히 닫았다가 새로 연다**
   - macOS: `brew install poppler` / Linux: `sudo apt install poppler-utils`
   - 확인: `pdftotext -v`
4. **설정 파일**
   ```bash
   cp .env.example .env      # Windows: copy .env.example .env
   ```
   `ANTHROPIC_API_KEY`를 채운다. 나머지는 기본값으로 시작하면 된다.

| 설정 | 기본값 | 뜻 |
| --- | --- | --- |
| `SPECPILOT_MODEL` | claude-sonnet-5 | 쓰는 모델 |
| `SPECPILOT_MAX_TOKENS` | 32000 | 생각 토큰 + 답 토큰 한도. "잘렸습니다" 오류가 나면 늘린다 |
| `SPECPILOT_THINKING` | adaptive | Sonnet 5는 기본으로 먼저 생각한다. `disabled`면 생각 없이 바로 답한다 |
| `SPECPILOT_EFFORT` | medium | 생각의 양: low / medium / high. 낮출수록 싸고 빠르다 |
| `SPECPILOT_MAX_RETRIES` | 2 | 검사에 걸렸을 때 다시 부르는 횟수 (첫 호출 제외) |
| `SPECPILOT_FULL_PDF` | false | true면 ②에도 PDF 전체를 보냄 |
| `SPECPILOT_COVERAGE_STRICT` | true | 기획서 항목 누락을 재시도 사유로 볼지 |
| `SPECPILOT_QUOTE_STRICT` | true | quote·문구가 원문에 없을 때 재시도할지 (false면 경고만) |
| `SPECPILOT_MARKER_MATCH_MIN` | 0.5 | 그림 마커와 설명 번호가 이 비율보다 적게 맞으면 그 쪽·화면 반려 |
| `SPECPILOT_REJECT_RATIO` | 0.5 | 반려된 쪽·화면이 이 비율 이상이면 기획서 전체 반려 |
| `SPECPILOT_CODE_TOKEN_LIMIT` | 100000 | ③에서 코드를 통째로 넣을 최대 크기 |

5. **설치 확인** (API 키 필요 없음)
   ```bash
   python -m pytest -q        # 73 passed (pdftotext가 없으면 일부는 skipped)
   ```

Windows에서는 `python3` 대신 `python`을 쓰고, 경로에 공백이나 한글이 있으면 따옴표로 감싼다.

---

## 4. 테스트 순서 — 돈 안 드는 것 → 한 화면 → 전체 → 비교 실험

명령은 모두 저장소 폴더에서 실행한다. 아래 예시는 이런 폴더 배치를 기준으로 한다.

```
<저장소 폴더>/        ← 여기서 실행
  inputs/             ← 기업 자료. plan.pdf = 기획서, sample-code/ = 기업 샘플 코드 (.gitignore가 막음)
  output/             ← 실행 결과 (.gitignore가 막음)
../private/           ← 조장만 (저장소 밖). answer_key.json = 정답 세트
```

기획서 파일 이름은 영어(`plan.pdf`)로 바꿔 두면 경로 문제가 줄어든다. 샘플 코드 폴더 이름을 `specpilot`으로 두지 않는다(백엔드 코드 폴더와 섞인다).

### 0단계: 설치 확인 (무료)
`python -m pytest -q`. 검사 규칙, 재시도, 입력 점검, 근거 줄 대조, 집계, 채점이 의도대로 도는지 가짜 LLM으로 확인한다.

### 1단계: 입력 점검과 프롬프트 미리보기 (무료)
```bash
python -m specpilot check --pdf inputs/plan.pdf
python -m specpilot run --pdf inputs/plan.pdf --dry-run --name preview
```
`check`는 기획서 항목 수와 경고(그림에 없는 번호 등)를 보여 준다. `output/preview/prompts_preview/app_profile.txt`에 실제로 보낼 프롬프트가 저장된다.

### 2단계: ①과 한 화면만 (첫 유료 실행)
```bash
python -m specpilot run --pdf inputs/plan.pdf --screens LOGIN-001 --name t1
```
볼 것:
- 콘솔: `[입력 점검]`, `① 앱 프로필: 화면 N개`, `[게이트]`, `② LOGIN-001: 완료 (시도 1)`
- `app_profile.json`의 화면 목록이 기획서와 맞는지 (화면 수, 화면마다 페이지). 게이트가 "어느 화면에도 속하지 않은 쪽"을 경고하면 ①이 페이지를 빠뜨린 것
- `screens/LOGIN-001.json`을 열어 단위가 기획서 항목을 고르게 덮는지
- `screens/LOGIN-001.meta.json`의 `attempts`, `retry_reasons`(재시도했다면 이유), `usage`(토큰), `expected_items`(체크리스트), `items_seen`(모델이 본 항목), `issues`(원문 대조 경고, 함의 이동)
- `validation_report.json`에서 **나머지 화면이 "결과가 없습니다" 오류로 나오는 건 정상**이다 (안 돌렸으니까)

### 3단계: 그 화면의 ③
```bash
python -m specpilot judge --run output/t1 --code inputs/sample-code --screens LOGIN-001
python -m specpilot trace --run output/t1 --item "LOGIN-001 Description 3"
```

### 4단계: 전체
①을 다시 부르지 않도록 2단계의 앱 프로필을 재사용한다.
```bash
python -m specpilot run --pdf inputs/plan.pdf --app-profile output/t1/app_profile.json --name full
python -m specpilot judge --run output/full --code inputs/sample-code
python -m specpilot judge --run output/full --code inputs/sample-code --screens APP   # 화면을 언급하지 않은 앱 전체 단위가 있으면
```
상태가 확인필요나 실패인 화면은 `screen` 명령으로 그 화면만 다시 돌린다. 반려된 화면은 기획서를 고친 뒤 `screen --pdf 고친기획서.pdf --screen 화면ID`로 다시 돌린다 (쪽 수가 같아야 한다).

### 5단계: 채점 (조장)
```bash
python -m specpilot score --run output/full --key ../private/answer_key.json
```
정답 세트 형식은 `docs/answer_key.example.json`을 본다. **정답 세트는 팀 저장소에 올리지 않는다.**
API를 부르지 않으므로 몇 번을 돌려도 무료다. 결과는 세 파일이다.
- `score_review.md`: 맨 위에 전체 항목 비교표(항목 / 정답 / AI / 결과), 그 아래에 정답과 다른 항목마다 정답 근거와 AI가 쪼갠 단위별 판정·설명·근거 코드. **원인 분석은 이 파일 하나로 한다.** 정답이 들어 있어 공유 금지
- `implied_review.md`: 함의 단위마다 근거·추론·판정과 O/X 칸. 정답이 없어 프롬프트 담당과 공유해도 된다
- `score_report.json`: 위 두 파일의 원본 데이터. 정답 포함, 공유 금지

### 6단계: 비교 실험
| 실험 | 방법 | 보는 것 |
| --- | --- | --- |
| 코드가 커지면? | 같은 실행에 `judge --mode whole`과 `judge --mode screen`을 각각 돌려 결과 비교 | 두 방식의 채점 결과가 비슷하면 "화면별 묶음으로도 같은 결과"라는 근거 |
| 프롬프트를 고치면? | 프롬프트 수정 → 같은 화면을 `screen`·`judge`로 다시 → 채점 | meta의 `prompt_version`이 바뀐 전후로 지표 비교 |
| 결과가 안정적인가? | 같은 화면을 3번 돌려 단위 수, 함의 단위 집합, 판정 비교 | 실행마다 크게 달라지는 화면이 기준이 애매한 곳 |

---

## 5. 평가지표

### 5-1. 핵심 지표 — ③ 결과 vs 정답 세트 (`score`)

| 지표 | 계산 | 뜻 |
| --- | --- | --- |
| **결함 탐지율** | 정답 세트의 결함(불일치·미구현·부분구현) 중 ③도 결함으로 판정한 비율 | 높을수록 좋다. **가장 중요한 숫자** |
| **오탐** | 정답이 구현인데 ③이 결함으로 판정한 개수 | 낮을수록 좋다 |
| 정밀도 | ③이 결함이라고 한 것 중 실제 결함인 비율 | 오탐을 비율로 본 것 |
| 판정 완전 일치 | 불일치·미구현까지 정확히 맞힌 비율 | 탐지율보다 엄격한 기준 |
| 확인필요로 보류 | 정답 세트 항목 중 ③이 확인필요로 둔 개수 | 너무 많으면 판정을 피하는 것 |
| 판정 안 됨 | 정답 세트 항목인데 판정 결과 자체가 없는 개수 | ②에서 그 항목을 빠뜨렸거나 화면을 안 돌린 것(반려 포함) → score가 이유를 붙임(함의로만 나옴, 질문으로 감, skipped, rejected, 화면 반려) |

**채점 기준: 명시 단위만.** 정답 세트는 기획서에 적힌 것만 보고 정했으므로, 항목 판정도 명시 단위만 모아 계산한다. 함의 단위는 근거 항목 여러 개에 판정이 퍼져 추론이 맞아도 오탐이 되므로 채점하지 않고, `implied_review.md` 검토지로 따로 낸다. 단위마다 '추론이 정당한가', '판정이 맞나'를 O/X로 채워 "함의 N개 중 M개 맞음"으로 보고한다.

분류 오류는 따로 비교하지 않아도 드러난다: 지어낸 내용을 명시로 붙이면 **오탐**, 명시 내용을 함의·질문으로 보내면 **판정 안 됨**(이유 표시), 정해지지 않은 것을 함의로 정하면 **함의 검토**, 확실한 것을 질문으로 보내면 **질문 시트**에서 보인다.

### 5-2. 단계별 진단 지표 — 문제가 어느 단계인지 가리기

| 단계 | 지표 | 어디서 보나 | 판단 |
| --- | --- | --- | --- |
| 입력 | 입력 점검·게이트 경고 | `preflight.json`, `gate.json`, `validation_report.json`의 `input` | 반려·경고가 나온 쪽을 기획서에서 직접 확인 |
| ① | 화면 수 | `app_profile.json` | 기획서의 화면 ID 개수와 같아야 함 |
| ① | 페이지 누락 | `gate.json`의 "어느 화면에도 속하지 않은 쪽" | 0이어야 함 |
| ② | 화면 상태 | `validation_report.json` | 모두 완료가 목표 |
| ② | 시도 횟수, 재시도 사유 | `screens/*.meta.json`의 `attempts`, `retry_reasons` | 어떤 오류로 재시도가 많은지 → 프롬프트를 고칠 곳 |
| ② | 커버리지 누락 | meta의 `issues` | 0이 목표 |
| ② | 원문 대조 경고 | meta의 `issues` 중 "원문과 한두 글자 다릅니다" | 많으면 모델이 quote를 고쳐 쓰는 것 |
| ② | 함의 → 질문 이동 | meta의 `issues` 중 level "fix" | 많으면 프롬프트가 함의를 너무 쉽게 만드는 것 |
| ② | 검사에서 빠진 단위 | `requirements.json`의 `rejected_units` | 0이 목표 |
| ③ | **근거 불일치** | `judge_report.json`의 `evidence_failures` | 0에 가까워야 함. LLM이 근거를 지어낸 횟수 |
| ③ | 띄어쓰기만 다른 문구 | `spacing_only` | 참고용 |
| ③ | **판정 갈림** (덜 쪼갬) | `split_issues` | 0에 가까울수록 ②의 쪼개기가 적절 |
| ③ | **합칠 후보** (너무 쪼갬) | `merge_candidates` | 0에 가까울수록 적절 |
| ③ | 확인필요 비율 | `by_status` | 너무 높으면 판정을 피하는 것 |
| ③ | 판정 안 된 단위 | `units_not_judged` | 실패한 화면이나 안 돌린 묶음 |
| ③ | 기획서에 없는 구현 | `extras` | 참고용 |
| 공통 | 토큰 사용량, 캐시 | 각 meta의 `usage` | `cache_read_input_tokens`가 0보다 크면 캐시가 동작하는 것 |

### 5-3. 실험 기록표

| 실행ID | 날짜 | 바꾼 것 (prompt_version) | 결함 탐지율 | 오탐 | 근거 불일치 | 판정 갈림 | 합칠 후보 | 재시도 화면 수 | 토큰 | 메모 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

---

## 6. 결과가 이상할 때

| 증상 | 볼 곳 | 조치 |
| --- | --- | --- |
| 기획서 전체가 반려됨 | 콘솔의 `[입력 점검]`·`[게이트]`, `preflight.json` | 이유대로 기획서를 고친다. 점검이 틀렸다고 보면 `--force`로 돌리고, 기준은 `SPECPILOT_MARKER_MATCH_MIN`·`SPECPILOT_REJECT_RATIO`로 조정 |
| 화면이 반려 | `screens/화면ID.meta.json`의 `reject_reason` | 기획서를 고친 뒤 `screen --pdf 고친기획서.pdf --screen 화면ID`. 기획서가 맞는데 반려됐으면 `screen --force` |
| 화면이 확인필요 | `screens/화면ID.meta.json`의 `issues`, `retry_reasons`, 결과 파일의 `rejected` | 어떤 검사에 걸렸는지 보고 프롬프트나 기준 수정 |
| 화면이 실패 | `raw/screen_화면ID.attemptN.txt` | LLM이 실제로 뭘 냈는지 확인 (JSON이 깨졌는지, 설명만 했는지) |
| "잘렸습니다" 오류 | meta의 `issues`, `usage.thinking_tokens` | 생각 토큰이 대부분이면 `SPECPILOT_EFFORT=low` 또는 `SPECPILOT_THINKING=disabled`, 아니면 `SPECPILOT_MAX_TOKENS` 늘리기 |
| "원문에 없습니다"로 재시도가 많음 | meta의 `retry_reasons` | quote를 지어내거나 줄여 쓰는 것. 그림 글자처럼 원문 대조가 어려운 문서면 `SPECPILOT_QUOTE_STRICT=false` |
| 커버리지 누락이 이상함 | meta의 `expected_items` vs 기획서 | pdftotext가 설치됐는지(`text_extractor`) 확인. 그래도 이상하면 `SPECPILOT_COVERAGE_STRICT=false` |
| ③ 판정이 정답과 다름 | `trace --unit` 또는 `trace --item` | 원인 질문 1~5로 단계를 가린 뒤 그 단계 수정 |
| 근거 불일치가 많음 | `judgments.json`의 `evidence_problems` | 줄 번호를 잘못 세는지, 없는 파일을 대는지 보고 ③ 프롬프트 수정 |
| 화면별 묶음에서 확인필요가 많음 | `judge/code_map.json` | 빠진 파일을 직접 넣고 다시 `judge` |
| API 오류로 중간에 멈춤 | 콘솔 | 끝난 화면은 남아 있으니 `screen --screen 남은화면들`로 이어서 |

**trace의 원인 질문**
1. 기획서 항목이 ② 결과에 있나? → 아니오면 ② 누락 (또는 ①이 화면 페이지를 잘못 묶음, 화면이 반려됨)
2. 단위 내용(then, exact)이 기획서 원문과 같나? → 아니오면 ② 읽기 오류
3. 단위 하나에 결과가 하나인가? → 아니오면 ② 쪼개기 문제
4. 판정에 필요한 코드가 ③ 입력에 들어갔나? → 아니오면 코드 묶기 문제
5. 1~4가 모두 예인데 판정이 틀렸다면 → ③ 프롬프트 문제

---

## 7. 알려진 한계

- **실제 API로는 v3.1 프롬프트를 아직 돌려 보지 않았다.** 가짜 LLM, 샘플 기획서의 실제 글자, 가상의 응답으로 흐름(입력 점검 → ① → 게이트 → ② → 합치기)과 검사를 확인했다. 한 화면부터 돌린다.
- 설명표 번호 찾기와 그림 마커 대조는 이 기획서 형식(오른쪽 설명표, 숫자·알파벳 번호, 글자로 된 마커)에 맞춰져 있다. 형식이 다르면 "지원하지 않는 양식"으로 반려되거나 마커 대조를 건너뛴다. 이때 `--force`로 돌릴 수 있다.
- 그림 속에 마커와 같은 숫자(날짜, 쪽 번호)가 있으면 잘린 마커를 놓칠 수 있다. 마커 대조는 경고용으로 본다.
- 재실행할 때 단위 ID를 이어받지 않는다. 같은 화면을 다시 돌리면 단위 수가 바뀔 때 ID도 바뀐다.
- 토큰 수는 어림값이다(영문 4글자 = 1토큰, 한글 1글자 = 1토큰으로 넉넉히 잡음).
- 화면별 묶음 방식은 샘플 코드가 작아서 기본으로는 쓰이지 않는다.
- ④는 가짜 LLM과 실제 `requirements.json`(단위 167개)으로 흐름과 엑셀만 확인했다. 실제 API로는 한 묶음부터 돌린다.
- ④의 시험데이터는 더미만 만든다. 기업 샘플처럼 실제 계정을 넣으려면 코드에서 값을 가져와야 한다(예정).

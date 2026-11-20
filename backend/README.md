# SpecPilot 백엔드 — 입력 점검 → ① 앱 프로필 → 게이트 → ② 화면별 분해 → 합치기·검사 → ③ 정합성 판정 / ④ 시나리오 합성

기획서 PDF를 넣으면 요구사항 단위 목록(`requirements.json`)이 나오고, 소스 코드를 함께 주면 단위마다 정합성 판정(`judgments.json`)이 나온다.
④ 시나리오 합성은 같은 단위 목록으로 테스트 사양서(`테스트사양서.xlsx`, 기업 샘플 양식)를 만든다. ③의 판정 결과와 코드는 쓰지 않는다.
요구사항 → ③ 판정 → ④ 시험 단계를 한 줄로 잇는 추적표(`추적표.xlsx`)는 사양서와 따로 나온다.
웹 화면(`frontend/`)에서 기획서와 코드를 올려 ①~④를 한 번에 돌리려면 시연 서버(`serve`)를 켠다 → [웹으로 시연](#웹으로-시연-specpilotserverpy).

**자세한 구조 설명, 테스트 순서, 평가지표는 [`docs/GUIDE.md`](docs/GUIDE.md)를 본다.**
프롬프트는 v3.1을 반영했고, v3.1과 다른 곳은 [`docs/PROMPT_CHANGES.md`](docs/PROMPT_CHANGES.md)에 있다.

## 설치

처음 한 번만 하면 된다.

1. **Python 3.10 이상** 설치
2. **poppler 설치** (PDF 좌표를 읽는 `pdftotext`가 들어 있다)
   - Windows (PowerShell): `winget install poppler`
     - Microsoft Store 약관 질문이 나오면 `Y`
     - 설치 후 **터미널(VS Code 포함)을 완전히 닫았다가 새로 연다**. 안 그러면 PATH가 반영되지 않는다.
   - macOS: `brew install poppler`
   - Linux: `sudo apt install poppler-utils`
   - 확인: `pdftotext -v` 에 버전이 나오면 성공
3. 패키지 설치 (이 폴더에서)
   ```bash
   pip install -r requirements.txt
   ```
4. API 키 설정
   ```bash
   cp .env.example .env        # Windows: copy .env.example .env
   ```
   `.env`에 `ANTHROPIC_API_KEY=본인 키`를 채운다. 키는 **사람마다 따로 발급**하고, 공유하거나 커밋하지 않는다.
5. 설치 확인 (API 키 필요 없음)
   ```bash
   python -m pytest -q         # 73 passed 이면 정상
   ```
   `65 passed, 8 skipped`가 나오면 poppler를 못 찾은 것이니 2번을 다시 확인한다.

poppler 없이도 돌아가지만, 입력 점검의 그림 마커 대조와 quote 원문 대조가 경고로만 남아서 결과가 사람마다 달라질 수 있다. 같이 돌려볼 때는 모두 설치하는 것을 권장한다.

### 입력 파일 두는 곳

```
<저장소 폴더>/        ← 명령은 모두 여기서 실행
  inputs/             ← 기획서 PDF, 샘플 코드 폴더 (.gitignore가 막아서 올라가지 않음)
  output/             ← 실행 결과 (올라가지 않음)
  .env                ← API 키 (올라가지 않음)
../private/           ← 조장만. 정답 세트 answer_key.json (저장소 밖)
```

- 기획서 파일 이름은 영어(`plan.pdf`)로 바꿔 두면 경로 문제가 줄어든다.
- 샘플 코드 폴더 이름을 `specpilot`으로 두지 않는다. 백엔드 코드 폴더(`specpilot/`)와 이름이 같아 섞인다. 예: `inputs/sample-code`
- 커밋 전에 `git status`로 `.env`, `inputs`, `output`, PDF가 목록에 없는지 확인한다.

## 실행

```bash
# 입력 점검만 (API 호출 없음, 무료): 기획서 항목 수, 그림에 없는 번호 등
python -m specpilot check --pdf inputs/plan.pdf

# 전체 실행 (입력 점검 → ① → 게이트 → ② → 합치기)
python -m specpilot run --pdf inputs/plan.pdf

# API 호출 없이 실제로 들어갈 프롬프트만 확인 (output/<실행ID>/prompts_preview/)
python -m specpilot run --pdf inputs/plan.pdf --dry-run --app-profile 기존/app_profile.json

# 입력 점검·게이트에서 반려돼도 그대로 돌리기
python -m specpilot run --pdf inputs/plan.pdf --force

# 프롬프트 고친 뒤 화면 하나만 다시 → 자동으로 다시 합침
python -m specpilot screen --run output/20261005-2030 --screen NOTICE-001

# 기획서를 고친 뒤 반려됐던 화면만 다시 (쪽 수가 같아야 함. ①은 그대로 씀)
python -m specpilot screen --run output/20261005-2030 --screen MYPAGE-001 --pdf inputs/plan-v2.pdf

# ①은 그대로 두고 ②만 새로 (① 비용 아끼기)
python -m specpilot run --pdf inputs/plan.pdf --app-profile output/20261005-2030/app_profile.json

# ③ 정합성 판정 (코드 크기를 재서 통째로 / 화면별 묶음을 자동 선택)
python -m specpilot judge --run output/20261005-2030 --code inputs/sample-code
python -m specpilot judge --run output/20261005-2030 --code inputs/sample-code --mode screen   # 화면별 묶음 강제
python -m specpilot judge --run output/20261005-2030 --code inputs/sample-code --facts code_facts.json   # 코드팀 정적 분석 결과를 같이 넣기 (형식: docs/code_facts.example.json)

# ④ 시나리오 합성: 단위를 묶어 테스트 사양서를 만든다 (코드·판정 결과는 보지 않음)
python -m specpilot scenario --run output/20261005-2030
python -m specpilot scenario --run output/20261005-2030 --screens LOGIN-001   # 그 화면이 든 묶음만 (APP도 됨)
python -m specpilot scenario --run output/20261005-2030 --excel-only          # 지난 결과로 엑셀만 다시 (무료)

# 웹으로 시연: 웹에서 올린 기획서·코드로 run → judge → scenario를 차례로 돌리는 서버 (아래 "웹으로 시연")
python -m specpilot serve

# 결과가 틀렸을 때 거꾸로 따라가기: 기획서 원문 → ② 단위 → ③ 판정·근거 코드 → 원인 질문
python -m specpilot trace --run output/20261005-2030 --unit REQ-LOGIN-001-07
python -m specpilot trace --run output/20261005-2030 --item "LOGIN-001 Description 3"

# ③ 채점 (조장 전용): 정답 세트와 기획서 항목 단위로 비교. API를 부르지 않아 무료
#   → score_review.md(정답과 AI 판정 나란히, 공유 금지), implied_review.md(함의 O/X 검토지, 공유 가능)
python -m specpilot score --run output/20261005-2030 --key ../private/answer_key.json

# 합치기·검사만 다시 / JSON 파일 하나만 검사
python -m specpilot merge --run output/20261005-2030
python -m specpilot validate --screen-file screens/NOTICE-001.json --screen-id NOTICE-001

# 테스트 (API 키 필요 없음, 73개. pdftotext가 없으면 일부는 건너뜀)
python -m pytest -q
```

입력 점검이나 게이트에서 기획서 전체를 반려하면 종료 코드 3으로 멈춘다.

## 결과 폴더

```
output/<실행ID>/
  run.json                  모델, 옵션, 원본 PDF 경로 (screen --pdf로 바꾼 기록 포함)
  input.pdf                 실행에 쓴 PDF 사본 (화면만 다시 돌릴 때 사용)
  preflight.json            입력 점검 결과: 쪽마다 기획서 항목 번호(체크리스트), 그림 마커 대조, 경고·반려 이유
  app_profile.json          ① 결과
  app_profile.meta.json     ① 시도 횟수, 토큰 사용량, 프롬프트 버전, 검사 결과
  gate.json                 게이트 판정: 화면마다 통과/경고/반려, 이동 대상 경고, ①이 적은 메모
  screens/LOGIN-001.json    ② 결과 (검사에서 빠진 단위는 rejected에 남음)
  screens/LOGIN-001.meta.json
  raw/                      LLM 원본 응답 (시도마다)
  requirements.json         합친 결과 → ③④가 쓰는 파일
  validation_report.json    화면별 상태, 단위 수, 입력 점검 요약, 검사 결과
  judge/run.json            코드 위치, 코드 크기, 고른 방식(whole/screen)
  judge/code_map.json       화면별 묶음일 때 화면 ↔ 코드 파일 대응표 (사람이 고쳐도 됨. 있으면 다시 만들지 않음)
  judge/LOGIN-001.json      ③ 판정 결과 (+ .meta.json)
  judgments.json            단위별 판정 + 기획서 항목별 집계(부분구현) + 기획서에 없는 구현
  judge_report.json         판정 개수, 근거 불일치, 띄어쓰기만 다른 문구, 쪼개기 신호
  scenario/LOGIN-001.json   ④ 묶음별 시나리오 (+ .meta.json). 팝업은 여는 화면 묶음에, 앱 전체 단위는 APP.json
  scenarios.json            ④ 시나리오 전체 (결과 화면의 사양서 탭이 읽음). 못 넣은 단위·제약이라 뺀 단위 목록
  scenario_report.json      시나리오·단계 수, 단위 커버리지, 경고
  테스트사양서.xlsx          기업 양식 사양서: 개정이력, 목차, 메뉴(Depth)별 시나리오 시트
  추적표.xlsx               요구사항 단위 전체 → ③ 판정·근거 코드(돌렸으면) → ④ 시나리오·단계, 제약·빠진 단위 표시
  score_report.json         채점 원본: 요약 숫자, 항목별 정답·판정 (정답 포함, 공유 금지)
  score_review.md           전체 항목 비교표 + 틀린 항목의 정답 근거와 AI 판정·근거 코드 (정답 포함, 공유 금지)
  implied_review.md         함의 단위 O/X 검토지 (정답 없음, 프롬프트 담당과 공유 가능)
  job.json, server.log      웹에서 올려 돌린 실행만: 프로젝트 이름·작업 상태, 단계별 출력

output/_uploads/<실행ID>/   웹에서 올린 기획서 PDF(여러 개면 plan.pdf로 이어 붙임)와 코드 zip·압축 푼 코드
```

## 기획서에 문제가 있을 때

- **전체 반려** (입력 점검, ① 전): PDF가 안 열림, 암호, 글자층 없음(스캔본), 설명표를 못 찾음(다른 양식), 그림 마커와 설명 번호가 대부분의 쪽에서 안 맞음
- **화면 반려** (게이트, ① 후): 그 화면의 그림 마커와 설명 번호가 절반 넘게 안 맞음. ②를 부르지 않는다. 반려 화면이 절반 이상이면 전체 반려
- **경고만**: 그림이 조금 잘림, 번호가 비어 있음, 어느 화면에도 속하지 않은 쪽, 설계서에 없는 화면으로 가는 이동
- **②가 처리**: 가벼운 오타는 문맥으로 해석하고 넘어감. 정하지 않은 것(빈 화면, 활성화 조건)은 지어내지 않고 issue나 질문. 항목 절반 이상을 읽을 수 없으면 그 화면만 반려(`reject_reason`)

LLM 검사를 앞에 따로 두지 않은 이유는 [`docs/GUIDE.md`](docs/GUIDE.md) 1-4절에 있다.

## ③ 정합성 판정 (`specpilot/judge.py`, `code_prep.py`)

1. **코드 모으기**: 코드 확장자만, 테스트·빌드 산출물·라이브러리·`.min.js`는 뺀다.
2. **크기 재기**: `SPECPILOT_CODE_TOKEN_LIMIT`(기본 10만) 이하면 **통째로**(화면마다 같은 코드라 캐시됨), 넘으면 **화면별 묶음**.
3. **화면별 묶음**: 프로그램이 화면마다 파일을 고른다(`code_scope.py`, LLM 호출 없음). 단위 문구·화면 이름이 든 파일과 code_analysis의 도달 정보에서 출발해 템플릿 → JS·CSS·컨트롤러, Java → 쓰는 클래스로 참조를 따라가고, 결과와 이유를 `code_map.json`에 남긴다.
4. **근거 줄 대조**: LLM이 댄 `파일:줄`에 그 코드가 실제로 있는지 본다. 없으면 구현·불일치를 확인필요로 내린다(`original_status`에 원래 판정을 남김).
5. **띄어쓰기**: 문구가 띄어쓰기만 다르면 불일치가 아니라 구현으로 본다(원래 판정을 남김).
6. **항목별 집계**: 같은 기획서 항목에서 나온 단위들의 판정이 섞이면 부분구현.

### 쪼개기가 적절했는지 보는 신호 (`judge_report.json`)

| 신호 | 뜻 | 어디서 나오나 |
| --- | --- | --- |
| `split_issues` | **덜 쪼갬**: 한 단위 안에서 판정이 갈림 | ③이 판정하면서 `split_issue` 칸에 적음 |
| `merge_candidates` | **너무 쪼갬**: 행동·판정·근거 코드 줄이 모두 같은 단위 쌍 | 프로그램이 계산 |

## ④ 시나리오 합성 (`specpilot/scenario.py`, `excel.py`)

1. **묶기**: 화면마다 한 묶음. 팝업은 그 팝업을 여는 화면(화면 이동 `flows`, 없으면 `repeats_from`)의 묶음에 넣고, 앱 전체 단위는 APP 묶음. kind "제약"은 화면에서 확인할 수 없어 사양서에 넣지 않는다.
2. **합성 호출**: 묶음마다 단위(`then`·`exact` 등. `quote`·`ref_hint`는 빼고 보냄)와 앱 프로필 요약을 넣는다. 예상결과는 단위의 then·exact로만 쓰고, 계정·입력값은 더미로 만든다.
3. **검사**: 형식, 묶음에 없는 단위 ID(재시도). 어느 단계에도 들어가지 않은 단위가 있으면 **그 단위만 다시 요청**하고, 그래도 없으면 `uncovered`로 남긴다.
4. **마무리**: 시나리오 ID(`TC-<묶음>-NN`), 단계 번호, DEPTH(1)(기획서 Depth)·DEPTH(2)(화면 이름)는 프로그램이 붙인다. 함의 단위·issue가 있는 단위를 확인하는 단계에는 비고를 붙인다. 근거 단위 없는 단계, 문구가 예상결과에 없는 단계는 경고.
5. **엑셀**: 기업 샘플 양식(정보 칸, 두 줄 머리글, 시험데이터 = 계정/입력값/비고, 확인결과 빈칸)에 근거 요구사항·데이터 출처 열을 더했다. 판정 결과는 넣지 않는다.

## 웹으로 시연 (`specpilot/server.py`)

웹에서 기획서 PDF와 소스 코드(zip 또는 저장소 주소)를 올리면 서버가 명령어와 똑같이 `run`(입력 점검 → ① → 게이트 → ②) → `judge`(③) → `scenario`(④)를 차례로 돌린다. 진행 화면은 실행 폴더에 단계마다 남는 파일로 상태를 보여 주고, 끝나면 그 실행의 결과 화면이 열린다.

```bash
# 터미널 1 (backend 폴더): 시연 서버. .env의 API 키를 쓴다
python -m specpilot serve                 # http://127.0.0.1:8765, ② 동시 호출 2개
python -m specpilot serve --workers 4     # ② 동시 호출 수
python -m specpilot serve --code-facts    # ③ 전에 code_analysis(코드팀 정적 분석)를 돌려 --facts로 넣기

# 터미널 2 (frontend 폴더): 웹. /api 요청을 시연 서버로 넘긴다
npm run dev
```

- 실행 ID는 `demo-<날짜>-<시각>`이고 결과는 명령어로 돌린 것과 같은 `output/<실행ID>/`에 쌓인다. 웹의 "최근 분석"에는 `output/`의 실행이 바로 보인다 (명령어로 돌린 실행 포함).
- **한 번에 하나만** 돌린다. 진행 중에 또 올리면 거절한다. 서버를 끄면 돌던 분석은 중단되고, 다시 켜면 실패로 표시된다.
- 기획서를 반려하면(입력 점검·게이트) 진행 화면에 이유가 나오고 멈춘다. 단계가 실패하면 `output/<실행ID>/server.log`를 본다.
- 걸리는 시간은 명령어로 돌릴 때와 같다 (기획서 화면 수에 따라 수십 분).
- 서버 주소와 응답 형식은 프론트가 정한 것을 따른다 (`frontend/src/api/api.ts`, `frontend/src/types/progress.ts`).

## 프롬프트 수정 (프롬프트 담당)

프롬프트 문장은 전부 `prompts/`에 있고 코드는 `{{자리표시자}}`만 채운다. 프롬프트를 고칠 때 코드는 건드리지 않는다.

| 파일 | 내용 |
| --- | --- |
| `app_profile.txt` | 프롬프트 ① |
| `screen_decompose.txt` | 프롬프트 ② (예시 1·2의 입력 화면 글자 포함) |
| `judge.txt` | 프롬프트 ③ (판정) |
| `scenario.txt` | 프롬프트 ④ (시나리오 합성). 예시는 `examples/scenario_example.json` |
| `blocks/reading_guide.txt` · `implied_rule.txt` · `unit_schema.txt` | 공통 블록 (①②에 같이 들어감) |
| `examples/*.json` | 출력 예시 (테스트의 정상 입력으로도 쓰임. 예시 quote가 예시 입력 글자에 그대로 있는지도 테스트함) |
| `hints.txt` | ①이 앱 전체 질문을 만들 때 참고할 후보 (비워 둬도 됨. 정답 세트 내용은 넣지 않는다) |

- 템플릿의 **마지막 `# 입력` 제목 앞은 고정 부분**(캐시됨), 뒤는 실행마다 바뀌는 부분이다. 화면마다 바뀌는 값은 `# 입력` 뒤에만 둔다.
- 고정 부분의 해시가 `prompt_version`으로 meta 파일에 남는다. 고치기 전후 결과를 비교할 때 쓴다.
- LLM은 응답 안 번호(key: u01, a01, q01)만 쓰고, 최종 ID(REQ-…, Q-…)는 프로그램이 붙인다.
- `unit_schema.txt`의 필드를 바꾸면 `specpilot/schema.py`도 같이 바꿔야 한다. 둘이 합의하고 바꾼다.

## 검사 (`specpilot/schema.py`)

| 수준 | 내용 | 처리 |
| --- | --- | --- |
| error | JSON 파싱 실패, 필수 필드 누락, kind·origin 값 오류, key 중복, 기획서 항목 누락(체크리스트·items_seen 대비), quote·문구가 원문에 없음 | 문제 목록을 붙여 **그 화면만 다시 호출** (기본 2회) |
| fix | 근거가 약한 함의(원문 하나뿐, 원문에 없음, 확신 낮음) → 질문으로 옮김(원래 단위는 `draft_unit`), 화면 ID 없는 화면에 ID 붙임, 그림 마커가 없던 항목의 단위에 issue 붙임 | 프로그램이 고침 |
| warning | quote가 원문과 한두 글자 다름(오타를 고쳐 씀), items_seen과 체크리스트의 차이, key 모양, 질문이 없는 단위를 가리킴 | 기록만 |

화면 상태: **완료** / **확인필요**(재시도 후에도 오류 → 오류 난 단위는 `rejected`로 옮김) / **실패**(쓸 수 있는 JSON 없음) / **반려**(게이트나 ②가 읽을 수 없다고 판단). ①이 실패하면 전체를 멈춘다.

## 아직 안 한 것

- v3.1 프롬프트를 실제 API로는 아직 돌려 보지 않았다. 첫 실행은 `--screens LOGIN-001`처럼 한두 화면으로 먼저 확인한다.
- 재실행할 때 단위 ID 이어받기 (지금은 응답 순서대로 다시 붙임)
- 같은 규칙의 단위 묶음 표시, 제약 단위 모음
- ④를 실제 API로는 아직 돌려 보지 않았다. 첫 실행은 `--screens LOGIN-001`처럼 한 묶음으로 먼저 확인한다.
- ④ 시험데이터를 코드에서 가져오기 (지금은 더미만), 화면 이동을 따라 여러 화면을 한 시나리오로 묶기
- 시연 서버: 진행 중인 분석 취소, 여러 분석 동시 실행, 로그인 (로컬 시연용이라 넣지 않음)

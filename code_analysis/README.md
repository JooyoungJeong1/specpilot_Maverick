# code_analysis — 소스 코드 정적 분석 (코드팀)

샘플 코드를 JavaParser, tree-sitter 등으로 분석해서, ③ 정합성 판정 때 AI에게 같이 줄 "사실"을 만든다.
백엔드 코드는 고치지 않는다. 이 폴더의 도구가 JSON 파일 하나를 만들면 끝이다.

## 입력과 출력
- 입력: 샘플 코드 폴더 경로 (기업 자료라 저장소에 넣지 않는다. 각자 PC에 둔다)
- 출력: `code_analysis/out/code_facts.json` (기업 코드에서 뽑은 내용이라 커밋하지 않는다)
- 형식: `backend/docs/code_facts.example.json`
  - `common`: 모든 화면에 줄 사실 / `screens`: 화면 ID → 그 화면 사실 목록
  - 화면 구분이 어려우면 처음엔 전부 `common`에 넣어도 된다
  - 파일 경로는 샘플 코드 폴더 기준 상대 경로, `/` 구분

## 넣을 사실 예
- 컨트롤러 경로 → 서비스 호출 (예: POST /notices → NoticeService.create)
- 서버가 화면에 넘긴 값을 템플릿이 실제로 출력하는지
- JS 입력 검사가 언제 실행되는지 (blur / submit)
- 로그인이 필요한 경로 (보안 설정)

## 백엔드에서 쓰는 법 (조장)
cd backend
python -m specpilot judge --run output/<실행> --code inputs/<샘플코드> --facts ../code_analysis/out/code_facts.json
`--facts`를 넣은 판정과 뺀 판정을 각각 채점해서 효과를 비교한다.
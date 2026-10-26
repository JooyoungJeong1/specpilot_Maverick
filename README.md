# SpecPilot

㈜씽크트리 산학 캡스톤 · 팀 Maverick

기획서(PDF)와 소스 코드를 비교해 **기획서대로 구현됐는지** 판정하고, 기획서 기준 **테스트 사양서**를 만드는 도구.

```
입력 점검 → ① 앱 프로필 → ② 화면별 분해 ─┬→ ③ 정합성 판정 → 채점
                                         └→ ④ 시나리오 합성 → 테스트 사양서 (엑셀)
```

## 폴더

| 폴더 | 내용 | 담당 |
| --- | --- | --- |
| `backend/` | 파이프라인(①②③, 채점), 프롬프트 | 조장, 요구사항분석팀, 코드팀 |
| `code_analysis/` | 코드 정적 분석 모듈 | 코드팀 |
| `frontend/` | 화면 (예정) | UI 담당 |


- 설치와 실행 방법: [`backend/README.md`](backend/README.md)
- 구조 설명, 파트별로 고칠 파일, 평가 방법: [`backend/docs/GUIDE.md`](backend/docs/GUIDE.md)
- 코드 분석 모듈: [`code_analysis/README.md`](code_analysis/README.md)

## 공통 규칙

1. **실행은 조장 PC에서만 한다.** 조원은 파일을 고쳐 PR을 올리고, 조장이 돌려서 결과와 점수를 공유한다.
2. **main에 바로 push 금지.** 브랜치를 만들어 작업하고 PR을 올린다. 조장이 확인 후 merge.
   - 브랜치 이름: `prompt/...`, `judge/...`, `scenario/...`, `code/...`, `front/...`
3. PR 설명에는 **바꾼 것 / 이유 / 어느 화면(또는 항목)을 보고 고쳤는지**를 적는다.
4. 작업 시작 전에 `git pull`로 최신 코드를 받는다.
5. `.env`, `inputs/`, `output/`은 올리지 않는다(`.gitignore`가 막음).

# SpecPilot

㈜씽크트리 산학 캡스톤 · 팀 Maverick

기획서(PDF)와 소스 코드를 비교해 **기획서대로 구현됐는지** 판정하는 도구.

```
입력 점검 → ① 앱 프로필 → ② 화면별 분해 → ③ 정합성 판정 → 채점
```

## 폴더

| 폴더 | 내용 | 담당 |
| --- | --- | --- |
| `backend/` | 파이프라인(①②③, 채점), 프롬프트 | 조장, 요구사항분석팀, 코드팀 |
| `code_analysis/` | 코드 정적 분석 모듈 | 코드팀 |
| `frontend/` | 화면 (예정) | UI 담당 |

설치와 실행 방법: [`backend/README.md`](backend/README.md)
코드 분석 모듈: [`code_analysis/README.md`](code_analysis/README.md)

## 공통 규칙

1. **main에 바로 push 금지.** 브랜치를 만들어 작업하고 PR을 올린다. 조장이 확인 후 merge.
   - 브랜치 이름: `prompt/...`, `judge/...`, `code/...`, `front/...`
2. **올리면 안 되는 것**: `.env`(API 키), `inputs/`(기획서·샘플 코드), `output/`(실행 결과). `.gitignore`가 막아 주지만 commit 전에 `git status`로 한 번 확인.
3. **API 키는 각자 발급**해서 `backend/.env`에 넣는다. 공유 금지.
4. 기획서 PDF와 샘플 코드는 조장이 따로 전달 → `backend/inputs/`에 넣는다. 샘플 코드 폴더 이름을 `specpilot`으로 두지 않는다.
5. **정답 세트는 저장소에 없다.** 실행 결과(`backend/output/<실행이름>/` 폴더)를 압축해 조장에게 보내면 점수를 돌려준다.
6. 작업 시작 전에 `git pull`로 최신 코드를 받는다.
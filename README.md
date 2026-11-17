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
| `frontend/` | 웹 화면: 기획서·코드 올리기 → 분석 진행 → 결과 검토, 엑셀 내보내기 | UI 담당 |


- 설치와 실행 방법: [`backend/README.md`](backend/README.md)
- 구조 설명, 파트별로 고칠 파일, 평가 방법: [`backend/docs/GUIDE.md`](backend/docs/GUIDE.md)
- 코드 분석 모듈: [`code_analysis/README.md`](code_analysis/README.md)
- 웹 화면: [`frontend/README.md`](frontend/README.md)

## 웹으로 시연

웹에서 기획서 PDF와 소스 코드를 올리면 ①~④가 실제로 돈다. 터미널 두 개를 연다.

```bash
# 터미널 1: 시연 서버 (처음 한 번 pip install -r requirements.txt, .env에 API 키)
cd backend
python -m specpilot serve

# 터미널 2: 웹 (처음 한 번 npm ci)
cd frontend
npm run dev
```

터미널 2에 찍힌 주소를 열고 "새로 분석하기" → 기획서 PDF와 코드 zip을 올려 "분석 시작" → 진행 화면 → "결과 보기".
명령어로 돌려 둔 결과(`backend/output/`)도 웹의 "최근 분석"에 그대로 보인다. 자세한 내용은 [`backend/README.md`](backend/README.md#웹으로-시연-specpilotserverpy).

팀 작업 규칙(브랜치·PR): [`CONTRIBUTING.md`](CONTRIBUTING.md)

// 테스트용: 커밋된 가짜 결과 폴더(mock/qna-example, mock/make_mock.py가 만듦)
import requirementsJson from '../../mock/qna-example/requirements.json'
import judgmentsJson from '../../mock/qna-example/judgments.json'
import reportJson from '../../mock/qna-example/judge_report.json'
import scenariosJson from '../../mock/qna-example/scenarios.json'
import type { JudgeReport } from '../types/judge_report.ts'
import type { Judgments } from '../types/judgments.ts'
import type { Requirements } from '../types/requirements.ts'
import type { Scenarios } from '../types/scenarios.ts'

// JSON은 문자열 값이 string으로 넓어져서 타입을 붙여 준다
export const requirements = requirementsJson as unknown as Requirements
export const judgments = judgmentsJson as unknown as Judgments
export const report = reportJson as unknown as JudgeReport
export const scenarios = scenariosJson as unknown as Scenarios

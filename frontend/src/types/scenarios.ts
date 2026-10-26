// 테스트 사양서 (④, backend/specpilot/scenario.py가 쓰는 scenarios.json). CLAUDE.md 3장(v3 문서 7장) 형식.
// 백엔드는 같은 내용으로 기업 양식 엑셀(테스트사양서.xlsx)과 추적표(추적표.xlsx)도 만든다.

export interface ScenarioStep {
  no: number
  /** 엑셀 "시험절차" */
  action: string
  /** 엑셀 "예상결과" */
  expected: string
  /** 엑셀 "시험데이터" 계정 / 입력값 / 비고 */
  account: string | null
  input: string | null
  /** "더미" 또는 "설계서"(기획서에 적힌 값). 시험데이터가 없으면 null */
  data_source: string | null
  note: string | null
  /** 엑셀 "근거 요구사항". 판정과는 이 값으로만 잇는다. */
  unit_ids: string[]
  /** 준비 단계(로그인·화면 이동 등)면 true. 예시 데이터(mock)는 null */
  setup: boolean | string | null
}

export interface Scenario {
  /** 엑셀 "시험번호" */
  scenario_id: string
  /** 엑셀 "시나리오명". 예시 데이터(mock)에는 없다 */
  title?: string
  /** 엑셀 DEPTH(1) / DEPTH(2) */
  depth1: string
  depth2: string
  steps: ScenarioStep[]
}

export interface Scenarios {
  /** 백엔드가 묶음별 결과를 합친 때와 묶음별 상태. 예시 데이터(mock)에는 없다 */
  meta?: { merged_at?: string; groups?: Record<string, string | null> }
  scenarios: Scenario[]
  /** 다시 요청해도 어느 단계에도 들어가지 않은 요구사항 ID */
  uncovered?: string[]
  /** 아직 ④를 돌리지 않았거나 실패한 화면 묶음의 요구사항 ID */
  not_run?: string[]
  /** 사양서 대상이 아닌 요구사항 ID (kind "제약") */
  excluded?: string[]
}

// 테스트 사양서 (④). 백엔드에 아직 없다. CLAUDE.md 3장(v3 문서 7장) 형식으로 둔 임시 타입이라
// ④가 나오면 실제 출력에 맞춰 고친다.

export interface ScenarioStep {
  no: number
  /** 엑셀 "시험절차" */
  action: string
  /** 엑셀 "예상결과" */
  expected: string
  /** 엑셀 "시험데이터" (account / input / note) */
  account: string | null
  input: string | null
  data_source: string | null
  note: string | null
  /** 엑셀 "근거 요구사항". 판정과는 이 값으로만 잇는다. */
  unit_ids: string[]
  setup: string | null
}

export interface Scenario {
  /** 엑셀 "시험번호" */
  scenario_id: string
  /** 엑셀 DEPTH(1) / DEPTH(2) */
  depth1: string
  depth2: string
  steps: ScenarioStep[]
}

export interface Scenarios {
  scenarios: Scenario[]
}

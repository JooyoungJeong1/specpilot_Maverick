// judgments.json: backend/specpilot/judge.py(judge_screen, merge_judgments)가 쓰는 형식 그대로.

export type JudgeStatus = '구현' | '불일치' | '미구현' | '확인필요'
/** 기획서 항목별 집계. 단위 판정이 섞이면 부분구현 (schema.aggregate_items) */
export type ItemStatus = JudgeStatus | '부분구현'

/** judge.txt가 정한 필드 이름 */
export type MismatchField = 'message' | 'values' | 'target' | 'when' | 'conditions' | 'then'
export type MismatchValue = string | number | string[] | null

export interface Mismatch {
  field: MismatchField
  spec: MismatchValue
  code: MismatchValue
}

export interface Evidence {
  file: string
  line: number
  code: string
}

export interface JudgeResult {
  unit_id: string
  /** 판정한 화면. 앱 전체 단위는 여러 화면에서 판정되고 가장 나쁜 판정을 낸 화면이 남는다. 단위의 화면이 아니다. */
  screen_id: string
  status: JudgeStatus
  mismatch: Mismatch[]
  evidence: Evidence[]
  /** 판정 이유, 찾아본 곳, 메모. 프로그램이 "[근거 불일치로 확인필요 처리]" 같은 꼬리표를 붙이기도 한다. */
  note: string | null
  /** 한 단위 안에서 판정이 갈린 경우의 설명 */
  split_issue: string | null
  /** false: 근거로 댄 파일:줄에 그 코드가 없음 */
  evidence_ok: boolean
  /** evidence_ok가 false일 때만. 예: "a.js:12: 인용한 코드가 실제 줄과 다름" */
  evidence_problems?: string[]
  /**
   * 프로그램이 판정을 바꿨을 때 원래 판정.
   * - 근거 불일치로 구현·불일치 → 확인필요 (evidence_ok: false)
   * - 문구가 띄어쓰기만 달라 불일치 → 구현
   */
  original_status?: JudgeStatus
}

export interface ItemVerdict {
  status: ItemStatus
  /** 이 항목에서 나온 단위 ID (판정된 것만) */
  units: string[]
}

/** 기획서에 없는 구현 */
export interface Extra {
  file: string
  line: number
  code: string
  description: string
  screen_id: string
}

export interface Judgments {
  /** 단위 ID → 판정. 없는 단위는 "판정 전"(그 화면의 ③이 실패했거나 안 돌림) */
  results: Record<string, JudgeResult>
  /** "LOGIN-001 Description 2" 같은 기획서 항목 → 집계. 프론트에서 다시 계산하지 않는다. */
  items: Record<string, ItemVerdict>
  extras: Extra[]
}

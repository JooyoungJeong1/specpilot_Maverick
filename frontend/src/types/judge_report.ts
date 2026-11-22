// judge_report.json: backend/specpilot/judge.py(merge_judgments)가 쓰는 형식 그대로.
import type { ItemStatus, JudgeStatus } from './judgments.ts'

export interface JudgeReport {
  summary: {
    units_judged: number
    /** 실패했거나 아직 안 돌린 화면의 단위 */
    units_not_judged: number
    /** 나온 판정만 키가 있다. 없는 키는 0이다. */
    by_status: Partial<Record<JudgeStatus, number>>
    items_by_status: Partial<Record<ItemStatus, number>>
    evidence_failures: number
    /** 띄어쓰기만 달라 구현으로 바꾼 수 */
    spacing_only: number
    /** 아래 목록의 개수 (프롬프트 담당용, 화면에 넣지 않음) */
    split_issues: number
    merge_candidates: number
    extras: number
  }
  /** 화면 ID(앱 전체 단위만 남으면 "APP"도) → ③ 상태 */
  screen_status: Record<string, '완료' | '확인필요' | '실패' | 'dry-run' | null>
  split_issues: { unit_id: string; split_issue: string }[]
  merge_candidates: { units: string[]; reason: string }[]
  /** 비용 기록 (judge.usage_summary). 이 기능을 넣기 전에 판정한 실행에는 없다 */
  usage?: JudgeUsage
}

/** 호출 한 묶음(화면 하나 또는 파일 고르기)의 토큰 · 처리시간 · 예상 비용 */
export interface UsageRow {
  input_tokens: number
  /** 생각(thinking) 토큰도 여기에 들어 있다 */
  output_tokens: number
  thinking_tokens: number
  cache_creation_input_tokens: number
  cache_read_input_tokens: number
  calls: number
  elapsed_sec: number
  /** 공식 가격표로 계산한 예상 비용(USD). 가격을 모르는 모델이면 null */
  cost_usd: number | null
  model: string | null
  /** 지난 실행의 판정을 그대로 썼으면 true (이번 실행 비용 0) */
  reused: boolean
}

export interface JudgeUsage {
  total: Omit<UsageRow, 'model' | 'reused'> & {
    /** 입력 전체(입력 + 캐시 쓰기 + 캐시 읽기) 중 캐시에서 읽은 비율 */
    cache_read_ratio: number
    screens_reused: number
    saved_cost_usd: number
  }
  /** 화면 ID → 그 화면 판정. "code_map"은 화면별 파일 고르기 */
  by_call: Record<string, UsageRow>
}

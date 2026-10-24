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
}

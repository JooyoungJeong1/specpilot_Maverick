import type { ItemStatus, JudgeResult, JudgeStatus, Judgments } from '../types/judgments.ts'
import type { Unit } from '../types/requirements.ts'

/** judgments.results에 없는 단위. 그 화면의 ③이 실패했거나 아직 안 돌렸다. */
export const NOT_JUDGED = '판정 전'
export type UnitStatus = JudgeStatus | typeof NOT_JUDGED

/** 문제 큰 순 (CLAUDE.md 7장) */
export const UNIT_STATUSES: readonly UnitStatus[] = ['미구현', '불일치', '확인필요', '구현', NOT_JUDGED]
/** 기획서 항목 집계에서는 부분구현을 불일치 다음에 둔다 */
export const ITEM_STATUSES: readonly ItemStatus[] = ['미구현', '불일치', '부분구현', '확인필요', '구현']

/** 프로그램이 판정을 바꾼 이유 */
export type StatusChange =
  /** 근거로 댄 코드를 확인하지 못해 구현·불일치를 확인필요로 내림 */
  | { reason: 'evidence'; from: JudgeStatus }
  /** 문구가 띄어쓰기만 달라 불일치를 구현으로 봄 */
  | { reason: 'spacing'; from: '불일치' }

export interface UnitView {
  unit: Unit
  result: JudgeResult | null
  status: UnitStatus
  change: StatusChange | null
  /** 근거 줄 대조 실패. 미구현·확인필요는 판정이 바뀌지 않아 change 없이 이것만 true일 수 있다. */
  evidenceFailed: boolean
}

export function statusChange(r: JudgeResult): StatusChange | null {
  if (!r.original_status) return null
  if (r.evidence_ok === false) return { reason: 'evidence', from: r.original_status }
  if (r.original_status === '불일치' && r.status === '구현') return { reason: 'spacing', from: '불일치' }
  return null
}

/** 단위마다 판정을 붙인다. 판정이 없으면 "판정 전". 순서는 단위 순서 그대로. */
export function mergeVerdicts(units: Unit[], judgments: Judgments | null): UnitView[] {
  return units.map((unit) => {
    const result = judgments?.results[unit.id] ?? null
    return {
      unit,
      result,
      status: result ? result.status : NOT_JUDGED,
      change: result ? statusChange(result) : null,
      evidenceFailed: result?.evidence_ok === false,
    }
  })
}

/** 판정별 개수. 없는 판정도 0으로 채운다. 단위(UnitView)와 기획서 항목(judgments.items) 모두에 쓴다. */
export function countStatuses<S extends string>(rows: Iterable<{ status: S }>, statuses: readonly S[]): Record<S, number> {
  const out = Object.fromEntries(statuses.map((s) => [s, 0])) as Record<S, number>
  for (const r of rows) {
    if (r.status in out) out[r.status] += 1
  }
  return out
}

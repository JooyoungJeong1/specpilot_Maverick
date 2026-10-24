import type { Question } from '../types/requirements.ts'
import type { ScreenGroup } from './screens.ts'
import { countStatuses, NOT_JUDGED, UNIT_STATUSES, type UnitStatus } from './verdicts.ts'

export type SortMode = 'doc' | 'prob'

/** 판정 이름을 CSS 클래스 꼬리로 ("판정 전" → "판정전"). .p-판정전, .c-판정전 */
export function statusClass(status: string): string {
  return status.replace(/\s+/g, '')
}

export function groupCounts(g: ScreenGroup): Record<UnitStatus, number> {
  return countStatuses(g.units, UNIT_STATUSES)
}

/** 확인해야 하는 판정 수 (미구현 + 불일치 + 확인필요). 판정 전은 따로 센다. */
export function problemCount(c: Record<UnitStatus, number>): number {
  return c['미구현'] + c['불일치'] + c['확인필요']
}

/** "문제 많은 순" 정렬 점수 (초안과 같음) */
export function problemScore(c: Record<UnitStatus, number>): number {
  return c['미구현'] * 3 + c['불일치'] * 2 + c['확인필요']
}

/**
 * "문제 있는 화면만"에서 남길 화면.
 * 초안 규칙(문제 판정이 있음, 앱 전체는 질문이 있음)에 더해 반려 화면과 판정 전 단위가 있는 화면도 남긴다.
 * 파이프라인이 만든 상태를 숨기지 않기 위해서다 (CLAUDE.md 4장 10번).
 */
export function hasProblem(g: ScreenGroup): boolean {
  const c = groupCounts(g)
  return problemCount(c) > 0 || c[NOT_JUDGED] > 0 || !!g.rejectReason || (g.isApp && g.questions.length > 0)
}

/** 문제 많은 순은 같은 점수끼리 기획서 순서를 지킨다 */
export function sortGroups(groups: ScreenGroup[], mode: SortMode): ScreenGroup[] {
  if (mode === 'doc') return groups
  return groups
    .map((g, i) => ({ g, i, score: problemScore(groupCounts(g)) }))
    .sort((a, b) => b.score - a.score || a.i - b.i)
    .map((x) => x.g)
}

export function visibleGroups(groups: ScreenGroup[], onlyProblems: boolean): ScreenGroup[] {
  return onlyProblems ? groups.filter(hasProblem) : groups
}

/** [1, 2] → "1~2쪽", [4] → "4쪽", [1, 3] → "1, 3쪽" */
export function formatPages(pages: number[] | undefined): string {
  const ps = [...new Set(pages ?? [])].sort((a, b) => a - b)
  if (!ps.length) return ''
  if (ps.length === 1) return `${ps[0]}쪽`
  const contiguous = ps.every((p, i) => i === 0 || p === ps[i - 1] + 1)
  return contiguous ? `${ps[0]}~${ps.at(-1)}쪽` : `${ps.join(', ')}쪽`
}

/** 우선순위 상을 먼저. 같은 우선순위 안에서는 원래 순서 (백엔드도 이렇게 정렬하지만 한 번 더 지킨다) */
export function sortByPriority(questions: Question[]): Question[] {
  return [...questions.filter((q) => q.priority === '상'), ...questions.filter((q) => q.priority !== '상')]
}

export interface Overview {
  total: number
  counts: Record<UnitStatus, number>
  problems: number
  implied: number
  /** 앱 전체를 뺀 화면 수 */
  screens: number
  screensWithProblems: number
  rejected: number
}

export function overview(groups: ScreenGroup[]): Overview {
  const units = groups.flatMap((g) => g.units)
  const counts = countStatuses(units, UNIT_STATUSES)
  const screens = groups.filter((g) => !g.isApp)
  return {
    total: units.length,
    counts,
    problems: problemCount(counts),
    implied: units.filter((v) => v.unit.origin === '함의').length,
    screens: screens.length,
    screensWithProblems: screens.filter((g) => problemCount(groupCounts(g)) > 0).length,
    rejected: screens.filter((g) => g.rejectReason).length,
  }
}

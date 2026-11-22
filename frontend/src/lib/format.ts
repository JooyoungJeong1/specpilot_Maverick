import type { RunData, RunSummary } from '../api/api.ts'
import { NOT_JUDGED, UNIT_STATUSES, type UnitStatus } from './verdicts.ts'

/** 실행 이름. mock은 가짜 데이터라는 것이 보이게 한다. 웹에서 올려 돌린 실행은 입력한 프로젝트 이름. */
export function runLabel(run: Pick<RunData, 'id' | 'source'> & { name?: string | null }): string {
  if (run.source === 'mock') return `예시 데이터 (${run.id})`
  return run.name || run.id
}

/** "2026-10-16T01:50:12" → "2026-10-16 01:50" */
export function formatDateTime(iso: string | null | undefined): string {
  const m = /^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})/.exec(iso ?? '')
  return m ? `${m[1]} ${m[2]}` : iso || '-'
}

/** 최근 분석 목록의 판정 수 (판정 전 포함). ③을 안 돌렸으면 모두 판정 전 */
export function runCounts(run: Pick<RunSummary, 'units' | 'byStatus' | 'notJudged'>): Record<UnitStatus, number> {
  const counts = Object.fromEntries(UNIT_STATUSES.map((s) => [s, 0])) as Record<UnitStatus, number>
  if (!run.byStatus) return { ...counts, [NOT_JUDGED]: run.units }
  for (const [s, n] of Object.entries(run.byStatus)) counts[s as UnitStatus] = n ?? 0
  counts[NOT_JUDGED] = run.notJudged ?? 0
  return counts
}

/** 상단 바 프로젝트 정보. 초안: "이름 · 기획서 화면 n개 · 분석 날짜". 날짜는 마지막으로 결과가 바뀐 때 */
export function projectMeta(run: Pick<RunData, 'id' | 'source' | 'requirements' | 'updatedAt'> & { name?: string | null }): string {
  const req = run.requirements
  return `${runLabel(run)} · 기획서 화면 ${req.app_profile.screens.length}개 · 분석 ${formatDateTime(run.updatedAt ?? req.meta.merged_at)}`
}

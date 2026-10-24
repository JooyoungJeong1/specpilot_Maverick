// 결과 파일을 읽을 때 빠질 수 있는 값을 채운다. 화면 코드는 타입대로 값이 있다고 믿고 쓴다.
// ③은 재시도 끝에도 형식 오류가 남으면 판정을 그대로 저장한다 (judge.judge_screen: status, unit_id만 확인).
// 그래서 mismatch, evidence 같은 필드가 드물게 빠질 수 있다.
import type { JudgeResult, Judgments } from '../types/judgments.ts'

type Loose<T> = { [K in keyof T]?: unknown }

function list<T>(v: unknown): T[] {
  return Array.isArray(v) ? (v as T[]) : []
}

function text(v: unknown): string | null {
  return typeof v === 'string' && v.trim() ? v : null
}

export function normalizeResult(r: Loose<JudgeResult> & { unit_id: string; status: JudgeResult['status'] }, screenId: string): JudgeResult {
  return {
    ...(r as JudgeResult),
    screen_id: typeof r.screen_id === 'string' ? r.screen_id : screenId,
    mismatch: list(r.mismatch),
    evidence: list(r.evidence),
    note: text(r.note),
    split_issue: text(r.split_issue),
    evidence_ok: r.evidence_ok !== false,
  }
}

export function normalizeJudgments(j: Loose<Judgments> | null): Judgments | null {
  if (!j) return null
  const results: Judgments['results'] = {}
  const raw = (j.results && typeof j.results === 'object' ? j.results : {}) as Record<string, Parameters<typeof normalizeResult>[0]>
  for (const [id, r] of Object.entries(raw)) {
    if (r && typeof r === 'object') results[id] = normalizeResult({ ...r, unit_id: r.unit_id ?? id }, '')
  }
  return {
    results,
    items: (j.items && typeof j.items === 'object' ? j.items : {}) as Judgments['items'],
    extras: list(j.extras),
  }
}

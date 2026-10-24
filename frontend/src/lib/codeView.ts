import type { Evidence } from '../types/judgments.ts'

/** 근거 코드가 차지하는 줄 (code_prep.verify_evidence처럼 인용한 코드의 빈 줄이 아닌 줄 수만큼) */
export function evidenceLines(ev: Pick<Evidence, 'line' | 'code'>): { from: number; to: number } {
  const n = Math.max(1, String(ev.code ?? '').split(/\r?\n/).filter((l) => l.trim()).length)
  return { from: ev.line, to: ev.line + n - 1 }
}

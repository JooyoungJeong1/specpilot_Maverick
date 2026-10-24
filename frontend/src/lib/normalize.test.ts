import { describe, expect, it } from 'vitest'
import { normalizeJudgments } from './normalize.ts'
import { judgments } from './testFixtures.ts'

describe('normalizeJudgments', () => {
  it('정상 결과는 그대로', () => {
    expect(normalizeJudgments(judgments)).toEqual(judgments)
  })

  it('③이 형식 오류를 남긴 판정(차이·근거 칸 없음)도 화면에서 쓸 수 있게 채운다', () => {
    const broken = { results: { 'REQ-X-01': { unit_id: 'REQ-X-01', status: '불일치', note: '  ' } } }
    const r = normalizeJudgments(broken as never)!.results['REQ-X-01']
    expect(r).toMatchObject({ mismatch: [], evidence: [], note: null, split_issue: null, evidence_ok: true })
  })

  it('items, extras가 없어도 빈 값', () => {
    expect(normalizeJudgments({ results: {} } as never)).toEqual({ results: {}, items: {}, extras: [] })
    expect(normalizeJudgments(null)).toBeNull()
  })

  it('근거 확인 실패 표시는 지키고 unit_id가 없으면 키로 채운다', () => {
    const r = normalizeJudgments({ results: { A: { status: '확인필요', evidence_ok: false } } } as never)!.results.A
    expect(r.unit_id).toBe('A')
    expect(r.evidence_ok).toBe(false)
  })
})

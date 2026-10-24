import { describe, expect, it } from 'vitest'
import type { JudgeResult } from '../types/judgments.ts'
import { judgments, report, requirements } from './testFixtures.ts'
import { countStatuses, ITEM_STATUSES, mergeVerdicts, NOT_JUDGED, statusChange, UNIT_STATUSES } from './verdicts.ts'

const views = mergeVerdicts(requirements.units, judgments)
const byId = (id: string) => views.find((v) => v.unit.id === id)!

describe('mergeVerdicts', () => {
  it('단위 순서를 지키고 단위마다 하나씩 만든다', () => {
    expect(views.map((v) => v.unit.id)).toEqual(requirements.units.map((u) => u.id))
  })

  it('판정이 없는 단위는 판정 전 (③이 실패한 QNA-005)', () => {
    const notJudged = views.filter((v) => v.status === NOT_JUDGED)
    expect(notJudged.map((v) => v.unit.screen_id)).toEqual(Array(8).fill('QNA-005'))
    expect(notJudged.every((v) => v.result === null && v.change === null)).toBe(true)
    expect(notJudged.length).toBe(report.summary.units_not_judged)
  })

  it('③ 결과가 아예 없으면 모두 판정 전', () => {
    expect(mergeVerdicts(requirements.units, null).every((v) => v.status === NOT_JUDGED)).toBe(true)
  })

  it('근거 불일치로 내린 판정은 원래 판정을 알려 준다', () => {
    const v = byId('REQ-MEM-001-03')
    expect(v.status).toBe('확인필요')
    expect(v.change).toEqual({ reason: 'evidence', from: '불일치' })
    expect(v.evidenceFailed).toBe(true)
  })

  it('미구현은 근거 대조에 실패해도 판정이 바뀌지 않는다 (original_status 없음)', () => {
    const v = byId('REQ-QNA-003-02')
    expect(v.status).toBe('미구현')
    expect(v.change).toBeNull()
    expect(v.evidenceFailed).toBe(true)
  })

  it('띄어쓰기만 다른 문구는 구현으로 본 것을 알려 준다', () => {
    const v = byId('REQ-MEM-002-03')
    expect(v.status).toBe('구현')
    expect(v.change).toEqual({ reason: 'spacing', from: '불일치' })
    expect(v.evidenceFailed).toBe(false)
  })
})

describe('statusChange', () => {
  const base: JudgeResult = { unit_id: 'X', screen_id: 'S', status: '확인필요', mismatch: [], evidence: [], note: null, split_issue: null, evidence_ok: true }
  it('original_status가 없으면 바뀐 것이 없다', () => {
    expect(statusChange(base)).toBeNull()
  })
  it('근거 불일치로 구현을 내린 경우', () => {
    expect(statusChange({ ...base, evidence_ok: false, original_status: '구현' })).toEqual({ reason: 'evidence', from: '구현' })
  })
})

describe('countStatuses', () => {
  it('단위 판정 수가 judge_report와 같다', () => {
    const counts = countStatuses(views, UNIT_STATUSES)
    for (const s of ['구현', '불일치', '미구현', '확인필요'] as const) {
      expect(counts[s]).toBe(report.summary.by_status[s] ?? 0)
    }
    expect(counts[NOT_JUDGED]).toBe(report.summary.units_not_judged)
  })

  it('기획서 항목은 judgments.items를 그대로 센다 (부분구현 포함)', () => {
    const counts = countStatuses(Object.values(judgments.items), ITEM_STATUSES)
    expect(counts).toEqual({ 미구현: 0, 불일치: 0, 부분구현: 0, 확인필요: 0, 구현: 0, ...report.summary.items_by_status })
    expect(counts['부분구현']).toBeGreaterThan(0)
  })

  it('없는 판정은 0으로 채운다', () => {
    expect(countStatuses([], UNIT_STATUSES)).toEqual({ 미구현: 0, 불일치: 0, 확인필요: 0, 구현: 0, [NOT_JUDGED]: 0 })
  })
})

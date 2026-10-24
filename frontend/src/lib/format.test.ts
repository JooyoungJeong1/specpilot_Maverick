import { describe, expect, it } from 'vitest'
import { formatDateTime, projectMeta, runCounts, runLabel } from './format.ts'
import { requirements } from './testFixtures.ts'

describe('projectMeta', () => {
  it('초안과 같은 순서로 이름, 화면 수, 분석 날짜를 잇는다', () => {
    const req = { ...requirements, meta: { merged_at: '2026-10-12T21:40:05', run_dir: '20261012-2140' } }
    expect(projectMeta({ id: '20261012-2140', source: 'local', requirements: req }))
      .toBe('20261012-2140 · 기획서 화면 8개 · 분석 2026-10-12 21:40')
  })
})

describe('runLabel', () => {
  it('mock은 예시 데이터임을 밝힌다', () => {
    expect(runLabel({ id: 'qna-example', source: 'mock' })).toBe('예시 데이터 (qna-example)')
  })
})

describe('runCounts', () => {
  it('판정 수에 판정 전을 더한다', () => {
    expect(runCounts({ units: 10, byStatus: { 구현: 5, 미구현: 2 }, notJudged: 3 }))
      .toEqual({ 미구현: 2, 불일치: 0, 확인필요: 0, 구현: 5, '판정 전': 3 })
  })
  it('③을 안 돌렸으면 모두 판정 전', () => {
    expect(runCounts({ units: 7, byStatus: null, notJudged: null })['판정 전']).toBe(7)
  })
})

describe('formatDateTime', () => {
  it('없거나 모양이 다르면 그대로 또는 -', () => {
    expect(formatDateTime(null)).toBe('-')
    expect(formatDateTime('어제')).toBe('어제')
  })
})

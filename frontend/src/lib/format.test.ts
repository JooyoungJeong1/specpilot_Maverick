import { describe, expect, it } from 'vitest'
import { formatDateTime, projectMeta, runCounts, runLabel } from './format.ts'
import { requirements } from './testFixtures.ts'

describe('projectMeta', () => {
  it('초안과 같은 순서로 이름, 화면 수, 분석 날짜를 잇는다', () => {
    const req = { ...requirements, meta: { merged_at: '2026-10-12T21:40:05', run_dir: '20261012-2140' } }
    expect(projectMeta({ id: '20261012-2140', source: 'local', requirements: req }))
      .toBe('20261012-2140 · 기획서 화면 8개 · 분석 2026-10-12 21:40')
  })
  it('③만 다시 돌린 실행은 마지막으로 결과가 바뀐 때를 쓴다', () => {
    const req = { ...requirements, meta: { merged_at: '2026-11-09T19:48:12', run_dir: 'r3' } }
    expect(projectMeta({ id: 'r3', source: 'local', requirements: req, updatedAt: '2026-11-18T01:49:30' }))
      .toBe('r3 · 기획서 화면 8개 · 분석 2026-11-18 01:49')
  })
})

describe('runLabel', () => {
  it('mock은 예시 데이터임을 밝힌다', () => {
    expect(runLabel({ id: 'qna-example', source: 'mock' })).toBe('예시 데이터 (qna-example)')
  })
  it('웹에서 올려 돌린 실행은 프로젝트 이름을 쓴다', () => {
    expect(runLabel({ id: 'demo-20261026-213000', source: 'local', name: '시연 프로젝트' })).toBe('시연 프로젝트')
    expect(runLabel({ id: 'full1', source: 'local', name: null })).toBe('full1')
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

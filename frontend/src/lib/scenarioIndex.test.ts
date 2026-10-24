import { describe, expect, it } from 'vitest'
import { stepsByUnit } from './scenarioIndex.ts'
import { scenarios } from './testFixtures.ts'

describe('stepsByUnit', () => {
  const index = stepsByUnit(scenarios)

  it('단위 ID로 그 단위를 확인하는 단계를 찾는다', () => {
    expect(index.get('REQ-QNA-002-03')).toEqual([
      { scenarioId: 'TC-QNA-002-01', depth1: '고객센터', depth2: '문의 작성', no: 2, action: '제목을 비운 채 다른 입력란을 누른다.' },
    ])
  })

  it('여러 단계에 나오면 모두 모은다', () => {
    expect(index.get('REQ-QNA-002-12')?.map((s) => `${s.scenarioId}#${s.no}`)).toEqual(['TC-QNA-002-02#1', 'TC-QNA-002-02#2'])
  })

  it('한 단계에 같은 ID가 두 번 있어도 한 번만', () => {
    const idx = stepsByUnit({ scenarios: [{ scenario_id: 'T', depth1: 'a', depth2: 'b', steps: [
      { no: 1, action: 'x', expected: 'y', account: null, input: null, data_source: null, note: null, unit_ids: ['U', 'U'], setup: null },
    ] }] })
    expect(idx.get('U')).toHaveLength(1)
  })

  it('사양서가 없으면 빈 색인', () => {
    expect(stepsByUnit(null).size).toBe(0)
  })
})

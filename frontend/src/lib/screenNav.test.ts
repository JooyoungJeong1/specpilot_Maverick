import { describe, expect, it } from 'vitest'
import { stepsForUnits } from './scenarioIndex.ts'
import { screenNav, screenPages, sourceScreenId } from './screenNav.ts'
import { groupByScreen } from './screens.ts'
import { judgments, requirements, scenarios } from './testFixtures.ts'
import { mergeVerdicts } from './verdicts.ts'

const groups = groupByScreen(requirements, mergeVerdicts(requirements.units, judgments))

describe('screenPages', () => {
  it('쪽과 상태 화면 쪽을 합쳐 중복 없이 정렬', () => {
    expect(screenPages({ pages: [2, 1], state_pages: [2, 3] })).toEqual([1, 2, 3])
    expect(screenPages(null)).toEqual([])
  })
})

describe('screenNav', () => {
  it('기획서 순서로 이전·다음', () => {
    const n = screenNav(groups, 'MEM-001', false)
    expect(n).toMatchObject({ pos: 1, total: 9 })
    expect(n.prev?.id).toBe('APP')
    expect(n.next?.id).toBe('MEM-002')
  })
  it('없는 화면이면 첫 화면', () => {
    expect(screenNav(groups, undefined, false).current.id).toBe('APP')
  })
  it('문제 있는 화면만: 문제 없는 화면(QNA-001)은 건너뛰고, 그 화면을 보고 있었으면 첫 화면으로', () => {
    const n = screenNav(groups, 'MEM-002', true)
    expect(n.total).toBe(8)
    expect(screenNav(groups, 'QNA-002', true).prev?.id).toBe('MEM-002')
    expect(screenNav(groups, 'QNA-001', true).current.id).toBe('APP')
  })
})

describe('sourceScreenId', () => {
  it.each([
    ['LOGIN-004 Description 0', 'LOGIN-004'],
    ['QNA-001 화면 이미지', 'QNA-001'],
    ['Description 2', null],
  ])('%s', (s, id) => expect(sourceScreenId(s)).toBe(id))
})

describe('stepsForUnits', () => {
  it('그 화면 단위를 확인하는 단계만', () => {
    const ids = groups.find((g) => g.id === 'MEM-001')!.units.map((v) => v.unit.id)
    expect(stepsForUnits(scenarios, ids).map(({ scenario, step }) => `${scenario.scenario_id}#${step.no}`))
      .toEqual(['TC-MEM-001-01#1', 'TC-MEM-001-01#2', 'TC-MEM-001-01#3', 'TC-MEM-001-01#4'])
    expect(stepsForUnits(null, ids)).toEqual([])
  })
})

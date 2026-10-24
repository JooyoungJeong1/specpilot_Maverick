import { describe, expect, it } from 'vitest'
import type { Requirements } from '../types/requirements.ts'
import { groupByScreen, questionScope } from './screens.ts'
import { judgments, requirements } from './testFixtures.ts'
import { mergeVerdicts } from './verdicts.ts'

const groups = groupByScreen(requirements, mergeVerdicts(requirements.units, judgments))
const group = (id: string) => groups.find((g) => g.id === id)!

describe('groupByScreen', () => {
  it('앱 전체가 맨 앞, 그다음 app_profile.screens 순서', () => {
    expect(groups.map((g) => g.id)).toEqual(['APP', ...requirements.app_profile.screens.map((s) => s.screen_id)])
    expect(group('APP')).toMatchObject({ isApp: true, name: '앱 전체', meta: null })
  })

  it('앱 전체 단위는 판정한 화면이 아니라 APP 묶음에 둔다', () => {
    expect(judgments.results['REQ-APP-01'].screen_id).toBe('QNA-003')
    expect(group('APP').units.map((v) => v.unit.id)).toEqual(['REQ-APP-01', 'REQ-APP-02', 'REQ-APP-03'])
    expect(group('QNA-003').units.some((v) => v.unit.id === 'REQ-APP-01')).toBe(false)
  })

  it('모든 단위와 질문이 한 번씩 들어간다', () => {
    expect(groups.flatMap((g) => g.units).length).toBe(requirements.units.length)
    expect(groups.flatMap((g) => g.questions).length).toBe(requirements.questions.length)
  })

  it('반려 화면도 이유와 함께 남긴다', () => {
    expect(group('QNA-004')).toMatchObject({ units: [], rejectReason: requirements.rejected_screens['QNA-004'] })
    expect(group('QNA-004').runStatus?.status).toBe('반려')
  })

  it('질문은 ID의 화면으로 가고 상이 먼저인 순서를 지킨다', () => {
    expect(group('APP').questions.map((q) => q.priority)).toEqual(['상', '하', '하', '하'])
    expect(group('QNA-001').questions.map((q) => q.id)).toEqual(['Q-QNA-001-01'])
  })

  it('앱 전체 단위·질문이 없으면 APP 묶음을 만들지 않는다', () => {
    const noApp: Requirements = {
      ...requirements,
      units: requirements.units.filter((u) => u.screen_id !== 'APP'),
      questions: requirements.questions.filter((q) => !q.id.startsWith('Q-APP-')),
    }
    expect(groupByScreen(noApp, mergeVerdicts(noApp.units, null))[0].id).toBe('MEM-001')
  })

  it('화면 목록에 없는 화면의 단위도 버리지 않는다', () => {
    const unit = { ...requirements.units[3], id: 'REQ-ZZZ-001-01', screen_id: 'ZZZ-001' }
    const extra: Requirements = { ...requirements, units: [...requirements.units, unit] }
    const g = groupByScreen(extra, mergeVerdicts(extra.units, null))
    expect(g.at(-1)).toMatchObject({ id: 'ZZZ-001', name: 'ZZZ-001', meta: null })
  })
})

describe('questionScope', () => {
  it.each([
    ['Q-APP-01', 'APP'],
    ['Q-LOGIN-001-03', 'LOGIN-001'],
    ['Q-SCR-001-12', 'SCR-001'],
  ])('%s → %s', (id, scope) => expect(questionScope(id)).toBe(scope))
})

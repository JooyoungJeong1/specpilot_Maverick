import { describe, expect, it } from 'vitest'
import type { Question } from '../types/requirements.ts'
import { groupByScreen } from './screens.ts'
import { formatPages, groupCounts, hasProblem, overview, problemScore, sortByPriority, sortGroups, statusClass, visibleGroups } from './summary.ts'
import { judgments, report, requirements } from './testFixtures.ts'
import { mergeVerdicts } from './verdicts.ts'

const groups = groupByScreen(requirements, mergeVerdicts(requirements.units, judgments))
const ids = (gs: { id: string }[]) => gs.map((g) => g.id)

describe('overview', () => {
  const o = overview(groups)
  it('판정 수가 judge_report와 같다', () => {
    expect(o.total).toBe(requirements.units.length)
    expect(o.problems).toBe(['미구현', '불일치', '확인필요'].reduce((n, s) => n + (report.summary.by_status[s as '구현'] ?? 0), 0))
    expect(o.counts['판정 전']).toBe(report.summary.units_not_judged)
  })
  it('화면 수는 앱 전체를 빼고 센다', () => {
    expect(o.screens).toBe(requirements.app_profile.screens.length)
    expect(o.rejected).toBe(1)
    expect(o.implied).toBe(requirements.units.filter((u) => u.origin === '함의').length)
  })
})

describe('hasProblem / visibleGroups', () => {
  it('반려 화면, 판정 전 단위가 있는 화면, 질문이 있는 앱 전체는 남긴다', () => {
    const g = (id: string) => groups.find((x) => x.id === id)!
    expect(hasProblem(g('QNA-004'))).toBe(true)   // 반려
    expect(hasProblem(g('QNA-005'))).toBe(true)   // 판정 전
    expect(hasProblem(g('APP'))).toBe(true)
  })
  it('문제 판정이 없는 화면만 뺀다 (QNA-001은 모두 구현)', () => {
    expect(ids(visibleGroups(groups, true))).toEqual(ids(groups).filter((id) => id !== 'QNA-001'))
    expect(ids(visibleGroups(groups, false))).toEqual(ids(groups))
  })
})

describe('sortGroups', () => {
  it('기획서 순서는 그대로', () => {
    expect(sortGroups(groups, 'doc')).toBe(groups)
  })
  it('문제 많은 순은 점수가 같으면 기획서 순서를 지킨다', () => {
    const sorted = sortGroups(groups, 'prob')
    const scores = sorted.map((g) => problemScore(groupCounts(g)))
    expect(scores).toEqual([...scores].sort((a, b) => b - a))
    const zero = sorted.filter((_, i) => scores[i] === 0).map((g) => ids(groups).indexOf(g.id))
    expect(zero).toEqual([...zero].sort((a, b) => a - b))
  })
})

describe('formatPages', () => {
  it.each([
    [[4], '4쪽'],
    [[1, 2], '1~2쪽'],
    [[3, 1, 2], '1~3쪽'],
    [[1, 3], '1, 3쪽'],
    [[], ''],
  ])('%j → %s', (pages, text) => expect(formatPages(pages)).toBe(text))
})

describe('sortByPriority', () => {
  it('상을 먼저, 같은 우선순위는 원래 순서', () => {
    const q = (id: string, priority: '상' | '하') => ({ id, priority }) as Question
    expect(sortByPriority([q('a', '하'), q('b', '상'), q('c', '하'), q('d', '상')]).map((x) => x.id)).toEqual(['b', 'd', 'a', 'c'])
  })
})

describe('statusClass', () => {
  it('띄어쓰기를 뺀다', () => expect(statusClass('판정 전')).toBe('판정전'))
})

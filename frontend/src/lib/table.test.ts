import { describe, expect, it } from 'vitest'
import { groupByScreen } from './screens.ts'
import {
  appTablePath, cardPath, filterItemRows, filterUnitRows, itemQuote, itemRows, itemTarget, sortByStatus, splitItemKey, unitLinks,
  unitPath, unitRows,
  type TableFilters,
} from './table.ts'
import { judgments, requirements } from './testFixtures.ts'
import { ITEM_STATUSES, mergeVerdicts, UNIT_STATUSES } from './verdicts.ts'

const views = mergeVerdicts(requirements.units, judgments)
const groups = groupByScreen(requirements, views)
const units = unitRows(groups)
const items = itemRows(judgments, views)
const all: TableFilters = { statuses: new Set([...UNIT_STATUSES, ...ITEM_STATUSES]), screen: '', origin: '', query: '' }

describe('splitItemKey', () => {
  it.each([
    ['LOGIN-001 Description 2', 'LOGIN-001', 'Description 2'],
    ['APP Action A', 'APP', 'Action A'],
    ['QNA-001 화면 이미지', 'QNA-001', '화면 이미지'],
  ])('%s', (key, screenId, item) => expect(splitItemKey(key)).toEqual({ screenId, item }))
})

describe('itemRows', () => {
  it('judgments.items를 그대로 쓴다 (다시 계산하지 않음)', () => {
    expect(items.length).toBe(Object.keys(judgments.items).length)
    for (const r of items) expect(r.status).toBe(judgments.items[r.key].status)
  })
  it('③ 결과가 없으면 빈 목록', () => {
    expect(itemRows(null, views)).toEqual([])
  })
})

describe('itemTarget', () => {
  it('항목 화면의 단위를 먼저 연다 (앱 전체 단위가 섞여 있어도)', () => {
    const row = items.find((r) => r.key === 'MEM-001 Description 0')!
    expect(row.units.map((v) => v.unit.id)).toEqual(['REQ-APP-01', 'REQ-MEM-001-01'])
    expect(itemTarget(row)).toEqual({ screenId: 'MEM-001', unitId: 'REQ-MEM-001-01' })
    expect(itemQuote(row)).toBe(requirements.units.find((u) => u.id === 'REQ-MEM-001-01')!.quote)
  })
  it('그 화면 단위가 없으면 첫 단위 (QNA-005는 판정 전이라 앱 전체 단위만 남음)', () => {
    const row = items.find((r) => r.key === 'QNA-005 Action A')!
    expect(itemTarget(row)).toEqual({ screenId: 'APP', unitId: 'REQ-APP-03' })
  })
})

describe('filterUnitRows', () => {
  it('판정으로 거른다 (판정 전 포함)', () => {
    const only = filterUnitRows(units, { ...all, statuses: new Set(['판정 전']) })
    expect(only.length).toBe(8)
  })
  it('화면은 단위의 화면으로 거른다', () => {
    expect(filterUnitRows(units, { ...all, screen: 'APP' }).map((r) => r.view.unit.id)).toEqual(['REQ-APP-01', 'REQ-APP-02', 'REQ-APP-03'])
  })
  it('명시·함의로 거른다', () => {
    expect(filterUnitRows(units, { ...all, origin: '함의' }).every((r) => r.view.unit.origin === '함의')).toBe(true)
  })
  it('검색은 띄어쓰기와 대소문자를 무시한다', () => {
    const hit = filterUnitRows(units, { ...all, query: '비공개체크박스' })
    expect(hit.map((r) => r.view.unit.id)).toContain('REQ-QNA-002-01')
    expect(filterUnitRows(units, { ...all, query: 'req-mem-001-03' }).map((r) => r.view.unit.id)).toEqual(['REQ-MEM-001-03'])
  })
})

describe('filterItemRows', () => {
  it('부분구현만', () => {
    expect(filterItemRows(items, { ...all, statuses: new Set(['부분구현']) }).length).toBe(5)
  })
  it('화면은 항목 키의 화면으로', () => {
    expect(filterItemRows(items, { ...all, screen: 'QNA-002' }).every((r) => r.screenId === 'QNA-002')).toBe(true)
  })
})

describe('sortByStatus', () => {
  it('문제 큰 순, 같은 판정은 원래 순서', () => {
    const rows = [{ status: '구현', n: 1 }, { status: '미구현', n: 2 }, { status: '구현', n: 3 }, { status: '불일치', n: 4 }]
    expect(sortByStatus(rows, UNIT_STATUSES).map((r) => r.n)).toEqual([2, 4, 1, 3])
  })
})

describe('cardPath', () => {
  it('화면과 단위를 주소에 담는다', () => {
    expect(cardPath('QNA-002', 'REQ-QNA-002-03')).toBe('/screen/QNA-002?unit=REQ-QNA-002-03')
  })
})

describe('unitPath', () => {
  it('화면 요구사항은 화면별 보기의 카드로', () => {
    expect(unitPath('QNA-002', 'REQ-QNA-002-03')).toBe('/screen/QNA-002?unit=REQ-QNA-002-03')
  })

  it('앱 전체 요구사항은 요구사항 표에서 그 ID로 검색해 둔다', () => {
    expect(unitPath('APP', 'REQ-APP-01')).toBe('/table?screen=APP&q=REQ-APP-01')
    expect(appTablePath()).toBe('/table?screen=APP')
  })
})

describe('unitLinks', () => {
  const screenOf = new Map([['REQ-QNA-002-03', 'QNA-002'], ['REQ-APP-01', 'APP']])

  it('칸의 ID마다 판정 카드 주소를 붙인다', () => {
    expect(unitLinks('REQ-QNA-002-03, REQ-APP-01', screenOf)).toEqual([
      { id: 'REQ-QNA-002-03', path: '/screen/QNA-002?unit=REQ-QNA-002-03' },
      { id: 'REQ-APP-01', path: '/table?screen=APP&q=REQ-APP-01' },
    ])
  })

  it('결과에 없는 ID는 주소 없이', () => {
    expect(unitLinks('REQ-X-01', screenOf)).toEqual([{ id: 'REQ-X-01', path: null }])
  })

  it('빈 칸("-")은 빈 목록', () => {
    expect(unitLinks('-', screenOf)).toEqual([])
    expect(unitLinks('', screenOf)).toEqual([])
  })
})

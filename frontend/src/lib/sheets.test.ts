import { describe, expect, it } from 'vitest'
import { checklistSheet, exportFileName, exportSheets, judgmentSheets, questionSheet, sheetName, specSheets, SPEC_HEADER, testData } from './sheets.ts'
import { judgments, requirements, scenarios } from './testFixtures.ts'

describe('specSheets', () => {
  const sheets = specSheets(scenarios, requirements)

  it('전체 / depth1별 / 질문 시트 순서', () => {
    expect(sheets.map((s) => s.name)).toEqual(['전체', '회원', '고객센터', '질문 시트'])
  })

  it('열은 CLAUDE.md 3장 대응표를 따른다', () => {
    expect(sheets[0].header).toEqual(SPEC_HEADER)
    const first = scenarios.scenarios[0]
    const step = first.steps[1]
    expect(sheets[0].rows[1]).toEqual([
      first.scenario_id, first.depth1, first.depth2, step.no, step.action, step.expected,
      'user1@example.com / 비밀번호: wrong-pass', '', 'REQ-MEM-001-03, REQ-MEM-001-05',
    ])
  })

  it('판정 결과를 넣지 않는다', () => {
    const text = JSON.stringify(sheets)
    for (const s of ['미구현', '불일치', '확인필요', '부분구현']) expect(text).not.toContain(s)
  })

  it('depth1별 시트를 합치면 전체와 같다', () => {
    expect(sheets[1].rows.length + sheets[2].rows.length).toBe(sheets[0].rows.length)
  })
})

describe('questionSheet', () => {
  it('우선순위 상이 먼저, 답변 칸은 빈칸', () => {
    const q = questionSheet(requirements)
    expect(q.rows.length).toBe(requirements.questions.length)
    expect(q.rows.slice(0, 2).map((r) => r[2])).toEqual(['상', '상'])
    expect(q.rows.every((r) => r.at(-1) === '')).toBe(true)
    expect(q.rows[0][1]).toBe('앱 전체')
  })
})

describe('checklistSheet', () => {
  it('단위마다 한 줄, 판정 없음', () => {
    const c = checklistSheet(requirements)
    expect(c.rows.length).toBe(requirements.units.length)
    expect(c.header).not.toContain('판정')
  })
})

describe('judgmentSheets', () => {
  const [units, items, extras] = judgmentSheets(requirements, judgments)
  it('요구사항별: 판정 전과 바뀐 이유를 쉬운 말로', () => {
    expect(units.rows.length).toBe(requirements.units.length)
    const row = (id: string) => units.rows.find((r) => r[0] === id)!
    expect(row('REQ-QNA-005-01')[4]).toBe('판정 전')
    expect(row('REQ-MEM-001-03')[5]).toBe('AI가 댄 근거 코드를 확인하지 못해 확인필요로 바꿈 (원래: 불일치)')
    expect(row('REQ-QNA-002-03')[8]).toBe('문구: 기획서 "제목을 입력해주세요." / 코드 "제목을 입력하세요"')
  })
  it('기획서 항목별은 judgments.items 그대로 (부분구현 포함)', () => {
    expect(items.rows.length).toBe(Object.keys(judgments.items).length)
    expect(items.rows.filter((r) => r[2] === '부분구현').length).toBe(5)
  })
  it('기획서에 없는 구현', () => {
    expect(extras.rows.length).toBe(judgments.extras.length)
  })
})

describe('exportSheets / exportFileName', () => {
  it('사양서가 없으면 null, 나머지는 결과 파일만으로 만든다', () => {
    const data = { requirements, judgments, scenarios: null }
    expect(exportSheets('spec', data)).toBeNull()
    expect(exportSheets('checklist', data)?.map((s) => s.name)).toEqual(['구현 체크리스트'])
    expect(exportSheets('judgment', { ...data, judgments: null })?.[0].rows.every((r) => r[4] === '판정 전')).toBe(true)
  })
  it('파일 이름에 쓸 수 없는 글자를 바꾼다', () => {
    expect(exportFileName('spec', '예시 데이터 (a/b)')).toBe('테스트사양서_예시 데이터 (a_b).xlsx')
  })
})

describe('sheetName / testData', () => {
  it('쓸 수 없는 글자를 바꾸고 31자로 자르고 겹치면 번호', () => {
    const used = new Set<string>()
    expect(sheetName('회원/로그인', used)).toBe('회원 로그인')
    expect(sheetName('회원/로그인', used)).toBe('회원 로그인 2')
    expect(sheetName('가'.repeat(40), used)).toHaveLength(31)
  })
  it('시험데이터는 있는 값만 / 로 잇는다', () => {
    expect(testData({ no: 1, action: '', expected: '', account: 'a', input: null, data_source: null, note: 'n', unit_ids: [], setup: null })).toBe('a / n')
  })
})

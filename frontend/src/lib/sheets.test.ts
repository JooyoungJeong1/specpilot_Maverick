import { describe, expect, it } from 'vitest'
import type { Scenarios } from '../types/scenarios.ts'
import { checklistSheet, exportFileName, exportSheets, isSetup, judgmentSheets, questionSheet, sheetName, SPEC_FIRST_MENU, specSheets, SPEC_HEADER } from './sheets.ts'
import { judgments, requirements, scenarios } from './testFixtures.ts'

describe('specSheets', () => {
  const sheets = specSheets(scenarios)
  const total = scenarios.scenarios.reduce((n, s) => n + s.steps.length, 0)

  it('기업 양식: 개정이력, 목차, 메뉴(DEPTH(1))별 시트. 질문은 넣지 않는다', () => {
    expect(sheets.map((s) => s.name)).toEqual(['개정이력', '00. 목차', '01. 회원', '02. 고객센터'])
  })

  it('열은 CLAUDE.md 3장 대응표를 따른다. 빈 값은 "-", 확인결과는 빈칸', () => {
    const menu = sheets[SPEC_FIRST_MENU]
    expect(menu.header).toEqual(SPEC_HEADER)
    const first = scenarios.scenarios[0]
    const step = first.steps[1]
    expect(menu.rows[1]).toEqual([
      first.scenario_id, '', first.depth1, first.depth2, step.no, step.action, step.expected,
      'user1@example.com', '비밀번호: wrong-pass', '-', '', 'REQ-MEM-001-03, REQ-MEM-001-05', '-',
    ])
  })

  it('판정 결과를 넣지 않는다', () => {
    const text = JSON.stringify(sheets)
    for (const s of ['미구현', '불일치', '확인필요', '부분구현']) expect(text).not.toContain(s)
  })

  it('메뉴 시트를 합치면 모든 단계, 목차의 단계 수도 같다', () => {
    expect(sheets.slice(SPEC_FIRST_MENU).reduce((n, s) => n + s.rows.length, 0)).toBe(total)
    expect(sheets[1].rows.reduce((n, r) => n + Number(r[4]), 0)).toBe(total)
    expect(sheets[1].rows[0][0]).toBe('01. 회원')
  })

  it('백엔드 결과: 시나리오명은 첫 단계에만, 준비 단계, 데이터 출처, 작성일', () => {
    const backend: Scenarios = {
      meta: { merged_at: '2026-10-26T14:00:00' },
      scenarios: [{
        scenario_id: 'TC-QNA-002-01', title: '문의 작성 화면 표시와 입력 검사', depth1: '고객센터', depth2: '문의 작성',
        steps: [
          { no: 1, action: '문의 작성 화면에 들어간다.', expected: '문의 작성 화면이 표시된다.', account: '일반 사용자 / user1@example.com',
            input: null, data_source: '더미', note: null, unit_ids: [], setup: true },
          { no: 2, action: '제목에 31자를 입력한다.', expected: '30자까지만 입력된다.', account: null, input: '가×31 (31자)',
            data_source: '설계서', note: null, unit_ids: ['REQ-QNA-002-02'], setup: false },
        ],
      }],
    }
    const [history, toc, menu] = specSheets(backend)
    expect(history.rows[0][1]).toBe('2026-10-26')
    expect(toc.rows[0]).toEqual(['01. 고객센터', '고객센터 (01)', '문의 작성 (01)', 1, 2, 10101, 'O', '2026-10-26'])
    expect(menu.rows.map((r) => r[1])).toEqual(['문의 작성 화면 표시와 입력 검사', ''])
    expect(menu.rows.map((r) => r[9])).toEqual(['준비 단계', '-'])
    expect(menu.rows.map((r) => r[12])).toEqual(['더미', '기획서'])
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
  it('사양서가 없으면 null, 추적표는 백엔드 파일로만, 나머지는 결과 파일만으로 만든다', () => {
    const data = { requirements, judgments, scenarios: null }
    expect(exportSheets('spec', data)).toBeNull()
    expect(exportSheets('trace', { ...data, scenarios })).toBeNull()
    expect(exportSheets('checklist', data)?.map((s) => s.name)).toEqual(['구현 체크리스트'])
    expect(exportSheets('judgment', { ...data, judgments: null })?.[0].rows.every((r) => r[4] === '판정 전')).toBe(true)
  })
  it('파일 이름에 쓸 수 없는 글자를 바꾼다', () => {
    expect(exportFileName('spec', '예시 데이터 (a/b)')).toBe('테스트사양서_예시 데이터 (a_b).xlsx')
  })
})

describe('sheetName / isSetup', () => {
  it('쓸 수 없는 글자를 바꾸고 31자로 자르고 겹치면 번호', () => {
    const used = new Set<string>()
    expect(sheetName('회원/로그인', used)).toBe('회원 로그인')
    expect(sheetName('회원/로그인', used)).toBe('회원 로그인 2')
    expect(sheetName('가'.repeat(40), used)).toHaveLength(31)
  })
  it('준비 단계: 백엔드는 true, 예시 데이터는 null', () => {
    const step = { no: 1, action: '', expected: '', account: null, input: null, data_source: null, note: null, unit_ids: [] }
    expect([true, false, null].map((setup) => isSetup({ ...step, setup }))).toEqual([true, false, false])
  })
})

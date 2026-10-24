import { describe, expect, it } from 'vitest'
import { changeText, cleanNote, fieldLabel, formatValue, reviewText, unitLocation } from './judgeText.ts'
import { quoteSegments } from './quote.ts'
import { judgments, requirements } from './testFixtures.ts'
import { mergeVerdicts } from './verdicts.ts'

const views = mergeVerdicts(requirements.units, judgments)
const review = (id: string) => reviewText(views.find((v) => v.unit.id === id)!)

describe('reviewText (표 "검토사항")', () => {
  it('근거 불일치로 바뀐 판정은 원래 판정과 함께', () => {
    expect(review('REQ-MEM-001-03')).toBe('AI가 댄 근거 코드를 확인하지 못해 확인필요로 바꿈 (원래: 불일치)')
  })
  it('판정은 그대로인데 근거를 못 찾은 경우', () => {
    expect(review('REQ-QNA-003-02')).toBe('AI가 댄 근거 코드를 실제 코드에서 찾지 못함')
  })
  it('띄어쓰기만 다름', () => {
    expect(review('REQ-MEM-002-03')).toContain('띄어쓰기만 다름')
  })
  it('차이는 필드 이름 대신 쉬운 말로', () => {
    expect(review('REQ-QNA-002-03')).toBe('문구 다름: 기획서 "제목을 입력해주세요." → 코드 "제목을 입력하세요"')
    expect(review('REQ-MEM-002-05')).toBe('이동 화면 다름: 기획서 "MEM-001" → 코드 "/"')
  })
  it('판정 전', () => {
    expect(review('REQ-QNA-005-01')).toBe('코드와 아직 비교하지 않음')
  })
  it('판정 누락은 LLM이라는 말 없이', () => {
    expect(review('REQ-QNA-006-01')).toBe('AI가 이 요구사항의 판정을 내지 않아 확인필요로 두었습니다.')
  })
  it('화면 문구에 필드 이름이 나오지 않는다', () => {
    const words = /evidence|mismatch|original_status|split_issue|evidence_ok|LLM|note|issue/
    for (const v of views) expect(reviewText(v)).not.toMatch(words)
  })
})

describe('cleanNote', () => {
  it('프로그램 꼬리표를 뺀다', () => {
    expect(cleanNote('띄어쓰기 차이 [문구가 띄어쓰기만 달라 구현으로 처리]')).toBe('띄어쓰기 차이')
    expect(cleanNote('[근거 불일치로 확인필요 처리]')).toBeNull()
    expect(cleanNote(null)).toBeNull()
  })
})

describe('fieldLabel / formatValue', () => {
  it('필드 이름을 쉬운 말로', () => {
    expect(['message', 'values', 'target', 'when', 'conditions', 'then', 'x'].map(fieldLabel))
      .toEqual(['문구', '값', '이동 화면', '동작', '조건', '결과', '내용'])
  })
  it('목록과 빈 값', () => {
    expect(formatValue(['파란색 테두리', '굵게'])).toBe('파란색 테두리, 굵게')
    expect(formatValue(null)).toBe('(없음)')
    expect(formatValue({ min: 8 })).toBe('{"min":8}')
  })
})

describe('changeText', () => {
  it('근거 불일치', () => expect(changeText({ reason: 'evidence', from: '구현' })).toContain('(원래: 구현)'))
})

describe('unitLocation', () => {
  it('화면 단위는 쪽과 위치, 앱 전체는 근거 위치', () => {
    expect(unitLocation({ screen_id: 'QNA-002', source: ['Description 1'] }, [5])).toBe('5쪽 Description 1')
    expect(unitLocation({ screen_id: 'APP', source: ['MEM-001 Description 0', 'QNA-001 화면 이미지'] }, [])).toBe('MEM-001 Description 0, QNA-001 화면 이미지')
  })
})

describe('quoteSegments', () => {
  it('함의 원문을 " / "로 나눈다', () => {
    expect(quoteSegments('가 / 나')).toEqual(['가', '나'])
    expect(quoteSegments('')).toEqual([])
  })
})

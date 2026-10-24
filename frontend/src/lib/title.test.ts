import { describe, expect, it } from 'vitest'
import { cardTitle, shorten, TITLE_MAX } from './title.ts'

describe('cardTitle', () => {
  it('then을 제목, when을 맥락으로 쓰고 끝 마침표를 뺀다', () => {
    expect(cardTitle({ then: '오류 메시지가 표시된다.', when: '제목 입력란에서 다른 곳으로 이동한다', quote: '…' }))
      .toEqual({ title: '오류 메시지가 표시된다', context: '제목 입력란에서 다른 곳으로 이동한다' })
  })

  it('then이 비면 when, 그것도 비면 원문', () => {
    expect(cardTitle({ then: ' ', when: '등록 버튼을 누른다', quote: 'x' })).toEqual({ title: '등록 버튼을 누른다', context: null })
    expect(cardTitle({ then: '', when: null, quote: '문의가 저장되고' })).toEqual({ title: '문의가 저장되고', context: null })
  })

  it('줄바꿈과 겹친 공백을 하나로', () => {
    expect(cardTitle({ then: '팝업이\n  표시된다', when: null, quote: '' }).title).toBe('팝업이 표시된다')
  })

  it('길면 줄임표로 자른다', () => {
    const long = '가'.repeat(TITLE_MAX + 5)
    const { title } = cardTitle({ then: long, when: null, quote: '' })
    expect([...title].length).toBe(TITLE_MAX)
    expect(title.endsWith('…')).toBe(true)
  })
})

describe('shorten', () => {
  it('짧으면 그대로', () => expect(shorten('짧다', 5)).toBe('짧다'))
})

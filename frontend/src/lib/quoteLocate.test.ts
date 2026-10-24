import { describe, expect, it } from 'vitest'
import { allowedEdits, approxFind, findPiece, buildStreams, locateUnit, quotePieces, squash, type PageText } from './quoteLocate.ts'

// 기대값은 backend/specpilot/pdf_utils.py, schema.py를 직접 돌려서 얻은 것이다.
describe('squash (pdf_utils.squash와 같음)', () => {
  it.each([
    ['“안녕 ”하세요', '안녕하세요'],
    ['①번 ＡＢ', '1번AB'],
    ['ｶ', 'カ'],
    ['가 나', '가나'],
    ['「문의」 상세', '문의상세'],
    ['a​b﻿c', 'abc'],
  ])('%j → %j', (s, out) => expect(squash(s)).toBe(out))
})

describe('quotePieces (schema._pieces와 같음)', () => {
  it.each([
    ['문의가 저장되고 / 문의 목록(QNA-001)으로 이동한다.', ['문의가 저장되고', '문의 목록(QNA-001)으로 이동한다.']],
    ['앞부분…뒷부분 / 중간...끝', ['앞부분', '뒷부분']],
    ['가 / 나나나', ['나나나']],
  ])('%j', (q, out) => expect(quotePieces(q)).toEqual(out))
})

describe('allowedEdits / approxFind', () => {
  it('pdf_utils.allowed_edits와 같다', () => {
    expect([3, 5, 12, 13, 20, 21, 30, 50].map(allowedEdits)).toEqual([1, 1, 1, 2, 2, 3, 4, 6])
  })
  it('가장 비슷한 부분과 거리 (approx_distance와 같은 값)', () => {
    // 백엔드 approx_distance('문의가저장된다', 'xx문의가저장되고yy') == 2
    expect(approxFind('문의가저장된다', 'xx문의가저장되고yy', 2)).toMatchObject({ start: 2, dist: 2 })
    expect(approxFind('문의가저장된다', 'xx문의가저장되고yy', 1)).toBeNull()
  })
  it('그대로 있으면 거리 0', () => {
    expect(approxFind('저장', 'ab저장cd', 1)).toEqual({ start: 2, end: 4, dist: 0 })
  })
})

// 가짜 쪽: 1000 × 500, 글자 하나 폭 10
const item = (str: string, x: number, y: number) => ({ str, x, y, w: [...str].length * 10, h: 10 })
const page = (items: ReturnType<typeof item>[], n = 1): PageText => ({ page: n, width: 1000, height: 500, items })

describe('findPiece', () => {
  it('띄어쓰기·따옴표가 달라도 찾고 글자 위치로 사각형을 만든다', () => {
    const p = page([item('Action A: "문의가 등록되었습니다." 팝업', 100, 50)])
    const hit = findPiece('“문의가 등록되었습니다.”', buildStreams([p]))!
    expect(hit.approx).toBe(false)
    expect(hit.rects).toHaveLength(1)
    const r = hit.rects[0]
    expect(r.x).toBeCloseTo(((100 + 11 * 10) / 1000) * 100)   // "Action A: \"" 다음 글자부터
    expect(r.y).toBeCloseTo(10)
  })

  it('여러 줄에 걸친 원문은 줄마다 사각형', () => {
    const p = page([item('제목이 비어 있으면 에러', 100, 50), item('메시지를 표시한다.', 100, 70)])
    expect(findPiece('제목이 비어 있으면 에러 메시지를 표시한다.', buildStreams([p]))!.rects).toHaveLength(2)
  })

  it('표 칸 때문에 파일 순서가 섞여도 화면 줄 순서로 찾는다', () => {
    // 파일에는 오른쪽 칸이 먼저 적혀 있음
    const p = page([item('다른 칸', 600, 50), item('로그인 화면으로', 100, 70), item('이동한다', 100 + 8 * 10, 70)].reverse())
    expect(findPiece('로그인 화면으로 이동한다', buildStreams([p]))).not.toBeNull()
  })

  it('한두 글자 다르면 비슷한 곳 (approx)', () => {
    const p = page([item('취소: 문의 상셰(QNA-003)로 이동한다.', 0, 0)])
    const hit = findPiece('취소: 문의 상세(QNA-003)로 이동한다.', buildStreams([p]))!
    expect(hit.approx).toBe(true)
  })

  it('없으면 null', () => {
    expect(findPiece('전혀 다른 문장입니다', buildStreams([page([item('문의 목록', 0, 0)])]))).toBeNull()
  })
})

describe('locateUnit', () => {
  const p = page([item('수정 내용을 저장하고', 0, 0), item('문의 상세(QNA-003)로 이동한다.', 0, 20)])
  const unit = (quote: string, source: string[] = ['Action A']) => ({ screen_id: 'QNA-005', source, quote })

  it('함의는 원문마다 찾는다', () => {
    const r = locateUnit(unit('수정 내용을 저장하고 / 문의 상세(QNA-003)로 이동한다.'), [p])
    expect(r.status).toBe('found')
    expect(r.rects).toHaveLength(2)
  })
  it('그림만 근거면 찾지 않는다', () => {
    expect(locateUnit(unit('삭제하기 버튼', ['화면 이미지']), [p])).toMatchObject({ status: 'skipped' })
  })
  it('일부만 찾으면 partial, 다른 화면 원문이면 이유를 붙인다', () => {
    const r = locateUnit(unit('수정 내용을 저장하고 / 목록에는 본인 문의만 표시된다', ['Action A', 'QNA-001 Description 2']), [p])
    expect(r).toMatchObject({ status: 'partial', reason: '다른 화면의 원문을 근거로 함' })
  })
  it('못 찾으면 이유', () => {
    expect(locateUnit(unit('없는 문장을 찾아본다'), [p])).toMatchObject({ status: 'none', reason: '이 화면 페이지의 글자에서 원문을 찾지 못함' })
  })
})

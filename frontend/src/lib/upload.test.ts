import { describe, expect, it } from 'vitest'
import { defaultName, formatSize, isRepoUrl, isZip, missingInputs, splitPlans } from './upload.ts'

describe('splitPlans', () => {
  it('PDF만 받고 나머지는 따로', () => {
    const r = splitPlans([{ name: 'plan.PDF' }, { name: '기획.docx' }, { name: 'b.pdf' }])
    expect(r.pdfs.map((f) => f.name)).toEqual(['plan.PDF', 'b.pdf'])
    expect(r.rejected.map((f) => f.name)).toEqual(['기획.docx'])
  })
})

describe('isZip / isRepoUrl', () => {
  it('zip', () => { expect(isZip('code.ZIP')).toBe(true); expect(isZip('code.tar.gz')).toBe(false) })
  it.each([
    ['https://github.com/a/b', true],
    ['http://git.local/repo', true],
    ['github.com/a/b', false],
    ['ftp://x/y', false],
    ['', false],
  ])('%s → %s', (s, ok) => expect(isRepoUrl(s)).toBe(ok))
})

describe('missingInputs', () => {
  it('다 있으면 빈 목록', () => {
    expect(missingInputs({ plans: [1], zip: {}, repoUrl: '' })).toEqual([])
    expect(missingInputs({ plans: [1], zip: null, repoUrl: 'https://github.com/a/b' })).toEqual([])
  })
  it('빠진 것을 알려 준다', () => {
    expect(missingInputs({ plans: [], zip: null, repoUrl: '' })).toHaveLength(2)
    expect(missingInputs({ plans: [1], zip: null, repoUrl: 'github.com/a' })).toEqual(['저장소 주소는 https:// 로 시작해야 합니다.'])
  })
})

describe('defaultName / formatSize', () => {
  it('첫 기획서 이름에서 확장자를 뺀다', () => expect(defaultName([{ name: '문의앱 기획서 v2.pdf' }])).toBe('문의앱 기획서 v2'))
  it('크기', () => { expect(formatSize(900 * 1024)).toBe('900KB'); expect(formatSize(1.5 * 1024 * 1024)).toBe('1.5MB') })
})

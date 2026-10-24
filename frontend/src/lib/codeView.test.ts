import { describe, expect, it } from 'vitest'
import { evidenceLines } from './codeView.ts'

describe('evidenceLines', () => {
  it('한 줄', () => expect(evidenceLines({ line: 12, code: 'a();' })).toEqual({ from: 12, to: 12 }))
  it('여러 줄 인용은 빈 줄을 빼고 센다', () => expect(evidenceLines({ line: 5, code: 'a();\n\n  b();\n' })).toEqual({ from: 5, to: 6 }))
  it('코드가 비어도 그 줄은 강조', () => expect(evidenceLines({ line: 3, code: '' })).toEqual({ from: 3, to: 3 }))
})

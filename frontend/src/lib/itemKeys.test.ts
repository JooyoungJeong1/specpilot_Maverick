import { describe, expect, it } from 'vitest'
import { itemKeys } from './itemKeys.ts'
import { judgments, requirements } from './testFixtures.ts'

// 기대값은 backend/specpilot/schema.py의 item_keys를 직접 돌려서 얻은 것이다.
const CASES: [string, string[], string[]][] = [
  ['LOGIN-001', ['Description 2-(1)', 'Action E'], ['LOGIN-001 Description 2', 'LOGIN-001 Action E']],
  ['LOGIN-001', ['Action/Event B'], ['LOGIN-001 Action B']],
  ['LOGIN-001', ['Action / Event C'], ['LOGIN-001 Action C']],
  ['APP', ['LOGIN-004 Description 0', 'Action A'], ['LOGIN-004 Description 0', 'APP Action A']],
  ['LOGIN-001', ['상태 화면 p.2'], ['LOGIN-001 상태 화면 p.2']],
  ['LOGIN-001', ['화면 이미지'], ['LOGIN-001 화면 이미지']],
  ['LOGIN-001', ['Description 02'], ['LOGIN-001 Description 2']],
  ['LOGIN-001', ['Description 1, Description 3, Action B'], ['LOGIN-001 Description 1', 'LOGIN-001 Description 3', 'LOGIN-001 Action B']],
  ['APP', ['QNA-001 화면 이미지'], ['QNA-001 화면 이미지']],
  ['LOGIN-001', ['  화면 이미지 '], ['LOGIN-001   화면 이미지 ']],
  ['LOGIN-001', ['Action E화면'], ['LOGIN-001 Action E화면']],
  ['LOGIN-001', ['Action AB'], ['LOGIN-001 Action AB']],
  ['SCR-001', ['SCR-001 Description 3'], ['SCR-001 Description 3']],
  ['LOGIN-001', ['Description 2-(1)', 'Description 2-(2)'], ['LOGIN-001 Description 2']],
  ['LOGIN-001', ['Action A, Description 1'], ['LOGIN-001 Description 1', 'LOGIN-001 Action A']],
  ['LOGIN-001', ['Description1'], ['LOGIN-001 Description 1']],
  ['LOGIN-001', ['LOGIN-004  Description 0'], ['LOGIN-004 Description 0']],
  ['LOGIN-001', ['login-004 Description 0'], ['LOGIN-001 Description 0']],
  ['LOGIN-001', ['Action e'], ['LOGIN-001 Action e']],
  ['LOGIN-001', ['Action E.'], ['LOGIN-001 Action E']],
  ['LOGIN-001', [], []],
  ['APP', ['MEM-001 Description 0', 'QNA-001 화면 이미지'], ['MEM-001 Description 0', 'QNA-001 화면 이미지']],
]

describe('itemKeys (schema.item_keys와 같은 규칙)', () => {
  it.each(CASES)('%s %j', (screen_id, source, expected) => {
    expect(itemKeys({ screen_id, source })).toEqual(expected)
  })

  it('mock의 judgments.items 키와 같은 이름을 만든다', () => {
    const fromUnits = new Set(requirements.units.filter((u) => u.id in judgments.results).flatMap(itemKeys))
    expect(fromUnits).toEqual(new Set(Object.keys(judgments.items)))
  })
})

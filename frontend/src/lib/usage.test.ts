import { describe, expect, it } from 'vitest'
import type { JudgeUsage, UsageRow } from '../types/judge_report.ts'
import { formatDuration, formatPercent, formatTokens, formatUsd, inputTotal, usageRows } from './usage.ts'

const row = (o: Partial<UsageRow> = {}): UsageRow => ({
  input_tokens: 0, output_tokens: 0, thinking_tokens: 0, cache_creation_input_tokens: 0, cache_read_input_tokens: 0,
  calls: 1, elapsed_sec: 10, cost_usd: 0.1, model: 'claude-sonnet-5', reused: false, ...o,
})

describe('formatDuration', () => {
  it('1분이 넘으면 분 · 초, 아래면 소수 한 자리 초', () => {
    expect(formatDuration(827.05)).toBe('13분 47초')
    expect(formatDuration(60.52)).toBe('1분 1초')
    expect(formatDuration(6.73)).toBe('6.7초')
  })
  it('기록이 없으면 -', () => {
    expect(formatDuration(0)).toBe('-')
    expect(formatDuration(null)).toBe('-')
  })
})

describe('formatUsd', () => {
  it('1달러 아래는 세 자리, 위는 두 자리', () => {
    expect(formatUsd(1.4333)).toBe('$1.43')
    expect(formatUsd(0.0275)).toBe('$0.028')
    expect(formatUsd(0)).toBe('$0')
  })
  it('가격을 모르면 그렇게 쓴다', () => {
    expect(formatUsd(null)).toBe('가격 모름')
  })
})

describe('토큰 · 비율', () => {
  it('만 단위로 줄인다', () => {
    expect(formatTokens(857_120)).toBe('85.7만')
    expect(formatTokens(9_500)).toBe('9,500')
  })
  it('입력 전체는 캐시 쓰기 · 읽기를 더한다', () => {
    expect(inputTotal({ input_tokens: 132_332, cache_creation_input_tokens: 60_399, cache_read_input_tokens: 664_389 })).toBe(857_120)
  })
  it('비율은 반올림한 퍼센트', () => {
    expect(formatPercent(0.775)).toBe('78%')
  })
})

describe('usageRows', () => {
  const usage: JudgeUsage = {
    total: { ...row(), cache_read_ratio: 0, screens_reused: 0, saved_cost_usd: 0 },
    by_call: { 'NOTICE-001': row(), ZZZ: row(), code_map: row(), 'LOGIN-001': row({ reused: true, cost_usd: 0 }) },
  }
  const screens = [{ id: 'LOGIN-001', name: '로그인' }, { id: 'NOTICE-001', name: '공지 목록' }]
  it('파일 고르기 → 기획서 화면 순서 → 모르는 키', () => {
    expect(usageRows(usage, screens).map((r) => r.key)).toEqual(['code_map', 'LOGIN-001', 'NOTICE-001', 'ZZZ'])
  })
  it('화면 이름을 붙이고, 파일 고르기는 이름으로 쓴다', () => {
    const labels = usageRows(usage, screens).map((r) => r.label)
    expect(labels).toEqual(['화면별 파일 고르기', 'LOGIN-001 로그인', 'NOTICE-001 공지 목록', 'ZZZ'])
  })
})

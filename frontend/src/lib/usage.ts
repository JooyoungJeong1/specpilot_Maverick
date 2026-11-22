// ③ 판정의 비용 · 처리시간 (judge_report.json의 usage). 값은 백엔드가 계산한 그대로 보여 주고, 여기서는 모양만 다듬는다.
import type { JudgeUsage, UsageRow } from '../types/judge_report.ts'

/** 화면별 파일 고르기 호출의 키 (backend judge.py) */
export const CODE_MAP_KEY = 'code_map'

/** 요약 화면 아래 비용 카드의 DOM id (위 요약의 "자세히 보기"가 그리로 내려간다) */
export const COST_CARD_ID = 'cost'

/** 827.05 → "13분 47초", 6.73 → "6.7초". 기록이 없으면(0) "-" */
export function formatDuration(sec: number | null | undefined): string {
  if (!sec || sec <= 0) return '-'
  if (sec < 60) return `${Math.round(sec * 10) / 10}초`
  const s = Math.round(sec)
  return `${Math.floor(s / 60)}분 ${s % 60}초`
}

/** 1.4333 → "$1.43", 0.0275 → "$0.028". 가격을 모르면 "가격 모름" */
export function formatUsd(usd: number | null | undefined): string {
  if (usd == null) return '가격 모름'
  if (usd === 0) return '$0'
  return `$${usd.toFixed(usd < 1 ? 3 : 2)}`
}

/** 856,720 → "85.7만", 9,500 → "9,500" */
export function formatTokens(n: number): string {
  return n >= 10_000 ? `${Math.round(n / 1_000) / 10}만` : n.toLocaleString('ko-KR')
}

/** 0.775 → "78%" */
export function formatPercent(ratio: number): string {
  return `${Math.round(ratio * 100)}%`
}

/** 입력 토큰 전체 (새로 보낸 것 + 캐시에 쓴 것 + 캐시에서 읽은 것) */
export function inputTotal(u: Pick<UsageRow, 'input_tokens' | 'cache_creation_input_tokens' | 'cache_read_input_tokens'>): number {
  return u.input_tokens + u.cache_creation_input_tokens + u.cache_read_input_tokens
}

export interface UsageLine extends UsageRow {
  key: string
  label: string
}

/** 화면별 줄: 파일 고르기를 먼저, 그다음 기획서 화면 순서, 모르는 키는 끝에 */
export function usageRows(usage: JudgeUsage, screens: { id: string; name: string }[]): UsageLine[] {
  const order = new Map(screens.map((s, i) => [s.id, i]))
  const name = new Map(screens.map((s) => [s.id, s.name]))
  const rank = (k: string) => (k === CODE_MAP_KEY ? -1 : order.get(k) ?? screens.length)
  return Object.entries(usage.by_call)
    .sort(([a], [b]) => rank(a) - rank(b) || a.localeCompare(b))
    .map(([key, row]) => ({
      ...row,
      key,
      label: key === CODE_MAP_KEY ? '화면별 파일 고르기' : [key, name.get(key)].filter(Boolean).join(' '),
    }))
}

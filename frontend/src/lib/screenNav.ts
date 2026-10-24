// 화면별 보기: 보여 줄 쪽, 이전·다음 화면, 근거 위치의 화면
import type { ScreenMeta } from '../types/requirements.ts'
import type { ScreenGroup } from './screens.ts'
import { hasProblem } from './summary.ts'

/** 그 화면의 쪽과 상태 화면 쪽 (CLAUDE.md 6장: pages + state_pages) */
export function screenPages(meta: Pick<ScreenMeta, 'pages' | 'state_pages'> | null): number[] {
  return [...new Set([...(meta?.pages ?? []), ...(meta?.state_pages ?? [])])].sort((a, b) => a - b)
}

/**
 * 지금 보여 줄 화면과 이전·다음.
 * "문제 있는 화면만"이 켜져 있으면 문제 있는 화면 사이에서만 넘기고, 지금 화면이 빠지면 첫 화면으로 간다 (초안과 같음).
 */
export function screenNav(groups: ScreenGroup[], id: string | undefined, onlyProblems: boolean) {
  const visible = onlyProblems ? groups.filter(hasProblem) : groups
  const list = visible.length ? visible : groups
  const asked = groups.find((g) => g.id === id)
  const current = asked && list.includes(asked) ? asked : list[0]
  const pos = list.indexOf(current)
  return { current, pos, total: list.length, prev: list[pos - 1] ?? null, next: list[pos + 1] ?? null }
}

const SCREEN_PREFIX = /^([A-Z][A-Z0-9]*-\d{2,})\s/

/** "LOGIN-004 Description 0" → "LOGIN-004". 화면 ID가 없으면 null */
export function sourceScreenId(source: string): string | null {
  return SCREEN_PREFIX.exec(source.trim())?.[1] ?? null
}

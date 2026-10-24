import type { Unit } from '../types/requirements.ts'

/** 카드 제목 최대 글자 수 */
export const TITLE_MAX = 40

export interface CardTitle {
  /** 관찰할 결과(then). 없으면 행동(when), 그것도 없으면 원문 */
  title: string
  /** 제목이 then일 때 그 행동(when). 같은 결과("오류 메시지가 표시된다")를 구별하는 데 쓴다. */
  context: string | null
}

function clean(s: string | null | undefined): string {
  return (s ?? '').replace(/\s+/g, ' ').trim().replace(/[.。]+$/, '')
}

export function shorten(s: string, max = TITLE_MAX): string {
  const chars = [...s]
  return chars.length > max ? chars.slice(0, max - 1).join('') + '…' : s
}

/** 단위에 제목 필드가 없어서 then/when으로 짧게 만든다 (CLAUDE.md 5장 판정 카드) */
export function cardTitle(unit: Pick<Unit, 'then' | 'when' | 'quote'>): CardTitle {
  const then = clean(unit.then)
  const when = clean(unit.when)
  if (then) return { title: shorten(then), context: when ? shorten(when) : null }
  return { title: shorten(when || clean(unit.quote)), context: null }
}

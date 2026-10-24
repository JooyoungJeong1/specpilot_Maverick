import type { Unit } from '../types/requirements.ts'

// backend/specpilot/schema.py의 item_keys와 같은 규칙. 바뀌면 같이 바꾼다.
const SOURCE_DESC = /Description\s*(\d+)/g
// 파이썬 \b는 한글도 글자로 본다. JS \b는 영문만 보므로 뒤에 글자·숫자·_가 없는지로 대신한다.
const SOURCE_ACTION = /Action(?:\s*\/\s*Event)?\s*([A-Z])(?![\p{L}\p{N}_])/gu
const SCREEN_PREFIX = /^([A-Z][A-Z0-9]*-\d{2,})\s+(.*)$/s

/**
 * 단위의 source를 기획서 항목 이름으로 바꾼다.
 * 예: screen_id "LOGIN-001", source ["Description 2-(1)", "Action/Event E"] → ["LOGIN-001 Description 2", "LOGIN-001 Action E"]
 * 다른 화면 ID가 붙은 source는 그 화면 항목이 되고, 번호가 없으면("화면 이미지") 원문을 그대로 붙인다.
 */
export function itemKeys(unit: Pick<Unit, 'screen_id' | 'source'>): string[] {
  const keys: string[] = []
  for (const raw of unit.source ?? []) {
    let s = String(raw)
    let prefix = unit.screen_id ?? ''
    const m = SCREEN_PREFIX.exec(s.trim())
    if (m) [, prefix, s] = m
    const found = [
      ...[...s.matchAll(SOURCE_DESC)].map((x) => `Description ${Number(x[1])}`),
      ...[...s.matchAll(SOURCE_ACTION)].map((x) => `Action ${x[1]}`),
    ]
    keys.push(...(found.length ? found.map((f) => `${prefix} ${f}`) : [`${prefix} ${s}`]))
  }
  return [...new Set(keys)]
}

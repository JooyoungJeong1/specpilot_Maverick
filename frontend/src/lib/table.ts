// 요구사항 표 (CLAUDE.md 5장 /table): 행 만들기, 거르기, 정렬
import type { ItemStatus, Judgments } from '../types/judgments.ts'
import { APP_SCREEN_ID, type Origin } from '../types/requirements.ts'
import type { ScreenGroup } from './screens.ts'
import { cardTitle } from './title.ts'
import type { UnitStatus, UnitView } from './verdicts.ts'

export type TableView = 'unit' | 'item'

export interface TableFilters {
  /** 보일 판정 */
  statuses: ReadonlySet<string>
  /** 화면 ID, "" = 모든 화면 */
  screen: string
  /** "" = 명시 + 함의 */
  origin: '' | Origin
  query: string
}

export interface UnitRow {
  view: UnitView
  group: ScreenGroup
  status: UnitStatus
}

export interface ItemRow {
  /** judgments.items의 키. 예: "LOGIN-001 Description 2" */
  key: string
  screenId: string
  /** 화면 ID를 뗀 항목 이름. 예: "Description 2" */
  item: string
  status: ItemStatus
  units: UnitView[]
}

/** "LOGIN-001 Description 2" → { screenId: "LOGIN-001", item: "Description 2" } */
export function splitItemKey(key: string): { screenId: string; item: string } {
  const m = /^(\S+) (.*)$/s.exec(key)
  return m ? { screenId: m[1], item: m[2] } : { screenId: '', item: key }
}

export function unitRows(groups: ScreenGroup[]): UnitRow[] {
  return groups.flatMap((group) => group.units.map((view) => ({ view, group, status: view.status })))
}

/** 기획서 항목 행. 집계(부분구현)는 judgments.items를 그대로 쓴다. 판정 전 단위는 items에 없다. */
export function itemRows(judgments: Judgments | null, views: UnitView[]): ItemRow[] {
  const byId = new Map(views.map((v) => [v.unit.id, v]))
  return Object.entries(judgments?.items ?? {}).map(([key, it]) => ({
    key,
    ...splitItemKey(key),
    status: it.status,
    units: it.units.map((id) => byId.get(id)).filter((v): v is UnitView => !!v),
  }))
}

function norm(s: string): string {
  return s.replace(/\s+/g, '').toLowerCase()
}

function matches(texts: (string | null | undefined)[], query: string): boolean {
  const q = norm(query)
  return !q || texts.some((t) => t && norm(t).includes(q))
}

function unitTexts(v: UnitView): string[] {
  const u = v.unit
  return [u.id, cardTitle(u).title, u.when ?? '', u.then, u.quote, u.source.join(' ')]
}

export function filterUnitRows(rows: UnitRow[], f: TableFilters): UnitRow[] {
  return rows.filter((r) =>
    f.statuses.has(r.status)
    && (!f.screen || r.view.unit.screen_id === f.screen)
    && (!f.origin || r.view.unit.origin === f.origin)
    && matches([...unitTexts(r.view), r.group.name], f.query))
}

export function filterItemRows(rows: ItemRow[], f: TableFilters): ItemRow[] {
  return rows.filter((r) =>
    f.statuses.has(r.status)
    && (!f.screen || r.screenId === f.screen)
    && (!f.origin || r.units.some((v) => v.unit.origin === f.origin))
    && matches([r.key, ...r.units.flatMap(unitTexts)], f.query))
}

/** 판정 순서(문제 큰 순)로. 같은 판정 안에서는 원래 순서 */
export function sortByStatus<R extends { status: string }>(rows: R[], order: readonly string[]): R[] {
  return rows.map((r, i) => ({ r, i })).sort((a, b) => order.indexOf(a.r.status) - order.indexOf(b.r.status) || a.i - b.i).map((x) => x.r)
}

/** 항목 행을 눌렀을 때 열 카드: 그 항목 화면의 단위를 먼저, 없으면 첫 단위 */
export function itemTarget(row: ItemRow): { screenId: string; unitId: string } | null {
  const v = row.units.find((x) => x.unit.screen_id === row.screenId) ?? row.units[0]
  return v ? { screenId: v.unit.screen_id, unitId: v.unit.id } : null
}

/** 그 판정의 카드가 펼쳐진 화면별 보기 주소 */
export function cardPath(screenId: string, unitId: string): string {
  return `/screen/${encodeURIComponent(screenId)}?unit=${encodeURIComponent(unitId)}`
}

/** 앱 전체 요구사항은 화면별 보기에 두지 않고 요구사항 표에서 본다. 단위 ID를 주면 그 요구사항으로 검색해 둔다 */
export function appTablePath(unitId?: string): string {
  const q = new URLSearchParams({ screen: APP_SCREEN_ID, ...(unitId ? { q: unitId } : {}) })
  return `/table?${q}`
}

/** 그 판정을 보는 곳: 화면 요구사항은 화면별 보기의 카드, 앱 전체 요구사항은 요구사항 표 */
export function unitPath(screenId: string, unitId: string): string {
  return screenId === APP_SCREEN_ID ? appTablePath(unitId) : cardPath(screenId, unitId)
}

/**
 * 사양서 "근거 요구사항" 칸("REQ-A, REQ-B" 또는 "-") → 단위 ID와 그 판정을 보는 주소.
 * 결과에 없는 ID는 주소 없이 글자로만 둔다.
 */
export function unitLinks(cell: string, screenOf: ReadonlyMap<string, string>): { id: string; path: string | null }[] {
  return cell.split(',').map((s) => s.trim()).filter((s) => s && s !== '-').map((id) => {
    const screenId = screenOf.get(id)
    return { id, path: screenId ? unitPath(screenId, id) : null }
  })
}

/** 판정 카드의 DOM id (행을 눌러 온 카드로 스크롤할 때) */
export function cardDomId(unitId: string): string {
  return `card-${unitId}`
}

/** 원문 칸: 그 항목 화면의 단위 원문을 먼저 */
export function itemQuote(row: ItemRow): string {
  return (row.units.find((v) => v.unit.screen_id === row.screenId) ?? row.units[0])?.unit.quote ?? ''
}

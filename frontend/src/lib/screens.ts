import { APP_SCREEN_ID } from '../types/requirements.ts'
import type { Question, Requirements, ScreenMeta, ScreenStatusEntry, SkippedItem } from '../types/requirements.ts'
import type { UnitView } from './verdicts.ts'

export interface ScreenGroup {
  /** 화면 ID 또는 "APP" */
  id: string
  isApp: boolean
  name: string
  /** app_profile.screens의 화면 정보. 앱 전체는 null */
  meta: ScreenMeta | null
  /** ② 상태 (완료·확인필요·실패·반려 …). 앱 전체는 null */
  runStatus: ScreenStatusEntry | null
  /** 반려된 화면이면 이유. 반려 화면도 숨기지 않고 묶음에 남긴다. */
  rejectReason: string | null
  units: UnitView[]
  questions: Question[]
  skipped: SkippedItem[]
}

export const APP_GROUP_NAME = '앱 전체'

/** 질문 ID에서 화면을 읽는다. Q-APP-01 → "APP", Q-LOGIN-001-03 → "LOGIN-001" */
export function questionScope(id: string): string {
  const m = /^Q-(.+)-\d+$/.exec(id)
  return m ? m[1] : APP_SCREEN_ID
}

/**
 * 단위와 질문을 화면별로 묶는다. 앱 전체(APP)가 맨 앞, 그다음 app_profile.screens 순서.
 * 단위는 단위의 screen_id로 묶는다 (판정의 screen_id는 판정한 화면이라 다를 수 있다).
 * 화면 목록에 없는 화면 ID가 나오면 버리지 않고 맨 뒤에 묶음을 만든다.
 */
export function groupByScreen(requirements: Requirements, views: UnitView[]): ScreenGroup[] {
  const groups = new Map<string, ScreenGroup>()
  const make = (id: string, meta: ScreenMeta | null): ScreenGroup => ({
    id,
    isApp: id === APP_SCREEN_ID,
    name: id === APP_SCREEN_ID ? APP_GROUP_NAME : meta?.name ?? id,
    meta,
    runStatus: requirements.screen_status[id] ?? null,
    rejectReason: requirements.rejected_screens[id] ?? requirements.screen_status[id]?.reject_reason ?? null,
    units: [],
    questions: [],
    skipped: requirements.skipped[id] ?? [],
  })
  const get = (id: string) => {
    let g = groups.get(id)
    if (!g) groups.set(id, (g = make(id, null)))
    return g
  }

  const app = make(APP_SCREEN_ID, null)
  groups.set(APP_SCREEN_ID, app)
  for (const s of requirements.app_profile.screens) groups.set(s.screen_id, make(s.screen_id, s))

  for (const v of views) get(v.unit.screen_id).units.push(v)
  for (const q of requirements.questions) get(questionScope(q.id)).questions.push(q)

  if (!app.units.length && !app.questions.length) groups.delete(APP_SCREEN_ID)
  return [...groups.values()]
}

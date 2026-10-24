// requirements.json: backend/specpilot/merge.py가 쓰는 형식 그대로.
// 단위·질문 필드는 backend/prompts/blocks/unit_schema.txt, schema.py(UNIT_FIELDS, assign_ids, gate_implied).

export const APP_SCREEN_ID = 'APP'

export type UnitKind = '표시' | '검증' | '상태' | '이동' | '처리' | '실패' | '접근' | '제약'
export type Origin = '명시' | '함의'
export type Priority = '상' | '하'

export interface Exact {
  message: string | null
  values: string[]
  target: string | null
}

/** 값이 이 화면에 없고 다른 화면에 같은 규칙으로 적혀 있을 때. 판정 기준이 아니라 참고용. */
export interface RefHint {
  screen_id: string
  source?: string
  value: string
}

export interface Unit {
  /** REQ-{화면ID}-{번호}, 앱 전체는 REQ-APP-{번호}. 프로그램이 붙인다. */
  id: string
  /** LLM 응답 안 번호(u01, a01). 화면에 쓰지 않는다. */
  key: string | null
  /** 화면 ID, 앱 전체는 "APP" */
  screen_id: string
  /** 예: ["Description 2-(1)", "Action E"], ["상태 화면 p.2"], ["화면 이미지"], ["LOGIN-004 Description 0"] */
  source: string[]
  /** 원문 그대로. 함의는 근거 원문 둘 이상을 " / "로 잇는다. */
  quote: string
  origin: Origin
  /** 함의의 추론 한 문장. 명시는 null. */
  reason: string | null
  kind: UnitKind
  given: string | null
  when: string | null
  conditions: string[]
  then: string
  exact: Exact
  issue: string | null
  ref_hint: RefHint | null
}

export interface Question {
  /** Q-APP-{번호} 또는 Q-{화면ID}-{번호} */
  id: string
  /** LLM 응답 안 번호(q01). 프로그램이 만든 질문은 null. */
  key: string | null
  topic: string
  question: string
  why: string
  priority: Priority
  /** 단위 ID 목록 */
  related_units: string[]
  /** 근거가 약한 함의를 프로그램이 질문으로 옮겼을 때 원래 단위 (schema.gate_implied) */
  draft_unit?: Unit
}

/**
 * 백엔드가 반드시 검사하는 필드는 screen_id, name, pages뿐이다 (schema.SCREEN_META_FIELDS).
 * 나머지는 ①이 빠뜨려도 통과하므로 없을 수 있다.
 */
export interface ScreenMeta {
  screen_id: string
  name: string
  depth?: string | null
  pages: number[]
  type?: '화면' | '팝업'
  state_pages?: number[]
  /** 다른 화면(부모)의 항목을 그대로 되풀이하는 화면이면 그 화면과 항목 */
  repeats_from?: { screen_id: string; items: string[] } | null
  /** 기획서에 화면 ID가 없어 프로그램이 SCR-001… 을 붙였을 때만 true */
  id_assigned?: boolean
}

export interface Flow {
  from: string
  trigger: string
  to: string
  source: string
}

export interface CommonArea {
  name: string
  described_in: string
  described_scope: string[]
  appears_in: string[]
}

export interface LoginRequired {
  screen_id: string
  value: boolean
  evidence: string
}

export interface Role {
  name: string
  origin: Origin
  evidence: string
}

export interface RoleLimited {
  feature: string
  screen_id: string
  element: string
  opens: string | null
  allowed: string[]
  origin: Origin
  evidence: string
  reason: string | null
}

export interface ReadingNote {
  screen_id: string | null
  pages: number[]
  note: string
}

/** ①의 결과에서 units, questions, rejected를 뺀 것 */
export interface AppProfile {
  screens: ScreenMeta[]
  flows: Flow[]
  common_areas: CommonArea[]
  login_required: LoginRequired[]
  roles: Role[]
  role_limited: RoleLimited[]
  reading_notes: ReadingNote[]
}

export interface SkippedItem {
  source: string
  reason: string
}

/** ② 화면 상태. "미실행"·"알수없음"은 결과 파일이나 meta가 없을 때 merge.py가 붙인다. */
export type ScreenRunStatus = '완료' | '확인필요' | '실패' | '반려' | '미실행' | '알수없음'

/**
 * 경우마다 있는 필드가 다르다 (merge.py).
 * - 결과 있음(완료·확인필요·실패): status, units, questions, attempts, prompt_version
 * - 반려: status, units(0), reject_reason, rejected_by("②" 또는 "게이트(입력 점검)")
 * - 결과 파일 없음: status, units(0)
 */
export interface ScreenStatusEntry {
  status: ScreenRunStatus
  units: number
  questions?: number
  attempts?: number | null
  prompt_version?: string | null
  reject_reason?: string
  rejected_by?: string
}

/** 검사를 끝내 통과하지 못해 뺀 단위·질문 (stages._split_invalid). ID를 붙이기 전이라 모양이 자유롭다. */
export interface RejectedUnits {
  units: { unit: Record<string, unknown>; errors: string[] }[]
  questions: { question: Record<string, unknown>; errors: string[] }[]
}

export interface Requirements {
  meta: { merged_at: string; run_dir: string }
  app_profile: AppProfile
  /** 앱 전체 단위가 먼저, 그다음 화면 순서 */
  units: Unit[]
  /** 우선순위 상이 먼저 (merge.py가 정렬함) */
  questions: Question[]
  /** 결과가 있는 화면만 키가 있다 */
  skipped: Record<string, SkippedItem[]>
  screen_status: Record<string, ScreenStatusEntry>
  /** 화면 ID → 반려 이유 */
  rejected_screens: Record<string, string>
  /** 화면 ID 또는 "APP" → 뺀 단위·질문 */
  rejected_units: Record<string, RejectedUnits>
}

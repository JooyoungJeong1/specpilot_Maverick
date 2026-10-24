// 판정 카드와 요구사항 표에 쓰는 쉬운 문장. 필드 이름(evidence, mismatch …)을 화면에 내보내지 않는다.
import type { MismatchField, MismatchValue } from '../types/judgments.ts'
import { APP_SCREEN_ID, type Unit } from '../types/requirements.ts'
import { formatPages } from './summary.ts'
import { NOT_JUDGED, type StatusChange, type UnitView } from './verdicts.ts'

const FIELD_LABELS: Record<MismatchField, string> = {
  message: '문구',
  values: '값',
  target: '이동 화면',
  when: '동작',
  conditions: '조건',
  then: '결과',
}

export function fieldLabel(field: string): string {
  return FIELD_LABELS[field as MismatchField] ?? '내용'
}

/** 차이 표의 값. AI가 정한 형식 밖의 값(객체 등)도 글자로 보여 준다 */
export function formatValue(v: MismatchValue | unknown): string {
  if (v === null || v === undefined || v === '') return '(없음)'
  if (Array.isArray(v)) return v.map((x) => (typeof x === 'object' && x !== null ? JSON.stringify(x) : String(x))).join(', ')
  return typeof v === 'object' ? JSON.stringify(v) : String(v)
}

export const EVIDENCE_FAILED = 'AI가 댄 근거 코드를 실제 코드에서 찾지 못함'
export const NOT_JUDGED_TEXT = '아직 코드와 비교하지 않았습니다. 이 화면의 코드 비교가 실패했거나 아직 실행하지 않았습니다.'

/** 프로그램이 판정을 바꾼 이유 (CLAUDE.md 3장) */
export function changeText(change: StatusChange): string {
  return change.reason === 'evidence'
    ? `AI가 댄 근거 코드를 확인하지 못해 확인필요로 바꿈 (원래: ${change.from})`
    : '띄어쓰기만 다름 (원래: 불일치 → 구현으로 봄)'
}

// 프로그램이 note 끝에 붙이는 꼬리표. 같은 내용을 "판정이 바뀐 이유"로 따로 보여 주므로 뺀다.
const PROGRAM_TAGS = /\s*\[(근거 불일치로 확인필요 처리|문구가 띄어쓰기만 달라 구현으로 처리)\]/g

/** 판정 메모. 프로그램 꼬리표를 빼고, "판정 누락 (LLM이 …)"은 쉬운 말로 바꾼다. */
export function cleanNote(note: string | null | undefined): string | null {
  if (!note) return null
  if (note.startsWith('판정 누락')) return 'AI가 이 요구사항의 판정을 내지 않아 확인필요로 두었습니다.'
  return note.replace(PROGRAM_TAGS, '').trim() || null
}

/** 단위의 기획서 위치. 예: "4쪽 Description 2", 앱 전체는 근거 위치를 그대로 */
export function unitLocation(unit: Pick<Unit, 'screen_id' | 'source'>, pages?: number[]): string {
  const src = unit.source.join(', ')
  if (unit.screen_id === APP_SCREEN_ID) return src
  return [formatPages(pages), src].filter(Boolean).join(' ')
}

/** 요구사항 표 "검토사항" 칸: 가장 먼저 봐야 할 한 가지 */
export function reviewText(v: UnitView): string {
  const r = v.result
  if (v.status === NOT_JUDGED) return '코드와 아직 비교하지 않음'
  if (v.change) return changeText(v.change)
  if (v.evidenceFailed) return EVIDENCE_FAILED
  const mm = r?.mismatch?.[0]
  if (mm) return `${fieldLabel(mm.field)} 다름: 기획서 "${formatValue(mm.spec)}" → 코드 "${formatValue(mm.code)}"`
  if (r?.split_issue) return `한 요구사항 안에서 판정이 갈림: ${r.split_issue}`
  if (v.unit.issue) return `기획서 확인 필요: ${v.unit.issue}`
  if (v.unit.origin === '함의' && v.unit.reason) return `추론: ${v.unit.reason}`
  if (v.status !== '구현') return cleanNote(r?.note) ?? '-'
  return '-'
}

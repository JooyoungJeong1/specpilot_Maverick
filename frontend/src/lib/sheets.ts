// 엑셀 시트 내용. 사양서 미리보기(/spec)와 내보내기(xlsx)가 같은 행을 쓴다.
// 사양서는 백엔드가 만드는 기업 양식 엑셀(backend/specpilot/excel.py, 테스트사양서.xlsx)과 같은 시트·열이다:
//   개정이력, 00. 목차, NN. <DEPTH(1)> (메뉴별 시나리오 시트)
// 열은 CLAUDE.md 3장 대응표: 시험번호=scenario_id, 시나리오명=title, DEPTH(1)/(2)=depth1/depth2, 시험절차=action,
// 예상결과=expected, 시험데이터=계정 account / 입력값 input / 비고 note, 확인결과=빈칸, 근거 요구사항=unit_ids,
// 데이터 출처=data_source. 백엔드 엑셀이 있으면 내려받기는 그 파일을 그대로 쓰고(서식 포함), 여기 행은 미리보기와
// 백엔드 파일이 없을 때(예시 데이터 등)만 쓴다. 사양서에는 판정 결과를 넣지 않는다 (CLAUDE.md 4장 6번).
import type { Judgments } from '../types/judgments.ts'
import type { Requirements, Unit } from '../types/requirements.ts'
import type { Scenario, Scenarios, ScenarioStep } from '../types/scenarios.ts'
import { changeText, cleanNote, EVIDENCE_FAILED, fieldLabel, formatValue, reviewText } from './judgeText.ts'
import { groupByScreen, questionScope } from './screens.ts'
import { sortByPriority } from './summary.ts'
import { itemRows, sortByStatus } from './table.ts'
import { cardTitle } from './title.ts'
import { ITEM_STATUSES, mergeVerdicts } from './verdicts.ts'

export type Cell = string | number
export interface Sheet {
  name: string
  header: string[]
  rows: Cell[][]
}

export type ExportKind = 'spec' | 'trace' | 'checklist' | 'judgment' | 'questions'

/**
 * backend: 백엔드가 실행 폴더에 만들어 두는 엑셀. 있으면 그 파일을 그대로 내려받는다.
 * 추적표는 백엔드 파일로만 내려받는다 (④를 돌리면 사양서와 함께 생긴다).
 */
export const EXPORT_KINDS: { kind: ExportKind; title: string; desc: string; file: string; backend?: string }[] = [
  { kind: 'spec', title: '테스트 사양서', desc: '기업 양식: 개정이력, 목차, 메뉴별 시험절차와 예상결과 (엑셀)', file: '테스트사양서', backend: '테스트사양서.xlsx' },
  { kind: 'trace', title: '추적표', desc: '요구사항마다 판정(③)과 사양서 시나리오·단계(④)를 한 줄로 잇는 표 (엑셀)', file: '추적표', backend: '추적표.xlsx' },
  { kind: 'checklist', title: '구현 체크리스트', desc: '기획서에서 뽑은 구현 확인 항목 목록 (엑셀)', file: '구현체크리스트' },
  { kind: 'judgment', title: '정합성 판정 결과', desc: '요구사항별 판정, 기획서 항목별 집계(부분구현 포함), 근거 코드 위치 (엑셀)', file: '정합성판정결과' },
  { kind: 'questions', title: '질문 시트', desc: '기획자에게 확인할 항목 (엑셀)', file: '질문시트' },
]

/** 파일 이름에 쓸 수 없는 글자를 _로 */
export function fileSafe(s: string): string {
  return s.replace(/[\\/:*?"<>|]+/g, '_').trim()
}

export function exportFileName(kind: ExportKind, label: string): string {
  const file = EXPORT_KINDS.find((k) => k.kind === kind)!.file
  return `${file}_${fileSafe(label)}.xlsx`
}

/** 브라우저에서 만들어 내보낼 시트. 사양서가 없으면(④ 전) null, 추적표는 백엔드 파일로만 내므로 null */
export function exportSheets(kind: ExportKind, data: { requirements: Requirements; judgments: Judgments | null; scenarios: Scenarios | null }): Sheet[] | null {
  switch (kind) {
    case 'spec': return data.scenarios ? specSheets(data.scenarios) : null
    case 'trace': return null
    case 'checklist': return [checklistSheet(data.requirements)]
    case 'judgment': return judgmentSheets(data.requirements, data.judgments)
    case 'questions': return [questionSheet(data.requirements)]
  }
}

export const SPEC_HEADER = ['시험번호', '시나리오명', 'DEPTH(1)', 'DEPTH(2)', 'No', '시험절차', '예상결과', '계정', '입력값', '비고', '확인결과', '근거 요구사항', '데이터 출처']
export const TOC_HEADER = ['메뉴명', 'DEPTH(1)', 'DEPTH(2)', '시나리오 수', '단계 수', '목차번호', '작성여부', '작성일자']
export const HISTORY_HEADER = ['버전', '일자', '내용', '작성자']
export const QUESTION_HEADER = ['번호', '화면', '우선순위', '주제', '질문', '이유', '관련 요구사항', '답변']
/** 사양서 작성자 칸 (백엔드 엑셀과 같다) */
export const SPEC_WRITER = 'SpecPilot (자동 생성)'
/** 데이터 출처: 프롬프트 안의 말(설계서)을 사양서에서는 기획서로 보여 준다 */
const DATA_SOURCE: Record<string, string> = { 설계서: '기획서' }

/** 준비 단계(로그인·화면 이동 등). 백엔드는 true/false, 예시 데이터는 null */
export function isSetup(step: ScenarioStep): boolean {
  return step.setup === true || (typeof step.setup === 'string' && step.setup !== '')
}

/** 엑셀 시트 이름: 31자까지, : \ / ? * [ ] 는 쓸 수 없고, 겹치면 번호를 붙인다 */
export function sheetName(name: string, used: Set<string>): string {
  const base = (name.replace(/[:\\/?*[\]]/g, ' ').trim() || '시트').slice(0, 31)
  let n = base
  for (let i = 2; used.has(n); i++) n = `${base.slice(0, 31 - String(i).length - 1)} ${i}`
  used.add(n)
  return n
}

/** 메뉴 시트 행. 빈 값은 "-" (기업 양식), 확인결과는 테스터가 채울 빈칸. 시나리오명은 시나리오 첫 단계에만 */
function specRows(scenarios: Scenario[]): Cell[][] {
  return scenarios.flatMap((sc) => sc.steps.map((st, k) => [
    sc.scenario_id, k === 0 ? sc.title ?? '' : '', sc.depth1, sc.depth2, st.no, st.action, st.expected,
    st.account || '-', st.input || '-', st.note || (isSetup(st) ? '준비 단계' : '-'), '',
    st.unit_ids.join(', ') || '-', (st.data_source && (DATA_SOURCE[st.data_source] ?? st.data_source)) || '-',
  ]))
}

export function questionSheet(requirements: Requirements): Sheet {
  return {
    name: '질문 시트',
    header: QUESTION_HEADER,
    rows: sortByPriority(requirements.questions).map((q) => {
      const scope = questionScope(q.id)
      return [q.id, scope === 'APP' ? '앱 전체' : scope, q.priority, q.topic, q.question, q.why, q.related_units.join(', '), '']
    }),
  }
}

const pad2 = (n: number) => String(n).padStart(2, '0')

/** 사양서를 합친 날짜 (scenarios.json meta.merged_at). 예시 데이터처럼 없으면 빈칸 */
export function specDate(scenarios: Scenarios): string {
  return /^\d{4}-\d{2}-\d{2}/.exec(scenarios.meta?.merged_at ?? '')?.[0] ?? ''
}

/**
 * 테스트 사양서: 개정이력, 00. 목차, 메뉴(DEPTH(1))별 시나리오 시트 (기업 양식, 미리보기의 시트 탭과 같은 순서).
 * 질문은 사양서에 넣지 않는다 (내보내기의 "질문 시트"로 따로 낸다).
 */
export function specSheets(scenarios: Scenarios): Sheet[] {
  const written = specDate(scenarios)
  const used = new Set(['개정이력', '00. 목차'])
  const depth1s = [...new Set(scenarios.scenarios.map((s) => s.depth1))]
  const menus = depth1s.map((d, i) => ({
    name: sheetName(`${pad2(i + 1)}. ${d}`, used), depth1: d, list: scenarios.scenarios.filter((s) => s.depth1 === d),
  }))
  const toc: Cell[][] = menus.flatMap((m, i) => {
    const depth2s = [...new Set(m.list.map((s) => s.depth2))]
    return depth2s.map((d2, j) => {
      const mine = m.list.filter((s) => s.depth2 === d2)
      return [j === 0 ? m.name : '', j === 0 ? `${m.depth1} (01)` : '', `${d2} (${pad2(j + 1)})`, mine.length,
        mine.reduce((n, s) => n + s.steps.length, 0), Number(`${i + 1}01${pad2(j + 1)}`), 'O', written]
    })
  })
  return [
    { name: '개정이력', header: HISTORY_HEADER, rows: [['1.0', written, '④ 시나리오 합성으로 처음 만듦 (예상결과는 기획서 기준)', SPEC_WRITER]] },
    { name: '00. 목차', header: TOC_HEADER, rows: toc },
    ...menus.map((m) => ({ name: m.name, header: SPEC_HEADER, rows: specRows(m.list) })),
  ]
}

/** 미리보기에서 처음 여는 시트: 첫 메뉴 시트 (개정이력·목차 다음) */
export const SPEC_FIRST_MENU = 2

function condition(u: Unit): string {
  return [u.given && `사전 상태: ${u.given}`, u.when && `동작: ${u.when}`, ...u.conditions.map((c) => `조건: ${c}`)]
    .filter(Boolean).join('\n')
}

function specValues(u: Unit): string {
  const ex = u.exact
  return [ex.message && `문구: ${ex.message}`, ex.values.length ? `값: ${ex.values.join(', ')}` : '', ex.target && `이동: ${ex.target}`]
    .filter(Boolean).join('\n')
}

/** 구현 체크리스트: 기획서에서 뽑은 구현 확인 항목. 판정은 넣지 않는다. */
export function checklistSheet(requirements: Requirements): Sheet {
  const names = new Map(requirements.app_profile.screens.map((s) => [s.screen_id, s.name]))
  return {
    name: '구현 체크리스트',
    header: ['요구사항 ID', '화면', '화면 이름', '기획서 위치', '명시/함의', '조건', '기대 결과', '기획서 값', '기획서 원문', '추론', '기획서 확인 필요', '확인'],
    rows: requirements.units.map((u) => [
      u.id, u.screen_id === 'APP' ? '앱 전체' : u.screen_id, u.screen_id === 'APP' ? '' : names.get(u.screen_id) ?? '',
      u.source.join(', '), u.origin, condition(u), u.then, specValues(u), u.quote, u.reason ?? '', u.issue ?? '', '',
    ]),
  }
}

/** 정합성 판정 결과: 요구사항별 / 기획서 항목별(부분구현 포함) / 기획서에 없는 구현 */
export function judgmentSheets(requirements: Requirements, judgments: Judgments | null): Sheet[] {
  const views = mergeVerdicts(requirements.units, judgments)
  const groups = groupByScreen(requirements, views)
  const name = new Map(groups.map((g) => [g.id, g.name]))
  return [
    {
      name: '요구사항별',
      header: ['요구사항 ID', '화면', '요구사항', '명시/함의', '판정', '판정이 바뀐 이유', '판정 메모', '한 요구사항 안에서 갈린 판정', '기획서와 코드 차이', '근거 코드', '기획서 확인 필요', '검토사항'],
      rows: views.map((v) => {
        const r = v.result
        return [
          v.unit.id, name.get(v.unit.screen_id) ?? v.unit.screen_id, cardTitle(v.unit).title, v.unit.origin, v.status,
          v.change ? changeText(v.change) : v.evidenceFailed ? EVIDENCE_FAILED : '',
          cleanNote(r?.note) ?? '', r?.split_issue ?? '',
          (r?.mismatch ?? []).map((m) => `${fieldLabel(m.field)}: 기획서 "${formatValue(m.spec)}" / 코드 "${formatValue(m.code)}"`).join('\n'),
          (r?.evidence ?? []).map((e) => `${e.file}:${e.line}`).join('\n'),
          v.unit.issue ?? '', reviewText(v),
        ]
      }),
    },
    {
      name: '기획서 항목별',
      header: ['화면', '기획서 항목', '판정', '요구사항'],
      rows: sortByStatus(itemRows(judgments, views), ITEM_STATUSES)
        .map((r) => [r.screenId === 'APP' ? '앱 전체' : r.screenId, r.item, r.status, r.units.map((v) => v.unit.id).join(', ')]),
    },
    {
      name: '기획서에 없는 구현',
      header: ['화면', '파일', '줄', '코드', '설명'],
      rows: (judgments?.extras ?? []).map((e) => [e.screen_id, e.file, e.line, e.code, e.description]),
    },
  ]
}

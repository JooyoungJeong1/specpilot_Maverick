// 엑셀 시트 내용. 사양서 미리보기(/spec)와 내보내기(xlsx)가 같은 행을 쓴다.
// 사양서 열은 CLAUDE.md 3장 대응표: 시험번호=scenario_id, DEPTH(1)/(2)=depth1/depth2, 시험절차=action,
// 예상결과=expected, 시험데이터=account / input / note, 확인결과=빈칸, 근거 요구사항=unit_ids.
// 사양서에는 판정 결과를 넣지 않는다 (CLAUDE.md 4장 6번).
import type { Judgments } from '../types/judgments.ts'
import type { Requirements, Unit } from '../types/requirements.ts'
import type { Scenarios, ScenarioStep } from '../types/scenarios.ts'
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

export type ExportKind = 'spec' | 'checklist' | 'judgment' | 'questions'

export const EXPORT_KINDS: { kind: ExportKind; title: string; desc: string; file: string }[] = [
  { kind: 'spec', title: '테스트 사양서', desc: '기획서 기준 시험절차와 예상결과 (엑셀)', file: '테스트사양서' },
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

/** 내보낼 시트. 사양서가 없으면(④ 전) null */
export function exportSheets(kind: ExportKind, data: { requirements: Requirements; judgments: Judgments | null; scenarios: Scenarios | null }): Sheet[] | null {
  switch (kind) {
    case 'spec': return data.scenarios ? specSheets(data.scenarios, data.requirements) : null
    case 'checklist': return [checklistSheet(data.requirements)]
    case 'judgment': return judgmentSheets(data.requirements, data.judgments)
    case 'questions': return [questionSheet(data.requirements)]
  }
}

export const SPEC_HEADER =['시험번호', 'DEPTH(1)', 'DEPTH(2)', 'No', '시험절차', '예상결과', '시험데이터', '확인결과', '근거 요구사항']
export const QUESTION_HEADER = ['번호', '화면', '우선순위', '주제', '질문', '이유', '관련 요구사항', '답변']

/** 시험데이터 = account / input / note */
export function testData(step: ScenarioStep): string {
  return [step.account, step.input, step.note].filter(Boolean).join(' / ')
}

/** 엑셀 시트 이름: 31자까지, : \ / ? * [ ] 는 쓸 수 없고, 겹치면 번호를 붙인다 */
export function sheetName(name: string, used: Set<string>): string {
  const base = (name.replace(/[:\\/?*[\]]/g, ' ').trim() || '시트').slice(0, 31)
  let n = base
  for (let i = 2; used.has(n); i++) n = `${base.slice(0, 31 - String(i).length - 1)} ${i}`
  used.add(n)
  return n
}

function specRows(scenarios: Scenarios, depth1?: string): Cell[][] {
  return scenarios.scenarios
    .filter((sc) => depth1 === undefined || sc.depth1 === depth1)
    .flatMap((sc) => sc.steps.map((st) => [
      sc.scenario_id, sc.depth1, sc.depth2, st.no, st.action, st.expected, testData(st), '', st.unit_ids.join(', '),
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

/** 테스트 사양서: 전체 / depth1별 / 질문 시트 (미리보기의 시트 탭과 같은 순서) */
export function specSheets(scenarios: Scenarios, requirements: Requirements): Sheet[] {
  const used = new Set<string>()
  const depth1s = [...new Set(scenarios.scenarios.map((s) => s.depth1))]
  return [
    { name: sheetName('전체', used), header: SPEC_HEADER, rows: specRows(scenarios) },
    ...depth1s.map((d) => ({ name: sheetName(d, used), header: SPEC_HEADER, rows: specRows(scenarios, d) })),
    { ...questionSheet(requirements), name: sheetName('질문 시트', used) },
  ]
}

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

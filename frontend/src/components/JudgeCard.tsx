// 판정 카드 (CLAUDE.md 5장). 화면별 보기의 오른쪽 탭에서도 그대로 쓴다. 초안 .unit 구조를 따른다.
import type { Evidence } from '../types/judgments.ts'
import { changeText, cleanNote, EVIDENCE_FAILED, fieldLabel, formatValue, NOT_JUDGED_TEXT, unitLocation } from '../lib/judgeText.ts'
import type { LocateResult } from '../lib/quoteLocate.ts'
import type { StepRef } from '../lib/scenarioIndex.ts'
import { quoteSegments } from '../lib/quote.ts'
import { statusClass } from '../lib/summary.ts'
import { cardDomId } from '../lib/table.ts'
import { cardTitle } from '../lib/title.ts'
import { NOT_JUDGED, type UnitView } from '../lib/verdicts.ts'

interface Props {
  view: UnitView
  /** 그 화면의 기획서 쪽 (위치 표시용) */
  pages?: number[]
  open: boolean
  onToggle: () => void
  /** 이 단위를 확인하는 테스트 단계 */
  steps?: StepRef[]
  /** "확인하는 테스트"의 단계를 누르면 사양서 탭의 그 단계로 간다. 없으면 글자로만 보여 준다 */
  onPickStep?: (step: StepRef) => void
  /** "코드 앞뒤 보기". 없으면 버튼을 막아 둔다 */
  onShowCode?: (ev: Evidence) => void
  /** 기획서 페이지에서 원문 위치를 찾은 결과. 페이지를 보여 주지 않으면 undefined */
  locate?: LocateResult
  /** 카드에 마우스를 올리면 형광펜을 강조 */
  onHover?: (on: boolean) => void
}

/** 원문 위치를 못 찾았거나 비슷한 곳에 표시했을 때 카드에 붙일 말 */
function locateNote(r: LocateResult | undefined): string | null {
  if (!r) return null
  switch (r.status) {
    case 'found': return null
    case 'approx': return '원문과 한두 글자 다른 곳에 표시했습니다.'
    case 'partial': return `원문 일부만 위치를 찾았습니다 (${r.reason}).`
    case 'skipped': return r.reason
    case 'none': return `원문 위치를 찾지 못함 (${r.reason})`
  }
}

export default function JudgeCard({ view, pages, open, onToggle, steps = [], onPickStep, onShowCode, locate, onHover }: Props) {
  const { unit: u, result: r, status } = view
  const { title, context } = cardTitle(u)
  const note = cleanNote(r?.note)
  const where = unitLocation(u, pages)
  const bodyId = `${cardDomId(u.id)}-body`

  return (
    <div className={`unit${open ? ' on' : ''}`} id={cardDomId(u.id)} data-box={u.id}>
      <button type="button" aria-expanded={open} aria-controls={bodyId} onClick={onToggle}
        onMouseEnter={() => onHover?.(true)} onMouseLeave={() => onHover?.(false)}>
        <span className={`i c-${statusClass(status)}`} />
        <span className="tt">
          {title}{u.origin === '함의' && <span className="og">함의</span>}
          <small>{context && `${context} · `}<span className="nw">{u.id}</span>{where && ` · ${where}`}</small>
        </span>
        <span className={`pill p-${statusClass(status)}`}>{status}</span>
      </button>
      {open && (
        <div className="more" id={bodyId}>
          <div className="qlbl">기획서 원문 · {u.source.join(', ')}</div>
          {quoteSegments(u.quote).map((q, i) => <div className="quote" key={i}>{q}</div>)}
          {locateNote(locate) && <p className="small faint loc-note">{locateNote(locate)}</p>}

          {u.origin === '함의' && u.reason && <>
            <div className="lbl" style={{ marginTop: 0 }}>추론 (함의)</div>
            <div className="muted" style={{ marginBottom: 8 }}>{u.reason}</div>
          </>}

          {status === NOT_JUDGED && <div className="muted">{NOT_JUDGED_TEXT}</div>}
          {note && <div>{note}</div>}
          {r?.split_issue && <p className="small muted split">한 요구사항 안에서 판정이 갈림: {r.split_issue}</p>}

          {r?.mismatch.map((m, i) => (
            <table className="cmp" key={i}>
              <caption>{fieldLabel(m.field)} 차이</caption>
              <tbody>
                <tr><td>기획서</td><td>{formatValue(m.spec)}</td></tr>
                <tr><td>코드</td><td>{formatValue(m.code)}</td></tr>
              </tbody>
            </table>
          ))}

          {(view.change || view.evidenceFailed) && <>
            <div className="lbl">판정이 바뀐 이유</div>
            <div className="muted">{view.change ? changeText(view.change) : `${EVIDENCE_FAILED} (판정은 그대로)`}</div>
            {r?.evidence_problems?.map((p, i) => <div className="small faint" key={i}>{p}</div>)}
          </>}

          {u.issue && <>
            <div className="lbl">기획서 확인 필요</div>
            <div className="muted">{u.issue}</div>
          </>}

          {u.ref_hint && (
            <p className="small faint" style={{ margin: '8px 0 0' }}>
              참고: {u.ref_hint.screen_id} {u.ref_hint.source} 에는 "{u.ref_hint.value}"로 적혀 있음 (판정 기준 아님)
            </p>
          )}

          {!!r?.evidence.length && <>
            <div className="lbl">{view.evidenceFailed ? 'AI가 댄 근거 코드 (확인 안 됨)' : '근거 코드'}</div>
            {r.evidence.map((ev, i) => (
              <div key={i} className="ev">
                <div className="cref">{ev.file}:{ev.line}</div>
                <div className="code"><span className="ln">{ev.line}</span>{ev.code}</div>
                <button type="button" className="linkbtn" style={{ marginTop: 6 }} disabled={!onShowCode}
                  title={onShowCode ? undefined : '코드 보기는 준비 중입니다'} onClick={() => onShowCode?.(ev)}>
                  코드 앞뒤 보기
                </button>
              </div>
            ))}
          </>}

          {steps.length > 0 && <>
            <div className="lbl">확인하는 테스트</div>
            <div className="steprefs">
              {steps.map((s) => {
                const label = `${s.scenarioId} ${s.no}단계`
                return onPickStep
                  ? <button type="button" className="linkbtn" key={label} title={s.action} onClick={() => onPickStep(s)}>{label}</button>
                  : <span className="muted" key={label}>{label}</span>
              })}
            </div>
          </>}
        </div>
      )}
    </div>
  )
}

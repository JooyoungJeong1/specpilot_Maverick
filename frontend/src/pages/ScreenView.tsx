// 화면별 보기 (CLAUDE.md 5장 /screen/:id). 초안 local/reference/app.html의 screen()을 옮겼다.
// 왼쪽 화면 목록, 가운데 기획서 페이지와 형광펜, 오른쪽 탭(정합성 판정 / 테스트 사양서 / 질문).
// ?unit=<단위 ID>: 펼친 카드. 요구사항 표에서 행을 눌러 오면 그 카드가 펼쳐지고 형광펜 위치로 스크롤한다.
// 판정 카드의 "확인하는 테스트"와 사양서 탭 단계의 근거 요구사항은 서로 오간다 (요구사항 ↔ 테스트 추적).
// 앱 전체 요구사항(REQ-APP)은 기획서 페이지가 없어서 여기 두지 않고 요구사항 표에서 본다 (/screen/APP는 표로 보낸다).
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useCurrentRun, usePdfUrl } from '../api/useRun.ts'
import { useCodeView } from '../components/codeViewContext.ts'
import JudgeCard from '../components/JudgeCard.tsx'
import { useLayout } from '../components/layoutContext.ts'
import PdfPage, { type Highlight } from '../components/PdfPage.tsx'
import ScreenRail from '../components/ScreenRail.tsx'
import { usePageTexts } from '../components/usePdf.ts'
import { buildStreams, locateUnit } from '../lib/quoteLocate.ts'
import { stepDomId, stepsByUnit, stepsForUnits } from '../lib/scenarioIndex.ts'
import { screenNav, screenPages } from '../lib/screenNav.ts'
import { groupByScreen, type ScreenGroup } from '../lib/screens.ts'
import { formatPages, groupCounts, statusClass } from '../lib/summary.ts'
import { appTablePath, cardDomId, sortByStatus, unitPath } from '../lib/table.ts'
import { cardTitle } from '../lib/title.ts'
import { mergeVerdicts, NOT_JUDGED, UNIT_STATUSES, type UnitStatus } from '../lib/verdicts.ts'
import { APP_SCREEN_ID } from '../types/requirements.ts'

type Tab = 'judge' | 'spec' | 'q'
/** 단위 ID → 그 단위가 속한 화면과 판정 (사양서 탭의 근거 요구사항 칩) */
type UnitIndex = Map<string, { screenId: string; status: UnitStatus }>
const LEGEND = UNIT_STATUSES.filter((s) => s !== NOT_JUDGED)
const reducedMotion = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

export default function ScreenView() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [params, setParams] = useSearchParams()
  const openId = params.get('unit')
  const { run, isLoading, error } = useCurrentRun()
  const pdfUrl = usePdfUrl(run?.id)
  const { onlyProblems } = useLayout()
  const showCode = useCodeView()
  const [tab, setTab] = useState<Tab>('judge')
  const [showOk, setShowOk] = useState(false)
  const [zoom, setZoom] = useState(false)
  const [hoverId, setHoverId] = useState<string | null>(null)
  /** 판정 카드에서 골라 사양서 탭에 강조할 단계 (stepDomId) */
  const [stepId, setStepId] = useState<string | null>(null)
  /** 형광펜을 눌러 연 카드는 페이지를 다시 스크롤하지 않는다 */
  const pickedFromPage = useRef(false)

  const data = useMemo(() => {
    if (!run) return null
    const groups = groupByScreen(run.requirements, mergeVerdicts(run.requirements.units, run.judgments))
    const units: UnitIndex = new Map(groups.flatMap((x) => x.units.map((v) => [v.unit.id, { screenId: x.id, status: v.status }] as const)))
    return { screens: groups.filter((x) => !x.isApp), units, steps: stepsByUnit(run.scenarios) }
  }, [run])

  const nav = data && data.screens.length ? screenNav(data.screens, id, onlyProblems) : null
  const g = nav?.current ?? null
  const pages = useMemo(() => (g ? screenPages(g.meta) : []), [g])
  const { data: texts } = usePageTexts(pdfUrl, pages)
  const locates = useMemo(() => {
    if (!g || !texts) return null
    const streams = buildStreams(texts)     // 화면마다 한 번만 정리
    return new Map(g.units.map((v) => [v.unit.id, locateUnit(v.unit, texts, streams)]))
  }, [g, texts])

  const go = useCallback((target: ScreenGroup | null) => { if (target) navigate(`/screen/${target.id}`) }, [navigate])

  // 펼친 카드: 카드는 패널 안에서 보이게, 형광펜은 페이지 가운데로.
  // 사양서 탭에서 판정 탭으로 돌아올 때도 다시 맞춘다.
  useEffect(() => {
    if (!openId || tab !== 'judge') return
    document.getElementById(cardDomId(openId))?.scrollIntoView({ block: 'nearest' })
    if (pickedFromPage.current) { pickedFromPage.current = false; return }
    document.querySelector(`.hl[data-u="${CSS.escape(openId)}"]`)
      ?.scrollIntoView({ block: 'center', inline: 'center', behavior: reducedMotion() ? 'auto' : 'smooth' })
  }, [openId, locates, tab])

  // 판정 카드에서 고른 테스트 단계: 사양서 탭에서 보이게
  useEffect(() => {
    if (tab !== 'spec' || !stepId) return
    document.getElementById(stepId)?.scrollIntoView({ block: 'center', behavior: reducedMotion() ? 'auto' : 'smooth' })
  }, [tab, stepId])

  // ← → 키로 화면 넘기기 (입력 중이거나 창이 열려 있으면 무시)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.target instanceof Element) || e.target.closest('input, textarea, select') || document.querySelector('dialog[open]')) return
      if (e.key === 'ArrowRight') go(nav?.next ?? null)
      if (e.key === 'ArrowLeft') go(nav?.prev ?? null)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [go, nav?.next, nav?.prev])

  if (id === APP_SCREEN_ID) return <Navigate to={appTablePath(openId ?? undefined)} replace />
  if (error) return <div className="tv"><div className="empty">결과를 불러오지 못했습니다. {String(error)}</div></div>
  if (isLoading || !data) return <div className="tv"><div className="empty">불러오는 중…</div></div>
  if (!nav || !g) return <div className="tv"><div className="empty">화면이 없습니다.</div></div>

  const open = (unitId: string, fromPage = false) => {
    const closing = openId === unitId
    pickedFromPage.current = fromPage && !closing
    setTab('judge')
    const v = g.units.find((x) => x.unit.id === unitId)
    if (!closing && v?.status === '구현') setShowOk(true)      // 구현 카드를 열면 그 형광펜도 보이게
    setParams(closing ? {} : { unit: unitId }, { replace: true })
  }
  /**
   * 사양서 탭의 근거 요구사항 → 판정 탭의 그 카드.
   * 다른 화면의 단위(여는 화면 묶음에 들어간 팝업 등)면 그 화면으로, 앱 전체 단위면 요구사항 표로 간다.
   */
  const pickUnit = (unitId: string) => {
    const target = data.units.get(unitId)
    if (!target) return
    setTab('judge')
    if (target.status === '구현') setShowOk(true)
    if (target.screenId === g.id) {
      if (openId !== unitId) open(unitId)
    } else {
      navigate(unitPath(target.screenId, unitId))
    }
  }
  const pickStep = (scenarioId: string, no: number) => {
    setStepId(stepDomId(scenarioId, no))
    setTab('spec')
  }
  const counts = groupCounts(g)
  const units = sortByStatus(g.units, UNIT_STATUSES)
  const steps = stepsForUnits(run?.scenarios ?? null, g.units.map((v) => v.unit.id))
  const highlights: Highlight[] = g.units.map((v) => ({
    unitId: v.unit.id, status: v.status, title: cardTitle(v.unit).title, rects: locates?.get(v.unit.id)?.rects ?? [],
  }))

  return (
    <div className="deck">
      <ScreenRail groups={data.screens} currentId={g.id} onlyProblems={onlyProblems} pdfUrl={pdfUrl} />
      <section className="stage">
        <div className="bar2">
          <div>
            <span className="id">{[g.id, formatPages(g.meta?.pages) && `기획서 ${formatPages(g.meta?.pages)}`].filter(Boolean).join(' · ')}</span>
            <h1>{g.name}</h1>
          </div>
          <div className="row small" style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            {g.rejectReason && <span className="pill p-반려">반려</span>}
            {UNIT_STATUSES.filter((s) => counts[s]).map((s) => <span key={s} className={`pill p-${statusClass(s)}`}>{s} {counts[s]}</span>)}
          </div>
          <div className="nav">
            <button type="button" className="btn" disabled={!nav.prev} aria-label="이전 화면" onClick={() => go(nav.prev)}>◀ 이전</button>
            <span className="pos">{nav.pos + 1} / {nav.total}</span>
            <button type="button" className="btn" disabled={!nav.next} aria-label="다음 화면" onClick={() => go(nav.next)}>다음 ▶</button>
          </div>
        </div>

        <div className="body2">
          <div className={`view${zoom ? ' zoom2' : ''}`}>
            {!g.rejectReason && <div className="vtools">
              <label className="toggle"><input type="checkbox" checked={showOk} onChange={(e) => setShowOk(e.target.checked)} /><span>구현된 부분도 표시</span></label>
              <label className="toggle"><input type="checkbox" checked={zoom} onChange={(e) => setZoom(e.target.checked)} /><span>크게 보기</span></label>
              <span className="lg hide-sm">{LEGEND.map((s) => <span key={s}><i className={`c-${statusClass(s)}`} />{s}</span>)}</span>
              <span className="hide-sm" style={{ marginLeft: 'auto' }}><span className="kbd">←</span> <span className="kbd">→</span> 화면 넘기기</span>
            </div>}
            {g.rejectReason && <div className="note">이 화면은 반려되어 요구사항을 뽑지 않았습니다. 이유: {g.rejectReason}</div>}
            {!pdfUrl
              ? <div className="empty card">기획서 PDF가 없어 페이지를 보여 줄 수 없습니다. 판정은 오른쪽에서 볼 수 있습니다.</div>
              : <div className={showOk ? '' : 'only-prob'}>
                  {pages.map((p) => (
                    <PdfPage key={p} url={pdfUrl} page={p} highlights={highlights}
                      label={pages.length > 1 ? `${p}쪽${g.meta?.state_pages?.includes(p) ? ' (상태 화면)' : ''}` : undefined}
                      selectedId={openId} hoverId={hoverId} onPick={(u) => open(u, true)} onHover={setHoverId} />
                  ))}
                </div>}
          </div>

          <aside className="panel">
            <div className="ptabs" role="tablist">
              <button type="button" role="tab" aria-selected={tab === 'judge'} onClick={() => setTab('judge')}>정합성 판정 <span className="n">{g.units.length}</span></button>
              <button type="button" role="tab" aria-selected={tab === 'spec'} onClick={() => setTab('spec')}>테스트 사양서 <span className="n">{steps.length}</span></button>
              <button type="button" role="tab" aria-selected={tab === 'q'} onClick={() => setTab('q')}>질문 <span className="n">{g.questions.length}</span></button>
            </div>
            <div className="pbody">
              {tab === 'judge' && (units.length
                ? units.map((v) => (
                    <JudgeCard key={v.unit.id} view={v} pages={g.meta?.pages} open={openId === v.unit.id}
                      onToggle={() => open(v.unit.id)} steps={data.steps.get(v.unit.id)}
                      onPickStep={(s) => pickStep(s.scenarioId, s.no)}
                      locate={pdfUrl ? locates?.get(v.unit.id) : undefined}
                      onShowCode={showCode ? (evidence) => showCode({ evidence, failed: v.evidenceFailed }) : undefined}
                      onHover={(on) => setHoverId(on ? v.unit.id : null)} />
                  ))
                : <div className="empty">{g.rejectReason ? '반려된 화면이라 요구사항이 없습니다.' : '이 화면의 요구사항이 없습니다.'}</div>)}
              {tab === 'spec' && <SpecSteps steps={steps} selectedId={stepId} units={data.units} onPickUnit={pickUnit} />}
              {tab === 'q' && (g.questions.length
                ? g.questions.map((q) => (
                    <div className="qq" key={q.id}>
                      <b><span className={`prio prio-${q.priority}`}>{q.priority}</span>{q.question}</b>
                      <p className="small muted" style={{ margin: '4px 0 0' }}>{q.why}</p>
                    </div>
                  ))
                : <div className="empty">이 화면에서 기획자에게 확인할 질문이 없습니다.</div>)}
            </div>
          </aside>
        </div>
      </section>
    </div>
  )
}

/**
 * 화면별 보기의 사양서 탭. 근거 요구사항은 누르면 판정 카드로 가는 칩이다.
 * 칩의 색 점은 어느 판정의 요구사항인지 알려 주는 표시일 뿐, 사양서 내용(절차·예상결과)과 엑셀에는 판정을 넣지 않는다.
 */
function SpecSteps({ steps, selectedId, units, onPickUnit }: {
  steps: ReturnType<typeof stepsForUnits>
  selectedId: string | null
  units: UnitIndex
  onPickUnit: (unitId: string) => void
}) {
  if (!steps.length) return <div className="empty">이 화면의 테스트 단계가 아직 없습니다.</div>
  return (
    <>
      {steps.map(({ scenario, step }) => {
        const domId = stepDomId(scenario.scenario_id, step.no)
        return (
          <div className={`step${domId === selectedId ? ' on' : ''}`} id={domId} key={domId}>
            <div className="h">
              <span>{scenario.scenario_id} · {step.no}단계</span>
              <span className="reqs">
                {step.unit_ids.map((u) => {
                  const t = units.get(u)
                  return t
                    ? <button type="button" className="reqchip" key={u} title={`이 요구사항의 판정 보기 (${t.status})`}
                        aria-label={`${u} 판정 보기, ${t.status}`} onClick={() => onPickUnit(u)}>
                        <i className={`c-${statusClass(t.status)}`} />{u}
                      </button>
                    : <span key={u}>{u}</span>
                })}
              </span>
            </div>
            {step.action}
            <div className="exp">{step.expected}</div>
            {(step.account || step.input || step.note) && (
              <div className="h" style={{ margin: '6px 0 0' }}><span>시험데이터: {[step.account, step.input, step.note].filter(Boolean).join(' / ')}</span></div>
            )}
          </div>
        )
      })}
      <p className="small faint" style={{ margin: '10px 2px' }}>예상결과는 기획서 기준으로 작성했습니다. 판정 결과는 사양서에 넣지 않습니다.</p>
    </>
  )
}

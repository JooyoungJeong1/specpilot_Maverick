// 화면별 보기 (CLAUDE.md 5장 /screen/:id). 초안 local/reference/app.html의 screen()을 옮겼다.
// 왼쪽 화면 목록, 가운데 기획서 페이지와 형광펜, 오른쪽 탭(정합성 판정 / 테스트 사양서 / 질문).
// ?unit=<단위 ID>: 펼친 카드. 요구사항 표에서 행을 눌러 오면 그 카드가 펼쳐지고 형광펜 위치로 스크롤한다.
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useCurrentRun, usePdfUrl } from '../api/useRun.ts'
import { useCodeView } from '../components/codeViewContext.ts'
import JudgeCard from '../components/JudgeCard.tsx'
import { useLayout } from '../components/layoutContext.ts'
import PdfPage, { type Highlight } from '../components/PdfPage.tsx'
import ScreenRail from '../components/ScreenRail.tsx'
import { usePageTexts } from '../components/usePdf.ts'
import { quoteSegments } from '../lib/quote.ts'
import { buildStreams, locateUnit } from '../lib/quoteLocate.ts'
import { stepsByUnit, stepsForUnits } from '../lib/scenarioIndex.ts'
import { screenNav, screenPages, sourceScreenId } from '../lib/screenNav.ts'
import { groupByScreen, type ScreenGroup } from '../lib/screens.ts'
import { formatPages, groupCounts, statusClass } from '../lib/summary.ts'
import { cardDomId, sortByStatus } from '../lib/table.ts'
import { cardTitle } from '../lib/title.ts'
import { mergeVerdicts, NOT_JUDGED, UNIT_STATUSES } from '../lib/verdicts.ts'

type Tab = 'judge' | 'spec' | 'q'
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
  /** 형광펜을 눌러 연 카드는 페이지를 다시 스크롤하지 않는다 */
  const pickedFromPage = useRef(false)

  const data = useMemo(() => {
    if (!run) return null
    return {
      groups: groupByScreen(run.requirements, mergeVerdicts(run.requirements.units, run.judgments)),
      steps: stepsByUnit(run.scenarios),
    }
  }, [run])

  const nav = data && data.groups.length ? screenNav(data.groups, id, onlyProblems) : null
  const g = nav?.current ?? null
  const pages = useMemo(() => (g && !g.isApp ? screenPages(g.meta) : []), [g])
  const { data: texts } = usePageTexts(pdfUrl, pages)
  const locates = useMemo(() => {
    if (!g || !texts) return null
    const streams = buildStreams(texts)     // 화면마다 한 번만 정리
    return new Map(g.units.map((v) => [v.unit.id, locateUnit(v.unit, texts, streams)]))
  }, [g, texts])

  const go = useCallback((target: ScreenGroup | null) => { if (target) navigate(`/screen/${target.id}`) }, [navigate])

  // 펼친 카드: 카드는 패널 안에서 보이게, 형광펜은 페이지 가운데로
  useEffect(() => {
    if (!openId) return
    document.getElementById(cardDomId(openId))?.scrollIntoView({ block: 'nearest' })
    if (pickedFromPage.current) { pickedFromPage.current = false; return }
    document.querySelector(`.hl[data-u="${CSS.escape(openId)}"]`)
      ?.scrollIntoView({ block: 'center', inline: 'center', behavior: reducedMotion() ? 'auto' : 'smooth' })
  }, [openId, locates])

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
  const counts = groupCounts(g)
  const units = sortByStatus(g.units, UNIT_STATUSES)
  const steps = stepsForUnits(run?.scenarios ?? null, g.units.map((v) => v.unit.id))
  const highlights: Highlight[] = g.units.map((v) => ({
    unitId: v.unit.id, status: v.status, title: cardTitle(v.unit).title, rects: locates?.get(v.unit.id)?.rects ?? [],
  }))

  return (
    <div className="deck">
      <ScreenRail groups={data.groups} currentId={g.id} onlyProblems={onlyProblems} pdfUrl={pdfUrl} />
      <section className="stage">
        <div className="bar2">
          <div>
            <span className="id">{g.isApp ? 'REQ-APP · 여러 화면에 걸친 요구사항' : [g.id, formatPages(g.meta?.pages) && `기획서 ${formatPages(g.meta?.pages)}`].filter(Boolean).join(' · ')}</span>
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
          {g.isApp ? <AppSources group={g} groups={data.groups} /> : (
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
          )}

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
                      locate={pdfUrl && !g.isApp ? locates?.get(v.unit.id) : undefined}
                      onShowCode={showCode ? (evidence) => showCode({ evidence, failed: v.evidenceFailed }) : undefined}
                      onHover={(on) => setHoverId(on ? v.unit.id : null)} />
                  ))
                : <div className="empty">{g.rejectReason ? '반려된 화면이라 요구사항이 없습니다.' : '이 화면의 요구사항이 없습니다.'}</div>)}
              {tab === 'spec' && <SpecSteps steps={steps} />}
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

/** 앱 전체: 페이지 대신 근거 위치 목록. 위치를 누르면 그 화면으로 */
function AppSources({ group, groups }: { group: ScreenGroup; groups: ScreenGroup[] }) {
  const known = new Set(groups.map((x) => x.id))
  return (
    <div className="view" style={{ padding: 20 }}>
      <div className="appbox">
        <h2>앱 전체 요구사항</h2>
        <p className="small muted" style={{ margin: '0 0 10px' }}>
          한 화면에 속하지 않고 여러 화면을 함께 봐야 나오는 요구사항입니다. 근거가 된 기획서 위치를 누르면 그 화면으로 갑니다.
        </p>
        {group.units.map((v) => (
          <div className="appu" key={v.unit.id}>
            <b>{v.unit.id}</b> {cardTitle(v.unit).title}<span className="og">{v.unit.origin}</span>{' '}
            <span className={`pill p-${statusClass(v.status)}`}>{v.status}</span>
            <div className="srcs">
              {v.unit.source.map((s) => {
                const sid = sourceScreenId(s)
                return sid && known.has(sid)
                  ? <Link key={s} to={`/screen/${sid}`}>{s}</Link>
                  : <span key={s} className="small">{s}</span>
              })}
            </div>
            {quoteSegments(v.unit.quote).map((q, i) => <div className="quote" key={i}>{q}</div>)}
          </div>
        ))}
        {!group.units.length && <div className="empty">앱 전체 요구사항이 없습니다.</div>}
      </div>
    </div>
  )
}

function SpecSteps({ steps }: { steps: ReturnType<typeof stepsForUnits> }) {
  if (!steps.length) return <div className="empty">이 화면의 테스트 단계가 아직 없습니다.</div>
  return (
    <>
      {steps.map(({ scenario, step }) => (
        <div className="step" key={`${scenario.scenario_id}-${step.no}`}>
          <div className="h"><span>{scenario.scenario_id} · {step.no}단계</span><span>{step.unit_ids.join(' ')}</span></div>
          {step.action}
          <div className="exp">{step.expected}</div>
          {(step.account || step.input || step.note) && (
            <div className="h" style={{ margin: '6px 0 0' }}><span>시험데이터: {[step.account, step.input, step.note].filter(Boolean).join(' / ')}</span></div>
          )}
        </div>
      ))}
      <p className="small faint" style={{ margin: '10px 2px' }}>예상결과는 기획서 기준으로 작성했습니다. 판정 결과는 사양서에 넣지 않습니다.</p>
    </>
  )
}

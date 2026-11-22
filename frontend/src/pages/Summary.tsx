// 요약 (CLAUDE.md 5장 /summary). 초안 local/reference/app.html의 summary()를 옮겼다.
import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useCurrentRun, usePdfUrl } from '../api/useRun.ts'
import { useLayout } from '../components/layoutContext.ts'
import ScreenCard from '../components/ScreenCard.tsx'
import StackBar from '../components/StackBar.tsx'
import UsageCard from '../components/UsageCard.tsx'
import { groupByScreen, questionScope } from '../lib/screens.ts'
import { overview, sortByPriority, sortGroups, statusClass, visibleGroups, type SortMode } from '../lib/summary.ts'
import { appTablePath } from '../lib/table.ts'
import { countStatuses, ITEM_STATUSES, mergeVerdicts, NOT_JUDGED, UNIT_STATUSES } from '../lib/verdicts.ts'

/** 위쪽 판정별 칸. 판정 전은 있을 때만 */
const JUDGED = UNIT_STATUSES.filter((s) => s !== NOT_JUDGED)

export default function Summary() {
  const { run, isLoading, error, noRuns } = useCurrentRun()
  const pdfUrl = usePdfUrl(run?.id)
  const { onlyProblems } = useLayout()
  const [sort, setSort] = useState<SortMode>('doc')

  const groups = useMemo(
    () => (run ? groupByScreen(run.requirements, mergeVerdicts(run.requirements.units, run.judgments)) : []),
    [run],
  )

  if (error) return <div className="sum"><div className="empty">결과를 불러오지 못했습니다. {String(error)}</div></div>
  if (noRuns) return <div className="sum"><div className="empty">분석 결과가 없습니다.</div></div>
  if (isLoading || !run) return <div className="sum"><div className="empty">불러오는 중…</div></div>

  const o = overview(groups)
  const items = Object.values(run.judgments?.items ?? {})
  const itemCounts = countStatuses(items, ITEM_STATUSES)
  // 화면 카드는 기획서 화면만. 앱 전체 요구사항은 요구사항 표에서 본다
  const screens = groups.filter((g) => !g.isApp)
  const appUnits = groups.find((g) => g.isApp)?.units.length ?? 0
  const docNo = new Map(screens.map((g, i) => [g.id, i + 1]))
  const list = sortGroups(visibleGroups(screens, onlyProblems), sort)
  const extras = run.judgments?.extras ?? []
  const questions = sortByPriority(run.requirements.questions)
  const lgd = o.counts[NOT_JUDGED] ? UNIT_STATUSES : JUDGED

  return (
    <div className="sum">
      <section className="card sum-top">
        <div>
          <p className="big">요구사항 {o.total}개 중 <em>{o.problems}개</em>를<br />확인해야 합니다</p>
          <p className="sub">
            기획서 화면 {o.screens}개 중 {o.screensWithProblems}개 화면에 확인할 곳이 있습니다.
            {' '}기획서에서 추론한 함의 요구사항 {o.implied}개 포함.
            {o.counts[NOT_JUDGED] > 0 && ` 코드와 비교하지 못한 판정 전 요구사항이 ${o.counts[NOT_JUDGED]}개 있습니다.`}
            {o.rejected > 0 && ` 반려된 화면 ${o.rejected}개는 요구사항을 뽑지 않았습니다.`}
            {appUnits > 0 && <>{' '}여러 화면에 걸친 <Link to={appTablePath()}>앱 전체 요구사항 {appUnits}개</Link>는 요구사항 표에서 봅니다.</>}
          </p>
          <StackBar counts={o.counts} statuses={UNIT_STATUSES} />
        </div>
        <div className="lgd">
          {lgd.map((s) => (
            <div key={s} className={s === NOT_JUDGED ? 'wide' : undefined}><i className={`c-${statusClass(s)}`} />{s}<b>{o.counts[s]}</b></div>
          ))}
        </div>
        <div className="ilv" style={{ gridColumn: '1 / -1' }}>
          <b style={{ color: 'var(--ink)' }}>기획서 항목 {items.length}개 기준</b>
          {ITEM_STATUSES.map((s) => <span key={s}><i className={`c-${statusClass(s)}`} />{s} {itemCounts[s]}</span>)}
          <Link to="/table?view=item" className="linkbtn" style={{ marginLeft: 'auto' }}>항목별로 보기 →</Link>
        </div>
      </section>

      <div className="sec-h">
        <h2>기획서 화면</h2>
        <span className="small faint">화면을 누르면 기획서 순서대로 넘겨 보며 확인할 수 있습니다</span>
        <div className="right">
          <div className="seg" role="group" aria-label="정렬">
            <button type="button" aria-pressed={sort === 'doc'} onClick={() => setSort('doc')}>기획서 순서</button>
            <button type="button" aria-pressed={sort === 'prob'} onClick={() => setSort('prob')}>문제 많은 순</button>
          </div>
        </div>
      </div>
      <div className="grid">
        {list.length
          ? list.map((g) => <ScreenCard key={g.id} group={g} no={docNo.get(g.id) ?? 0} pdfUrl={pdfUrl} />)
          : <div className="empty">문제 있는 화면이 없습니다.</div>}
      </div>

      <div className="two">
        <section className="card">
          <h3>기획서에 없는 구현 {extras.length}건</h3>
          {extras.map((e, i) => (
            <div className="li" key={i}>{e.description}<br /><code>{e.file}:{e.line}</code></div>
          ))}
        </section>
        <section className="card">
          <h3>기획자에게 확인할 질문 {questions.length}건</h3>
          {questions.map((q) => {
            const scope = questionScope(q.id)
            return (
              <div className="li" key={q.id}>
                <span className={`prio prio-${q.priority}`}>{q.priority}</span>{q.question}
                {' '}<span className="small faint">· {scope === 'APP' ? '앱 전체' : scope}</span>
              </div>
            )
          })}
        </section>
      </div>

      {run.report && <UsageCard usage={run.report.usage} screens={screens.map((g) => ({ id: g.id, name: g.name }))} />}
    </div>
  )
}

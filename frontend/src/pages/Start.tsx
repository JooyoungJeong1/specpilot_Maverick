// 시작 (CLAUDE.md 5장 /). 초안 local/reference/app.html의 start()를 옮겼다.
import { Link } from 'react-router-dom'
import { selectRun, useRuns, useServerStatus } from '../api/useRun.ts'
import StackBar from '../components/StackBar.tsx'
import { formatDateTime, runCounts, runLabel } from '../lib/format.ts'
import { UNIT_STATUSES } from '../lib/verdicts.ts'

export default function Start() {
  const { data: runs, isLoading, error } = useRuns()
  const running = useServerStatus().data?.running

  return (
    <div className="wrapS">
      <div className="hello">
        <h1>SpecPilot</h1>
        <p>기획서와 소스코드를 비교해 구현 상태를 판정하고 테스트 사양서를 만듭니다.</p>
      </div>
      <div className="choices" style={{ gridTemplateColumns: '1fr' }}>
        <Link className="card choice" to="/new">
          <span className="ic">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" strokeWidth="1.8" aria-hidden="true" style={{ stroke: 'var(--accent)' }}>
              <path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" />
            </svg>
          </span>
          <b>새로 분석하기</b>
          <span>기획서와 소스코드를 올리면 요구사항을 뽑아 코드와 비교하고 테스트 사양서를 만듭니다.</span>
          <span className="go">기획서·코드 올리기 →</span>
        </Link>
      </div>
      {running && (
        <div className="note" role="status">
          분석이 진행 중입니다.{' '}
          <Link className="linkbtn" to={`/progress?job=${encodeURIComponent(running)}`}>진행 화면 보기 →</Link>
        </div>
      )}
      <section className="card recent">
        <h2>최근 분석</h2>
        {error && <div className="empty">분석 목록을 불러오지 못했습니다. {String(error)}</div>}
        {isLoading && <div className="empty">불러오는 중…</div>}
        {runs?.length === 0 && <div className="empty">아직 분석한 프로젝트가 없습니다.</div>}
        {runs?.map((r) => (
          <Link key={r.id} to="/summary" onClick={() => selectRun(r.id)}>
            <span className="nm">
              <b>{runLabel(r)}</b>
              <span className="small muted">기획서 화면 {r.screens}개 · 요구사항 {r.units}개</span>
            </span>
            <span className="small muted hide-sm2">{formatDateTime(r.mergedAt)}</span>
            <span className="hide-sm2"><StackBar counts={runCounts(r)} statuses={UNIT_STATUSES} /></span>
          </Link>
        ))}
      </section>
    </div>
  )
}

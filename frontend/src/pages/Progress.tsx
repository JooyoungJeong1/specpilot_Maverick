// 분석 진행 (CLAUDE.md 5장 /progress?job=<작업 ID>). 초안 local/reference/app.html의 progress()를 옮겼다.
// 입력 점검 → ① → ② → ③ (→ ④) 단계별 진행률과 화면별 상태 표.
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { selectRun, useProgress } from '../api/useRun.ts'
import FlowSteps from '../components/FlowSteps.tsx'
import type { ScreenProgress, StageProgress } from '../types/progress.ts'

const STAGE_TEXT: Record<StageProgress['key'], { title: string; sub: (total: number) => string }> = {
  preflight: { title: '입력 점검', sub: () => '기획서 확인' },
  profile: { title: '① 문서 파악', sub: () => '기획서 전체' },
  decompose: { title: '② 요구사항 추출', sub: (n) => `화면 ${n}개` },
  judge: { title: '③ 코드와 비교', sub: (n) => `화면 ${n}개` },
  scenario: { title: '④ 사양서 작성', sub: () => '시나리오' },
}
const STATE_TEXT: Record<StageProgress['state'], string> = {
  waiting: '대기', running: '진행 중', done: '완료', failed: '실패', skipped: '준비 중',
}

function Stage({ s }: { s: StageProgress }) {
  const t = STAGE_TEXT[s.key]
  const pct = s.state === 'done' ? 100 : s.total ? (s.done / s.total) * 100 : 0
  const sub = s.key === 'judge' && s.state === 'skipped' ? '코드 없음' : t.sub(s.total)
  return (
    <div className={`card stp${s.state === 'done' ? ' done' : ''}${s.state === 'skipped' ? ' skip' : ''}`}>
      <div className="t"><span>{sub}</span><em>{STATE_TEXT[s.state]}{s.state === 'running' && s.total > 1 ? ` ${s.done}/${s.total}` : ''}</em></div>
      <b>{t.title}</b>
      <div className="prog" role="progressbar" aria-label={t.title} aria-valuenow={Math.round(pct)} aria-valuemin={0} aria-valuemax={100}>
        <span style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

/** 화면 상태 글자: 완료·확인필요·실패·반려는 색을 붙인다 */
function RunState({ value }: { value: string | null }) {
  if (value === null) return <span className="faint">비교 안 함</span>
  const cls = value === '대기' ? 'faint' : `rs rs-${value.replace(/\s+/g, '')}`
  return <span className={cls}>{value}</span>
}

function ScreenRow({ r }: { r: ScreenProgress }) {
  return (
    <tr>
      <td><b>{r.screenId}</b> {r.name}</td>
      <td>
        <RunState value={r.decompose} />
        {r.units !== null && <span className="small muted"> · 요구사항 {r.units}개</span>}
        {r.rejectReason && <div className="small muted">{r.rejectReason}</div>}
      </td>
      <td><RunState value={r.judge} /></td>
    </tr>
  )
}

export default function Progress() {
  const [params] = useSearchParams()
  const jobId = params.get('job')
  const navigate = useNavigate()
  const { data: p, isLoading, error } = useProgress(jobId)

  if (!jobId || (!isLoading && !p && !error)) {
    return (
      <div className="wrapS">
        <FlowSteps now={1} />
        <div className="empty card">진행 중인 분석이 없습니다. <Link to="/new" className="linkbtn">새로 분석하기 →</Link></div>
      </div>
    )
  }
  if (error) return <div className="wrapS"><div className="empty">진행 상태를 불러오지 못했습니다. {String(error)}</div></div>
  if (!p) return <div className="wrapS"><div className="empty">불러오는 중…</div></div>

  const done = p.state === 'done'
  const message = done
    ? `분석이 끝났습니다.${p.problems !== null ? ` 확인할 곳 ${p.problems}건이 있습니다.` : ''}`
    : p.state === 'running' ? '요구사항을 뽑아 코드와 비교하고 있습니다. 창을 닫아도 계속 진행됩니다.'
      : `분석을 마치지 못했습니다. ${p.message ?? ''}`
  const openResult = () => {
    if (!p.runId) return
    selectRun(p.runId)
    navigate('/summary')
  }

  return (
    <div className="wrapS">
      <FlowSteps now={done ? 2 : 1} />
      <div className="hello" style={{ display: 'flex', justifyContent: 'space-between', gap: 16, alignItems: 'flex-end', flexWrap: 'wrap' }}>
        <div>
          <h1>{done ? '분석 완료' : p.state === 'running' ? '분석 중' : '분석 중단'}{p.name && <span className="muted" style={{ fontWeight: 400, fontSize: 16 }}> · {p.name}</span>}</h1>
          <p style={{ marginBottom: 0 }} role="status">{message}</p>
        </div>
        <button type="button" className="btn pri" disabled={!done || !p.runId} onClick={openResult}>결과 보기</button>
      </div>
      <div className="steps five" style={{ marginTop: 20 }}>
        {p.stages.map((s) => <Stage key={s.key} s={s} />)}
      </div>
      <section className="card tw">
        <table className="tbl">
          <thead><tr><th>기획서 화면</th><th>요구사항</th><th>코드 비교</th></tr></thead>
          <tbody>{p.screens.map((r) => <ScreenRow key={r.screenId} r={r} />)}</tbody>
        </table>
      </section>
    </div>
  )
}

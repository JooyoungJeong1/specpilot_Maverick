// 테스트 사양서 (CLAUDE.md 5장 /spec). 초안 local/reference/app.html의 specView()를 옮겼다.
// 엑셀 모양 미리보기. 시트와 열은 내려받는 xlsx와 같다 (lib/sheets.ts). 판정 결과는 넣지 않는다.
import { useMemo, useState } from 'react'
import { useCurrentRun } from '../api/useRun.ts'
import { downloadWorkbook } from '../components/xlsx.ts'
import { runLabel } from '../lib/format.ts'
import { exportFileName, specSheets } from '../lib/sheets.ts'

/**
 * 열 모양. 초안은 시험번호·시험데이터·근거 요구사항을 모두 줄바꿈 없이(td.tc) 그렸는데,
 * 값이 길면 시험절차·예상결과 칸이 찌그러져서 짧은 번호 열만 줄바꿈을 막고 긴 열은 흐린 글자로만 둔다.
 */
const COL_CLASS: Record<string, string> = {
  시험번호: 'tc', 번호: 'tc', 화면: 'tc', 우선순위: 'tc', No: 'tc',
  시험데이터: 'sub', '근거 요구사항': 'sub', '관련 요구사항': 'sub',
  시험절차: 'wide', 예상결과: 'wide', 질문: 'wide', 이유: 'wide',
}

export default function SpecView() {
  const { run, isLoading, error } = useCurrentRun()
  const [tab, setTab] = useState(0)
  const [busy, setBusy] = useState(false)
  const sheets = useMemo(() => (run?.scenarios ? specSheets(run.scenarios, run.requirements) : null), [run])

  if (error) return <div className="tv"><div className="empty">결과를 불러오지 못했습니다. {String(error)}</div></div>
  if (isLoading || !run) return <div className="tv"><div className="empty">불러오는 중…</div></div>

  const fileName = exportFileName('spec', runLabel(run))
  const sheet = sheets?.[Math.min(tab, sheets.length - 1)]
  const steps = run.scenarios?.scenarios.reduce((n, s) => n + s.steps.length, 0) ?? 0
  const download = async () => {
    if (!sheets) return
    setBusy(true)
    try { await downloadWorkbook(fileName, sheets) } finally { setBusy(false) }
  }

  return (
    <div className="tv">
      <div className="tv-h">
        <div>
          <h1>테스트 사양서</h1>
          <p>기획서를 기준으로 만든 시험절차와 예상결과입니다. 판정 결과는 넣지 않습니다.</p>
        </div>
        <button className="btn pri" type="button" disabled={!sheets || busy} onClick={download}>{busy ? '만드는 중…' : '엑셀로 내려받기'}</button>
      </div>
      {!sheets || !sheet ? (
        <section className="card"><div className="empty">테스트 사양서가 아직 만들어지지 않았습니다.</div></section>
      ) : (
        <section className="card">
          <div style={{ padding: '14px 18px', borderBottom: '1px solid var(--line)', display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
            <b style={{ overflowWrap: 'anywhere' }}>{fileName}</b>
            <span className="small faint">시나리오 {run.scenarios!.scenarios.length}개 · 단계 {steps}개 · 질문 {run.requirements.questions.length}개</span>
            {import.meta.env.DEV && <span className="devtag" title="개발 중에만 보이는 표시">개발용: 사양서 생성(④) 전이라 예시 데이터</span>}
          </div>
          <div className="tw">
            <table className="xls">
              <thead><tr>{sheet.header.map((h) => <th key={h}>{h}</th>)}</tr></thead>
              <tbody>
                {sheet.rows.map((row, i) => (
                  <tr key={i}>{row.map((c, j) => <td key={j} className={COL_CLASS[sheet.header[j]]}>{c}</td>)}</tr>
                ))}
              </tbody>
            </table>
            {!sheet.rows.length && <div className="empty">이 시트는 비어 있습니다.</div>}
          </div>
          <div className="sheet-tabs" role="group" aria-label="시트">
            {sheets.map((s, i) => <button key={s.name} type="button" aria-pressed={i === tab} onClick={() => setTab(i)}>{s.name}</button>)}
          </div>
        </section>
      )}
    </div>
  )
}

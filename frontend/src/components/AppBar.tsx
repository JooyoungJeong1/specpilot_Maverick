import { useRef } from 'react'
import { Link, NavLink } from 'react-router-dom'
import { useCurrentRun } from '../api/useRun.ts'
import { projectMeta } from '../lib/format.ts'
import ExportDialog from './ExportDialog.tsx'

const VIEWS = [
  { to: '/summary', label: '요약' },
  { to: '/screen', label: '화면별 보기' },
  { to: '/table', label: '요구사항 표' },
  { to: '/spec', label: '테스트 사양서' },
]

interface Props {
  resultBar: boolean
  onlyProblems: boolean
  onOnlyProblemsChange: (v: boolean) => void
}

export default function AppBar({ resultBar, onlyProblems, onOnlyProblemsChange }: Props) {
  const exportRef = useRef<HTMLDialogElement>(null)
  const { run } = useCurrentRun(resultBar)

  return (
    <header className="appbar">
      <Link className="brand" to="/" aria-label="SpecPilot 처음으로">
        <BrandMark />SpecPilot
      </Link>
      {resultBar && (
        <>
          <nav className="views" aria-label="보기">
            {VIEWS.map((v) => <NavLink key={v.to} to={v.to}>{v.label}</NavLink>)}
          </nav>
          <span className="meta">{run ? projectMeta(run) : ''}</span>
          <div className="right">
            <label className="toggle">
              <input type="checkbox" checked={onlyProblems} onChange={(e) => onOnlyProblemsChange(e.target.checked)} />
              <span>문제 있는 화면만</span>
            </label>
            <button className="btn pri" type="button" onClick={() => exportRef.current?.showModal()}>내보내기</button>
          </div>
          <ExportDialog ref={exportRef} />
        </>
      )}
    </header>
  )
}

function BrandMark() {
  const accent = { stroke: 'var(--accent)' }
  return (
    <svg width="22" height="22" viewBox="0 0 22 22" aria-hidden="true">
      <rect x="1" y="3" width="9" height="16" rx="2" fill="none" strokeWidth="2" style={accent} />
      <rect x="12" y="3" width="9" height="16" rx="2" style={{ fill: 'var(--accent)' }} />
      <path d="M4 8h3M4 11h3M4 14h3" strokeWidth="1.6" style={accent} />
      <path d="M15 8h3M15 11h3M15 14h3" strokeWidth="1.6" style={{ stroke: 'var(--on-accent)' }} />
    </svg>
  )
}

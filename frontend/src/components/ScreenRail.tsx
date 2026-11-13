// 화면별 보기 왼쪽 화면 목록 (초안 .rail). 기획서 화면만 받는다 (앱 전체는 요구사항 표에서 본다).
import { Link } from 'react-router-dom'
import type { ScreenGroup } from '../lib/screens.ts'
import { groupCounts, hasProblem, problemCount } from '../lib/summary.ts'
import { THUMB_WIDTH } from './pdf.ts'
import { usePageImage } from './usePdf.ts'

interface Props {
  groups: ScreenGroup[]
  currentId: string
  onlyProblems: boolean
  pdfUrl: string | null
}

export default function ScreenRail({ groups, currentId, onlyProblems, pdfUrl }: Props) {
  return (
    <nav className="rail" aria-label="기획서 화면">
      {groups.map((g, i) => (
        <RailItem key={g.id} g={g} no={i + 1} current={g.id === currentId}
          dim={onlyProblems && !hasProblem(g)} pdfUrl={pdfUrl} />
      ))}
    </nav>
  )
}

function RailItem({ g, no, current, dim, pdfUrl }: { g: ScreenGroup; no: number; current: boolean; dim: boolean; pdfUrl: string | null }) {
  const { data: thumb } = usePageImage(pdfUrl, g.meta?.pages[0], THUMB_WIDTH)
  const c = groupCounts(g)
  const prob = problemCount(c)
  const worst = c['미구현'] ? '미구현' : c['불일치'] ? '불일치' : '확인필요'
  const cls = [dim && 'dim', g.rejectReason && 'rej'].filter(Boolean).join(' ')
  return (
    <Link to={`/screen/${g.id}`} aria-current={current} className={cls || undefined}>
      <div className="t" style={thumb ? { backgroundImage: `url(${thumb})` } : undefined}>
        {prob > 0 && <i className={`c-${worst}`}>{prob}</i>}
      </div>
      <div className="l">
        <span>{no}</span><b>{g.name}</b>
        {g.rejectReason && <span className="rej-tag">반려</span>}
      </div>
    </Link>
  )
}

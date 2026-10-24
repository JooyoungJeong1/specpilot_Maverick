import { Link } from 'react-router-dom'
import type { ScreenGroup } from '../lib/screens.ts'
import { formatPages, groupCounts, hasProblem, statusClass } from '../lib/summary.ts'
import { UNIT_STATUSES } from '../lib/verdicts.ts'
import { THUMB_WIDTH } from './pdf.ts'
import StackBar from './StackBar.tsx'
import { usePageImage } from './usePdf.ts'

interface Props {
  group: ScreenGroup
  /** 기획서 순서 번호 (1부터). 앱 전체는 null */
  no: number | null
  pdfUrl: string | null
}

export default function ScreenCard({ group: g, no, pdfUrl }: Props) {
  const counts = groupCounts(g)
  const firstPage = g.meta?.pages[0]
  const { data: thumb } = usePageImage(pdfUrl, firstPage, THUMB_WIDTH)
  const rejected = !!g.rejectReason
  const clean = !hasProblem(g) && g.units.length > 0
  const cls = ['card', 'scr', clean && 'clean', rejected && 'rej'].filter(Boolean).join(' ')

  return (
    <Link className={cls} to={`/screen/${g.id}`}>
      {g.isApp
        ? <div className="thumb appt">여러 화면에 걸친 요구사항과 질문<span className="no">전체</span></div>
        : <div className="thumb" style={thumb ? { backgroundImage: `url(${thumb})` } : undefined}>
            <span className="no">{no}</span>
          </div>}
      <div className="body">
        <span className="id">{g.isApp ? 'REQ-APP · 앱 프로필' : [g.id, formatPages(g.meta?.pages)].filter(Boolean).join(' · ')}</span>
        <b>{g.name}</b>
        {rejected
          ? <p className="rej-why"><span className="pill p-반려">반려</span>{g.rejectReason}</p>
          : <>
              <StackBar counts={counts} statuses={UNIT_STATUSES} />
              <div className="counts">
                {UNIT_STATUSES.filter((s) => counts[s]).map((s) => (
                  <span key={s}><i className={`c-${statusClass(s)}`} />{s} {counts[s]}</span>
                ))}
              </div>
            </>}
      </div>
    </Link>
  )
}

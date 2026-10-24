// 기획서 한 쪽과 그 위의 형광펜 (초안 .page, .hl, .tip).
// 형광펜 숨김(문제 있는 판정만)은 부모의 .only-prob 클래스가 CSS로 한다.
import { useState } from 'react'
import type { HighlightRect } from '../lib/quoteLocate.ts'
import { statusClass } from '../lib/summary.ts'
import type { UnitStatus } from '../lib/verdicts.ts'
import { PAGE_WIDTH } from './pdf.ts'
import { usePageImage } from './usePdf.ts'

export interface Highlight {
  unitId: string
  status: UnitStatus
  title: string
  rects: HighlightRect[]
}

interface Props {
  url: string
  page: number
  /** 이 쪽에 표시할 형광펜 (다른 쪽 사각형은 걸러서 그린다) */
  highlights: Highlight[]
  /** 이 쪽 위에 붙일 이름 (여러 쪽일 때) */
  label?: string
  selectedId: string | null
  hoverId: string | null
  onPick: (unitId: string) => void
  onHover: (unitId: string | null) => void
}

interface Tip { text: string; x: number; y: number }

export default function PdfPage({ url, page, highlights, label, selectedId, hoverId, onPick, onHover }: Props) {
  const { data: image, isError } = usePageImage(url, page, PAGE_WIDTH)
  const [tip, setTip] = useState<Tip | null>(null)

  return (
    <figure className="pg">
      {label && <figcaption className="pg-label">{label}</figcaption>}
      <div className="page">
        {image
          ? <img src={image} alt={`기획서 ${page}쪽`} />
          : <div className="pg-wait">{isError ? `기획서 ${page}쪽을 그리지 못했습니다.` : `기획서 ${page}쪽을 그리는 중…`}</div>}
        {image && highlights.map((h) => h.rects.filter((r) => r.page === page).map((r, i) => {
          const cls = ['hl', `h-${statusClass(h.status)}`, h.unitId === selectedId && 'on', h.unitId === hoverId && 'hov']
          return (
            <div
              key={`${h.unitId}-${i}`}
              className={cls.filter(Boolean).join(' ')}
              data-u={h.unitId}
              style={{ left: `${r.x}%`, top: `${r.y}%`, width: `${r.w}%`, height: `${r.h}%` }}
              {...(i === 0 ? { tabIndex: 0, role: 'button', 'aria-label': `${h.status}: ${h.title}` } : {})}
              onClick={() => onPick(h.unitId)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onPick(h.unitId) } }}
              onMouseEnter={() => { onHover(h.unitId); setTip({ text: `${h.status} · ${h.title}`, x: r.x + r.w / 2, y: r.y }) }}
              onMouseLeave={() => { onHover(null); setTip(null) }}
            />
          )
        }))}
        {tip && (
          <div className="tip" style={{
            display: 'block',
            left: `${Math.min(tip.x, 99)}%`,
            top: `${tip.y}%`,
            ...(tip.x > 70 ? { transform: 'translate(-100%, calc(-100% - 6px))' } : {}),
          }}>{tip.text}</div>
        )}
      </div>
    </figure>
  )
}

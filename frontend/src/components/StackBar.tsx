import { statusClass } from '../lib/summary.ts'

interface Props<S extends string> {
  counts: Record<S, number>
  statuses: readonly S[]
}

/** 판정별 비율 막대 (초안 .stack) */
export default function StackBar<S extends string>({ counts, statuses }: Props<S>) {
  const total = statuses.reduce((n, s) => n + counts[s], 0)
  return (
    <div className="stack" role="img" aria-label={statuses.map((s) => `${s} ${counts[s]}`).join(', ')}>
      {total > 0 && statuses.map((s) => counts[s] > 0 && (
        <span key={s} className={`c-${statusClass(s)}`} style={{ width: `${(counts[s] / total) * 100}%` }} />
      ))}
    </div>
  )
}

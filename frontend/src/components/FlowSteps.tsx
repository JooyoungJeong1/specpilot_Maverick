// 새로 분석하기 흐름 표시 (초안 .flow): 기획서·코드 올리기 → 분석 → 결과
const STEPS = ['기획서·코드 올리기', '분석', '결과']

export default function FlowSteps({ now }: { now: number }) {
  return (
    <div className="flow" aria-label="진행 순서">
      {STEPS.map((s, i) => (
        <span key={s} className={i < now ? 'done' : i === now ? 'now' : undefined} aria-current={i === now ? 'step' : undefined}>
          {i < now && '✓ '}{s}
        </span>
      ))}
    </div>
  )
}

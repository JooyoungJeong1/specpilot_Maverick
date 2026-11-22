// 요약 화면 아래 "③ 판정 비용 · 처리시간" 카드. judge_report.json의 usage를 그대로 보여 준다 (비용 계산은 백엔드 cost.py).
import { COST_CARD_ID, formatDuration, formatPercent, formatTokens, formatUsd, inputTotal, usageRows } from '../lib/usage.ts'
import type { JudgeUsage } from '../types/judge_report.ts'

interface Props {
  /** 없으면 비용 기록 기능을 넣기 전에 판정한 실행 */
  usage: JudgeUsage | undefined
  /** 기획서 화면 순서와 이름 (화면별 줄 정렬용) */
  screens: { id: string; name: string }[]
  /** "화면별로 보기"가 펼쳐져 있는지 (위 요약의 "자세히 보기"가 연다) */
  open: boolean
  onOpenChange: (open: boolean) => void
}

export default function UsageCard({ usage, screens, open, onOpenChange }: Props) {
  if (!usage) {
    return (
      <section className="card cost" id={COST_CARD_ID}>
        <h3>③ 판정 비용 · 처리시간</h3>
        <p className="small muted">이 실행에는 비용 기록이 없습니다. 비용 기록 기능을 넣기 전에 판정한 실행입니다.</p>
      </section>
    )
  }
  const t = usage.total
  const rows = usageRows(usage, screens)
  const models = [...new Set(rows.filter((r) => !r.reused && r.model).map((r) => r.model))]
  return (
    <section className="card cost" id={COST_CARD_ID}>
      <div className="cost-h">
        <h3>③ 판정 비용 · 처리시간</h3>
        <span className="small faint">예상 비용은 공식 가격표로 계산한 값{models.length > 0 && ` · 모델 ${models.join(', ')}`}</span>
      </div>
      <div className="cost-stats">
        <div><span>AI 호출</span><b>{t.calls}번</b></div>
        <div><span>처리시간</span><b>{formatDuration(t.elapsed_sec)}</b></div>
        <div><span>예상 비용</span><b>{formatUsd(t.cost_usd)}</b></div>
        <div><span>캐시에서 읽은 입력</span><b>{formatPercent(t.cache_read_ratio)}</b></div>
        <div><span>토큰</span><b>입력 {formatTokens(inputTotal(t))} · 출력 {formatTokens(t.output_tokens)}</b></div>
      </div>
      {t.screens_reused > 0 && (
        <p className="small muted">지난 실행의 판정을 그대로 쓴 화면 {t.screens_reused}개 · 아낀 비용 {formatUsd(t.saved_cost_usd)}</p>
      )}
      <details open={open} onToggle={(e) => onOpenChange(e.currentTarget.open)}>
        <summary>화면별로 보기</summary>
        <table className="tbl">
          <thead>
            <tr><th>화면</th><th>호출</th><th>처리시간</th><th>예상 비용</th><th>토큰 (입력 · 출력)</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <td>{r.label}{r.reused && <span className="small faint"> · 지난 판정 재사용</span>}</td>
                <td>{r.reused ? '-' : r.calls}</td>
                <td>{r.reused ? '-' : formatDuration(r.elapsed_sec)}</td>
                <td>{r.reused ? '$0' : formatUsd(r.cost_usd)}</td>
                <td className="small muted">{r.reused ? '-' : `${formatTokens(inputTotal(r))} · ${formatTokens(r.output_tokens)}`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </section>
  )
}

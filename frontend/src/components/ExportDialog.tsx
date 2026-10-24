// 내보내기 4종 (CLAUDE.md 5장). 지금은 브라우저에서 SheetJS로 xlsx를 만든다.
import { useState, type Ref } from 'react'
import { useCurrentRun } from '../api/useRun.ts'
import { runLabel } from '../lib/format.ts'
import { EXPORT_KINDS, exportFileName, exportSheets, type ExportKind } from '../lib/sheets.ts'
import { downloadWorkbook } from './xlsx.ts'

export default function ExportDialog({ ref }: { ref: Ref<HTMLDialogElement> }) {
  const { run } = useCurrentRun()
  const [picked, setPicked] = useState<Set<ExportKind>>(() => new Set(EXPORT_KINDS.map((k) => k.kind)))
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const noSpec = !run?.scenarios
  const chosen = EXPORT_KINDS.filter((k) => picked.has(k.kind) && !(k.kind === 'spec' && noSpec))

  const toggle = (kind: ExportKind) => setPicked((prev) => {
    const next = new Set(prev)
    if (next.has(kind)) next.delete(kind)
    else next.add(kind)
    return next
  })

  const download = async () => {
    if (!run) return
    setBusy(true)
    setMessage(null)
    try {
      for (const k of chosen) {
        const sheets = exportSheets(k.kind, run)
        if (sheets) await downloadWorkbook(exportFileName(k.kind, runLabel(run)), sheets)
      }
      setMessage(`${chosen.length}개 파일을 내려받았습니다.`)
    } catch (e) {
      setMessage(`내려받지 못했습니다. ${String(e)}`)
    } finally {
      setBusy(false)
    }
  }

  return (
    <dialog ref={ref} onClose={() => setMessage(null)}>
      <div className="dh">
        <b>내보내기</b>
        <button className="btn" type="button" onClick={(e) => e.currentTarget.closest('dialog')?.close()}>닫기</button>
      </div>
      <div className="dl">
        {EXPORT_KINDS.map((k) => {
          const off = k.kind === 'spec' && noSpec
          return (
            <label key={k.kind} style={off ? { opacity: 0.5, cursor: 'not-allowed' } : undefined}>
              <input type="checkbox" checked={picked.has(k.kind) && !off} disabled={off} onChange={() => toggle(k.kind)} />
              <span><b>{k.title}</b><small>{off ? '테스트 사양서가 아직 만들어지지 않았습니다.' : k.desc}</small></span>
            </label>
          )
        })}
        <div style={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 12, marginTop: 14 }}>
          {message && <span className="small muted" role="status">{message}</span>}
          <button className="btn pri" type="button" disabled={!run || busy || !chosen.length} onClick={download}>
            {busy ? '만드는 중…' : '내려받기'}
          </button>
        </div>
      </div>
    </dialog>
  )
}

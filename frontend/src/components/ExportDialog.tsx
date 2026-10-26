// 내보내기 5종 (CLAUDE.md 5장). 사양서·추적표는 백엔드가 만든 엑셀(기업 양식)이 있으면 그 파일을 그대로 내려받고,
// 나머지는 브라우저에서 SheetJS로 xlsx를 만든다. 백엔드 사양서가 없으면(예시 데이터 등) 사양서도 브라우저에서 만든다.
import { useState, type Ref } from 'react'
import { useCurrentRun, useRunFile } from '../api/useRun.ts'
import { runLabel } from '../lib/format.ts'
import { EXPORT_KINDS, exportFileName, exportSheets, type ExportKind } from '../lib/sheets.ts'
import { downloadFile, downloadWorkbook } from './xlsx.ts'

export default function ExportDialog({ ref }: { ref: Ref<HTMLDialogElement> }) {
  const { run } = useCurrentRun()
  const files: Partial<Record<ExportKind, string | null>> = {
    spec: useRunFile(run?.id, EXPORT_KINDS.find((k) => k.kind === 'spec')?.backend),
    trace: useRunFile(run?.id, EXPORT_KINDS.find((k) => k.kind === 'trace')?.backend),
  }
  const [picked, setPicked] = useState<Set<ExportKind>>(() => new Set(EXPORT_KINDS.map((k) => k.kind)))
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<string | null>(null)

  /** 못 내려받는 이유. 내려받을 수 있으면 null */
  const unavailable = (kind: ExportKind): string | null => {
    if (kind === 'spec' && !files.spec && !run?.scenarios) return '테스트 사양서가 아직 만들어지지 않았습니다.'
    if (kind === 'trace' && !files.trace) return '추적표는 사양서(④)를 만들 때 함께 생깁니다. 이 실행에는 아직 없습니다.'
    return null
  }
  const chosen = EXPORT_KINDS.filter((k) => picked.has(k.kind) && !unavailable(k.kind))

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
        const name = exportFileName(k.kind, runLabel(run))
        const url = files[k.kind]
        if (url) {
          downloadFile(url, name)
          continue
        }
        const sheets = exportSheets(k.kind, run)
        if (sheets) await downloadWorkbook(name, sheets)
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
          const off = unavailable(k.kind)
          return (
            <label key={k.kind} style={off ? { opacity: 0.5, cursor: 'not-allowed' } : undefined}>
              <input type="checkbox" checked={picked.has(k.kind) && !off} disabled={!!off} onChange={() => toggle(k.kind)} />
              <span><b>{k.title}</b><small>{off ?? k.desc}</small></span>
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

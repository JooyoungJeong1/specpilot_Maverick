// 코드 보기 창 (초안 #codeDlg, .cv). 근거 파일:줄의 앞뒤 줄을 보여 주고 근거 줄을 강조한다.
import { useQuery } from '@tanstack/react-query'
import { useEffect, useRef, useState, type ReactNode } from 'react'
import { getCodeContext } from '../api/api.ts'
import { useCurrentRun } from '../api/useRun.ts'
import { evidenceLines } from '../lib/codeView.ts'
import { CodeViewContext, type CodeViewRequest } from './codeViewContext.ts'

/** 근거 줄 앞뒤로 보여 줄 줄 수 */
const AROUND = 8

export default function CodeViewProvider({ children }: { children: ReactNode }) {
  const [req, setReq] = useState<CodeViewRequest | null>(null)
  return (
    <CodeViewContext.Provider value={setReq}>
      {children}
      {req && <CodeDialog req={req} onClose={() => setReq(null)} />}
    </CodeViewContext.Provider>
  )
}

function CodeDialog({ req, onClose }: { req: CodeViewRequest; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const { run } = useCurrentRun()
  const ev = req.evidence
  const { data, isLoading, isError } = useQuery({
    queryKey: ['code', run?.id, ev.file, ev.line],
    queryFn: () => getCodeContext(run!.id, ev.file, ev.line, AROUND),
    enabled: !!run,
    staleTime: Infinity,
  })
  const { from, to } = evidenceLines(ev)

  useEffect(() => {
    const d = ref.current
    if (d && !d.open) d.showModal()
  }, [])

  return (
    <dialog ref={ref} className="code-dlg" onClose={onClose} aria-label={`코드 보기 ${ev.file}:${ev.line}`}>
      <div className="dh">
        <b className="cref" style={{ fontSize: 13.5, color: 'var(--ink)' }}>{ev.file}:{ev.line}</b>
        <button className="btn" type="button" onClick={() => ref.current?.close()}>닫기</button>
      </div>
      {req.failed && <p className="note" style={{ margin: '12px 18px 0' }}>AI가 댄 근거 코드가 이 줄의 실제 코드와 맞지 않습니다. 아래는 실제 코드입니다.</p>}
      {isLoading && <div className="empty">코드를 불러오는 중…</div>}
      {(isError || (!isLoading && !data)) && (
        <div className="empty">
          코드를 찾지 못했습니다. 샘플 코드 폴더가 없거나 그 파일이 없습니다.
          <div className="code" style={{ textAlign: 'left', marginTop: 12 }}><span className="ln">{ev.line}</span>{ev.code}</div>
        </div>
      )}
      {data && (
        <div className="cv">
          {data.lines.map((line, i) => {
            const no = data.start + i
            return <div key={no} className={no >= from && no <= to ? 'on' : undefined}><i>{no}</i>{line || ' '}</div>
          })}
        </div>
      )}
    </dialog>
  )
}

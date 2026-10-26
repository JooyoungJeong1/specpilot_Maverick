// 새 프로젝트 (CLAUDE.md 5장 /new). 초안 local/reference/app.html의 newPage()를 옮겼다.
// 프로젝트 이름, 기획 문서(PDF, 여러 개), 소스코드(zip 또는 저장소 주소). 문서 종류·언어 선택은 넣지 않는다.
import { useRef, useState, type DragEvent, type KeyboardEvent, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { startAnalysis } from '../api/api.ts'
import { useServerStatus } from '../api/useRun.ts'
import FlowSteps from '../components/FlowSteps.tsx'
import { defaultName, formatSize, isZip, missingInputs, splitPlans } from '../lib/upload.ts'

const UploadIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" strokeWidth="1.6" aria-hidden="true" style={{ stroke: 'var(--sub)' }}>
    <path d="M12 16V4M7 9l5-5 5 5M4 16v3a1 1 0 001 1h14a1 1 0 001-1v-3" />
  </svg>
)
const CodeIcon = () => (
  <svg width="28" height="28" viewBox="0 0 24 24" fill="none" strokeWidth="1.6" aria-hidden="true" style={{ stroke: 'var(--sub)' }}>
    <path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16" />
  </svg>
)

/** 끌어다 놓기 + 눌러서 고르기 영역 (초안 .drop) */
function DropZone({ accept, multiple, onFiles, children }: { accept: string; multiple?: boolean; onFiles: (f: File[]) => void; children: ReactNode }) {
  const input = useRef<HTMLInputElement>(null)
  const [over, setOver] = useState(false)
  const open = () => input.current?.click()
  return (
    <div
      className={`drop${over ? ' over' : ''}`}
      role="button"
      tabIndex={0}
      onClick={open}
      onKeyDown={(e: KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); open() } }}
      onDragOver={(e: DragEvent) => { e.preventDefault(); setOver(true) }}
      onDragLeave={() => setOver(false)}
      onDrop={(e: DragEvent) => { e.preventDefault(); setOver(false); onFiles([...e.dataTransfer.files]) }}
    >
      {children}
      <input ref={input} type="file" accept={accept} multiple={multiple} hidden
        onChange={(e) => { onFiles([...(e.target.files ?? [])]); e.target.value = '' }} />
    </div>
  )
}

function FileRow({ kind, file, onRemove }: { kind: 'pdf' | 'zip'; file: File; onRemove: () => void }) {
  return (
    <div className="file">
      <div className={`fi ${kind}`}>{kind.toUpperCase()}</div>
      <div className="meta"><b>{file.name}</b><span className="small muted">{formatSize(file.size)}</span></div>
      <button className="btn" type="button" aria-label={`${file.name} 빼기`} onClick={onRemove}>빼기</button>
    </div>
  )
}

export default function NewProject() {
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [plans, setPlans] = useState<File[]>([])
  const [zip, setZip] = useState<File | null>(null)
  const [repoUrl, setRepoUrl] = useState('')
  const [warn, setWarn] = useState<string | null>(null)
  const [tried, setTried] = useState(false)
  const [busy, setBusy] = useState(false)
  const server = useServerStatus()

  const addPlans = (files: File[]) => {
    const { pdfs, rejected } = splitPlans(files)
    setPlans((prev) => [...prev, ...pdfs.filter((f) => !prev.some((p) => p.name === f.name && p.size === f.size))])
    setWarn(rejected.length ? `PDF만 올릴 수 있습니다: ${rejected.map((f) => f.name).join(', ')}` : null)
  }
  const addZip = (files: File[]) => {
    const z = files.find((f) => isZip(f.name))
    if (z) { setZip(z); setWarn(null) } else if (files.length) setWarn('소스코드는 .zip 압축 파일로 올려 주세요.')
  }

  const missing = missingInputs({ plans, zip, repoUrl })
  const start = async () => {
    setTried(true)
    if (missing.length) return
    setBusy(true)
    try {
      const { jobId } = await startAnalysis({
        name: name.trim() || defaultName(plans),
        plans,
        code: zip ? { zip } : { repoUrl: repoUrl.trim() },
      })
      navigate(`/progress?job=${encodeURIComponent(jobId)}`)
    } catch (e) {
      setWarn(`분석을 시작하지 못했습니다. ${e instanceof Error ? e.message : String(e)}`)
      setBusy(false)
    }
  }

  return (
    <div className="wrapS">
      <FlowSteps now={0} />
      <div className="hello">
        <h1>새 프로젝트</h1>
        <p>프로젝트 이름을 정하고 기획서와 소스코드를 올립니다. 기획 문서는 여러 개를 함께 올릴 수 있습니다.</p>
      </div>
      <section className="card" style={{ padding: '16px 20px', marginBottom: 16, display: 'flex', gap: 14, alignItems: 'center', flexWrap: 'wrap' }}>
        <label htmlFor="pname" style={{ fontWeight: 700, fontSize: 15 }}>프로젝트 이름</label>
        <input type="text" id="pname" value={name} placeholder={defaultName(plans) || '예: 고객센터 개편'}
          onChange={(e) => setName(e.target.value)} style={{ flex: 1, minWidth: 0 }} />
      </section>
      <div className="up">
        <section className="card">
          <h2>기획 문서</h2>
          <DropZone accept=".pdf,application/pdf" multiple onFiles={addPlans}>
            <UploadIcon /><b>파일을 끌어다 놓거나 눌러서 선택</b><span className="small muted">PDF</span>
          </DropZone>
          {plans.map((f, i) => <FileRow key={`${f.name}-${i}`} kind="pdf" file={f} onRemove={() => setPlans(plans.filter((_, j) => j !== i))} />)}
        </section>
        <section className="card">
          <h2>소스코드</h2>
          <DropZone accept=".zip,application/zip" onFiles={addZip}>
            <CodeIcon /><b>압축 파일(.zip)을 끌어다 놓기</b><span className="small muted">또는 아래에 저장소 주소 입력</span>
          </DropZone>
          {zip && <FileRow kind="zip" file={zip} onRemove={() => setZip(null)} />}
          <input type="text" placeholder="https://github.com/…" aria-label="저장소 주소" value={repoUrl} disabled={!!zip}
            onChange={(e) => setRepoUrl(e.target.value)} style={{ width: '100%', marginTop: 12 }} />
        </section>
      </div>
      {(warn || (tried && missing.length > 0)) && (
        <div className="note" role="alert">{[warn, ...(tried ? missing : [])].filter(Boolean).join(' ')}</div>
      )}
      {server.data?.running && (
        <div className="note" role="status">
          다른 분석이 진행 중입니다. 끝난 뒤에 시작할 수 있습니다.{' '}
          <Link className="linkbtn" to={`/progress?job=${encodeURIComponent(server.data.running)}`}>진행 화면 보기 →</Link>
        </div>
      )}
      {server.data && !server.data.running && (
        <p className="small muted" style={{ margin: '0 0 12px' }}>올린 파일로 실제 분석을 돌립니다. 기획서 크기에 따라 수십 분이 걸릴 수 있습니다.</p>
      )}
      {import.meta.env.DEV && server.data === null && (
        <p style={{ margin: '0 0 12px' }}>
          <span className="devtag">개발용: 시연 서버(backend에서 python -m specpilot serve)가 꺼져 있어 파일을 올리지 않고, 가장 최근 결과로 진행 화면을 보여 줍니다</span>
        </p>
      )}
      <div className="actions">
        <Link className="btn" to="/">취소</Link>
        <button className="btn pri" type="button" disabled={busy} onClick={start}>{busy ? '시작하는 중…' : '분석 시작'}</button>
      </div>
    </div>
  )
}

// 데이터를 가져오는 곳은 여기 한 곳만 둔다 (CLAUDE.md 6장).
// 지금은 Vite 개발 서버의 /data 미들웨어(vite-local-runs.ts)가 local/runs/<실행ID>/ 또는 mock/을 내려 준다.
// 로컬 서버가 생기면 이 파일의 주소와 응답 처리만 바꾼다. 화면은 아래 함수와 타입만 쓴다.
import type { JudgeReport } from '../types/judge_report.ts'
import type { Judgments, JudgeStatus } from '../types/judgments.ts'
import type { AnalysisInput, Progress } from '../types/progress.ts'
import { normalizeJudgments } from '../lib/normalize.ts'
import { loadJob, saveJob, simulateProgress } from './mockProgress.ts'
import type { Requirements } from '../types/requirements.ts'
import type { Scenarios } from '../types/scenarios.ts'

const BASE = '/data'

export interface RunSummary {
  id: string
  /** local: 조장에게 받은 실제 결과(local/runs), mock: 커밋된 가짜 데이터 */
  source: 'local' | 'mock'
  /** 기획서 화면 수 */
  screens: number
  /** 요구사항(단위) 수 */
  units: number
  /** requirements.json을 만든 시각 */
  mergedAt: string | null
  /** judge_report.json의 판정 수. ③을 안 돌렸으면 null */
  byStatus: Partial<Record<JudgeStatus, number>> | null
  /** 판정 전 단위 수. ③을 안 돌렸으면 null */
  notJudged: number | null
}

export interface RunData {
  id: string
  source: RunSummary['source']
  requirements: Requirements
  /** ③을 아직 안 돌렸으면 null */
  judgments: Judgments | null
  report: JudgeReport | null
  /** ④는 아직 없어 실제 결과에는 없다 (mock에만 있음) */
  scenarios: Scenarios | null
}

export interface CodeContext {
  file: string
  /** 근거 줄 */
  line: number
  /** lines[0]의 줄 번호 */
  start: number
  lines: string[]
}

function runUrl(runId: string, ...rest: string[]): string {
  return [BASE, 'runs', runId, ...rest].map((p, i) => (i < 2 ? p : encodeURIComponent(p))).join('/')
}

async function getJson<T>(url: string): Promise<T> {
  const res = await fetch(url)
  if (!res.ok) throw new Error(`${url}: ${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

/** 없으면(404) null */
async function getOptionalJson<T>(url: string): Promise<T | null> {
  const res = await fetch(url)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`${url}: ${res.status} ${await res.text()}`)
  return res.json() as Promise<T>
}

/** 실행 목록. 최신이 먼저. local/runs/에 결과가 있으면 그것만, 없으면 mock */
export function listRuns(): Promise<RunSummary[]> {
  return getJson<RunSummary[]>(`${BASE}/runs`)
}

export async function getRun(runId: string): Promise<RunData> {
  const file = (name: string) => `${runUrl(runId, 'files')}/${name}`
  const runs = await listRuns()
  const summary = runs.find((r) => r.id === runId)
  if (!summary) throw new Error(`실행 결과가 없습니다: ${runId}`)
  const [requirements, judgments, report, scenarios] = await Promise.all([
    getJson<Requirements>(file('requirements.json')),
    getOptionalJson<Judgments>(file('judgments.json')).then(normalizeJudgments),
    getOptionalJson<JudgeReport>(file('judge_report.json')),
    getOptionalJson<Scenarios>(file('scenarios.json')),
  ])
  return { id: runId, source: summary.source, requirements, judgments, report, scenarios }
}

/** 기획서 원본(input.pdf) 주소. 파일이 없으면(mock 등) null */
export async function getPdfUrl(runId: string): Promise<string | null> {
  const url = `${runUrl(runId, 'files')}/input.pdf`
  const res = await fetch(url, { method: 'HEAD' })
  return res.ok ? url : null
}

/** 근거 코드 앞뒤 줄. 코드 폴더가 없으면 null */
export async function getCodeContext(runId: string, file: string, line: number, around = 5): Promise<CodeContext | null> {
  const q = new URLSearchParams({ file, line: String(line), around: String(around) })
  return getOptionalJson<CodeContext>(`${runUrl(runId, 'code')}?${q}`)
}

// ---------- 새 분석과 진행 상태 ----------
// 서버가 아직 없어서 mock이다: 파일을 올리지 않고, 가장 최근 실행 결과를 시간에 따라 단계별로 보여 준다 (mockProgress.ts).
// 서버가 생기면 이렇게 바꾼다.
//   startAnalysis: POST /api/analyses (multipart: name, plans[], code zip 또는 repoUrl) → { jobId }
//   getProgress:   GET  /api/analyses/<jobId> → Progress (types/progress.ts 주석의 meta 파일 status로 만든다)

/** 분석 시작. 진행 화면에서 쓸 작업 ID를 돌려준다. */
export async function startAnalysis(input: AnalysisInput): Promise<{ jobId: string }> {
  const runs = await listRuns()
  if (!runs.length) throw new Error('예시로 보여 줄 실행 결과가 없습니다')
  const jobId = `job-${Date.now()}`
  saveJob({ jobId, name: input.name, runId: runs[0].id, startedAt: Date.now() })
  return { jobId }
}

const mockRuns = new Map<string, Promise<RunData>>()

/** 진행 상태. 작업이 없으면 null */
export async function getProgress(jobId: string): Promise<Progress | null> {
  const job = loadJob(jobId)
  if (!job) return null
  let run = mockRuns.get(job.runId)
  if (!run) {
    run = getRun(job.runId)
    mockRuns.set(job.runId, run)
  }
  const { requirements, report } = await run
  return simulateProgress(job, requirements, report, Date.now() - job.startedAt)
}

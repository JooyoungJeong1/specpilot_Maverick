// 데이터를 가져오는 곳은 여기 한 곳만 둔다 (CLAUDE.md 6장).
// 결과 파일: Vite 개발 서버의 /data 미들웨어(vite-local-runs.ts)가 backend/output/, local/runs/ 또는 mock/을 내려 준다.
// 새 분석: 시연 서버(backend `python -m specpilot serve`, /api)가 켜져 있으면 실제로 올리고 돌린다.
//          꺼져 있으면 지금까지처럼 mock으로 흉내 낸다 (mockProgress.ts). 화면은 아래 함수와 타입만 쓴다.
import type { JudgeReport } from '../types/judge_report.ts'
import type { Judgments, JudgeStatus } from '../types/judgments.ts'
import type { AnalysisInput, Progress } from '../types/progress.ts'
import { normalizeJudgments } from '../lib/normalize.ts'
import { loadJob, saveJob, simulateProgress } from './mockProgress.ts'
import type { Requirements } from '../types/requirements.ts'
import type { Scenarios } from '../types/scenarios.ts'

const BASE = '/data'
const API = '/api'

export interface RunSummary {
  id: string
  /** local: 실제 결과(backend/output 또는 조장에게 받은 local/runs), mock: 커밋된 가짜 데이터 */
  source: 'local' | 'mock'
  /** 웹에서 올려 돌린 실행이면 새 분석에서 입력한 프로젝트 이름 (job.json). 아니면 null */
  name: string | null
  /** 기획서 화면 수 */
  screens: number
  /** 요구사항(단위) 수 */
  units: number
  /** requirements.json을 만든 시각 */
  mergedAt: string | null
  /** 마지막으로 결과가 바뀐 시각: ①② · ③ · ④ 중 가장 늦은 것. ③만 다시 돌린 실행은 ③을 돌린 때 */
  updatedAt: string | null
  /** judge_report.json의 판정 수. ③을 안 돌렸으면 null */
  byStatus: Partial<Record<JudgeStatus, number>> | null
  /** 판정 전 단위 수. ③을 안 돌렸으면 null */
  notJudged: number | null
}

export interface RunData {
  id: string
  source: RunSummary['source']
  name: string | null
  requirements: Requirements
  /** ③을 아직 안 돌렸으면 null */
  judgments: Judgments | null
  report: JudgeReport | null
  /** ④ 결과 (scenarios.json). ④를 아직 안 돌렸으면 null */
  scenarios: Scenarios | null
  /** RunSummary.updatedAt (예시 데이터는 없을 수 있다) */
  updatedAt?: string | null
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

/** 실행 목록. 최신이 먼저. backend/output/·local/runs/에 결과가 있으면 그것만, 없으면 mock */
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
  return { id: runId, source: summary.source, name: summary.name ?? null, requirements, judgments, report, scenarios,
    updatedAt: summary.updatedAt ?? null }
}

/** 실행 폴더의 파일 주소 (백엔드가 만든 테스트사양서.xlsx, 추적표.xlsx 등). 파일이 없으면 null */
export async function getRunFileUrl(runId: string, name: string): Promise<string | null> {
  const url = `${runUrl(runId, 'files')}/${encodeURIComponent(name)}`
  const res = await fetch(url, { method: 'HEAD' })
  return res.ok ? url : null
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
// 시연 서버(backend/specpilot/server.py)가 켜져 있으면:
//   startAnalysis: POST /api/analyses (multipart: name, plans 여러 개, code zip 또는 repoUrl) → { jobId }
//   getProgress:   GET  /api/analyses/<jobId> → Progress (서버가 실행 폴더의 meta 파일로 만든다)
// 서버가 꺼져 있으면 mock: 파일을 올리지 않고, 가장 최근 실행 결과를 시간에 따라 단계별로 보여 준다 (mockProgress.ts).
// mock 작업 ID는 "job-"로 시작해서 진행 상태를 물을 때 둘을 가린다.

const MOCK_JOB = 'job-'

/** 서버 없이 흉내 낸 작업인지 */
export function isMockJob(jobId: string): boolean {
  return jobId.startsWith(MOCK_JOB)
}

export interface ServerStatus {
  /** 지금 돌고 있는 작업 ID. 없으면 null (한 번에 하나만 돈다) */
  running: string | null
}

/** 시연 서버 상태. 서버가 꺼져 있으면 null (웹 개발 서버가 /api를 넘기는데 받을 곳이 없어 오류가 난다) */
export async function getServerStatus(): Promise<ServerStatus | null> {
  try {
    const res = await fetch(`${API}/health`)
    if (!res.ok) return null
    const body = await res.json()
    return body?.ok === true ? { running: typeof body.running === 'string' ? body.running : null } : null
  } catch {
    return null
  }
}

/** 시연 서버가 켜져 있는지 */
export async function hasServer(): Promise<boolean> {
  return (await getServerStatus()) !== null
}

async function serverError(res: Response): Promise<Error> {
  const text = await res.text()
  try {
    return new Error(JSON.parse(text).detail ?? text)
  } catch {
    return new Error(text || `${res.status}`)
  }
}

/** 분석 시작. 진행 화면에서 쓸 작업 ID를 돌려준다. */
export async function startAnalysis(input: AnalysisInput): Promise<{ jobId: string }> {
  if (await hasServer()) {
    const form = new FormData()
    form.append('name', input.name)
    for (const f of input.plans) form.append('plans', f)
    if ('zip' in input.code) form.append('code', input.code.zip)
    else form.append('repoUrl', input.code.repoUrl)
    const res = await fetch(`${API}/analyses`, { method: 'POST', body: form })
    if (!res.ok) throw await serverError(res)
    return res.json() as Promise<{ jobId: string }>
  }
  const runs = await listRuns()
  if (!runs.length) throw new Error('예시로 보여 줄 실행 결과가 없습니다')
  const jobId = `${MOCK_JOB}${Date.now()}`
  saveJob({ jobId, name: input.name, runId: runs[0].id, startedAt: Date.now() })
  return { jobId }
}

const mockRuns = new Map<string, Promise<RunData>>()

/** 진행 상태. 작업이 없으면 null */
export async function getProgress(jobId: string): Promise<Progress | null> {
  if (!isMockJob(jobId)) {
    const res = await fetch(`${API}/analyses/${encodeURIComponent(jobId)}`)
    if (res.status === 404) return null
    if (!res.ok) throw await serverError(res)
    return res.json() as Promise<Progress>
  }
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

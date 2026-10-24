// 가짜 분석 진행 (서버 연결 전). 실제로 분석하지 않고, 이미 있는 실행 결과를 시간에 따라 단계별로 보여 준다.
// 서버가 생기면 api.ts의 startAnalysis / getProgress가 서버를 부르고 이 파일은 지운다.
import type { JudgeReport } from '../types/judge_report.ts'
import type { Progress, ScreenProgress, StageProgress, StageState } from '../types/progress.ts'
import type { Requirements } from '../types/requirements.ts'

/** 단계별 걸리는 시간(ms). 시연에서 지루하지 않을 정도 */
export const MOCK_TIMING = { preflight: 1200, profile: 2500, perScreen: 700, perJudge: 700 }

function stage(key: StageProgress['key'], start: number, total: number, per: number, t: number): StageProgress {
  const done = Math.max(0, Math.min(total, Math.floor((t - start) / per)))
  const state: StageState = t < start ? 'waiting' : done >= total ? 'done' : 'running'
  return { key, state, done, total }
}

/** 실행 결과(requirements, judge_report)와 시작 뒤 지난 시간으로 진행 상태를 만든다 */
export function simulateProgress(
  job: { jobId: string; name: string; runId: string },
  requirements: Requirements,
  report: JudgeReport | null,
  elapsed: number,
): Progress {
  const T = MOCK_TIMING
  const screens = requirements.app_profile.screens
  const judged = report ? screens.filter((s) => report.screen_status[s.screen_id] !== undefined) : []

  const tProfile = T.preflight
  const tDecompose = tProfile + T.profile
  const tJudge = tDecompose + screens.length * T.perScreen
  const tEnd = tJudge + judged.length * T.perJudge

  const preflight = stage('preflight', 0, 1, T.preflight, elapsed)
  const profile = stage('profile', tProfile, 1, T.profile, elapsed)
  const decompose = stage('decompose', tDecompose, screens.length, T.perScreen, elapsed)
  const judge: StageProgress = report
    ? stage('judge', tJudge, judged.length, T.perJudge, elapsed)
    : { key: 'judge', state: 'skipped', done: 0, total: 0 }
  const scenario: StageProgress = { key: 'scenario', state: 'skipped', done: 0, total: 0 }

  const rows: ScreenProgress[] = screens.map((s, i) => {
    const st = requirements.screen_status[s.screen_id]
    const decomposeDone = i < decompose.done
    const j = judged.findIndex((x) => x.screen_id === s.screen_id)
    const judgeFinal = report?.screen_status[s.screen_id]
    return {
      screenId: s.screen_id,
      name: s.name,
      decompose: decomposeDone ? st?.status ?? '미실행' : decompose.state === 'running' && i === decompose.done ? '진행 중' : '대기',
      units: decomposeDone && st && st.status !== '반려' ? st.units : null,
      rejectReason: decomposeDone ? requirements.rejected_screens[s.screen_id] ?? null : null,
      // 코드와 비교하지 않는 화면(반려 등)인지는 ②가 그 화면을 끝내야 안다
      judge: j < 0 ? (decomposeDone ? null : '대기')
        : j < judge.done ? (judgeFinal === '완료' || judgeFinal === '확인필요' || judgeFinal === '실패' ? judgeFinal : '완료')
          : judge.state === 'running' && j === judge.done ? '진행 중' : '대기',
    }
  })

  const done = elapsed >= (report ? tEnd : tJudge)
  const by = report?.summary.by_status
  return {
    jobId: job.jobId,
    name: job.name,
    state: done ? 'done' : 'running',
    stages: [preflight, profile, decompose, judge, scenario],
    screens: rows,
    runId: done ? job.runId : null,
    problems: done && by ? (by['미구현'] ?? 0) + (by['불일치'] ?? 0) + (by['확인필요'] ?? 0) : null,
    message: null,
  }
}

// ---------- 가짜 작업 저장 (새로 고침해도 진행 화면이 이어지게 그 탭의 sessionStorage에) ----------

export interface MockJob {
  jobId: string
  name: string
  runId: string
  startedAt: number
}

const KEY = 'specpilot.mockJobs'

function readJobs(): Record<string, MockJob> {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) ?? '{}')
  } catch {
    return {}
  }
}

const memory: Record<string, MockJob> = {}

export function saveJob(job: MockJob): void {
  memory[job.jobId] = job
  try {
    sessionStorage.setItem(KEY, JSON.stringify({ ...readJobs(), [job.jobId]: job }))
  } catch { /* 저장소를 못 쓰면 이 페이지 안에서만 기억한다 */ }
}

export function loadJob(jobId: string): MockJob | null {
  return memory[jobId] ?? readJobs()[jobId] ?? null
}

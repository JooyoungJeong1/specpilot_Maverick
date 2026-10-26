// 분석 진행 상태. 프론트가 정한 모양이고, 시연 서버(backend/specpilot/server.py의 build_progress)가
// 실행 폴더의 파일로 이 값을 만든다 (CLAUDE.md 9장).
//   입력 점검: preflight.json의 verdict (반려면 전체 반려)
//   ①: app_profile.json
//   ②: screens/<화면ID>.meta.json의 status (완료/확인필요/실패/반려), 단위 수
//   ③: judge/<화면ID>.meta.json의 status (완료/확인필요/실패)
//   ④: scenario/<묶음ID>.meta.json의 status (화면 묶음별), 끝나면 scenario_report.json
import type { ScreenRunStatus } from './requirements.ts'

export type StageKey = 'preflight' | 'profile' | 'decompose' | 'judge' | 'scenario'
/** skipped: 이번 실행에서 하지 않는 단계 (③은 코드 없이 돌린 경우, 서버 없이 흉내 낼 때의 ④) */
export type StageState = 'waiting' | 'running' | 'done' | 'failed' | 'skipped'

export interface StageProgress {
  key: StageKey
  state: StageState
  /** 화면 단위 단계(②③)의 끝난 화면 수 */
  done: number
  /** 화면 단위 단계의 전체 화면 수. 한 번에 끝나는 단계(입력 점검, ①)는 1 */
  total: number
}

export type ScreenStepState = '대기' | '진행 중'

export interface ScreenProgress {
  screenId: string
  name: string
  /** ② 화면 상태. 끝나면 백엔드 status 그대로 */
  decompose: ScreenStepState | ScreenRunStatus
  /** ② 단위 수 (끝났을 때만) */
  units: number | null
  /** 반려 이유 */
  rejectReason: string | null
  /** ③ 화면 상태. 이 화면을 코드와 비교하지 않으면(반려 등) null */
  judge: ScreenStepState | '완료' | '확인필요' | '실패' | null
}

export interface Progress {
  jobId: string
  /** 프로젝트 이름 (새 프로젝트에서 입력) */
  name: string
  state: 'running' | 'done' | 'failed' | 'rejected'
  stages: StageProgress[]
  screens: ScreenProgress[]
  /** 끝나면 결과 폴더(실행 ID). 결과 화면은 이 실행을 연다. */
  runId: string | null
  /** 끝났을 때 확인할 판정 수 (미구현 + 불일치 + 확인필요) */
  problems: number | null
  /** 전체 반려·실패 이유 */
  message: string | null
}

/** 새 분석에 올리는 것. 기획 문서는 PDF만 (지금 백엔드가 PDF만 받는다) */
export interface AnalysisInput {
  name: string
  plans: File[]
  code: { zip: File } | { repoUrl: string }
}

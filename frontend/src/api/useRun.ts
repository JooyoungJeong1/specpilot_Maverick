// api.ts를 TanStack Query로 감싼 훅. 화면은 이 훅이나 api.ts만 쓴다.
import { useQuery } from '@tanstack/react-query'
import { useSyncExternalStore } from 'react'
import { getPdfUrl, getProgress, getRun, getRunFileUrl, getServerStatus, isMockJob, listRuns } from './api.ts'

// ---------- 지금 보는 실행 ----------
// 최근 분석에서 고르거나 분석이 끝나면 그 실행을 연다. 고르지 않았으면 최신 실행.
// 그 탭에서만 기억한다 (sessionStorage, 못 쓰면 이 페이지 안에서만).

const KEY = 'specpilot.run'
let selected: string | null = (() => {
  try { return sessionStorage.getItem(KEY) } catch { return null }
})()
const listeners = new Set<() => void>()

export function selectRun(runId: string): void {
  selected = runId
  try { sessionStorage.setItem(KEY, runId) } catch { /* 이 페이지 안에서만 기억 */ }
  listeners.forEach((l) => l())
}

function useSelectedRunId(): string | null {
  return useSyncExternalStore(
    (l) => { listeners.add(l); return () => listeners.delete(l) },
    () => selected,
  )
}

export function useRuns(enabled = true) {
  return useQuery({ queryKey: ['runs'], queryFn: listRuns, enabled })
}

/** 지금 보는 실행 */
export function useCurrentRun(enabled = true) {
  const runs = useRuns(enabled)
  const chosen = useSelectedRunId()
  const runId = runs.data?.find((r) => r.id === chosen)?.id ?? runs.data?.[0]?.id
  const run = useQuery({ queryKey: ['run', runId], queryFn: () => getRun(runId!), enabled: enabled && !!runId })
  return {
    run: run.data,
    isLoading: runs.isLoading || run.isLoading,
    error: runs.error ?? run.error,
    noRuns: runs.data?.length === 0,
  }
}

/** 기획서 원본 PDF 주소. 없으면 null */
export function usePdfUrl(runId: string | undefined): string | null {
  const { data } = useQuery({ queryKey: ['pdf', runId], queryFn: () => getPdfUrl(runId!), enabled: !!runId, staleTime: Infinity })
  return data ?? null
}

/** 실행 폴더의 파일 주소 (백엔드가 만든 테스트사양서.xlsx, 추적표.xlsx 등). 없으면 null */
export function useRunFile(runId: string | undefined, name: string | undefined): string | null {
  const { data } = useQuery({ queryKey: ['file', runId, name], queryFn: () => getRunFileUrl(runId!, name!), enabled: !!runId && !!name })
  return data ?? null
}

/** 시연 서버 상태. 꺼져 있으면 null. 진행 중인 작업이 바뀌는 것을 보려고 5초마다 다시 묻는다 */
export function useServerStatus() {
  return useQuery({ queryKey: ['server'], queryFn: getServerStatus, refetchInterval: 5000 })
}

/** 분석 진행 상태. 끝날 때까지 다시 묻는다 (서버 없이 흉내 낼 때는 0.5초, 실제 분석은 2초마다) */
export function useProgress(jobId: string | null) {
  return useQuery({
    queryKey: ['progress', jobId],
    queryFn: () => getProgress(jobId!),
    enabled: !!jobId,
    refetchInterval: (q) => (q.state.data && q.state.data.state !== 'running' ? false : jobId && isMockJob(jobId) ? 500 : 2000),
  })
}

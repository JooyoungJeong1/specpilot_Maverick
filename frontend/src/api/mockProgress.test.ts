import { describe, expect, it } from 'vitest'
import { report, requirements } from '../lib/testFixtures.ts'
import { MOCK_TIMING as T, simulateProgress } from './mockProgress.ts'

const job = { jobId: 'job-1', name: '문의 앱', runId: 'qna-example' }
const at = (ms: number, r = report) => simulateProgress(job, requirements, r, ms)
const screens = requirements.app_profile.screens.length
const tDecompose = T.preflight + T.profile
const tJudge = tDecompose + screens * T.perScreen
const judged = Object.keys(report.screen_status).length
const tEnd = tJudge + judged * T.perJudge

describe('simulateProgress', () => {
  it('처음에는 입력 점검만 진행 중', () => {
    const p = at(0)
    expect(p.state).toBe('running')
    expect(p.stages.map((s) => s.state)).toEqual(['running', 'waiting', 'waiting', 'waiting', 'skipped'])
    expect(p.screens.every((s) => s.decompose === '대기' && s.judge === '대기')).toBe(true)   // 반려 화면도 아직은 대기
    expect(p.runId).toBeNull()
  })

  it('② 중간: 끝난 화면은 백엔드 상태와 단위 수, 다음 화면은 진행 중', () => {
    const p = at(tDecompose + 2 * T.perScreen + 10)
    expect(p.stages[2]).toMatchObject({ state: 'running', done: 2, total: screens })
    expect(p.screens[0]).toMatchObject({ decompose: '완료', units: 5 })
    expect(p.screens[2].decompose).toBe('진행 중')
    expect(p.screens[3].decompose).toBe('대기')
  })

  it('끝나면 실제 결과 상태와 같다 (반려·확인필요·③ 실패 포함)', () => {
    const p = at(tEnd + 1)
    expect(p.state).toBe('done')
    expect(p.runId).toBe('qna-example')
    expect(p.stages.slice(0, 4).every((s) => s.state === 'done')).toBe(true)
    const row = (id: string) => p.screens.find((s) => s.screenId === id)!
    expect(row('QNA-004')).toMatchObject({ decompose: '반려', units: null, judge: null })
    expect(row('QNA-004').rejectReason).toContain('그림 마커')
    expect(row('QNA-003').decompose).toBe('확인필요')
    expect(row('QNA-005').judge).toBe('실패')
    expect(p.problems).toBe(14)
  })

  it('③ 결과가 없는 실행은 ③을 건너뛰고 ②가 끝나면 끝', () => {
    const p = at(tJudge + 1, null as never)
    expect(p.stages[3].state).toBe('skipped')
    expect(p.state).toBe('done')
    expect(p.screens.every((s) => s.judge === null)).toBe(true)
  })
})

import type { Scenario, ScenarioStep, Scenarios } from '../types/scenarios.ts'

/** 그 단위들 중 하나라도 확인하는 테스트 단계 (화면별 보기 "테스트 사양서" 탭) */
export function stepsForUnits(scenarios: Scenarios | null, unitIds: Iterable<string>): { scenario: Scenario; step: ScenarioStep }[] {
  const ids = new Set(unitIds)
  return (scenarios?.scenarios ?? []).flatMap((scenario) =>
    scenario.steps.filter((step) => step.unit_ids.some((u) => ids.has(u))).map((step) => ({ scenario, step })))
}

/** 사양서 탭의 단계 하나를 가리키는 DOM id. 판정 카드의 "확인하는 테스트"를 누르면 이 단계로 간다. */
export function stepDomId(scenarioId: string, no: number): string {
  return `step-${scenarioId}-${no}`
}

export interface StepRef {
  scenarioId: string
  depth1: string
  depth2: string
  no: number
  action: string
}

/**
 * 단위 ID → 그 단위를 확인하는 테스트 단계. 판정 카드의 "확인하는 테스트"에 쓴다.
 * 사양서에는 판정을 넣지 않고 unit_ids로만 잇는다 (CLAUDE.md 4장 6번).
 */
export function stepsByUnit(scenarios: Scenarios | null): Map<string, StepRef[]> {
  const index = new Map<string, StepRef[]>()
  for (const sc of scenarios?.scenarios ?? []) {
    for (const st of sc.steps) {
      const ref = { scenarioId: sc.scenario_id, depth1: sc.depth1, depth2: sc.depth2, no: st.no, action: st.action }
      for (const uid of new Set(st.unit_ids)) {
        const list = index.get(uid)
        if (list) list.push(ref)
        else index.set(uid, [ref])
      }
    }
  }
  return index
}

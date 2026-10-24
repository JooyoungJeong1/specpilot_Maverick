import { useOutletContext } from 'react-router-dom'

/** Layout이 결과 화면들에 내려 주는 값 */
export interface LayoutContext {
  onlyProblems: boolean
}

export function useLayout() {
  return useOutletContext<LayoutContext>()
}

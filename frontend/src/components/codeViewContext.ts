import { createContext, useContext } from 'react'
import type { Evidence } from '../types/judgments.ts'

export interface CodeViewRequest {
  evidence: Evidence
  /** 근거 줄 대조에 실패한 근거 (그 줄이 실제 코드와 다를 수 있음) */
  failed?: boolean
}

/** "코드 보기" 창 열기. 결과 화면 어디서나 쓴다 (CodeDialog가 Layout에 하나 있다). */
export const CodeViewContext = createContext<((req: CodeViewRequest) => void) | null>(null)

export function useCodeView(): ((req: CodeViewRequest) => void) | null {
  return useContext(CodeViewContext)
}

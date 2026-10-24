import { useState } from 'react'
import { Outlet } from 'react-router-dom'
import AppBar from './AppBar.tsx'
import CodeViewProvider from './CodeDialog.tsx'
import type { LayoutContext } from './layoutContext.ts'

export default function Layout({ resultBar }: { resultBar: boolean }) {
  // "문제 있는 화면만" 스위치. 결과 화면들(요약, 화면별 보기 …)이 같이 쓴다.
  const [onlyProblems, setOnlyProblems] = useState(false)
  const page = <Outlet context={{ onlyProblems } satisfies LayoutContext} />
  return (
    <>
      <AppBar resultBar={resultBar} onlyProblems={onlyProblems} onOnlyProblemsChange={setOnlyProblems} />
      <div id="app">
        {resultBar ? <CodeViewProvider>{page}</CodeViewProvider> : page}
      </div>
    </>
  )
}

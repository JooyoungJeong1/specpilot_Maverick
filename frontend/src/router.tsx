import { createBrowserRouter } from 'react-router-dom'
import Layout from './components/Layout.tsx'
import Start from './pages/Start.tsx'
import NewProject from './pages/NewProject.tsx'
import Progress from './pages/Progress.tsx'
import Summary from './pages/Summary.tsx'
import ScreenView from './pages/ScreenView.tsx'
import RequirementTable from './pages/RequirementTable.tsx'
import SpecView from './pages/SpecView.tsx'

// CLAUDE.md 5장. 시작·새 프로젝트·진행은 상단 바에 로고만, 결과 화면은 보기 메뉴와 내보내기까지 보인다.
export const router = createBrowserRouter([
  {
    element: <Layout resultBar={false} />,
    children: [
      { path: '/', element: <Start /> },
      { path: '/new', element: <NewProject /> },
      { path: '/progress', element: <Progress /> },
    ],
  },
  {
    element: <Layout resultBar />,
    children: [
      { path: '/summary', element: <Summary /> },
      { path: '/screen/:id?', element: <ScreenView /> },
      { path: '/table', element: <RequirementTable /> },
      { path: '/spec', element: <SpecView /> },
    ],
  },
])

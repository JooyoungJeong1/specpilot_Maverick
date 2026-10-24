// 요구사항 표 (CLAUDE.md 5장 /table). 초안 local/reference/app.html의 table()을 옮겼다.
import { useMemo, useState, type KeyboardEvent } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useCurrentRun } from '../api/useRun.ts'
import { useCodeView } from '../components/codeViewContext.ts'
import { reviewText } from '../lib/judgeText.ts'
import { groupByScreen } from '../lib/screens.ts'
import { formatPages, statusClass } from '../lib/summary.ts'
import {
  cardPath, filterItemRows, filterUnitRows, itemQuote, itemRows, itemTarget, sortByStatus, unitRows,
  type TableFilters, type TableView,
} from '../lib/table.ts'
import { cardTitle } from '../lib/title.ts'
import { countStatuses, ITEM_STATUSES, mergeVerdicts, UNIT_STATUSES } from '../lib/verdicts.ts'
import type { Origin } from '../types/requirements.ts'

const ALL_STATUSES = new Set<string>([...UNIT_STATUSES, ...ITEM_STATUSES])

/** 행 전체를 눌러 이동. 키보드로도 열 수 있게 한다. */
function rowProps(go: () => void) {
  return {
    className: 'click',
    tabIndex: 0,
    onClick: go,
    onKeyDown: (e: KeyboardEvent) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go() } },
  }
}

export default function RequirementTable() {
  const { run, isLoading, error } = useCurrentRun()
  const navigate = useNavigate()
  const showCode = useCodeView()
  const [params, setParams] = useSearchParams()
  const view: TableView = params.get('view') === 'item' ? 'item' : 'unit'
  const [statuses, setStatuses] = useState<Set<string>>(() => new Set(ALL_STATUSES))
  const [screen, setScreen] = useState('')
  const [origin, setOrigin] = useState<'' | Origin>('')
  const [query, setQuery] = useState('')

  const data = useMemo(() => {
    if (!run) return null
    const views = mergeVerdicts(run.requirements.units, run.judgments)
    const groups = groupByScreen(run.requirements, views)
    return { groups, units: unitRows(groups), items: itemRows(run.judgments, views) }
  }, [run])

  if (error) return <div className="tv"><div className="empty">결과를 불러오지 못했습니다. {String(error)}</div></div>
  if (isLoading || !data) return <div className="tv"><div className="empty">불러오는 중…</div></div>

  const isItem = view === 'item'
  const order = isItem ? ITEM_STATUSES : UNIT_STATUSES
  const counts = isItem ? countStatuses(data.items, ITEM_STATUSES) : countStatuses(data.units, UNIT_STATUSES)
  const filters: TableFilters = { statuses, screen, origin, query }
  const groupOf = new Map(data.groups.map((g) => [g.id, g]))
  const where = (screenId: string) => (screenId === 'APP' ? '여러 화면' : formatPages(groupOf.get(screenId)?.meta?.pages))

  const setView = (v: TableView) => {
    setParams(v === 'item' ? { view: 'item' } : {}, { replace: true })
    setStatuses(new Set(ALL_STATUSES))
  }
  const toggle = (s: string) => setStatuses((prev) => {
    const next = new Set(prev)
    if (next.has(s)) next.delete(s)
    else next.add(s)
    return next
  })

  const unitList = isItem ? [] : sortByStatus(filterUnitRows(data.units, filters), order)
  const itemList = isItem ? sortByStatus(filterItemRows(data.items, filters), order) : []
  const empty = isItem ? !itemList.length : !unitList.length

  return (
    <div className="tv">
      <div className="tv-h">
        <div>
          <h1>요구사항 표</h1>
          <p>모든 요구사항의 구현 상태와 관련 코드를 한 번에 봅니다. 행을 누르면 그 화면으로 이동합니다.</p>
        </div>
        <div className="seg" role="group" aria-label="보는 단위">
          <button type="button" aria-pressed={!isItem} onClick={() => setView('unit')}>요구사항별 {data.units.length}</button>
          <button type="button" aria-pressed={isItem} onClick={() => setView('item')}>기획서 항목별 {data.items.length}</button>
        </div>
      </div>

      <div className="flt">
        {order.filter((s) => counts[s as keyof typeof counts]).map((s) => (
          <button key={s} type="button" className="chip" aria-pressed={statuses.has(s)} onClick={() => toggle(s)}>
            <i className={`c-${statusClass(s)}`} />{s} {counts[s as keyof typeof counts]}
          </button>
        ))}
        <select aria-label="화면" value={screen} onChange={(e) => setScreen(e.target.value)}>
          <option value="">모든 화면</option>
          {data.groups.map((g) => <option key={g.id} value={g.id}>{g.isApp ? '앱 전체' : `${g.id} ${g.name}`}</option>)}
        </select>
        <select aria-label="명시·함의" value={origin} onChange={(e) => setOrigin(e.target.value as '' | Origin)}>
          <option value="">명시 + 함의</option>
          <option value="명시">명시만</option>
          <option value="함의">함의만</option>
        </select>
        <input type="text" placeholder="검색" aria-label="검색" value={query} onChange={(e) => setQuery(e.target.value)} />
      </div>

      <section className="card tw">
        {isItem ? (
          <table className="tr-tbl">
            <thead><tr><th>화면</th><th>기획서 항목</th><th>기획서 원문</th><th>요구사항</th><th>구현상태</th></tr></thead>
            <tbody>
              {itemList.map((r) => {
                const target = itemTarget(r)
                const g = groupOf.get(r.screenId)
                return (
                  <tr key={r.key} {...rowProps(() => target && navigate(cardPath(target.screenId, target.unitId)))}>
                    <td style={{ whiteSpace: 'nowrap' }}><b>{r.screenId === 'APP' ? '앱 전체' : r.screenId}</b><span className="q">{g && !g.isApp ? g.name : ''}</span></td>
                    <td style={{ whiteSpace: 'nowrap' }}>{r.item}<span className="q">{where(r.screenId)}</span></td>
                    <td>{itemQuote(r)}</td>
                    <td style={{ whiteSpace: 'nowrap' }}>
                      {r.units.map((v) => (
                        <div className="small" key={v.unit.id}><i className={`dot c-${statusClass(v.status)}`} />{v.unit.id}</div>
                      ))}
                    </td>
                    <td><span className={`pill p-${statusClass(r.status)}`}>{r.status}</span></td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        ) : (
          <table className="tr-tbl">
            <thead><tr><th>요구사항 ID</th><th>화면</th><th>요구사항</th><th>구현상태</th><th>관련 코드</th><th>검토사항</th></tr></thead>
            <tbody>
              {unitList.map(({ view: v, group: g }) => {
                const ev = v.result?.evidence ?? []
                return (
                  <tr key={v.unit.id} {...rowProps(() => navigate(cardPath(v.unit.screen_id, v.unit.id)))}>
                    <td style={{ whiteSpace: 'nowrap' }} className="small muted">{v.unit.id}</td>
                    <td style={{ whiteSpace: 'nowrap' }}><b>{g.isApp ? '앱 전체' : g.id}</b><span className="q">{g.isApp ? '' : g.name}</span></td>
                    <td>
                      {cardTitle(v.unit).title}{v.unit.origin === '함의' && <span className="og">함의</span>}
                      <span className="q">{v.unit.source.join(', ')} · {where(v.unit.screen_id)}</span>
                    </td>
                    <td><span className={`pill p-${statusClass(v.status)}`}>{v.status}</span></td>
                    <td>
                      {ev.length ? <>
                        <span className="cref">{ev[0].file.split('/').pop()}:{ev[0].line}</span>
                        {ev.length > 1 && <span className="small faint"> 외 {ev.length - 1}곳</span>}
                        {v.evidenceFailed && <span className="small faint"> (확인 안 됨)</span>}
                        <br />
                        <button type="button" className="linkbtn" disabled={!showCode}
                          onClick={(e) => { e.stopPropagation(); showCode?.({ evidence: ev[0], failed: v.evidenceFailed }) }}
                          onKeyDown={(e) => e.stopPropagation()}>코드 보기</button>
                      </> : <span className="faint">-</span>}
                    </td>
                    <td className="small" style={{ maxWidth: 300 }}>{reviewText(v)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
        {empty && (groupOf.get(screen)?.rejectReason
          ? <div className="empty">이 화면은 반려되어 요구사항을 뽑지 않았습니다. 이유: {groupOf.get(screen)?.rejectReason}</div>
          : <div className="empty">조건에 맞는 요구사항이 없습니다. 필터를 바꿔 보세요.</div>)}
      </section>
      {isItem && (
        <p className="small faint" style={{ margin: '10px 2px' }}>
          같은 기획서 항목에서 나온 요구사항의 판정이 모두 같으면 그 판정, 섞여 있으면 부분구현으로 표시합니다.
          코드와 아직 비교하지 않은(판정 전) 요구사항은 항목 집계에 들어가지 않습니다.
        </p>
      )}
    </div>
  )
}

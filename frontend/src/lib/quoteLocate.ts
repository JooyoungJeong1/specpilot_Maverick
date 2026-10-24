// 원문 찾기 (CLAUDE.md 6장): 단위의 quote가 기획서 페이지 어디에 있는지 찾아 형광펜 사각형을 만든다.
// 대조 기준은 백엔드와 같다.
//   - squash: backend/specpilot/pdf_utils.py (NFKC, 따옴표·보이지 않는 문자·공백 제거)
//   - 조각 나누기: schema._pieces (" / " → 줄임표, 3글자 미만은 뺌)
//   - 같음 / 한두 글자 다름: TextIndex.find, approx_distance, allowed_edits (편집 수 ≤ max(1, round(길이 × 0.12)))
// 백엔드는 여러 읽기 순서(설명표 줄 순서, 그림 영역, pdftotext)를 이어 붙여 찾는다.
// 여기서는 PDF.js 글자 조각을 "파일에 적힌 순서"와 "화면 줄 순서" 두 가지로 이어 찾는다.
import type { Unit } from '../types/requirements.ts'
import { quoteSegments } from './quote.ts'
import { sourceScreenId } from './screenNav.ts'

const QUOTE_CHARS = '"\'`‘’“”「」『』〈〉《》'
const DROP = new Set([...QUOTE_CHARS, '​', '‌', '‍', '﻿'])

/** pdf_utils.squash와 같다 */
export function squash(text: string | null | undefined): string {
  if (!text) return ''
  return [...text.normalize('NFKC')].filter((c) => !DROP.has(c)).join('').replace(/\s+/g, '')
}

/** schema._pieces와 같다: 함의 원문(" / ")과 줄임표로 끊긴 인용을 조각으로, 3글자 미만은 뺀다 */
export function quotePieces(quote: string | null | undefined): string[] {
  return quoteSegments(quote)
    .flatMap((seg) => seg.split(/…|\.\.\.+/))
    .map((p) => p.trim())
    .filter((p) => squash(p).length >= 3)
}

/** pdf_utils.allowed_edits와 같다 */
export function allowedEdits(n: number): number {
  return Math.max(1, Math.round(n * 0.12))
}

/** text 안에서 pattern과 가장 비슷한 부분 (편집 거리가 가장 작은 곳). 없으면 null */
export function approxFind(pattern: string, text: string, limit: number): { start: number; end: number; dist: number } | null {
  const m = pattern.length
  if (!m) return null
  let prev = Array.from({ length: m + 1 }, (_, i) => i)
  let prevStart = new Array<number>(m + 1).fill(0)
  let best: { start: number; end: number; dist: number } | null = null
  for (let j = 1; j <= text.length; j++) {
    const cur = [0]
    const curStart = [j]
    for (let i = 1; i <= m; i++) {
      const sub = prev[i - 1] + (pattern[i - 1] === text[j - 1] ? 0 : 1)
      const del = cur[i - 1] + 1          // 패턴 글자가 빠짐
      const ins = prev[i] + 1             // 원문 글자가 더 있음
      if (sub <= del && sub <= ins) { cur[i] = sub; curStart[i] = prevStart[i - 1] }
      else if (del <= ins) { cur[i] = del; curStart[i] = curStart[i - 1] }
      else { cur[i] = ins; curStart[i] = prevStart[i] }
    }
    if (cur[m] <= limit && (!best || cur[m] < best.dist)) best = { start: curStart[m], end: j, dist: cur[m] }
    prev = cur
    prevStart = curStart
  }
  return best
}

// ---------- 페이지 글자 ----------

/** PDF.js 글자 조각 하나. 좌표는 PDF 쪽 단위(배율 1), y는 위쪽 */
export interface TextItem {
  str: string
  x: number
  y: number
  w: number
  h: number
}

export interface PageText {
  page: number
  width: number
  height: number
  items: TextItem[]
}

/** 형광펜 사각형. 쪽 크기 대비 % */
export interface HighlightRect {
  page: number
  x: number
  y: number
  w: number
  h: number
}

export interface Stream {
  page: PageText
  text: string
  /** text의 글자마다 원래 위치 (조각 번호, 조각 안 글자 번호) */
  map: { item: number; k: number }[]
}

function streamFrom(page: PageText, order: number[]): Stream {
  let text = ''
  const map: Stream['map'] = []
  for (const idx of order) {
    const chars = [...page.items[idx].str]
    chars.forEach((c, k) => {
      for (const s of squash(c)) {
        text += s
        map.push({ item: idx, k })
      }
    })
  }
  return { page, text, map }
}

/** 화면 줄 순서: 위에서 아래로 줄을 묶고, 줄 안에서는 왼쪽부터 */
function visualOrder(items: TextItem[]): number[] {
  const idx = items.map((_, i) => i).sort((a, b) => items[a].y - items[b].y || items[a].x - items[b].x)
  const lines: number[][] = []
  for (const i of idx) {
    const line = lines.at(-1)
    const ref = line && items[line[0]]
    if (ref && Math.abs(items[i].y - ref.y) < Math.min(ref.h, items[i].h) * 0.5) line.push(i)
    else lines.push([i])
  }
  return lines.flatMap((l) => l.sort((a, b) => items[a].x - items[b].x))
}

export function buildStreams(pages: PageText[]): Stream[] {
  return pages.flatMap((p) => {
    const stream = p.items.map((_, i) => i)
    return [streamFrom(p, stream), streamFrom(p, visualOrder(p.items))]
  })
}

/** 찾은 글자들을 조각별 구간으로 묶고, 같은 줄에 붙어 있는 구간은 하나로 합친다 */
function rectsFor(s: Stream, start: number, end: number): HighlightRect[] {
  const spans = new Map<number, { k0: number; k1: number }>()
  for (const { item, k } of s.map.slice(start, end)) {
    const sp = spans.get(item)
    if (sp) { sp.k0 = Math.min(sp.k0, k); sp.k1 = Math.max(sp.k1, k) }
    else spans.set(item, { k0: k, k1: k })
  }
  const boxes = [...spans].map(([i, { k0, k1 }]) => {
    const it = s.page.items[i]
    const n = Math.max(1, [...it.str].length)
    return { x0: it.x + (it.w * k0) / n, x1: it.x + (it.w * (k1 + 1)) / n, y: it.y, h: it.h }
  }).sort((a, b) => a.y - b.y || a.x0 - b.x0)

  const merged: typeof boxes = []
  for (const b of boxes) {
    const last = merged.at(-1)
    if (last && Math.abs(b.y - last.y) < Math.min(b.h, last.h) * 0.5 && b.x0 - last.x1 < Math.max(b.h, last.h) * 2) {
      last.x0 = Math.min(last.x0, b.x0)
      last.x1 = Math.max(last.x1, b.x1)
      last.y = Math.min(last.y, b.y)
      last.h = Math.max(last.h, b.h)
    } else merged.push({ ...b })
  }
  const { width, height, page } = s.page
  return merged.map((b) => ({
    page,
    x: (b.x0 / width) * 100,
    y: (b.y / height) * 100,
    w: ((b.x1 - b.x0) / width) * 100,
    h: (b.h / height) * 100,
  }))
}

/** 조각 하나 찾기: 그대로 있는 곳을 먼저, 없으면 한두 글자 다른 곳 */
export function findPiece(piece: string, streams: Stream[]): { rects: HighlightRect[]; approx: boolean } | null {
  const s = squash(piece)
  for (const st of streams) {
    const at = st.text.indexOf(s)
    if (at >= 0) return { rects: rectsFor(st, at, at + s.length), approx: false }
  }
  const limit = allowedEdits(s.length)
  let best: { st: Stream; start: number; end: number; dist: number } | null = null
  for (const st of streams) {
    const r = approxFind(s, st.text, limit)
    if (r && (!best || r.dist < best.dist)) best = { st, ...r }
  }
  return best ? { rects: rectsFor(best.st, best.start, best.end), approx: true } : null
}

// ---------- 단위 하나 ----------

export type LocateStatus =
  /** 원문을 모두 그대로 찾음 */
  | 'found'
  /** 모두 찾았지만 한두 글자 다른 곳이 있음 */
  | 'approx'
  /** 원문 일부만 찾음 */
  | 'partial'
  /** 못 찾음 */
  | 'none'
  /** 그림이 근거라 찾지 않음 */
  | 'skipped'

export interface LocateResult {
  status: LocateStatus
  rects: HighlightRect[]
  /** 못 찾았거나 찾지 않은 이유 (화면 문구) */
  reason: string | null
}

const IMAGE_SOURCE = /이미지|그림/

/** streams: 같은 화면의 여러 단위를 찾을 때 한 번 만든 것을 넘기면 페이지 글자를 다시 정리하지 않는다 */
export function locateUnit(unit: Pick<Unit, 'screen_id' | 'source' | 'quote'>, pages: PageText[], streams?: Stream[]): LocateResult {
  const sources = unit.source ?? []
  if (sources.length && sources.every((s) => IMAGE_SOURCE.test(s))) {
    return { status: 'skipped', rects: [], reason: '그림이 근거라 위치를 찾지 않음' }
  }
  const pieces = quotePieces(unit.quote)
  if (!pieces.length) return { status: 'none', rects: [], reason: '원문이 비어 있음' }

  const all = streams ?? buildStreams(pages)
  const hits = pieces.map((p) => findPiece(p, all))
  const found = hits.filter((h): h is NonNullable<typeof h> => !!h)
  const rects = found.flatMap((h) => h.rects)
  if (found.length === pieces.length) return { status: found.some((h) => h.approx) ? 'approx' : 'found', rects, reason: null }

  const otherScreen = sources.some((s) => {
    const sid = sourceScreenId(s)
    return sid !== null && sid !== unit.screen_id
  })
  const reason = otherScreen ? '다른 화면의 원문을 근거로 함'
    : sources.some((s) => IMAGE_SOURCE.test(s)) ? '그림이 근거인 부분이 있음'
      : '이 화면 페이지의 글자에서 원문을 찾지 못함'
  return { status: found.length ? 'partial' : 'none', rects, reason }
}

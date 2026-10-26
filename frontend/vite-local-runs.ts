// 결과 파일 서버 (Vite 미들웨어). 새 분석(업로드·진행)은 backend의 시연 서버(/api, vite.config.ts)가 맡는다.
//
//   GET /data/runs                          실행 목록 (최근 것이 먼저). backend/output/과 local/runs/에 결과 폴더가 있으면
//                                           그것만, 없으면 mock/. 조장 PC에서는 backend/output을 바로 읽어 복사할 필요가 없다
//   GET /data/runs/<실행ID>/files/<경로>      결과 폴더의 파일 (requirements.json, input.pdf …)
//   GET /data/runs/<실행ID>/code?file=&line=&around=   근거 코드 앞뒤 줄
//
// 코드 위치는 codeRoot() 참고 (실제: ③을 돌린 코드 폴더 또는 local/code/<샘플코드>/, mock: mock/code/).
// 올린 파일 폴더(backend/output/_uploads)는 실행 목록에 넣지 않는다.
// 정답 세트·채점 결과(블라인드)는 내려 주지 않는다.
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Connect, Plugin } from 'vite'

const ROOT = path.dirname(fileURLToPath(import.meta.url))
const LOCAL_RUNS = path.join(ROOT, 'local', 'runs')
const BACKEND_RUNS = path.join(ROOT, '..', 'backend', 'output')
const MOCK_RUNS = path.join(ROOT, 'mock')
const LOCAL_CODE = path.join(ROOT, 'local', 'code')
const MOCK_CODE = path.join(MOCK_RUNS, 'code')
const RUN_ID = /^[\w.-]+$/
const BLOCKED = /^(score_report\.json|score_review\.md|answer_key.*\.json)$/i
const TYPES: Record<string, string> = {
  '.json': 'application/json; charset=utf-8',
  '.pdf': 'application/pdf',
  '.md': 'text/markdown; charset=utf-8',
  '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
}

interface RunEntry { id: string; source: 'local' | 'mock'; dir: string }

function runsIn(base: string, source: RunEntry['source']): RunEntry[] {
  if (!fs.existsSync(base)) return []
  return fs.readdirSync(base, { withFileTypes: true })
    .filter((d) => d.isDirectory() && RUN_ID.test(d.name) && !d.name.startsWith('_')
      && fs.existsSync(path.join(base, d.name, 'requirements.json')))
    .map((d) => ({ id: d.name, source, dir: path.join(base, d.name) }))
}

/** requirements.json을 만든 때 (최신이 먼저 오게). 실행 ID는 날짜가 아닐 수도 있다 (full1 등) */
function modified(run: RunEntry): number {
  try {
    return fs.statSync(path.join(run.dir, 'requirements.json')).mtimeMs
  } catch {
    return 0
  }
}

function listRuns(): RunEntry[] {
  const seen = new Set<string>()
  const local = [...runsIn(LOCAL_RUNS, 'local'), ...runsIn(BACKEND_RUNS, 'local')]
    .filter((r) => !seen.has(r.id) && seen.add(r.id))   // 같은 ID면 local/runs 것을 쓴다
    .sort((a, b) => modified(b) - modified(a))
  return local.length ? local : runsIn(MOCK_RUNS, 'mock').sort((a, b) => b.id.localeCompare(a.id))
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- 결과 파일 모양을 하나하나 확인하며 읽는다
function readJson(file: string): Record<string, any> | null {
  try {
    return JSON.parse(fs.readFileSync(file, 'utf-8'))
  } catch {
    return null
  }
}

/** 최근 분석 목록에 쓸 요약. 결과 파일이 깨져 있어도 목록은 보여 준다. */
function runSummary(run: RunEntry) {
  const req = readJson(path.join(run.dir, 'requirements.json'))
  const report = readJson(path.join(run.dir, 'judge_report.json'))
  const job = readJson(path.join(run.dir, 'job.json'))           // 웹에서 올려 돌린 실행 (시연 서버가 씀)
  return {
    id: run.id,
    source: run.source,
    name: typeof job?.name === 'string' && job.name ? job.name : null,
    screens: Array.isArray(req?.app_profile?.screens) ? req.app_profile.screens.length : 0,
    units: Array.isArray(req?.units) ? req.units.length : 0,
    mergedAt: typeof req?.meta?.merged_at === 'string' ? req.meta.merged_at : null,
    byStatus: report?.summary?.by_status ?? null,
    notJudged: typeof report?.summary?.units_not_judged === 'number' ? report.summary.units_not_judged : null,
  }
}

/** base 안의 경로만 허용한다 (../ 막기) */
function inside(base: string, rel: string): string | null {
  const p = path.resolve(base, rel)
  return p === base || p.startsWith(base + path.sep) ? p : null
}

function dirs(base: string): string[] {
  return fs.existsSync(base) ? fs.readdirSync(base, { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name) : []
}

/** judge/run.json의 code_root. 파일이 없거나 깨져 있으면 undefined (코드 보기만 못 할 뿐 나머지는 동작해야 한다) */
function readCodeRoot(meta: string): string | undefined {
  try {
    const v = JSON.parse(fs.readFileSync(meta, 'utf-8')).code_root
    return typeof v === 'string' ? v : undefined
  } catch {
    return undefined
  }
}

/**
 * 근거 코드를 읽을 폴더.
 * judge/run.json의 code_root는 ③을 돌린 PC의 경로다. 그 PC(조장 PC, 웹에서 올려 돌린 실행)에서는 그대로 쓰고,
 * 다른 PC에서는 받은 샘플 코드를 local/code/<폴더>/에 둔다.
 *   mock: mock/code/
 *   실제: code_root가 이 PC에 있으면 그것 → local/code/<code_root의 마지막 폴더 이름>/
 *         → local/code/에 폴더가 하나뿐이면 그것 → <결과 폴더>/code/
 */
function codeRoot(run: RunEntry): string | null {
  if (run.source === 'mock') return fs.existsSync(MOCK_CODE) ? MOCK_CODE : null
  const root = readCodeRoot(path.join(run.dir, 'judge', 'run.json'))
  if (root && fs.existsSync(root)) return root
  const name = root?.split(/[\\/]/).filter(Boolean).pop()
  const local = dirs(LOCAL_CODE)
  if (name && local.includes(name)) return path.join(LOCAL_CODE, name)
  if (local.length === 1) return path.join(LOCAL_CODE, local[0])
  const own = path.join(run.dir, 'code')
  return fs.existsSync(own) ? own : null
}

function send(res: Parameters<Connect.NextHandleFunction>[1], status: number, body: unknown) {
  res.statusCode = status
  res.setHeader('Content-Type', TYPES['.json'])
  res.end(JSON.stringify(body))
}

const handler: Connect.NextHandleFunction = (req, res, next) => {
  const url = new URL(req.url ?? '/', 'http://localhost')
  if (!url.pathname.startsWith('/data/')) return next()
  const parts = url.pathname.slice('/data/'.length).split('/').map(decodeURIComponent)
  if (parts[0] !== 'runs') return send(res, 404, { error: 'not found' })

  const runs = listRuns()
  if (parts.length === 1) return send(res, 200, runs.map(runSummary))

  const run = runs.find((x) => x.id === parts[1])
  if (!run) return send(res, 404, { error: `실행 결과가 없습니다: ${parts[1]}` })

  if (parts[2] === 'files') {
    const rel = parts.slice(3).join('/')
    const file = inside(run.dir, rel)
    if (!file || BLOCKED.test(path.basename(file))) return send(res, 403, { error: '읽을 수 없는 파일입니다' })
    if (!fs.existsSync(file) || !fs.statSync(file).isFile()) return send(res, 404, { error: `파일이 없습니다: ${rel}` })
    res.statusCode = 200
    res.setHeader('Content-Type', TYPES[path.extname(file).toLowerCase()] ?? 'application/octet-stream')
    if (req.method === 'HEAD') return res.end()
    return fs.createReadStream(file).pipe(res)
  }

  if (parts[2] === 'code') {
    const root = codeRoot(run)
    const rel = url.searchParams.get('file') ?? ''
    const line = Number(url.searchParams.get('line'))
    const around = Math.min(Number(url.searchParams.get('around') ?? 5), 50)
    const file = root && inside(root, rel)
    if (!file || !fs.existsSync(file) || !fs.statSync(file).isFile()) return send(res, 404, { error: '코드 폴더나 파일이 없습니다' })
    const lines = fs.readFileSync(file, 'utf-8').split(/\r?\n/)
    const start = Math.max(1, line - around)
    const end = Math.min(lines.length, line + around)
    return send(res, 200, { file: rel, line, start, lines: lines.slice(start - 1, end) })
  }

  return send(res, 404, { error: 'not found' })
}

export default function localRuns(): Plugin {
  return {
    name: 'specpilot-local-runs',
    configureServer(server) { server.middlewares.use(handler) },
    configurePreviewServer(server) { server.middlewares.use(handler) },
  }
}

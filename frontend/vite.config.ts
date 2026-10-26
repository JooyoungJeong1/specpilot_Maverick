import net from 'node:net'
import react from '@vitejs/plugin-react'
import { defineConfig, type ProxyOptions } from 'vite'
import localRuns from './vite-local-runs.ts'

// 새 분석(업로드·진행)은 backend의 시연 서버로 넘긴다: cd backend && python -m specpilot serve
// 포트는 serve의 --port(기본 8765)와 같아야 한다.
const API_SERVER = { host: '127.0.0.1', port: 8765 }

/** 시연 서버가 켜져 있는지 (포트에 붙어 본다) */
function apiServerUp(): Promise<boolean> {
  return new Promise((resolve) => {
    const socket = net.connect(API_SERVER)
    const done = (up: boolean) => { socket.destroy(); resolve(up) }
    socket.setTimeout(500, () => done(false))
    socket.once('connect', () => done(true))
    socket.once('error', () => done(false))
  })
}

// 서버가 꺼져 있으면 넘기지 않고 404로 답한다. 웹은 그걸 보고 mock으로 흉내 내고(src/api/api.ts),
// 터미널에 프록시 오류가 쌓이지 않는다.
const api: ProxyOptions = {
  target: `http://${API_SERVER.host}:${API_SERVER.port}`,
  bypass: async () => ((await apiServerUp()) ? undefined : false),
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), localRuns()],
  server: { proxy: { '/api': api } },
  preview: { proxy: { '/api': api } },
})

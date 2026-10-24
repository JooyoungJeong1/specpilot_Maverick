import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'
import localRuns from './vite-local-runs.ts'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), localRuns()],
})

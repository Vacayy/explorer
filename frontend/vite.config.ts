import path from "path"
import { defineConfig, loadEnv } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), 'VITE_')
  const accessMode = process.env.VITE_ACCESS_MODE ?? env.VITE_ACCESS_MODE ?? 'private'
  const apiBase = process.env.VITE_API_BASE ?? env.VITE_API_BASE ?? 'http://localhost:8000'
  if (!['private', 'public'].includes(accessMode)) throw new Error('Invalid VITE_ACCESS_MODE')
  if (accessMode === 'public' && !['', '/'].includes(apiBase)) {
    throw new Error('Public frontend requires a same-origin VITE_API_BASE')
  }
  return {
  define: {
    'import.meta.env.VITE_ACCESS_MODE': JSON.stringify(accessMode),
    'import.meta.env.VITE_API_BASE': JSON.stringify(apiBase),
  },
  // 5173은 다른 프로젝트가 쓴다(사용자 요청 2026-08-25). strictPort=포트가 점유돼 있으면
  // 조용히 다른 포트로 옮겨가지 않고 실패한다 — 백엔드 CORS 허용 목록과 어긋나면 API가 전부 막히므로
  // 조용한 폴백보다 즉시 실패가 낫다.
  server: { port: Number(process.env.VITE_PORT ?? 5174), strictPort: true },
  plugins: [react(), tailwindcss(), {
    name: 'explorer-build-mode',
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: '_explorer/build.json',
        source: JSON.stringify({ version: 1, access_mode: accessMode, api_base: apiBase }) + '\n' })
    },
  }],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  }
})

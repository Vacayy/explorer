import path from "path"
import { defineConfig } from "vite"
import react from "@vitejs/plugin-react"
import tailwindcss from "@tailwindcss/vite"

export default defineConfig({
  // 5173은 다른 프로젝트가 쓴다(사용자 요청 2026-08-25). strictPort=포트가 점유돼 있으면
  // 조용히 다른 포트로 옮겨가지 않고 실패한다 — 백엔드 CORS 허용 목록과 어긋나면 API가 전부 막히므로
  // 조용한 폴백보다 즉시 실패가 낫다.
  server: { port: 5174, strictPort: true },
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
})

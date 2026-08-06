import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// O build sai direto para dentro do pacote Python, servido em `/static/` pelo
// FastAPI. Quem serve é o Python, não o Node: depois de compilado, a PoC roda
// sem rede e sem processo de Node — mesma promessa do resto do projeto.
export default defineConfig({
  plugins: [react()],
  base: process.env.VITE_BASE || "/static/",
  build: {
    outDir: process.env.VITE_OUT_DIR || "../src/retrieval_poc/web/static",
    emptyOutDir: process.env.VITE_EMPTY_OUT_DIR !== "0",
  },
  server: {
    port: 5175, // 5173 é o deck open-slide, 5174 o front da PoC de imagens
    // `pnpm dev` só serve para iterar no layout; a API continua vindo do backend.
    proxy: { "/api": "http://127.0.0.1:8081" },
  },
});

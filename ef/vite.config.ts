import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5180,
    proxy: {
      // Dev: proxy AI calls to the MeshNet orchestrator so the browser stays same-origin.
      "/api": {
        target: process.env.VITE_MESH_API_BASE ?? "https://api.beta.meshnet.co",
        changeOrigin: true,
      },
    },
  },
  build: { outDir: "dist", sourcemap: false },
});

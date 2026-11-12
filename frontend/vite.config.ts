import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// In development the React app runs on Vite (port 5173) and forwards API calls
// to FastAPI. In production FastAPI serves the built app itself (one service).
const apiTarget = process.env.VITE_API_TARGET ?? "http://127.0.0.1:8001";
const apiPaths = ["/ask", "/extract", "/risk-check", "/stats", "/sources", "/health"];

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: Object.fromEntries(apiPaths.map((path) => [path, { target: apiTarget, changeOrigin: true }])),
  },
});

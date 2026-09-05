import path from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 3000,
    proxy: {
      "/api/society": {
        target: "http://127.0.0.1:18790",
        changeOrigin: true,
        configure: (proxy) =>
          proxy.on("proxyReq", (request) => {
            request.removeHeader("origin");
          }),
      },
    },
  },
});

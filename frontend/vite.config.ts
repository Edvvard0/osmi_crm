/// <reference types="vitest" />
import react from "@vitejs/plugin-react";
import path from "node:path";
import { defineConfig } from "vite";
import { VitePWA } from "vite-plugin-pwa";

import {
  API_CACHE_MAX_AGE_SECONDS,
  API_CACHE_MAX_ENTRIES,
  API_CACHE_NAME,
  API_CACHE_TIMEOUT_SECONDS,
  apiCacheUrlPattern,
} from "./src/shared/lib/apiCachePolicy";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      // «prompt»: новая версия не подменяет приложение молча — клиент показывает плашку C-05 «Доступна новая версия».
      registerType: "prompt",
      includeAssets: ["icon.svg", "offline.html", "offline.css", "apple-touch-icon.png"],
      manifest: {
        id: "/",
        name: "CRM Автосервис",
        short_name: "CRM",
        description: "Учёт заказ-нарядов, записей и склада автосервиса",
        lang: "ru",
        start_url: "/",
        scope: "/",
        display: "standalone",
        background_color: "#f8f9fa",
        theme_color: "#ffffff",
        icons: [
          { src: "icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
          { src: "icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
          { src: "icon-512-maskable.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
        ],
      },
      workbox: {
        // Оболочка приложения (HTML/JS/CSS/иконки) кладётся в precache при установке.
        globPatterns: ["**/*.{js,css,html,svg,png,ico,woff2}"],
        navigateFallback: "/index.html",
        // /api/ никогда не отдаётся как SPA-страница.
        navigateFallbackDenylist: [/^\/api\//],
        cleanupOutdatedCaches: true,
        clientsClaim: true,
        // skipWaiting не включаем: обновление применяет пользователь через плашку C-05.
        runtimeCaching: [
          {
            // Только белый список безопасных GET-эндпоинтов (см. docs/api-contract-m12.md); остальное — только сеть.
            urlPattern: apiCacheUrlPattern(),
            method: "GET",
            handler: "NetworkFirst",
            options: {
              cacheName: API_CACHE_NAME,
              networkTimeoutSeconds: API_CACHE_TIMEOUT_SECONDS,
              expiration: { maxEntries: API_CACHE_MAX_ENTRIES, maxAgeSeconds: API_CACHE_MAX_AGE_SECONDS },
              // Кэшируем только 200 (без opaque-ответов и ошибок).
              cacheableResponse: { statuses: [200] },
              plugins: [
                {
                  // Помечаем ответ из кэша, чтобы клиент показал «Показаны данные на HH:MM». Тело функции без замыканий.
                  cachedResponseWillBeUsed: async ({ cachedResponse }: { cachedResponse?: Response }) => {
                    if (!cachedResponse) return cachedResponse;
                    const headers = new Headers(cachedResponse.headers);
                    headers.set("X-From-Cache", "1");
                    return new Response(cachedResponse.body, {
                      status: cachedResponse.status,
                      statusText: cachedResponse.statusText,
                      headers,
                    });
                  },
                },
              ],
            },
          },
        ],
      },
    }),
  ],
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  build: { sourcemap: false },
  esbuild: process.env.NODE_ENV === "production" ? { drop: ["console", "debugger"] } : {},
  server: { host: true, port: 5173, proxy: { "/api": process.env.API_PROXY ?? "http://localhost:8000" } },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    alias: { "virtual:pwa-register": path.resolve(__dirname, "src/test/pwaRegisterStub.ts") },
    coverage: { provider: "v8", include: ["src/**"], thresholds: { lines: 70 } },
  },
});

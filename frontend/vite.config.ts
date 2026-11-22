import { defineConfig, type ProxyOptions } from 'vite';
import preact from '@preact/preset-vite';
import tailwindcss from '@tailwindcss/vite';
import { VitePWA } from 'vite-plugin-pwa';

// FastAPI serves the built app and the API from one origin. In dev, Vite
// forwards these prefixes to the API so cookies and paths behave the same.
const API_ORIGIN = (globalThis as { process?: { env: Record<string, string | undefined> } }).process?.env['RAHAT_API_ORIGIN'] ?? 'http://127.0.0.1:8000';
const SERVER_PREFIXES = ['/v1', '/healthz', '/readyz', '/metrics', '/docs', '/redoc', '/openapi.json', '/mock'];
const proxy: Record<string, ProxyOptions> = Object.fromEntries(
  SERVER_PREFIXES.map((prefix) => [prefix, { target: API_ORIGIN, changeOrigin: false }]),
);

// Navigations to these paths must reach the server, never the SPA shell.
const NAVIGATE_FALLBACK_DENYLIST = [
  /^\/v1(?:\/|$)/,
  /^\/docs(?:\/|$)/,
  /^\/redoc(?:\/|$)/,
  /^\/openapi\.json$/,
  /^\/healthz$/,
  /^\/readyz$/,
  /^\/metrics$/,
  /^\/mock(?:\/|$)/,
  /^\/demo-cards\//, // opening a test card in a new tab must show the image, not the app
];

// `npm run preview` sends the same strict policy the server sends in production
// (no 'unsafe-inline'), so a CSP violation shows up locally first. Not used by
// `npm run dev`, where Vite injects styles inline for hot reload.
const PREVIEW_CSP = [
  "default-src 'self'",
  "script-src 'self'",
  "style-src 'self'",
  "img-src 'self' data: blob:",
  "media-src 'self'",
  "connect-src 'self'",
  "worker-src 'self'",
  "manifest-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join('; ');

// The server answers a missing file with the app shell (index.html, 200). A
// runtime cache must keep only real files, so the content type is checked too.
// These functions are copied into sw.js as source text: no outside variables.
const KEEP_JSON = {
  cacheWillUpdate: async ({ response }: { response: Response }) =>
    response.status === 200 && (response.headers.get('content-type') ?? '').startsWith('application/json') ? response : null,
};
const KEEP_AUDIO = {
  cacheWillUpdate: async ({ response }: { response: Response }) =>
    response.status === 200 && (response.headers.get('content-type') ?? '').startsWith('audio/') ? response : null,
};


// The staff console is split per page so /staff paints the shell and one page, not all 30. Only the shell and its shared
// kit are a manual chunk ('staff'); each page is a dynamic import (src/staff/lazyPages.tsx) that Rollup splits itself, which
// keeps code shared with the citizen app in the citizen entry. Chunks made only of staff modules are named staff-* below, so
// check:bundle counts them as excluded and the service worker never precaches them (globIgnores).
const STAFF_CORE = ['StaffApp', 'StaffShell', 'StaffLogin', 'theme', 'nav', 'NavIcons', 'Palette', 'Pulse', 'ui', 'kit', 'loadview', 'viz', 'InfoTip', 'SectionTabs', 'lazyPages', 'Rise', 'phone', 'wpe', 'calm', 'shell', 'staff', 'PlaceholderPage'];
function staffChunk(path: string): string | undefined {
  const m = /\/src\/staff\/([A-Za-z]+)\.(?:tsx?|css)$/.exec(path);
  return m && STAFF_CORE.includes(m[1] as string) ? 'staff' : undefined;
}

export default defineConfig({
  plugins: [
    preact(),
    tailwindcss(),
    VitePWA({
      strategies: 'generateSW',
      registerType: 'autoUpdate',
      // Registered from bundled code (src/main.tsx) so the page needs no inline script.
      injectRegister: false,
      // globPatterns below already precaches the icons; avoid duplicate entries.
      includeManifestIcons: false,
      manifest: {
        id: '/',
        name: 'Rahat (Prototype)',
        short_name: 'Rahat',
        description:
          'Prototype relief program. Not an official service. All identity, payment and data services are simulated.',
        lang: 'en',
        dir: 'ltr',
        start_url: '/',
        scope: '/',
        display: 'standalone',
        background_color: '#0b1026',
        theme_color: '#0b1026',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
          { src: '/favicon.svg', sizes: 'any', type: 'image/svg+xml', purpose: 'any' },
        ],
      },
      workbox: {
        // App shell only, plus the silent clip that unlocks audio. Staff and demo
        // chunks load from the network so a citizen on a weak connection never
        // downloads them. The voice prompts are cached at runtime (below).
        globPatterns: ['**/*.{js,css,html,svg,png}', 'audio/silence.mp3'], // the plugin adds manifest.webmanifest itself
        globIgnores: ['**/assets/staff-*.js', '**/assets/demo-*.js', '**/assets/live-*.js', '**/assets/ussd-*.{js,css}', 'audio/**/*.json', 'demo-cards/**'],
        navigateFallback: '/index.html',
        navigateFallbackDenylist: NAVIGATE_FALLBACK_DENYLIST,
        // A stale service worker during the live demo would be a disaster.
        clientsClaim: true,
        skipWaiting: true,
        cleanupOutdatedCaches: true,
        // Runtime caching for /audio/ only. API responses are never cached: no
        // other route is registered, so every /v1 request goes to the network.
        runtimeCaching: [
          {
            // The list of recordings changes with each deploy: network first.
            urlPattern: ({ url, sameOrigin }) => sameOrigin && /^\/audio\/[a-z]{2}\/index\.json$/.test(url.pathname),
            handler: 'NetworkFirst',
            options: {
              cacheName: 'rahat-audio-index',
              networkTimeoutSeconds: 4,
              plugins: [KEEP_JSON],
            },
          },
          {
            // Fixed voice prompts: cache first. The page warms the chosen language
            // with plain fetches (full 200 responses); range requests from <audio>
            // are then answered from the cached copy.
            urlPattern: ({ url, sameOrigin }) => sameOrigin && /^\/audio\/[a-z]{2}\/[\w.-]+\.mp3$/.test(url.pathname),
            handler: 'CacheFirst',
            options: {
              cacheName: 'rahat-audio',
              rangeRequests: true,
              plugins: [KEEP_AUDIO],
              expiration: { maxEntries: 600, purgeOnQuotaError: true },
            },
          },
        ],
        maximumFileSizeToCacheInBytes: 2 * 1024 * 1024,
      },
      devOptions: { enabled: false },
    }),
  ],
  server: {
    port: 5173,
    proxy,
  },
  preview: {
    port: 4173,
    proxy,
    headers: { 'Content-Security-Policy': PREVIEW_CSP },
  },
  build: {
    manifest: true,
    rollupOptions: {
      output: {
        // Without this, Rollup pulls every unassigned dependency of a manual chunk
        // (preact, src/shared) into it, and the citizen entry then imports the
        // staff chunk statically. check:bundle fails the build if that happens.
        onlyExplicitManualChunks: true,
        chunkFileNames: (chunk: { moduleIds: string[]; name: string }) =>
          !/^(staff|demo)$/.test(chunk.name) && chunk.moduleIds.length > 0 && chunk.moduleIds.every((id) => id.replaceAll('\\', '/').includes('/src/staff/')) ? 'assets/staff-[name]-[hash].js' : 'assets/[name]-[hash].js',
        manualChunks(id) {
          const path = id.replace(/\\/g, '/');
          if (path.includes('/src/staff/demo/')) return 'demo';
          if (path.includes('/src/staff/')) return staffChunk(path);
          // /live: the page and its HUD in 'live'; three.js and the scene in 'live-three', fetched only when WebGL will run.
          if (path.includes('/node_modules/three/') || path.includes('/src/live/scene')) return 'live-three';
          if (path.includes('/src/live/')) return 'live';
          // /ussd: the feature-phone simulator, a lazy chunk the citizen app never loads.
          if (path.includes('/src/ussd/')) return 'ussd';
          return undefined;
        },
      },
    },
  },
});

/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

interface ImportMetaEnv {
  /** Set to "false" at build time to hide staff pages that are still dev placeholders. */
  readonly VITE_SHOW_UNBUILT?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

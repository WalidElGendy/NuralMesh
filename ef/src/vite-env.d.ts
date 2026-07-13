/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string;
  readonly VITE_SUPABASE_ANON_KEY: string;
  readonly VITE_MESH_API_BASE: string;
  readonly VITE_SENTINEL_HUB_INSTANCE_ID?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}

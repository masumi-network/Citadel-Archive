export interface CitadelPluginSettings {
  baseUrl: string;
  tokenSecretName: string;
  vaultId: string;
  vaultName: string;
  teamId: string;
  defaultDataset: string;
  syncFolder: string;
}

export interface CitadelSession {
  ok: boolean;
  role: "reader" | "writer" | "admin";
  capabilities: {
    read: boolean;
    write: boolean;
    admin: boolean;
  };
}

export interface CitadelVault {
  id: string;
  name: string;
  team_id: string | null;
  plugin_version: string | null;
}

export interface CitadelSearchResponse {
  results: unknown[];
}

export interface CitadelPushDocument {
  path: string;
  content: string;
  base_rev?: number | null;
  deleted?: boolean;
  tags?: string[];
  dataset?: string | null;
}

export interface CitadelPushResponse {
  ok: boolean;
  accepted: Array<{
    document_id: string;
    path: string;
    rev: number;
    content_hash: string;
    deleted: boolean;
  }>;
  skipped: unknown[];
  conflicts: unknown[];
  ingest_results: unknown[];
}

export const DEFAULT_SETTINGS: CitadelPluginSettings = {
  baseUrl: "http://localhost:8000",
  tokenSecretName: "",
  vaultId: "",
  vaultName: "",
  teamId: "",
  defaultDataset: "",
  syncFolder: "",
};

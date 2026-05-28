import { requestUrl } from "obsidian";

import type {
  CitadelPluginSettings,
  CitadelPushDocument,
  CitadelPushResponse,
  CitadelSearchResponse,
  CitadelSession,
  CitadelVault,
} from "./types";

export class CitadelClient {
  constructor(
    private readonly settings: CitadelPluginSettings,
    private readonly getToken: () => Promise<string>,
  ) {}

  async session(): Promise<CitadelSession> {
    return this.request<CitadelSession>("/api/session");
  }

  async search(query: string): Promise<CitadelSearchResponse> {
    return this.request<CitadelSearchResponse>("/search", {
      method: "POST",
      body: {
        query,
        dataset: this.settings.defaultDataset || null,
      },
    });
  }

  async registerVault(): Promise<CitadelVault> {
    const response = await this.request<{ vault: CitadelVault }>("/api/obsidian/vaults", {
      method: "POST",
      body: {
        vault_name: this.settings.vaultName,
        team_id: this.settings.teamId || null,
        plugin_version: "0.1.0",
      },
    });
    return response.vault;
  }

  async pushDocuments(vaultId: string, documents: CitadelPushDocument[]): Promise<CitadelPushResponse> {
    return this.request<CitadelPushResponse>("/api/obsidian/sync/push", {
      method: "POST",
      body: {
        vault_id: vaultId,
        dataset: this.settings.defaultDataset || null,
        documents,
      },
    });
  }

  private async request<T>(
    path: string,
    options: { method?: string; body?: unknown } = {},
  ): Promise<T> {
    const baseUrl = this.settings.baseUrl.replace(/\/$/, "");
    const token = await this.getToken();
    const response = await requestUrl({
      url: `${baseUrl}${path}`,
      method: options.method || "GET",
      headers: {
        Authorization: `Bearer ${token}`,
        "Content-Type": "application/json",
      },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      throw: false,
    });
    const payload = response.text ? JSON.parse(response.text) : {};
    if (response.status < 200 || response.status >= 300) {
      throw new Error(payload.detail || payload.message || `Citadel request failed: ${response.status}`);
    }
    return payload as T;
  }
}

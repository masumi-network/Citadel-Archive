import type { App } from "obsidian";

import type { CitadelPluginSettings } from "./types";

export async function getCitadelToken(app: App, settings: CitadelPluginSettings): Promise<string> {
  if (!settings.tokenSecretName) {
    throw new Error("Select a Citadel token secret in plugin settings.");
  }
  const token = app.secretStorage.getSecret(settings.tokenSecretName);
  if (!token) {
    throw new Error("Citadel token secret is empty.");
  }
  return token;
}

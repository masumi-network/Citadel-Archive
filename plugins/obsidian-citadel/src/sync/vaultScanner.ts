import type { App, TFile } from "obsidian";

export function markdownFilesInScope(app: App, folder: string): TFile[] {
  const prefix = folder.trim().replace(/^\/|\/$/g, "");
  return app.vault
    .getMarkdownFiles()
    .filter((file) => !prefix || file.path === prefix || file.path.startsWith(`${prefix}/`));
}

import type { App, TFile } from "obsidian";

export function readCitadelRev(app: App, file: TFile): number | null {
  const value = app.metadataCache.getFileCache(file)?.frontmatter?.citadel_rev;
  const parsed = typeof value === "number" ? value : Number.parseInt(String(value || ""), 10);
  return Number.isFinite(parsed) ? parsed : null;
}

export async function writeCitadelFrontmatter(
  app: App,
  file: TFile,
  metadata: { documentId: string; rev: number; source: string },
): Promise<void> {
  await app.fileManager.processFrontMatter(file, (frontmatter) => {
    frontmatter.citadel_id = metadata.documentId;
    frontmatter.citadel_rev = metadata.rev;
    frontmatter.citadel_source = metadata.source;
  });
}

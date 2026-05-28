import { Notice, TFile } from "obsidian";

import type CitadelPlugin from "../main";
import type { CitadelPushDocument } from "../types";
import { readCitadelRev, writeCitadelFrontmatter } from "./frontmatter";
import { markdownFilesInScope } from "./vaultScanner";

export class SyncEngine {
  constructor(private readonly plugin: CitadelPlugin) {}

  async ensureVault(): Promise<string> {
    if (this.plugin.settings.vaultId) {
      return this.plugin.settings.vaultId;
    }
    const vault = await this.plugin.client.registerVault();
    this.plugin.settings.vaultId = vault.id;
    await this.plugin.saveSettings();
    return vault.id;
  }

  async pushFile(file: TFile): Promise<void> {
    const vaultId = await this.ensureVault();
    const content = await this.plugin.app.vault.cachedRead(file);
    const baseRev = readCitadelRev(this.plugin.app, file);
    const response = await this.plugin.client.pushDocuments(vaultId, [
      {
        path: file.path,
        content,
        base_rev: baseRev,
      },
    ]);
    if (response.conflicts.length) {
      new Notice("Citadel conflict created for this note.");
      return;
    }
    const accepted = response.accepted[0];
    if (accepted) {
      await writeCitadelFrontmatter(this.plugin.app, file, {
        documentId: accepted.document_id,
        rev: accepted.rev,
        source: vaultId,
      });
    }
    new Notice(`Citadel indexed ${file.path}`);
  }

  async pushSelection(path: string, content: string): Promise<void> {
    const vaultId = await this.ensureVault();
    const document: CitadelPushDocument = {
      path,
      content,
      tags: ["selection"],
    };
    const response = await this.plugin.client.pushDocuments(vaultId, [document]);
    if (response.conflicts.length) {
      new Notice("Citadel conflict created for the selection.");
      return;
    }
    new Notice("Citadel indexed the selected text.");
  }

  async pushFolder(): Promise<void> {
    const folder = this.plugin.settings.syncFolder;
    const files = markdownFilesInScope(this.plugin.app, folder);
    for (const file of files) {
      await this.pushFile(file);
    }
  }
}

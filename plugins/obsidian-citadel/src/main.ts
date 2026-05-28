import { Notice, Plugin, WorkspaceLeaf } from "obsidian";

import { getCitadelToken } from "./auth";
import { CitadelClient } from "./citadelClient";
import { registerCitadelCommands } from "./commands";
import { CitadelSettingTab } from "./settings";
import { SyncEngine } from "./sync/syncEngine";
import { DEFAULT_SETTINGS, type CitadelPluginSettings } from "./types";
import { CitadelView, VIEW_TYPE_CITADEL } from "./ui/CitadelView";

export default class CitadelPlugin extends Plugin {
  settings: CitadelPluginSettings = { ...DEFAULT_SETTINGS };
  client!: CitadelClient;
  sync!: SyncEngine;

  async onload(): Promise<void> {
    await this.loadSettings();
    if (!this.settings.vaultName) {
      this.settings.vaultName = this.app.vault.getName();
    }
    this.client = new CitadelClient(this.settings, () => getCitadelToken(this.app, this.settings));
    this.sync = new SyncEngine(this);

    this.registerView(VIEW_TYPE_CITADEL, (leaf) => new CitadelView(leaf, this));
    this.addRibbonIcon("network", "Open Citadel", () => void this.activateView());
    this.addSettingTab(new CitadelSettingTab(this.app, this));
    registerCitadelCommands(this);
  }

  async onunload(): Promise<void> {
    this.app.workspace.detachLeavesOfType(VIEW_TYPE_CITADEL);
  }

  async activateView(query = ""): Promise<void> {
    const leaf = this.app.workspace.getRightLeaf(false) || this.app.workspace.getLeaf(true);
    await leaf.setViewState({ type: VIEW_TYPE_CITADEL, active: true });
    this.app.workspace.revealLeaf(leaf as WorkspaceLeaf);
    const view = leaf.view;
    if (view instanceof CitadelView) {
      view.render(query);
    }
  }

  async registerVault(): Promise<void> {
    const vault = await this.client.registerVault();
    this.settings.vaultId = vault.id;
    this.settings.vaultName = vault.name;
    await this.saveSettings();
    new Notice(`Citadel vault registered: ${vault.name}`);
  }

  async loadSettings(): Promise<void> {
    this.settings = { ...DEFAULT_SETTINGS, ...(await this.loadData()) };
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }
}

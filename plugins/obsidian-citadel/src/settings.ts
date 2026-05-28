import { App, PluginSettingTab, SecretComponent, Setting } from "obsidian";

import type CitadelPlugin from "./main";

export class CitadelSettingTab extends PluginSettingTab {
  constructor(
    app: App,
    private readonly plugin: CitadelPlugin,
  ) {
    super(app, plugin);
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "Citadel Archive" });

    new Setting(containerEl).setName("Server URL").addText((text) => {
      text
        .setPlaceholder("https://citadel.example.com")
        .setValue(this.plugin.settings.baseUrl)
        .onChange(async (value) => {
          this.plugin.settings.baseUrl = value.trim();
          await this.plugin.saveSettings();
        });
    });

    new Setting(containerEl)
      .setName("Access token")
      .addComponent((element) =>
        new SecretComponent(this.app, element)
          .setValue(this.plugin.settings.tokenSecretName)
          .onChange(async (value) => {
            this.plugin.settings.tokenSecretName = value;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl).setName("Vault name").addText((text) => {
      text.setValue(this.plugin.settings.vaultName).onChange(async (value) => {
        this.plugin.settings.vaultName = value.trim();
        await this.plugin.saveSettings();
      });
    });

    new Setting(containerEl).setName("Team scope").addText((text) => {
      text.setValue(this.plugin.settings.teamId).onChange(async (value) => {
        this.plugin.settings.teamId = value.trim();
        await this.plugin.saveSettings();
      });
    });

    new Setting(containerEl).setName("Dataset").addText((text) => {
      text.setValue(this.plugin.settings.defaultDataset).onChange(async (value) => {
        this.plugin.settings.defaultDataset = value.trim();
        await this.plugin.saveSettings();
      });
    });

    new Setting(containerEl).setName("Folder scope").addText((text) => {
      text.setValue(this.plugin.settings.syncFolder).onChange(async (value) => {
        this.plugin.settings.syncFolder = value.trim();
        await this.plugin.saveSettings();
      });
    });
  }
}

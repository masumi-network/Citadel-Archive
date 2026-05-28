import { Modal, Setting } from "obsidian";

import type CitadelPlugin from "../main";

export class SearchModal extends Modal {
  private query = "";

  constructor(private readonly plugin: CitadelPlugin) {
    super(plugin.app);
  }

  onOpen(): void {
    const { contentEl } = this;
    contentEl.empty();
    contentEl.createEl("h2", { text: "Citadel Search" });
    new Setting(contentEl)
      .setName("Query")
      .addText((text) => {
        text.onChange((value) => {
          this.query = value;
        });
        text.inputEl.addEventListener("keydown", (event) => {
          if (event.key === "Enter") {
            void this.runSearch();
          }
        });
      });
    new Setting(contentEl).addButton((button) => {
      button.setButtonText("Search").setCta().onClick(() => void this.runSearch());
    });
  }

  private async runSearch(): Promise<void> {
    await this.plugin.activateView(this.query);
    this.close();
  }
}

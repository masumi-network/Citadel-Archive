import { ItemView, WorkspaceLeaf } from "obsidian";

import type CitadelPlugin from "../main";

export const VIEW_TYPE_CITADEL = "citadel-archive-view";

export class CitadelView extends ItemView {
  constructor(
    leaf: WorkspaceLeaf,
    private readonly plugin: CitadelPlugin,
  ) {
    super(leaf);
  }

  getViewType(): string {
    return VIEW_TYPE_CITADEL;
  }

  getDisplayText(): string {
    return "Citadel";
  }

  getIcon(): string {
    return "network";
  }

  async onOpen(): Promise<void> {
    this.render();
  }

  render(initialQuery = ""): void {
    const root = this.containerEl.children[1];
    root.empty();
    root.addClass("citadel-pane");

    root.createEl("h3", { text: "Citadel Search" });
    const row = root.createDiv({ cls: "citadel-search-row" });
    const input = row.createEl("input", {
      type: "search",
      value: initialQuery,
      placeholder: "Search shared knowledge",
    });
    const button = row.createEl("button", { text: "Search" });
    const results = root.createDiv();

    const run = async () => {
      const query = input.value.trim();
      if (!query) return;
      button.disabled = true;
      button.textContent = "Searching";
      results.empty();
      try {
        const response = await this.plugin.client.search(query);
        response.results.slice(0, 8).forEach((result, index) => {
          const item = results.createDiv({ cls: "citadel-result" });
          item.createEl("strong", { text: `Result ${index + 1}` });
          item.createEl("pre", { text: JSON.stringify(result, null, 2) });
        });
        if (!response.results.length) {
          results.createEl("p", { text: "No results." });
        }
      } catch (error) {
        results.createEl("p", { text: error instanceof Error ? error.message : String(error) });
      } finally {
        button.disabled = false;
        button.textContent = "Search";
      }
    };

    button.addEventListener("click", () => void run());
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        void run();
      }
    });
  }
}

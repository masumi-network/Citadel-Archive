import type { Editor, MarkdownFileInfo } from "obsidian";

import type CitadelPlugin from "./main";
import { SearchModal } from "./ui/SearchModal";

export function registerCitadelCommands(plugin: CitadelPlugin): void {
  plugin.addCommand({
    id: "open-citadel-search",
    name: "Open Citadel search",
    callback: () => void plugin.activateView(),
  });

  plugin.addCommand({
    id: "search-citadel",
    name: "Search Citadel",
    callback: () => new SearchModal(plugin).open(),
  });

  plugin.addCommand({
    id: "register-citadel-vault",
    name: "Register vault with Citadel",
    callback: () => void plugin.registerVault(),
  });

  plugin.addCommand({
    id: "ingest-current-note",
    name: "Ingest current note",
    checkCallback: (checking) => {
      const file = plugin.app.workspace.getActiveFile();
      if (!file || file.extension !== "md") return false;
      if (!checking) void plugin.sync.pushFile(file);
      return true;
    },
  });

  plugin.addCommand({
    id: "ingest-selection",
    name: "Ingest selected text",
    editorCallback: (editor: Editor, view: MarkdownFileInfo) => {
      const selected = editor.getSelection().trim();
      if (!selected || !view.file) return;
      const path = `Citadel/Selections/${view.file.basename}-${Date.now()}.md`;
      void plugin.sync.pushSelection(path, selected);
    },
  });
}

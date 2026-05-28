export interface LocalDocumentState {
  path: string;
  rev: number | null;
  documentId: string | null;
}

export class LocalIndex {
  private readonly documents = new Map<string, LocalDocumentState>();

  upsert(state: LocalDocumentState): void {
    this.documents.set(state.path, state);
  }

  get(path: string): LocalDocumentState | null {
    return this.documents.get(path) || null;
  }
}

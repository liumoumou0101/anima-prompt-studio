export const DIRECT_IMPORT_KEY = "anima-v3-direct-import";

export interface DirectWorkbenchImport {
  positive_text: string;
  excluded_text: string;
  english_positive: string;
  english_negative: string;
}

let consumedImport: DirectWorkbenchImport | null | undefined;

export function storeDirectImport(payload: DirectWorkbenchImport): void {
  consumedImport = payload;
  sessionStorage.setItem(DIRECT_IMPORT_KEY, JSON.stringify(payload));
}

export function consumeDirectImport(): DirectWorkbenchImport | null {
  if (consumedImport !== undefined) return consumedImport;
  try {
    const raw = sessionStorage.getItem(DIRECT_IMPORT_KEY);
    if (!raw) {
      consumedImport = null;
      return null;
    }
    const parsed = JSON.parse(raw) as Partial<DirectWorkbenchImport>;
    if (!parsed.positive_text || typeof parsed.positive_text !== "string") {
      consumedImport = null;
      return null;
    }
    consumedImport = {
      positive_text: parsed.positive_text,
      excluded_text: typeof parsed.excluded_text === "string" ? parsed.excluded_text : "",
      english_positive: typeof parsed.english_positive === "string" ? parsed.english_positive : "",
      english_negative: typeof parsed.english_negative === "string" ? parsed.english_negative : "",
    };
    sessionStorage.removeItem(DIRECT_IMPORT_KEY);
    return consumedImport;
  } catch {
    consumedImport = null;
    return null;
  }
}

export function resetDirectImportForTests(): void {
  consumedImport = undefined;
  sessionStorage.removeItem(DIRECT_IMPORT_KEY);
}

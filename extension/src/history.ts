// Local-only download history + settings via chrome.storage.local.
// Minimal fields only: platform, filename, timestamp — nothing that
// reconstructs browsing activity. No server sync. Falls back to an
// in-memory store when chrome.storage is unavailable (tests / dev).

import type { HistoryEntry, UserSettings } from "./types";
import { DEFAULT_API_BASE } from "./api";

const HISTORY_KEY = "mediasaver.history.v1";
const SETTINGS_KEY = "mediasaver.settings.v1";
const HISTORY_LIMIT = 100;

export const DEFAULT_SETTINGS: UserSettings = {
  defaultQuality: "highest",
  theme: "dark",
  apiBase: DEFAULT_API_BASE,
};

interface Store {
  get(keys: string[]): Promise<Record<string, unknown>>;
  set(items: Record<string, unknown>): Promise<void>;
  remove(keys: string[]): Promise<void>;
}

function chromeStore(): Store | null {
  try {
    const storage = globalThis.chrome?.storage?.local;
    if (!storage) return null;
    return {
      get: (keys) => storage.get(keys) as Promise<Record<string, unknown>>,
      set: (items) => storage.set(items) as Promise<void>,
      remove: (keys) => storage.remove(keys) as Promise<void>,
    };
  } catch {
    return null;
  }
}

const memory = new Map<string, unknown>();
const memoryStore: Store = {
  get: async (keys) => Object.fromEntries(keys.map((k) => [k, memory.get(k)])),
  set: async (items) => {
    for (const [k, v] of Object.entries(items)) memory.set(k, v);
  },
  remove: async (keys) => {
    for (const k of keys) memory.delete(k);
  },
};

function store(): Store {
  return chromeStore() ?? memoryStore;
}

/** Test hook: clear the in-memory fallback. */
export function __clearMemoryStore(): void {
  memory.clear();
}

export async function getHistory(): Promise<HistoryEntry[]> {
  const raw = (await store().get([HISTORY_KEY]))[HISTORY_KEY];
  if (!Array.isArray(raw)) return [];
  return raw.filter(
    (e): e is HistoryEntry =>
      typeof e === "object" && e !== null &&
      typeof (e as HistoryEntry).platform === "string" &&
      typeof (e as HistoryEntry).filename === "string" &&
      typeof (e as HistoryEntry).savedAt === "string",
  );
}

export async function addHistory(entry: HistoryEntry): Promise<HistoryEntry[]> {
  const list = [entry, ...(await getHistory())].slice(0, HISTORY_LIMIT);
  await store().set({ [HISTORY_KEY]: list });
  return list;
}

export async function clearHistory(): Promise<void> {
  await store().remove([HISTORY_KEY]);
}

export async function getSettings(): Promise<UserSettings> {
  const raw = (await store().get([SETTINGS_KEY]))[SETTINGS_KEY] as Partial<UserSettings> | undefined;
  return {
    defaultQuality: raw?.defaultQuality ?? DEFAULT_SETTINGS.defaultQuality,
    theme: raw?.theme === "light" ? "light" : "dark",
    apiBase: typeof raw?.apiBase === "string" && raw.apiBase ? raw.apiBase : DEFAULT_API_BASE,
  };
}

export async function saveSettings(patch: Partial<UserSettings>): Promise<UserSettings> {
  const next = { ...(await getSettings()), ...patch };
  await store().set({ [SETTINGS_KEY]: next });
  return next;
}

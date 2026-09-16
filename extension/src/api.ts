// API client: plain fetch() against our own backend origin ONLY.
// Returns data, never scripts — nothing here evals or injects remote content.

import type { AnalyzeResponse } from "./types";

// Default API origin. Resolution order:
//   1. VITE_API_BASE when set at build time (REQUIRED for store releases).
//   2. `npm run dev` (import.meta.env.DEV): local backend.
//   3. Any other production build without VITE_API_BASE: prod origin placeholder
//      (deliberately NOT localhost — see scripts/prepare-dist.js fail-closed gate).
// The DEV branch is statement-level dead code in production builds, so bundlers
// drop the localhost literal entirely instead of leaving it in dist/.
function defaultApiBase(): string {
  const fromBuild = import.meta.env.VITE_API_BASE as string | undefined;
  if (typeof fromBuild === "string" && fromBuild.length > 0) return fromBuild;
  if (import.meta.env.DEV) return "http://localhost:8000";
  return "https://api.mediasaver.example";
}

export const DEFAULT_API_BASE: string = defaultApiBase();

export function normalizeApiBase(raw: string): string {
  const v = raw.trim().replace(/\/+$/, "");
  if (!/^https?:\/\/[^/]+$/.test(v)) {
    throw new Error("API base must be a plain http(s) origin, e.g. https://api.mediasaver.example");
  }
  return v;
}

export type FetchFn = (input: string, init?: RequestInit) => Promise<Response>;

export async function analyzeUrl(
  apiBase: string,
  pageUrl: string,
  fetchImpl: FetchFn = fetch,
): Promise<AnalyzeResponse> {
  const res = await fetchImpl(`${normalizeApiBase(apiBase)}/analyze`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url: pageUrl.trim() }),
  });
  // The backend always returns the {ok, ...} envelope, even for errors.
  const body = (await res.json()) as AnalyzeResponse;
  if (typeof body !== "object" || body === null || typeof body.ok !== "boolean") {
    return { ok: false, error: "SERVER_ERROR", reason: "", platform: null };
  }
  return body;
}

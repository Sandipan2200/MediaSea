// Shared types mirroring backend schemas (extension/src/types.ts).
// Kept in sync manually with backend/app/schemas.py — no codegen, no remote fetch.

export type ErrorCode =
  | "INVALID_URL"
  | "UNSUPPORTED_PLATFORM"
  | "MEDIA_NOT_FOUND"
  | "PRIVATE_CONTENT"
  | "ACCESS_DENIED"
  | "PROTECTED_CONTENT"
  | "RATE_LIMITED"
  | "TEMPORARY_FAILURE"
  | "NETWORK_ERROR"
  | "SERVER_ERROR"
  | "FILE_TOO_LARGE"
  | "TIMEOUT"
  | "UNSUPPORTED_ACCESS";

export type MediaType = "video" | "image" | "audio";

export interface MediaVariant {
  url: string;
  media_type: MediaType;
  quality_label: string;
  width: number | null;
  height: number | null;
  file_extension: string;
  file_size_bytes: number | null;
  is_manifest: boolean;
}

export interface AnalysisResult {
  platform: string;
  page_url: string;
  title: string | null;
  thumbnail_url: string | null;
  variants: MediaVariant[];
}

export type AnalyzeResponse =
  | { ok: true; data: AnalysisResult }
  | { ok: false; error: ErrorCode; reason: string; platform: string | null };

export type PopupState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "success"; result: AnalysisResult }
  | { kind: "empty" }
  | { kind: "error"; code: ErrorCode; message: string; platform: string | null };

export interface HistoryEntry {
  platform: string;
  filename: string;
  savedAt: string; // ISO timestamp — no URL stored (privacy: no browsing trail)
}

export interface UserSettings {
  defaultQuality: "highest" | "lowest" | "ask";
  theme: "dark" | "light";
  apiBase: string;
}

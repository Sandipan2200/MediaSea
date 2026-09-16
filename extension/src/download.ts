// Filename helpers: derive a safe local filename from a variant.
// No remote input is trusted blindly — basename is sanitized for Windows/macOS/Linux.

import type { MediaVariant } from "./types";

const UNSAFE_CHARS = /[<>:"/\\|?*\x00-\x1F]/g;

export function sanitizeFilename(name: string, fallback = "mediasaver"): string {
  const clean = name.replace(UNSAFE_CHARS, "_").replace(/\.+$/, "").trim();
  const sliced = clean.slice(0, 120);
  return sliced || fallback;
}

export function filenameForVariant(
  platform: string,
  variant: MediaVariant,
  index: number,
): string {
  let base = "media";
  try {
    const path = new URL(variant.url).pathname;
    const last = path.split("/").filter(Boolean).pop() ?? "";
    const stem = last.split(".")[0];
    if (stem) base = stem;
  } catch {
    base = `media-${index + 1}`;
  }
  const label = variant.quality_label.replace(/[^a-zA-Z0-9]+/g, "-").toLowerCase();
  const ext = (variant.file_extension || "mp4").replace(/[^a-zA-Z0-9]/g, "") || "mp4";
  return sanitizeFilename(`${platform}-${base}-${label}.${ext}`);
}

/** Order variants by preference for the "Download best" default-quality setting. */
export function rankVariants(
  variants: MediaVariant[],
  preference: "highest" | "lowest",
): MediaVariant[] {
  const score = (v: MediaVariant): number =>
    (v.height ?? 0) * 1000 + (v.width ?? 0);
  const sorted = [...variants].sort((a, b) => score(b) - score(a));
  return preference === "highest" ? sorted : sorted.reverse();
}

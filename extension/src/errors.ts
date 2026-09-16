// Every backend ErrorCode -> one plain-language, non-alarming message.
// The backend's `reason` string is never shown verbatim (defense in depth:
// even if a backend string changed, the UI cannot leak internals).

import type { ErrorCode } from "./types";

export const ERROR_MESSAGES: Record<ErrorCode, string> = {
  INVALID_URL: "That doesn't look like a valid link. Check it starts with http(s):// and try again.",
  UNSUPPORTED_PLATFORM:
    "This site isn't supported for downloads. YouTube links are never supported — see our supported-sites list.",
  MEDIA_NOT_FOUND:
    "No downloadable media was found on that page. It may be private, removed, or a type we don't handle yet.",
  PRIVATE_CONTENT: "That looks private or removed. We only work with publicly visible posts.",
  ACCESS_DENIED: "That page needs a login to view, and MediaSaver never logs in anywhere. Nothing was downloaded.",
  PROTECTED_CONTENT: "That media is protected (for example DRM video) and can't be saved. Nothing was downloaded.",
  RATE_LIMITED: "Too many lookups in a short time. Wait a few seconds and try again.",
  TEMPORARY_FAILURE: "The site is having issues right now. Try again in a bit.",
  NETWORK_ERROR: "Couldn't reach that page. Check your connection and the link, then retry.",
  SERVER_ERROR: "Something went wrong on our side. Try again in a bit.",
  FILE_TOO_LARGE: "That page is too large to inspect safely. Try a direct post link instead.",
  TIMEOUT: "The site took too long to respond. Try again.",
  UNSUPPORTED_ACCESS: "That address isn't publicly reachable, so it can't be checked.",
};

export function messageFor(code: ErrorCode): string {
  return ERROR_MESSAGES[code] ?? "Something went wrong. Try again.";
}

/** Client-side YouTube pre-check: fail fast without ever calling the API. */
const YOUTUBE_HOSTS = new Set([
  "youtube.com",
  "www.youtube.com",
  "m.youtube.com",
  "music.youtube.com",
  "youtu.be",
  "www.youtu.be",
  "youtube-nocookie.com",
  "www.youtube-nocookie.com",
]);

export function isYouTubeUrl(raw: string): boolean {
  let host = "";
  try {
    host = new URL(raw.trim()).hostname.toLowerCase().replace(/\.+$/, "");
  } catch {
    return false;
  }
  if (YOUTUBE_HOSTS.has(host)) return true;
  return host.endsWith(".youtube.com") || host.endsWith(".youtu.be");
}

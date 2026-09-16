# MediaSaver — Privacy Policy (draft v0.1.0, MVP)

**Short version:** MediaSaver knows as little about you as we could manage while
keeping the service running. No accounts, no browsing-history capture, no ad
tracking, no sale of data — there is nothing to sell.

## Data we process

| What | Where | Why | Retention |
|---|---|---|---|
| The media URL you submit | Backend memory only, for the duration of one analysis | To detect downloadable media on that page | Never written to disk or logs; only a SHA-256 hash prefix is logged for abuse correlation |
| Request metadata (timestamp, coarse rate-limit counters per IP) | Backend memory | Rate limiting and service health | Sliding 60-second window, then forgotten |
| Download history (platform, filename, timestamp) | `chrome.storage.local` on your device | So you can see what you saved | Until you press “Clear history”; never leaves your device |
| Settings (quality preference, theme, API address) | `chrome.storage.local` on your device | Your preferences | Until you change them; never leaves your device |

## Data we never collect

- No browsing history (the extension only sees the URL you explicitly paste).
- No full submitted URLs in logs (info-level logs carry only a hash prefix).
- No cookies, credentials, or login sessions (we never log in anywhere).
- No analytics, fingerprinting, or third-party trackers.

## What the backend does and doesn't do

- The backend fetches **page HTML and playlist manifests (text only, ≤2 MB)** to
  enumerate download options. It never downloads or stores media files.
- Downloads happen directly between your browser and the media host via
  `chrome.downloads.download()`.

## Contact

Security or privacy concerns: see README for the disclosure process.

# Permission justifications (Chrome Web Store review aid)

Manifest V3 allows no comments in `manifest.json`, so each permission is
justified here, one line each, as required by the project spec.

- `downloads` — Perform the actual save via `chrome.downloads.download()`. The
  backend returns metadata + a direct CDN URL only; bytes are never proxied.
- `storage` (`chrome.storage.local`) — Persist local-only download history
  (platform, filename, timestamp) and user settings (quality preference, theme).
  No server sync, ever.
- `host_permissions: https://api.mediasaver.example/*` — The ONLY remote
  origin the extension talks to: our own analysis API. No `<all_urls>`, no
  content scripts on third-party pages, no host access to media CDNs (the
  `downloads` API handles those URLs without needing host permission).
- `host_permissions: http://localhost:8000/*` — Local development only, so the
  popup can reach a dev backend. REMOVE this line in the Chrome Web Store
  release build (`npm run build:store` strips it automatically).
- Release rule: store builds MUST set `VITE_API_BASE` to the production API
  origin (e.g. `$env:VITE_API_BASE="https://api.mediasaver.example"`). The
  default settings value is baked in at build time, and `prepare-dist.js
  --store` fails the build (fail-closed) if any localhost/127.0.0.1/`:8000`
  string survives in `dist/`.

What we deliberately do NOT request: `tabs`, `history`, `cookies`,
`webRequest`, `scripting`, `activeTab`, `<all_urls>`, content scripts, or
background service workers with network access. The popup reads the URL the
user pastes — nothing else.

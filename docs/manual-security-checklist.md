# Manual security & release checklist (Phase 4)

Run these by hand before any Chrome Web Store submission. Automated suites
(`backend/tests`, `extension/tests`) cover the same properties with mocks;
this document covers what mocks cannot prove. Checked 2026-09-16 against
backend 0.1.0 + extension 0.1.0 — results inline.

## 1. Redirect-chain SSRF (run first)

Mocks prove the validator runs; only real multi-hop HTTP proves the underlying
client actually routes every hop back through it. Our client sets
`follow_redirects=False` and follows manually — verify that is still true
(`grep follow_redirects backend/app/fetcher.py`) on every release.

**Caveat:** pointing `/analyze` at `http://localhost:8899/...` (or any
loopback/non-default-port URL) returns `UNSUPPORTED_ACCESS` at hop 0 *by
design* — it never follows a redirect, so it proves nothing about chains.
Enter through an allowed public hop instead:

```bash
# hop1 public -> hop2 literal cloud-metadata IP. Must be UNSUPPORTED_ACCESS
# (not timeout, not 500, not success).
curl -X POST localhost:8000/analyze -H 'Content-Type: application/json' \
  -d '{"url":"https://httpbin.org/redirect-to?url=http%3A%2F%2F169.254.169.254%2Flatest%2Fmeta-data%2F"}'

# hop1 public -> hop2 DNS name resolving to 127.0.0.1 (DNS-rebinding style).
curl -X POST localhost:8000/analyze -H 'Content-Type: application/json' \
  -d '{"url":"https://httpbin.org/redirect-to?url=http%3A%2F%2F127.0.0.1.nip.io%2F"}'

# two-hop chain: httpbin -> httpbin -> metadata IP (proves iteration, not just
# first-hop handling). Nest the redirect-to URLs with double encoding.
```

Also probe the hop-0 DNS path directly (no listener needed — validation runs
before connect): `{"url":"http://127.0.0.1.nip.io/"}` must be
`UNSUPPORTED_ACCESS` with reason "not publicly reachable".

2026-09-16 results: all chain variants blocked with `UNSUPPORTED_ACCESS`,
correct reason, no timeouts. ✅

## 2. Rate limiter boundary

With the default limit (20/min/IP):

```bash
for i in $(seq 1 21); do curl -s -o /dev/null -w "%{http_code}\n" \
  -X POST localhost:8000/analyze -H 'Content-Type: application/json' \
  -d '{"url":"https://youtu.be/x"}'; done
# YouTube URLs used deliberately: they pass the limiter but refuse before any
# outbound fetch, so the loop is fast and side-effect free.
```

Expect: requests 1–20 served (422 refusal, not limited), 21st → 429 with
`{"ok":false,"error":"RATE_LIMITED",...}` envelope intact. Wait 65s, repeat
once → served again (no sticky off-by-one at window rollover). Then trigger
429 from the real popup once and confirm the UI shows the rate-limit message,
not a generic network error.

2026-09-16 results: exactly 20×422 → 429 (envelope stable) → rollover serves
again. ✅ (Boundary asserted via in-process ASGI; identical limiter path.)

## 3. `build:store` artifact check

```bash
$env:VITE_API_BASE="https://api.mediasaver.example"   # PowerShell example
npm run build:store
```

- Build must succeed — `prepare-dist.js --store` fails closed if any
  `localhost` / `127.0.0.1` / `0.0.0.0` / `:8000` string survives in `dist/`.
  (It caught two real leaks during development: the localhost default and a
  localhost example inside an error message.)
- `grep -ri "localhost\|127.0.0.1\|:8000\|:3000" extension/dist/` → nothing.
- `dist/manifest.json` → `host_permissions` shows ONLY the prod API origin.
- Load unpacked in `chrome://extensions`, popup → DevTools Network → run an
  analysis → every request goes to the prod origin, never localhost.

2026-09-16 results: manifest scoped to prod origin only, zero grep hits. ✅

## 4. Adapter edge cases (live probes)

| Probe | Expected | 2026-09-16 |
|---|---|---|
| `https://httpbin.org/status/403` | 403 `ACCESS_DENIED` (a bare 403 can't distinguish private from login-walled; `PRIVATE_CONTENT` is reserved for adapters with positive private-signals) | ✅ |
| `https://httpbin.org/status/404` | 404 `MEDIA_NOT_FOUND` | ✅ |
| JSON body served as `video/mp4` | `MEDIA_NOT_FOUND`, no crash, no variants | ✅ |
| Malformed/truncated HLS manifest | `MEDIA_NOT_FOUND`, never fabricated URIs (regression-tested in `test_adapters.py`) | ✅ |
| 5 MB body (`speed.cloudflare.com/__down?bytes=5000000`) | `FILE_TOO_LARGE`, stream aborted early (~2 MB inspected, not 5 MB buffered) | ✅ |
| Deleted pin (`pinterest.com/pin/1/`, HTTP 200 shell) | 404 `MEDIA_NOT_FOUND` — shell CSS asset URLs must never become variants (regression-tested) | ✅ fixed this pass |

**Deliberate non-goal — magic bytes:** we do not fetch media bytes at all
(backend returns direct URLs; extension downloads opaquely), so content-type
sniffing would require proxying bytes through the backend — extra SSRF surface
and bandwidth for zero trust gain. Correctness comes from only returning URLs
the platform's own payload declares. Do not "fix" this without revisiting
Option B.

## 5. Extension manual QA (needs a human + Chrome)

> CORS gotcha (found 2026-09-16): Starlette matches `allow_origins` exactly,
> so `chrome-extension://*` as a literal entry matches nothing — the popup's
> fetch fails while curl works fine, which looks exactly like "Analyze does
> nothing" with only hand-made 400s in the server log. Extension origins must
> go through `allow_origin_regex` (regression-tested). If Analyze ever dies
> silently while curl succeeds, check preflight first — or just press the
> **Test connection** button in ⚙ Settings, which reports reachability
> directly.

Automated: all popup states, YouTube fast-fail with zero fetch, Enter-key flow,
backend-down friendly message (no `ERR_CONNECTION_REFUSED` leak), history
privacy (no URLs stored) — see `extension/tests/popup.test.ts`.

By hand, once per release:
- [ ] Cold open, empty input → Analyze → invalid-URL message, focus in field.
- [ ] Paste → Analyze → loading spinner, button disabled, no layout flash
      (throttle to Slow 3G in DevTools to inspect).
- [ ] Keyboard only, start to finish (Tab order, Enter submits, Download
      buttons reachable, visible focus throughout).
- [ ] Backend stopped → friendly message, no internal strings.
- [ ] Real download per platform (public Pinterest pin of your own choosing +
      a direct-video page) → file lands in Downloads with a sane
      `platform-base-quality.ext` name and playable/viewable bytes. Check the
      MIME/extension matches (mp4 plays, jpg opens).

## 6. Known limitations (do not file as bugs without new evidence)

- Pinterest search/sitemap/discovery pages are JS-shells for non-JS clients;
  only direct pin URLs are analyzable. Positive live-pin verification needs a
  human-supplied public pin URL (§5).
- Instagram covers public posts/reels only via unauthenticated HTML
  (`video_url`/`display_url` payload fields, og tags). Login-walled or JS-only
  payloads degrade honestly to `ACCESS_DENIED`/`MEDIA_NOT_FOUND` — that is the
  intended behavior, not a bug to work around.
- On video pins, page-chrome images (related pins, board covers, avatars) are
  trimmed: only the poster frame family remains. On photo pins, observed page
  images still appear (carousels preserved); size siblings derive only from
  declared images, never invented for chrome.
- Rate limiter is in-memory: single-replica only; multi-replica deploys need
  sticky sessions or the documented Redis swap.

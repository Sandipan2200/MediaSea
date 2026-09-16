<div align="center">

# 📥 MediaSaver

**Detect and save public media from Pinterest, Instagram & direct pages — the downloader that refuses to misbehave.**

[![Chrome MV3](https://img.shields.io/badge/Chrome-Manifest%20V3-4285F4?logo=googlechrome&logoColor=white)](https://developer.chrome.com/docs/extensions/mv3/intro/)
[![Python 3.12](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)](backend/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?logo=fastapi&logoColor=white)](backend/app/main.py)
[![TypeScript strict](https://img.shields.io/badge/TypeScript-strict-3178C6?logo=typescript&logoColor=white)](extension/src/)
[![Backend tests](https://img.shields.io/badge/pytest-94%20passed-brightgreen?logo=pytest&logoColor=white)](backend/tests/)
[![Extension tests](https://img.shields.io/badge/vitest-42%20passed-brightgreen?logo=vite&logoColor=white)](extension/tests/)
[![No YouTube](https://img.shields.io/badge/YouTube-never-red)](backend/app/adapters/youtube_guard.py)

Paste a public link → pick **Format** + **Quality** (`720p HD`, `1080p Full HD`, `4K`…) → save it.

**No logins. No bypasses. No proxying.**

The backend returns direct media URLs and metadata; your browser performs the actual download.

[Quickstart](#-quickstart) ·
[How It Works](#-how-it-works) ·
[What It Won't Do](#-what-this-project-intentionally-does-not-support-and-why) ·
[API](#-api) ·
[Security](#-security-disclosure)

</div>

---

## ✨ Features

| | |
|---|---|
| 🎯 **Paste-a-link detection** | Pinterest pins, Instagram public posts/reels, raw video pages, HLS/DASH streams |
| 🎞 **Real quality tiers** | Every rendition the platform itself serves — labeled `240p` → `8K`, with codec tags (`· AV1`, `· HEVC`) when tiers collide |
| 🎛 **Format + Quality pickers** | One section per media type — choose container and tier, then download once |
| 🛡 **SSRF-hardened backend** | Every adapter is forced through one audited fetch layer: DNS-before-connect, per-hop redirect re-validation, size caps, and timeouts |
| 🔒 **Minimal permissions** | `downloads` + `storage` only, API-scoped hosts, no content scripts, no `<all_urls>` |
| 🚫 **Policy-safe by construction** | YouTube refused by policy, login walls return `ACCESS_DENIED`, DRM returns `PROTECTED_CONTENT` |
| 📴 **Private by default** | History lives in `chrome.storage.local` with platform, filename, and timestamp. URLs are never stored |
| 🧱 **Strict TypeScript** | Extension code is compiled with TypeScript strict mode |
| 🧪 **Extensively tested** | 94 backend tests + 42 extension tests |

---

## 🧭 How It Works

```mermaid
flowchart LR
    U[Paste public URL] --> P[Extension Popup<br/>MV3 · TypeScript strict]

    P -->|POST /analyze<br/>API origin only| A[FastAPI Backend]

    A --> D{Detector}

    D --> PIN[Pinterest<br/>Adapter]
    D --> IG[Instagram<br/>Public-only Adapter]
    D --> GEN[Generic<br/>Video / HLS / DASH Adapter]

    D --> YT{YouTube?}

    YT -->|Always| NO[UNSUPPORTED_PLATFORM<br/>Never extracted]

    PIN --> SF[SafeFetcher<br/>SSRF-hardened]
    IG --> SF
    GEN --> SF

    SF --> R[Direct CDN URLs<br/>+ Real Quality Labels]

    R --> P

    P -->|chrome.downloads| DL[(Downloads Folder)]
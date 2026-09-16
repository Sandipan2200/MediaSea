// Popup controller: all UI states (idle/loading/success/empty/error +
// explicit unsupported-platform), download flow, settings, local history.
// Decision logic ships in this bundle — the backend returns data only.

import { analyzeUrl, normalizeApiBase } from "./api";
import { isYouTubeUrl, messageFor } from "./errors";
import {
  addHistory,
  clearHistory,
  getHistory,
  getSettings,
  saveSettings,
} from "./history";
import { filenameForVariant, rankVariants } from "./download";
import type { AnalysisResult, MediaVariant, PopupState, UserSettings } from "./types";

function el<T extends HTMLElement>(id: string): T | null {
  return document.getElementById(id) as T | null;
}

function requireEl<T extends HTMLElement>(id: string): T {
  const node = el<T>(id);
  if (!node) throw new Error(`popup: missing #${id}`);
  return node;
}

function escapeHtml(s: string): string {
  return s.replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c] as string);
}

// -- state rendering (pure DOM writes; unit-tested with jsdom) ------------------

export function render(state: PopupState): void {
  const results = requireEl("results");
  const status = requireEl("statusRegion") as HTMLDivElement;
  const analyzeBtn = requireEl("analyzeBtn") as HTMLButtonElement;
  results.innerHTML = "";
  status.hidden = false;
  analyzeBtn.disabled = state.kind === "loading";

  if (state.kind === "idle") {
    status.hidden = true;
    return;
  }
  if (state.kind === "loading") {
    status.className = "status";
    status.innerHTML = '<span class="spinner" aria-hidden="true"></span>Analyzing…';
    return;
  }
  if (state.kind === "empty") {
    status.className = "status";
    status.textContent = "Paste a link above and press Analyze.";
    return;
  }
  if (state.kind === "error") {
    status.className = "status error";
    status.textContent = state.message;
    return;
  }
  // success
  status.hidden = true;
  results.appendChild(resultCard(state.result));
}

function resultCard(result: AnalysisResult): HTMLElement {
  const card = document.createElement("article");
  card.className = "result-card";
  const title = result.title ? escapeHtml(result.title) : "Untitled media";
  const thumb = result.thumbnail_url
    ? `<img src="${escapeHtml(result.thumbnail_url)}" alt="" loading="lazy" />`
    : `<div aria-hidden="true"></div>`;
  const count = result.variants.length;
  card.innerHTML =
    `<div class="result-head">${thumb}` +
    `<div><div><strong>${title}</strong></div>` +
    `<div><span class="badge">${escapeHtml(result.platform)}</span>` +
    `<span class="badge">${count} option${count === 1 ? "" : "s"}</span></div></div></div>`;
  // One download section per media type: pick Format + Quality, download once.
  // No long per-variant button lists.
  const order: MediaVariant["media_type"][] = ["video", "image", "audio"];
  for (const kind of order) {
    const section = mediaSection(result.platform, result.variants, kind);
    if (section) card.appendChild(section);
  }
  return card;
}

interface IndexedVariant {
  v: MediaVariant;
  i: number; // index into the full variants array (stable for filenames)
}

function mediaSection(
  platform: string,
  variants: MediaVariant[],
  kind: MediaVariant["media_type"],
): HTMLElement | null {
  const items: IndexedVariant[] = variants
    .map((v, i) => ({ v, i }))
    .filter(({ v }) => v.media_type === kind);
  if (items.length === 0) return null;

  const section = document.createElement("div");
  section.className = "media-section";
  section.setAttribute("role", "group");
  section.setAttribute("aria-label", `${kind} download options`);
  section.innerHTML = `<div class="badge">${escapeHtml(kind)}</div>`;

  const pickers = document.createElement("div");
  pickers.className = "pickers";

  const formatLabel = document.createElement("label");
  formatLabel.textContent = "Format ";
  const formatSel = document.createElement("select");
  formatSel.setAttribute("aria-label", `${kind} format`);
  const formats = [...new Set(items.map(({ v }) => v.file_extension || "mp4"))];
  for (const f of formats) {
    const o = document.createElement("option");
    o.value = f;
    o.textContent = `.${f}`;
    formatSel.appendChild(o);
  }
  formatLabel.appendChild(formatSel);

  const qualityLabel = document.createElement("label");
  qualityLabel.textContent = "Quality ";
  const qualitySel = document.createElement("select");
  qualitySel.setAttribute("aria-label", `${kind} quality`);
  qualityLabel.appendChild(qualitySel);

  pickers.append(formatLabel, qualityLabel);
  section.appendChild(pickers);

  function refreshQualities(): void {
    const fmt = formatSel.value || formats[0] || "mp4";
    qualitySel.innerHTML = "";
    for (const { v, i } of items.filter(({ v }) => (v.file_extension || "mp4") === fmt)) {
      const o = document.createElement("option");
      o.value = String(i);
      o.textContent = v.quality_label; // already carries size, e.g. "1080p Full HD"
      qualitySel.appendChild(o);
    }
  }
  formatSel.addEventListener("change", refreshQualities);
  refreshQualities();

  const btn = document.createElement("button");
  btn.className = "btn primary block";
  btn.textContent = `Download ${kind}`;
  btn.setAttribute("aria-label", `Download selected ${kind}`);
  btn.addEventListener("click", () => {
    const picked = items.find(({ i }) => i === Number(qualitySel.value)) ?? items[0];
    if (!picked) return;
    void downloadVariant(platform, picked.v.url, filenameForVariant(platform, picked.v, picked.i));
  });
  section.appendChild(btn);
  return section;
}

// -- actions -------------------------------------------------------------------

async function onAnalyze(): Promise<void> {
  const urlInput = requireEl("urlInput") as HTMLInputElement;
  const raw = urlInput.value.trim();
  if (!raw) {
    render({ kind: "error", code: "INVALID_URL", message: messageFor("INVALID_URL"), platform: null });
    urlInput.focus();
    return;
  }
  // Fail fast for YouTube without ever calling the API (belt and suspenders:
  // the backend refuses too, but the UI should never even ask).
  if (isYouTubeUrl(raw)) {
    render({
      kind: "error",
      code: "UNSUPPORTED_PLATFORM",
      message:
        "YouTube links aren't supported — YouTube's Terms of Service prohibit third-party " +
        "download tools, so MediaSaver will never attempt them. Try a Pinterest or direct-video link.",
      platform: "youtube",
    });
    return;
  }
  render({ kind: "loading" });
  try {
    const cfg = await getSettings();
    const res = await analyzeUrl(cfg.apiBase, raw);
    if (!res.ok) {
      render({ kind: "error", code: res.error, message: messageFor(res.error), platform: res.platform });
      return;
    }
    if (res.data.variants.length === 0) {
      render({ kind: "empty" });
      return;
    }
    // Default-quality shortcut: rank first so the best match is on top.
    if (cfg.defaultQuality !== "ask") {
      res.data.variants = rankVariants(res.data.variants, cfg.defaultQuality);
    }
    render({ kind: "success", result: res.data });
  } catch {
    render({ kind: "error", code: "NETWORK_ERROR", message: messageFor("NETWORK_ERROR"), platform: null });
  }
}

async function downloadVariant(platform: string, mediaUrl: string, filename: string): Promise<void> {
  try {
    await chrome.downloads.download({ url: mediaUrl, filename, saveAs: false });
    await addHistory({ platform, filename, savedAt: new Date().toISOString() });
    await renderHistory();
  } catch {
    render({ kind: "error", code: "NETWORK_ERROR", message: "Download failed to start. Try again.", platform });
  }
}

export async function renderHistory(): Promise<void> {
  const list = requireEl("historyList") as HTMLUListElement;
  const entries = await getHistory();
  list.innerHTML = "";
  if (entries.length === 0) {
    const li = document.createElement("li");
    li.innerHTML = '<span class="muted">Nothing saved yet.</span>';
    list.appendChild(li);
    return;
  }
  for (const e of entries.slice(0, 20)) {
    const li = document.createElement("li");
    const when = new Date(e.savedAt).toLocaleString();
    li.innerHTML =
      `<span>${escapeHtml(e.filename)}</span>` +
      `<span class="muted">${escapeHtml(e.platform)} · ${escapeHtml(when)}</span>`;
    list.appendChild(li);
  }
}

function applyTheme(theme: UserSettings["theme"]): void {
  document.documentElement.dataset.theme = theme;
}

// -- wiring (only runs inside the real popup, not under unit tests) -------------

export function wireUp(): void {
  // JS is alive: remove the pure-HTML boot signal first thing.
  document.getElementById("bootMsg")?.remove();
  (requireEl("analyzeBtn") as HTMLButtonElement).addEventListener("click", () => void onAnalyze());
  const urlInput = requireEl("urlInput") as HTMLInputElement;
  urlInput.addEventListener("keydown", (ev) => {
    if (ev.key === "Enter") void onAnalyze();
  });
  (requireEl("pasteBtn") as HTMLButtonElement).addEventListener("click", () => {
    void (async () => {
      try {
        urlInput.value = await navigator.clipboard.readText();
        urlInput.focus();
      } catch {
        urlInput.focus();
        urlInput.select();
      }
    })();
  });
  const settingsPanel = requireEl("settingsPanel");
  const settingsToggle = requireEl("settingsToggle") as HTMLButtonElement;
  settingsToggle.addEventListener("click", () => {
    const open = settingsPanel.hidden;
    settingsPanel.hidden = !open;
    settingsToggle.setAttribute("aria-expanded", String(open));
  });
  (requireEl("saveSettingsBtn") as HTMLButtonElement).addEventListener("click", () => {
    void (async () => {
      const msg = requireEl("settingsMsg");
      try {
        const apiBaseRaw = (requireEl("apiBaseInput") as HTMLInputElement).value.trim();
        const patch: Partial<UserSettings> = {
          defaultQuality: (requireEl("qualitySelect") as HTMLSelectElement).value as UserSettings["defaultQuality"],
          theme: (requireEl("themeSelect") as HTMLSelectElement).value as UserSettings["theme"],
        };
        if (apiBaseRaw) patch.apiBase = apiBaseRaw;
        const cfg = await saveSettings(patch);
        applyTheme(cfg.theme);
        msg.textContent = "Settings saved.";
      } catch {
        msg.textContent = "Couldn't save settings in this browser.";
      }
    })();
  });
  (requireEl("testConnBtn") as HTMLButtonElement).addEventListener("click", () => {
    void (async () => {
      const msg = requireEl("settingsMsg");
      const raw =
        (requireEl("apiBaseInput") as HTMLInputElement).value.trim() ||
        (await getSettings()).apiBase;
      let base: string;
      try {
        base = normalizeApiBase(raw);
      } catch {
        msg.textContent = "That API address doesn't look right — use a plain http(s) origin.";
        return;
      }
      msg.textContent = `Checking ${base}…`;
      try {
        const res = await fetch(`${base}/health`);
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const body = (await res.json()) as { version?: unknown };
        const version = typeof body.version === "string" ? ` (v${body.version})` : "";
        msg.textContent = `Backend reachable${version}. You can analyze links.`;
      } catch {
        msg.textContent =
          `Can't reach the backend at ${base} — is it running, and does it allow extension origins (CORS)?`;
      }
    })();
  });
  (requireEl("clearHistoryBtn") as HTMLButtonElement).addEventListener("click", () => {
    void (async () => {
      await clearHistory();
      await renderHistory();
    })();
  });
  void (async () => {
    const cfg = await getSettings();
    (requireEl("apiBaseInput") as HTMLInputElement).value = cfg.apiBase;
    (requireEl("qualitySelect") as HTMLSelectElement).value = cfg.defaultQuality;
    (requireEl("themeSelect") as HTMLSelectElement).value = cfg.theme;
    applyTheme(cfg.theme);
    await renderHistory();
  })();
}

// The real popup has #urlInput; unit tests import render()/renderHistory()
// with their own DOM and never trigger this branch at import time... except
// the module bottom runs on import. Guard with a DOM check so jsdom tests
// that haven't loaded popup.html yet don't throw.
if (typeof document !== "undefined" && document.getElementById("urlInput")) {
  wireUp();
}

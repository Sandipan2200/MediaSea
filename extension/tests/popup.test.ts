import { beforeEach, describe, expect, it, vi } from "vitest";
import popupHtml from "../src/popup.html?raw";
import { render, renderHistory, wireUp } from "../src/popup";
import { __clearMemoryStore, addHistory } from "../src/history";
import type { AnalysisResult } from "../src/types";

const sample: AnalysisResult = {
  platform: "pinterest",
  page_url: "https://www.pinterest.com/pin/123/",
  title: "Test pin",
  thumbnail_url: "https://i.pinimg.com/736x/a.jpg",
  variants: [
    {
      url: "https://i.pinimg.com/originals/a.jpg",
      media_type: "image",
      quality_label: "original",
      width: 1000,
      height: 1500,
      file_extension: "jpg",
      file_size_bytes: null,
      is_manifest: false,
    },
    {
      url: "https://v1.pinimg.com/videos/a.mp4",
      media_type: "video",
      quality_label: "720p",
      width: 1280,
      height: 720,
      file_extension: "mp4",
      file_size_bytes: null,
      is_manifest: false,
    },
  ],
};

function mount(): void {
  document.body.innerHTML = popupHtml;
}

const sampleMulti: AnalysisResult = {
  platform: "generic",
  page_url: "https://example.com/watch",
  title: "Clip",
  thumbnail_url: null,
  variants: [
    {
      url: "https://cdn.example.com/clip_720.mp4",
      media_type: "video",
      quality_label: "720p",
      width: 1280,
      height: 720,
      file_extension: "mp4",
      file_size_bytes: null,
      is_manifest: false,
    },
    {
      url: "https://cdn.example.com/clip_1080.mp4",
      media_type: "video",
      quality_label: "1080p",
      width: 1920,
      height: 1080,
      file_extension: "mp4",
      file_size_bytes: null,
      is_manifest: false,
    },
    {
      url: "https://cdn.example.com/clip_480.webm",
      media_type: "video",
      quality_label: "480p",
      width: 854,
      height: 480,
      file_extension: "webm",
      file_size_bytes: null,
      is_manifest: false,
    },
  ],
};

beforeEach(() => {
  __clearMemoryStore();
  vi.unstubAllGlobals();
  mount();
});

describe("popup states", () => {
  it("wireUp removes the boot signal (proof the script ran)", () => {
    expect(document.getElementById("bootMsg")).not.toBeNull();
    wireUp();
    expect(document.getElementById("bootMsg")).toBeNull();
  });

  it("idle hides the status region", () => {
    render({ kind: "idle" });
    expect(document.getElementById("statusRegion")?.hidden).toBe(true);
  });

  it("loading shows a spinner and disables Analyze", () => {
    render({ kind: "loading" });
    const status = document.getElementById("statusRegion");
    expect(status?.hidden).toBe(false);
    expect(status?.querySelector(".spinner")).not.toBeNull();
    expect((document.getElementById("analyzeBtn") as HTMLButtonElement).disabled).toBe(true);
  });

  it("error shows a plain-language message, never a stack trace", () => {
    render({ kind: "error", code: "TIMEOUT", message: "The site took too long.", platform: null });
    const status = document.getElementById("statusRegion");
    expect(status?.classList.contains("error")).toBe(true);
    expect(status?.textContent).toBe("The site took too long.");
  });

  it("empty prompts for a link", () => {
    render({ kind: "empty" });
    expect(document.getElementById("statusRegion")?.textContent).toMatch(/paste a link/i);
  });

  it("success groups by media type with Format + Quality dropdowns", () => {
    render({ kind: "success", result: sample });
    const groups = document.querySelectorAll('[role="group"]');
    expect(groups).toHaveLength(2); // video + image sections
    const videoQuality = document.querySelector('select[aria-label="video quality"]');
    expect(videoQuality?.textContent).toContain("720p");
    const videoFormat = document.querySelector('select[aria-label="video format"]');
    expect(videoFormat?.textContent).toContain(".mp4");
    expect(document.getElementById("statusRegion")?.hidden).toBe(true);
  });

  it("format + quality selection downloads exactly the chosen file", async () => {
    const seen: Array<Record<string, unknown>> = [];
    vi.stubGlobal("chrome", {
      downloads: {
        download: vi.fn(async (opts: Record<string, unknown>) => {
          seen.push(opts);
          return 1;
        }),
      },
    });
    render({ kind: "success", result: sampleMulti });
    const group = document.querySelector('[aria-label="video download options"]');
    const formatSel = group?.querySelector(
      'select[aria-label="video format"]',
    ) as HTMLSelectElement;
    const qualitySel = group?.querySelector(
      'select[aria-label="video quality"]',
    ) as HTMLSelectElement;
    const btn = group?.querySelector("button") as HTMLButtonElement;

    // mp4 offers 720p + 1080p: pick 1080p (original variant index 1).
    qualitySel.value = "1";
    btn.click();
    await new Promise((r) => setTimeout(r, 20));
    expect(seen).toHaveLength(1);
    expect(seen[0]?.["url"]).toBe("https://cdn.example.com/clip_1080.mp4");
    expect(String(seen[0]?.["filename"])).toContain("1080p");

    // Switch container to webm: qualities repopulate, download follows.
    formatSel.value = "webm";
    formatSel.dispatchEvent(new Event("change", { bubbles: true }));
    expect(qualitySel.options).toHaveLength(1);
    btn.click();
    await new Promise((r) => setTimeout(r, 20));
    expect(seen).toHaveLength(2);
    expect(seen[1]?.["url"]).toBe("https://cdn.example.com/clip_480.webm");
  });

  it("has an aria-live status region for screen readers", () => {
    expect(document.getElementById("statusRegion")?.getAttribute("aria-live")).toBe("polite");
  });
});

describe("analyze flow (wired popup, mocked network)", () => {
  it("youtube links fail fast without any fetch", async () => {
    const fetchMock = vi.fn(async () => new Response("{}"));
    vi.stubGlobal("fetch", fetchMock);
    wireUp();
    (document.getElementById("urlInput") as HTMLInputElement).value =
      "https://www.youtube.com/watch?v=x";
    document.getElementById("analyzeBtn")?.click();
    await new Promise((r) => setTimeout(r, 0));
    expect(fetchMock).not.toHaveBeenCalled();
    expect(document.getElementById("statusRegion")?.textContent).toMatch(/terms of service/i);
  });

  it("renders backend variants on success", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ ok: true, data: sample }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    wireUp();
    (document.getElementById("urlInput") as HTMLInputElement).value =
      "https://www.pinterest.com/pin/123/";
    document.getElementById("analyzeBtn")?.click();
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(document.querySelectorAll(".variant")).toHaveLength(0);
    expect(document.querySelectorAll(".media-section")).toHaveLength(2);
  });

  it("Enter key in the input starts analysis (keyboard-only flow)", async () => {
    const fetchMock = vi.fn(async () =>
      new Response(JSON.stringify({ ok: true, data: sample }), { status: 200 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    wireUp();
    (document.getElementById("urlInput") as HTMLInputElement).value =
      "https://www.pinterest.com/pin/123/";
    document
      .getElementById("urlInput")
      ?.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).toHaveBeenCalledOnce();
    expect(document.querySelectorAll(".media-section")).toHaveLength(2);
  });

  it("backend down shows a friendly message, never the raw error", async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError("Failed to fetch https://api… net::ERR_CONNECTION_REFUSED");
    });
    vi.stubGlobal("fetch", fetchMock);
    wireUp();
    (document.getElementById("urlInput") as HTMLInputElement).value =
      "https://www.pinterest.com/pin/123/";
    document.getElementById("analyzeBtn")?.click();
    await new Promise((r) => setTimeout(r, 20));
    const text = document.getElementById("statusRegion")?.textContent ?? "";
    expect(text).toMatch(/couldn't reach that page/i);
    expect(text).not.toContain("ERR_CONNECTION_REFUSED");
  });
});

describe("history panel", () => {
  it("renders saved entries, empty state otherwise", async () => {
    await renderHistory();
    expect(document.getElementById("historyList")?.textContent).toMatch(/nothing saved/i);
    await addHistory({ platform: "pinterest", filename: "p-a.jpg", savedAt: "2026-01-01T00:00:00.000Z" });
    await renderHistory();
    expect(document.getElementById("historyList")?.textContent).toContain("p-a.jpg");
  });
});

describe("settings panel", () => {
  it("save shows a visible confirmation", async () => {
    wireUp();
    await new Promise((r) => setTimeout(r, 0));
    (document.getElementById("apiBaseInput") as HTMLInputElement).value =
      "http://localhost:8000";
    document.getElementById("saveSettingsBtn")?.click();
    await new Promise((r) => setTimeout(r, 20));
    expect(document.getElementById("settingsMsg")?.textContent).toBe("Settings saved.");
  });

  it("test connection reports reachable backend with version", async () => {
    const fetchMock = vi.fn(async () => new Response(JSON.stringify({ ok: true, version: "0.1.0" })));
    vi.stubGlobal("fetch", fetchMock);
    wireUp();
    (document.getElementById("apiBaseInput") as HTMLInputElement).value =
      "http://localhost:8000";
    document.getElementById("testConnBtn")?.click();
    await new Promise((r) => setTimeout(r, 20));
    expect(fetchMock).toHaveBeenCalledWith("http://localhost:8000/health");
    expect(document.getElementById("settingsMsg")?.textContent).toMatch(/reachable.*0\.1\.0/);
  });

  it("test connection names the failing base instead of failing silently", async () => {
    const fetchMock = vi.fn(async () => {
      throw new TypeError("Failed to fetch");
    });
    vi.stubGlobal("fetch", fetchMock);
    wireUp();
    (document.getElementById("apiBaseInput") as HTMLInputElement).value =
      "http://localhost:8000";
    document.getElementById("testConnBtn")?.click();
    await new Promise((r) => setTimeout(r, 20));
    const text = document.getElementById("settingsMsg")?.textContent ?? "";
    expect(text).toMatch(/Can't reach the backend at http:\/\/localhost:8000/);
  });
});

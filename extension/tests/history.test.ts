import { beforeEach, describe, expect, it } from "vitest";
import { __clearMemoryStore, addHistory, clearHistory, getHistory, getSettings, saveSettings } from "../src/history";

beforeEach(() => {
  __clearMemoryStore();
});

describe("history (local only, minimal fields)", () => {
  it("starts empty and round-trips entries", async () => {
    expect(await getHistory()).toEqual([]);
    await addHistory({ platform: "pinterest", filename: "pinterest-a-original.jpg", savedAt: "2026-01-01T00:00:00.000Z" });
    const list = await getHistory();
    expect(list).toHaveLength(1);
    expect(list[0]).toEqual({
      platform: "pinterest",
      filename: "pinterest-a-original.jpg",
      savedAt: "2026-01-01T00:00:00.000Z",
    });
  });

  it("stores no URLs", async () => {
    await addHistory({ platform: "generic", filename: "generic-v-720p.mp4", savedAt: new Date().toISOString() });
    const raw = JSON.stringify(await getHistory());
    expect(raw).not.toContain("http");
  });

  it("clears fully", async () => {
    await addHistory({ platform: "generic", filename: "x.mp4", savedAt: new Date().toISOString() });
    await clearHistory();
    expect(await getHistory()).toEqual([]);
  });
});

describe("settings", () => {
  it("has dark-mode defaults", async () => {
    const s = await getSettings();
    expect(s.theme).toBe("dark");
    expect(s.defaultQuality).toBe("highest");
  });

  it("persists patches", async () => {
    await saveSettings({ theme: "light" });
    expect((await getSettings()).theme).toBe("light");
  });
});

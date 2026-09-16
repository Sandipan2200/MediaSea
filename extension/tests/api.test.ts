import { describe, expect, it, vi } from "vitest";
import { analyzeUrl, normalizeApiBase } from "../src/api";

describe("normalizeApiBase", () => {
  it("strips trailing slashes", () => {
    expect(normalizeApiBase("http://localhost:8000/")).toBe("http://localhost:8000");
  });

  it("rejects non-origins and paths", () => {
    expect(() => normalizeApiBase("not a url")).toThrow();
    expect(() => normalizeApiBase("http://localhost:8000/api/v1")).toThrow();
  });
});

describe("analyzeUrl", () => {
  it("posts the envelope and returns data", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(JSON.stringify({ ok: true, data: { variants: [] } }), { status: 200 }),
    );
    const res = await analyzeUrl("http://localhost:8000", "https://example.com/p", fetchImpl);
    expect(fetchImpl).toHaveBeenCalledOnce();
    const [url, init] = fetchImpl.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("http://localhost:8000/analyze");
    expect(JSON.parse(init.body as string)).toEqual({ url: "https://example.com/p" });
    expect(res.ok).toBe(true);
  });

  it("passes backend error envelopes through untouched", async () => {
    const fetchImpl = vi.fn(async () =>
      new Response(
        JSON.stringify({ ok: false, error: "UNSUPPORTED_PLATFORM", reason: "x", platform: "youtube" }),
        { status: 422 },
      ),
    );
    const res = await analyzeUrl("http://localhost:8000", "https://youtu.be/x", fetchImpl);
    expect(res).toEqual({ ok: false, error: "UNSUPPORTED_PLATFORM", reason: "x", platform: "youtube" });
  });

  it("treats malformed bodies as server errors", async () => {
    const fetchImpl = vi.fn(async () => new Response("oops", { status: 200 }));
    await expect(analyzeUrl("http://localhost:8000", "https://example.com", fetchImpl)).rejects.toThrow();
  });
});

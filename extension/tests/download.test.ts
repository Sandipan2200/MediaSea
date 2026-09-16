import { describe, expect, it } from "vitest";
import { filenameForVariant, rankVariants, sanitizeFilename } from "../src/download";
import type { MediaVariant } from "../src/types";

const v = (over: Partial<MediaVariant> = {}): MediaVariant => ({
  url: "https://cdn.example.com/path/clip_720.mp4?tok=1",
  media_type: "video",
  quality_label: "720p",
  width: 1280,
  height: 720,
  file_extension: "mp4",
  file_size_bytes: null,
  is_manifest: false,
  ...over,
});

describe("sanitizeFilename", () => {
  it("strips characters illegal on Windows", () => {
    expect(sanitizeFilename('a<b>c:d"e/f\\g|h?i*j')).toBe("a_b_c_d_e_f_g_h_i_j");
  });

  it("falls back on empty input", () => {
    expect(sanitizeFilename("...")).toBe("mediasaver");
  });
});

describe("filenameForVariant", () => {
  it("builds platform-base-quality.ext names", () => {
    expect(filenameForVariant("pinterest", v(), 0)).toBe("pinterest-clip_720-720p.mp4");
  });

  it("survives unparseable URLs", () => {
    expect(filenameForVariant("generic", v({ url: "::bad::" }), 2)).toMatch(/^generic-media-3-/);
  });
});

describe("rankVariants", () => {
  const low = v({ quality_label: "360p", width: 640, height: 360 });
  const high = v({ quality_label: "1080p", width: 1920, height: 1080 });

  it("highest puts biggest first", () => {
    expect(rankVariants([low, high], "highest")[0]?.quality_label).toBe("1080p");
  });

  it("lowest puts smallest first", () => {
    expect(rankVariants([low, high], "lowest")[0]?.quality_label).toBe("360p");
  });
});

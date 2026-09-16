import { describe, expect, it } from "vitest";
import { ERROR_MESSAGES, isYouTubeUrl, messageFor } from "../src/errors";

describe("error messages", () => {
  it("covers every backend ErrorCode", () => {
    expect(Object.keys(ERROR_MESSAGES).sort()).toEqual(
      [
        "ACCESS_DENIED",
        "FILE_TOO_LARGE",
        "INVALID_URL",
        "MEDIA_NOT_FOUND",
        "NETWORK_ERROR",
        "PRIVATE_CONTENT",
        "PROTECTED_CONTENT",
        "RATE_LIMITED",
        "SERVER_ERROR",
        "TEMPORARY_FAILURE",
        "TIMEOUT",
        "UNSUPPORTED_ACCESS",
        "UNSUPPORTED_PLATFORM",
      ].sort(),
    );
  });

  it("never exposes raw backend strings", () => {
    // messageFor takes only the code — there is no path for a backend
    // string to reach the UI.
    expect(messageFor("TIMEOUT")).toMatch(/too long/i);
    expect(messageFor("UNSUPPORTED_PLATFORM")).toMatch(/isn't supported/i);
  });
});

describe("isYouTubeUrl", () => {
  it.each([
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://m.youtube.com/watch?v=x",
    "https://www.youtube-nocookie.com/embed/x",
  ])("flags %s", (url) => {
    expect(isYouTubeUrl(url)).toBe(true);
  });

  it.each([
    "https://www.pinterest.com/pin/123/",
    "https://example.com/video.mp4",
    "not a url",
    "",
  ])("does not flag %s", (url) => {
    expect(isYouTubeUrl(url)).toBe(false);
  });
});

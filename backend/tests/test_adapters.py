"""Adapter selection, YouTube guard, generic + pinterest adapters, rate limiter."""

from __future__ import annotations

import httpx
import pytest

from app.adapters.youtube_guard import YOUTUBE_REFUSAL, is_youtube_url
from app.detector import analyze_url, detect_platform, select_adapter
from app.adapters.generic import GenericMediaAdapter, parse_hls_variants
from app.adapters.instagram import InstagramAdapter
from app.adapters.pinterest import PinterestAdapter
from app.fetcher import SafeFetcher, SafeFetchError
from app.rate_limit import RateLimiter
from app.schemas import ErrorCode


async def _public_resolver(host: str) -> list[str]:
    return ["93.184.216.34"]


def _fetcher(handler, **kw):  # type: ignore[no-untyped-def]
    return SafeFetcher(resolver=_public_resolver,
                       transport=httpx.MockTransport(handler), **kw)


# -- YouTube guard ------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "https://youtu.be/dQw4w9WgXcQ",
    "https://m.youtube.com/watch?v=x",
    "https://www.youtube-nocookie.com/embed/x",
])
def test_youtube_variants_detected(url: str) -> None:
    assert is_youtube_url(url) is True


def test_non_youtube_not_flagged() -> None:
    assert is_youtube_url("https://www.pinterest.com/pin/123/") is False
    assert is_youtube_url("https://example.com/video.mp4") is False


async def test_youtube_never_extracted() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no HTTP must happen for YouTube URLs")

    with pytest.raises(SafeFetchError) as ei:
        await analyze_url("https://www.youtube.com/watch?v=x", _fetcher(handler))
    assert ei.value.code == ErrorCode.UNSUPPORTED_PLATFORM
    assert "Terms of Service" in ei.value.reason


# -- selection -----------------------------------------------------------------

def test_pinterest_selected_for_pin_urls() -> None:
    assert isinstance(select_adapter("https://www.pinterest.com/pin/123/"), PinterestAdapter)
    assert isinstance(select_adapter("https://pin.it/abc"), PinterestAdapter)


def test_instagram_selected_for_ig_urls() -> None:
    assert isinstance(select_adapter("https://www.instagram.com/reel/abc/"), InstagramAdapter)
    assert isinstance(select_adapter("https://www.instagram.com/p/abc/"), InstagramAdapter)
    assert detect_platform("https://www.instagram.com/reel/abc/") == "instagram"


def test_generic_is_fallback() -> None:
    assert isinstance(select_adapter("https://example.com/v.mp4"), GenericMediaAdapter)


def test_detect_platform() -> None:
    assert detect_platform("https://youtu.be/x") == "youtube"
    assert detect_platform("https://www.pinterest.com/pin/1/") == "pinterest"
    assert detect_platform("https://example.com/") == "generic"


# -- generic adapter ------------------------------------------------------------

async def test_generic_finds_video_and_og_image() -> None:
    html = """
    <html><head><title>Demo</title>
    <meta property="og:image" content="https://cdn.example.com/t.jpg">
    </head><body>
    <video src="https://cdn.example.com/v.mp4"></video>
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    res = await analyze_url("https://example.com/page", _fetcher(handler))
    urls = [v.url for v in res.variants]
    assert "https://cdn.example.com/v.mp4" in urls
    assert "https://cdn.example.com/t.jpg" in urls


async def test_generic_finds_bare_file_url_in_page_data() -> None:
    """Reproduces the IG-reel shape: no <video> tag, only a video_url field
    in embedded JSON plus an og:image poster frame."""
    html = """
    <html><head><title>Reel</title>
    <meta property="og:image" content="https://cdn.example.com/thumb.jpg">
    </head><body><script>
    window._data={"video_url":"https:\\/\\/cdn.example.com\\/clips\\/r1.mp4?st=abc123","w":1080};
    </script></body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    res = await analyze_url("https://www.example-social.com/reel/abc", _fetcher(handler))
    urls = [v.url for v in res.variants]
    assert "https://cdn.example.com/clips/r1.mp4?st=abc123" in urls
    assert "https://cdn.example.com/thumb.jpg" in urls
    kinds = {v.url: v.media_type for v in res.variants}
    assert kinds["https://cdn.example.com/clips/r1.mp4?st=abc123"] == "video"


async def test_generic_ignores_non_url_media_mentions() -> None:
    """Bare words and truncated extensions must not become variants."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=(
            "<html><body>call my.mp4 handler; truncated "
            "https://cdn.example.com/clip.mp but real "
            "https://cdn.example.com/a.mp4</body></html>"
        ))

    res = await analyze_url("https://example.com/x", _fetcher(handler))
    assert [v.url for v in res.variants] == ["https://cdn.example.com/a.mp4"]


# -- instagram adapter (public posts only) --------------------------------------

_IG_REEL_HTML = """
<html><head><title>Cool reel - Instagram</title>
<meta property="og:image" content="https://scontent.cdn.com/v/t51.jpg?stp=1">
</head><body><script>
window.__data={"video_url":"https:\\/\\/scontent.cdn.com\\/v\\/r1.mp4?stp=dst-jpg_e35&_nc_cat=1","width":1080,"height":1920,"display_url":"https:\\/\\/scontent.cdn.com\\/v\\/t51.jpg?stp=1"};
</script></body></html>
"""

_IG_LOGIN_HTML = """
<html><head><title>Login • Instagram</title></head>
<body><div>Log in to continue</div></body></html>
"""


def _ig_handler(html: str):  # type: ignore[no-untyped-def]
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)
    return handler


async def test_instagram_reel_yields_video_not_just_poster() -> None:
    res = await analyze_url("https://www.instagram.com/reel/abc123/",
                            _fetcher(_ig_handler(_IG_REEL_HTML)))
    assert res.platform == "instagram"
    by_url = {v.url: v.media_type for v in res.variants}
    assert "https://scontent.cdn.com/v/r1.mp4?stp=dst-jpg_e35&_nc_cat=1" in by_url
    assert by_url["https://scontent.cdn.com/v/r1.mp4?stp=dst-jpg_e35&_nc_cat=1"] == "video"
    assert any(mt == "image" for mt in by_url.values())
    labels = {v.url: v.quality_label for v in res.variants}
    assert labels["https://scontent.cdn.com/v/r1.mp4?stp=dst-jpg_e35&_nc_cat=1"] == "1080p Full HD"


async def test_instagram_login_wall_is_access_denied() -> None:
    with pytest.raises(SafeFetchError) as ei:
        await analyze_url("https://www.instagram.com/p/secret/",
                          _fetcher(_ig_handler(_IG_LOGIN_HTML)))
    assert ei.value.code == ErrorCode.ACCESS_DENIED


async def test_instagram_no_media_is_not_found() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text="<html><head><title>Post - Instagram</title></head>"
                                   "<body>shell, no payload</body></html>")

    with pytest.raises(SafeFetchError) as ei:
        await analyze_url("https://www.instagram.com/p/empty/", _fetcher(handler))
    assert ei.value.code == ErrorCode.MEDIA_NOT_FOUND


async def test_generic_hls_manifest_enumerated() -> None:
    page = '<html><body>watch: https://cdn.example.com/hls/master.m3u8</body></html>'
    master = (
        "#EXTM3U\n"
        '#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360\n360p.m3u8\n'
        '#EXT-X-STREAM-INF:BANDWIDTH=2800000,RESOLUTION=1280x720\n720p.m3u8\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("master.m3u8"):
            return httpx.Response(200, headers={"content-type": "application/x-mpegURL"}, text=master)
        return httpx.Response(200, headers={"content-type": "text/html"}, text=page)

    res = await analyze_url("https://example.com/watch", _fetcher(handler))
    labels = sorted(v.quality_label for v in res.variants)
    assert labels == ["360p", "720p HD"]


def test_parse_hls_unit() -> None:
    master = "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1920x1080\nhi.m3u8\n"
    vs = parse_hls_variants(master, "https://cdn.example.com/m.m3u8")
    assert len(vs) == 1 and vs[0].quality_label == "1080p Full HD"


@pytest.mark.parametrize("garbage", [
    "",  # empty manifest
    "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=abc,RESOLUTION=AxB\n",  # truncated: no URI line
    "this is not a playlist at all, just text",
    "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=800000,RESOLUTION=640x360\n",  # header, no rendition
    "\x00\x01\x02 binary \xff garbage",
])
def test_parse_hls_malformed_never_raises(garbage: str) -> None:
    vs = parse_hls_variants(garbage, "https://cdn.example.com/m.m3u8")
    assert vs == []


async def test_generic_malformed_manifest_degrades_to_not_found() -> None:
    """Page references a manifest whose body is truncated garbage: no crash,
    no partial-fabricated variant — MEDIA_NOT_FOUND via analyze_url."""
    page = '<html><body>https://cdn.example.com/hls/broken.m3u8</body></html>'

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).endswith("broken.m3u8"):
            return httpx.Response(200, headers={"content-type": "application/x-mpegURL"},
                                  text="#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=\n")
        return httpx.Response(200, headers={"content-type": "text/html"}, text=page)

    with pytest.raises(SafeFetchError) as ei:
        await analyze_url("https://example.com/watch", _fetcher(handler))
    assert ei.value.code == ErrorCode.MEDIA_NOT_FOUND


def test_parse_hls_media_playlist_yields_manifest_not_segments() -> None:
    """A media playlist (segments) must not become N per-chunk 'variants'."""
    media = (
        "#EXTM3U\n#EXT-X-TARGETDURATION:10\n#EXTINF:10.0,\nseg0.ts\n"
        "#EXTINF:10.0,\nseg1.ts\n#EXT-X-ENDLIST\n"
    )
    vs = parse_hls_variants(media, "https://cdn.example.com/a.m3u8")
    assert len(vs) == 1
    assert vs[0].is_manifest is True
    assert vs[0].url == "https://cdn.example.com/a.m3u8"


async def test_generic_wrong_content_type_body_still_safe() -> None:
    """HTML error page served as video/* must not crash or yield variants."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "video/mp4"},
                              text="<html><body>Access Denied</body></html>")

    with pytest.raises(SafeFetchError) as ei:
        await analyze_url("https://example.com/err", _fetcher(handler))
    assert ei.value.code == ErrorCode.MEDIA_NOT_FOUND


async def test_generic_no_media_raises() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"},
                              text="<html><body>nothing here</body></html>")

    with pytest.raises(SafeFetchError) as ei:
        await analyze_url("https://example.com/empty", _fetcher(handler))
    assert ei.value.code == ErrorCode.MEDIA_NOT_FOUND


# -- pinterest adapter ----------------------------------------------------------

async def test_pinterest_extracts_og_and_variants() -> None:
    html = """
    <html><head><title>Cool pin - Pinterest</title>
    <meta property="og:image" content="https://i.pinimg.com/736x/ab/cd/ef123.jpg">
    <meta property="og:video" content="https://v1.pinimg.com/videos/mc/exp/abc.mp4">
    </head><body></body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    res = await analyze_url("https://www.pinterest.com/pin/123/", _fetcher(handler))
    assert res.platform == "pinterest"
    urls = [v.url for v in res.variants]
    assert "https://i.pinimg.com/736x/ab/cd/ef123.jpg" in urls
    assert "https://i.pinimg.com/originals/ab/cd/ef123.jpg" in urls  # derived sibling
    assert "https://v1.pinimg.com/videos/mc/exp/abc.mp4" in urls


async def test_pinterest_video_list_renditions_get_real_labels() -> None:
    """V_720P-style rendition blocks label from dims, not 'video file'."""
    html = """
    <html><head><title>Vid pin - Pinterest</title>
    <meta property="og:image" content="https://i.pinimg.com/736x/ab/cd/ef123.jpg">
    </head><body><script>
    {"V_720P":{"url":"https:\\/\\/v1.pinimg.com\\/videos\\/mc\\/x_720w.mp4","width":720,"height":1280},
     "V_480P":{"url":"https:\\/\\/v1.pinimg.com\\/videos\\/mc\\/x_480w.mp4","width":480,"height":852}}
    </script></body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    res = await analyze_url("https://www.pinterest.com/pin/456/", _fetcher(handler))
    labels = {v.url: v.quality_label for v in res.variants if v.media_type == "video"}
    assert labels["https://v1.pinimg.com/videos/mc/x_720w.mp4"] == "720p HD"
    assert labels["https://v1.pinimg.com/videos/mc/x_480w.mp4"] == "480p"


async def test_pinterest_video_pin_drops_page_chrome_images() -> None:
    """On video pins, avatars/covers/related images are page chrome: only the
    poster frame (+ its real size siblings) may remain in the image section."""
    html = """
    <html><head><title>Vid pin - Pinterest</title>
    <meta property="og:image" content="https://i.pinimg.com/736x/aa/bb/poster.jpg">
    <meta property="og:video" content="https://v1.pinimg.com/videos/mc/v_720w.mp4">
    </head><body>
    <img src="https://i.pinimg.com/60x60/av/at/avatar.jpg">
    <img src="https://i.pinimg.com/474x/cc/dd/related.jpg">
    </body></html>
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    res = await analyze_url("https://www.pinterest.com/pin/789/", _fetcher(handler))
    images = sorted(v.url for v in res.variants if v.media_type == "image")
    assert images, "poster frame must survive"
    assert all("/aa/bb/poster.jpg" in u for u in images), images
    assert any(v.media_type == "video" for v in res.variants)


async def test_generic_token_url_gets_real_label() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=(
            '<html><body>{"preview":"https://cdn.example.com/preview_720p.mp4"}</body></html>'
        ))

    res = await analyze_url("https://example.com/p", _fetcher(handler))
    assert [(v.url, v.quality_label) for v in res.variants] == [
        ("https://cdn.example.com/preview_720p.mp4", "720p HD")
    ]


async def test_pinterest_login_wall_maps_to_access_denied() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="login required")

    with pytest.raises(SafeFetchError) as ei:
        await analyze_url("https://www.pinterest.com/pin/secret/", _fetcher(handler))
    assert ei.value.code == ErrorCode.ACCESS_DENIED


async def test_pinterest_shell_page_without_declared_media_is_not_found() -> None:
    """Regression: deleted-pin shell pages (HTTP 200 + UI sprite in CSS) must
    yield MEDIA_NOT_FOUND, never asset URLs with CSS fragments glued on."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=_SHELL_HTML)

    with pytest.raises(SafeFetchError) as ei:
        await analyze_url("https://www.pinterest.com/pin/1/", _fetcher(handler))
    assert ei.value.code == ErrorCode.MEDIA_NOT_FOUND


async def test_pinterest_css_asset_urls_never_carry_markup() -> None:
    """Even on a real pin page, extracted URLs must terminate at the file
    extension — no `)`/`}`/CSS-fragment suffixes."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=_PIN_WITH_CSS_HTML)

    res = await analyze_url("https://www.pinterest.com/pin/123/", _fetcher(handler))
    assert res.variants, "og:image pin must still succeed"
    for v in res.variants:
        assert ")" not in v.url and "}" not in v.url and "{" not in v.url, v.url


_SHELL_HTML = """
<html><head><style>._YsBbF{border:0;display:block;padding:0}
.Z8mPtw{background:url(https://i.pinimg.com/originals/d5/3b/01/d53b014d86a6b6761bf649a0ed813c2b.png)}</style>
</head><body><div id="__PWS_DATA__">{"props":{}}</div></body></html>
"""

_PIN_WITH_CSS_HTML = """
<html><head><title>Cool pin - Pinterest</title>
<meta property="og:image" content="https://i.pinimg.com/736x/ab/cd/ef123.jpg">
<style>.Z8mPtw{background:url(https://i.pinimg.com/236x/sp/ri/te.png)}</style>
</head><body></body></html>
"""


# -- rate limiter ----------------------------------------------------------------

def test_rate_limiter_blocks_over_limit() -> None:
    rl = RateLimiter(per_minute=3)
    rl.check("k")
    rl.check("k")
    rl.check("k")
    with pytest.raises(SafeFetchError) as ei:
        rl.check("k")
    assert ei.value.code == ErrorCode.RATE_LIMITED


def test_rate_limiter_is_per_key() -> None:
    rl = RateLimiter(per_minute=1)
    rl.check("a")
    rl.check("b")  # different key: fine

"""Quality labeling: honest labels from evidence, fallbacks otherwise."""

from __future__ import annotations

from app.adapters.quality import (
    codec_hint,
    dims_near,
    disambiguate_labels,
    label_from_dims,
    label_from_url,
)
from app.schemas import MediaVariant


def test_dims_landscape() -> None:
    assert label_from_dims(1920, 1080) == "1080p Full HD"
    assert label_from_dims(1280, 720) == "720p HD"
    assert label_from_dims(3840, 2160) == "4K Ultra HD"
    assert label_from_dims(7680, 4320) == "8K Ultra HD 8K"
    assert label_from_dims(640, 480) == "480p"
    assert label_from_dims(640, 360) == "360p"


def test_dims_portrait_and_square_use_smaller_side() -> None:
    assert label_from_dims(1080, 1920) == "1080p Full HD"  # reel convention
    assert label_from_dims(720, 1280) == "720p HD"
    assert label_from_dims(1080, 1080) == "1080p Full HD"


def test_dims_floor_to_bucket() -> None:
    assert label_from_dims(2560, 1440) == "1440p"
    assert label_from_dims(1500, 844) == "720p HD"  # 844px height -> 720p class
    assert label_from_dims(200, 200) == "200p"


def test_dims_fps() -> None:
    assert label_from_dims(1920, 1080, fps=60) == "1080p60 Full HD"
    assert label_from_dims(3840, 2160, fps=60) == "4K60 Ultra HD"
    assert label_from_dims(1920, 1080, fps=9999) == "1080p Full HD"  # insane fps ignored


def test_url_tokens() -> None:
    assert label_from_url("https://cdn.example.com/clip_1080p.mp4") == "1080p Full HD"
    assert label_from_url("https://i.pinimg.com/x_720w.mp4") == "720p HD"
    assert label_from_url("https://cdn.example.com/4k/trailer.mp4") == "4K Ultra HD"
    assert label_from_url("https://cdn.example.com/v.mp4") == "video file"  # no evidence
    assert label_from_url("https://cdn.example.com/episode12345.mp4") == "video file"  # IDs aren't tiers
    assert label_from_url("https://cdn.example.com/clip.mp") == "video file"


def test_url_fps_tokens() -> None:
    assert label_from_url("https://cdn.example.com/game_1080p60.mp4") == "1080p60 Full HD"
    assert label_from_url("https://cdn.example.com/game_60fps.mp4") == "video file"  # fps alone means nothing


def test_url_custom_fallback() -> None:
    assert label_from_url("https://cdn.example.com/v.mp4", fallback="x") == "x"


def test_dims_near_finds_payload_dimensions() -> None:
    text = '{"video_url":"https://cdn.example.com/r.mp4","width":1080,"height":1920}'
    pos = text.index("video_url")
    assert dims_near(text, pos) == (1080, 1920)


def test_dims_near_rejects_garbage() -> None:
    assert dims_near('{"width":5,"height":999999}', 0) is None
    assert dims_near("no dims here", 0) is None


def _v(url: str, label: str = "720p HD", ext: str = "mp4") -> MediaVariant:
    return MediaVariant(url=url, media_type="video", quality_label=label,
                        file_extension=ext)


def test_codec_hint() -> None:
    assert codec_hint("https://cdn.example.com/h265-pt-mp4/x.mp4") == "HEVC"
    assert codec_hint("https://cdn.example.com/av1Mp4-enabled-v2/x.mp4") == "AV1"
    assert codec_hint("https://cdn.example.com/expMp4/x.mp4") == "H.264"
    assert codec_hint("https://cdn.example.com/plain/x.mp4") is None


def test_disambiguate_suffixes_duplicates_only() -> None:
    vs = [
        _v("https://cdn.example.com/expMp4/a_720w.mp4"),
        _v("https://cdn.example.com/av1Mp4-enabled-v2/a_720w.mp4"),
        _v("https://cdn.example.com/h265-pt-mp4/a_720w.mp4"),
        _v("https://cdn.example.com/b_480w.mp4", label="480p"),
    ]
    disambiguate_labels(vs)
    assert [v.quality_label for v in vs] == [
        "720p HD", "720p HD · AV1", "720p HD · HEVC", "480p",
    ]


def test_disambiguate_numbers_unhinted_collisions() -> None:
    vs = [_v("https://cdn.example.com/a/x.mp4"), _v("https://cdn.example.com/b/x.mp4")]
    disambiguate_labels(vs)
    assert [v.quality_label for v in vs] == ["720p HD", "720p HD (2)"]


def test_disambiguate_ignores_cross_format() -> None:
    vs = [_v("https://cdn.example.com/a.mp4"), _v("https://cdn.example.com/a.webm", ext="webm")]
    disambiguate_labels(vs)
    assert [v.quality_label for v in vs] == ["720p HD", "720p HD"]

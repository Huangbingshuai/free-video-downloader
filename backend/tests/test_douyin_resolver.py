from __future__ import annotations

from app.services.douyin_resolver import DouyinExternalResolver, EXTERNAL_FORMAT_ID, is_douyin_url


def test_is_douyin_url():
    assert is_douyin_url("https://v.douyin.com/abc/")
    assert is_douyin_url("https://www.douyin.com/video/123")
    assert not is_douyin_url("https://www.bilibili.com/video/BV123")


def test_external_resolver_maps_video_data(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "data": {
                    "desc": "公开抖音视频",
                    "cover": "https://example.com/cover.jpg",
                    "video_url": "https://example.com/video.mp4",
                }
            }

    monkeypatch.setenv("DOUYIN_RESOLVER_API_BASE", "http://resolver.local")
    monkeypatch.setattr("app.services.douyin_resolver.httpx.get", lambda *args, **kwargs: FakeResponse())

    info = DouyinExternalResolver().extract("https://v.douyin.com/abc/")

    assert info is not None
    assert info.title == "公开抖音视频"
    assert info.thumbnail == "https://example.com/cover.jpg"
    assert info.formats[0].format_id == EXTERNAL_FORMAT_ID
    assert info.formats[0].direct_url == "https://example.com/video.mp4"

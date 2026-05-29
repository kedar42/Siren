import unittest

from siren.config import Settings
from siren.youtube import YouTubeService


class FakeYoutubeDL:
    calls: list[dict[str, object]] = []

    def __init__(self, options: dict[str, object]) -> None:
        self.options = options
        FakeYoutubeDL.calls.append(options)

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def extract_info(self, target: str, download: bool) -> dict[str, object]:
        if target.startswith("ytsearch"):
            return {
                "entries": [
                    {
                        "title": "Song",
                        "uploader": "Artist",
                        "duration": 123,
                        "webpage_url": "https://youtube.test/watch?v=1",
                    }
                ]
            }
        return {
            "title": "Resolved Song",
            "channel": "Resolved Artist",
            "duration": 124,
            "webpage_url": target,
            "requested_formats": [
                {"acodec": "none", "url": "https://video.invalid"},
                {"acodec": "opus", "url": "https://audio.valid"},
            ],
        }


def settings() -> Settings:
    return Settings.from_env(
        {
            "DISCORD_TOKEN": "discord-token",
            "SPOTIFY_CLIENT_ID": "spotify-id",
            "SPOTIFY_CLIENT_SECRET": "spotify-secret",
            "YT_COOKIES_FILE": "/app/data/cookies.txt",
        }
    )


class YouTubeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_youtube_playlist_url_detection_accepts_playlist_forms(self) -> None:
        from siren.youtube import is_youtube_playlist_url

        self.assertTrue(is_youtube_playlist_url("http://youtube.com/playlist?list=OLAK5uy_example"))
        self.assertTrue(is_youtube_playlist_url("https://www.youtube.com/watch?v=abc123&list=OLAK5uy_example"))
        self.assertTrue(is_youtube_playlist_url("https://music.youtube.com/playlist?list=OLAK5uy_example"))
        self.assertFalse(is_youtube_playlist_url("https://www.youtube.com/watch?v=abc123"))
        self.assertFalse(is_youtube_playlist_url("https://soundcloud.com/artist/playlist?list=abc"))

    async def test_tracks_from_playlist_url_converts_flat_entries_in_order(self) -> None:
        class PlaylistYoutubeDL(FakeYoutubeDL):
            def extract_info(self, target: str, download: bool) -> dict[str, object]:
                return {
                    "entries": [
                        {"title": "First", "uploader": "Artist", "duration": 100, "url": "first-id"},
                        {
                            "title": "Second",
                            "channel": "Channel",
                            "duration": 120,
                            "webpage_url": "https://youtube.test/watch?v=second",
                        },
                    ]
                }

        service = YouTubeService(settings(), ydl_cls=PlaylistYoutubeDL)

        tracks = await service.tracks_from_playlist_url("https://youtube.com/playlist?list=abc")

        self.assertEqual([track.title for track in tracks], ["First", "Second"])
        self.assertEqual([track.author for track in tracks], ["Artist", "Channel"])
        self.assertEqual([track.duration_ms for track in tracks], [100000, 120000])
        self.assertEqual(tracks[0].webpage_url, "https://www.youtube.com/watch?v=first-id")
        self.assertEqual(tracks[1].webpage_url, "https://youtube.test/watch?v=second")
        self.assertFalse(tracks.truncated)
        self.assertEqual(tracks.skipped, 0)
        self.assertFalse(FakeYoutubeDL.calls[-1]["noplaylist"])
        self.assertEqual(FakeYoutubeDL.calls[-1]["extract_flat"], "in_playlist")
        self.assertEqual(FakeYoutubeDL.calls[-1]["playlistend"], 51)

    async def test_tracks_from_playlist_url_skips_malformed_entries(self) -> None:
        class MalformedPlaylistYoutubeDL(FakeYoutubeDL):
            def extract_info(self, target: str, download: bool) -> dict[str, object]:
                return {
                    "entries": [
                        {"title": "Good", "uploader": "Artist", "duration": 100, "url": "good-id"},
                        {"title": "Missing URL", "uploader": "Artist", "duration": 100},
                        None,
                        {"title": "Also Good", "uploader": "Artist", "duration": 110, "url": "also-good-id"},
                    ]
                }

        service = YouTubeService(settings(), ydl_cls=MalformedPlaylistYoutubeDL)

        tracks = await service.tracks_from_playlist_url("https://youtube.com/playlist?list=abc")

        self.assertEqual([track.title for track in tracks], ["Good", "Also Good"])
        self.assertEqual(tracks.skipped, 2)

    async def test_tracks_from_playlist_url_caps_usable_tracks_and_marks_truncated(self) -> None:
        class LongPlaylistYoutubeDL(FakeYoutubeDL):
            def extract_info(self, target: str, download: bool) -> dict[str, object]:
                return {
                    "entries": [
                        {"title": f"Track {index}", "uploader": "Artist", "duration": 100, "url": f"id-{index}"}
                        for index in range(52)
                    ]
                }

        service = YouTubeService(settings(), ydl_cls=LongPlaylistYoutubeDL)

        tracks = await service.tracks_from_playlist_url("https://youtube.com/playlist?list=abc")

        self.assertEqual(len(tracks), 50)
        self.assertEqual(tracks[0].title, "Track 0")
        self.assertEqual(tracks[-1].title, "Track 49")
        self.assertTrue(tracks.truncated)

    async def test_search_returns_tracks_from_flat_entries(self) -> None:
        service = YouTubeService(settings(), ydl_cls=FakeYoutubeDL)
        tracks = await service.search("artist song", limit=3)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].title, "Song")
        self.assertEqual(tracks[0].author, "Artist")
        self.assertEqual(tracks[0].duration_ms, 123000)
        self.assertEqual(tracks[0].webpage_url, "https://youtube.test/watch?v=1")
        self.assertTrue(FakeYoutubeDL.calls[-1]["extract_flat"])
        self.assertEqual(FakeYoutubeDL.calls[-1]["cookiefile"], "/app/data/cookies.txt")

    async def test_search_expands_flat_entry_video_id_to_youtube_url(self) -> None:
        class FlatIdYoutubeDL(FakeYoutubeDL):
            def extract_info(self, target: str, download: bool) -> dict[str, object]:
                return {
                    "entries": [
                        {
                            "title": "Song",
                            "uploader": "Artist",
                            "duration": 123,
                            "url": "abc123",
                        }
                    ]
                }

        service = YouTubeService(settings(), ydl_cls=FlatIdYoutubeDL)
        tracks = await service.search("artist song", limit=3)

        self.assertEqual(tracks[0].webpage_url, "https://www.youtube.com/watch?v=abc123")

    async def test_resolve_url_uses_audio_requested_format_when_url_missing(self) -> None:
        service = YouTubeService(settings(), ydl_cls=FakeYoutubeDL)
        resolved = await service.resolve_url("https://youtube.test/watch?v=1")
        self.assertIsNotNone(resolved)
        assert resolved is not None
        track, stream_url = resolved
        self.assertEqual(track.title, "Resolved Song")
        self.assertEqual(track.author, "Resolved Artist")
        self.assertEqual(track.duration_ms, 124000)
        self.assertEqual(stream_url, "https://audio.valid")
        self.assertEqual(FakeYoutubeDL.calls[-1]["format"], "bestaudio/best")

    async def test_resolve_url_skips_audio_formats_without_url(self) -> None:
        class MissingUrlAudioYoutubeDL(FakeYoutubeDL):
            def extract_info(self, target: str, download: bool) -> dict[str, object]:
                return {
                    "title": "Resolved Song",
                    "channel": "Resolved Artist",
                    "duration": 124,
                    "webpage_url": target,
                    "requested_formats": [
                        {"acodec": "opus"},
                        {"acodec": "aac", "url": "https://audio.valid/second"},
                    ],
                }

        service = YouTubeService(settings(), ydl_cls=MissingUrlAudioYoutubeDL)
        resolved = await service.resolve_url("https://youtube.test/watch?v=1")
        self.assertIsNotNone(resolved)
        assert resolved is not None
        _track, stream_url = resolved
        self.assertEqual(stream_url, "https://audio.valid/second")

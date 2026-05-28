import unittest

from siren.config import Settings
from siren.spotify import SpotifyService, SpotifyUrlKind, UnsupportedSpotifyUrl


class FakeSpotifyClient:
    def __init__(self) -> None:
        self.track_calls: list[str] = []
        self.search_calls: list[dict[str, object]] = []

    def track(self, url_or_id: str) -> dict[str, object]:
        self.track_calls.append(url_or_id)
        return {
            "name": "Song",
            "artists": [{"name": "Artist"}],
            "duration_ms": 123000,
            "external_urls": {"spotify": "https://open.spotify.com/track/abc123"},
            "external_ids": {"isrc": "USRC17607839"},
        }

    def search(self, q: str, type: str, limit: int) -> dict[str, object]:
        self.search_calls.append({"q": q, "type": type, "limit": limit})
        return {"tracks": {"items": [self.track("from-search")]}}


def settings() -> Settings:
    return Settings.from_env(
        {
            "DISCORD_TOKEN": "discord-token",
            "SPOTIFY_CLIENT_ID": "spotify-id",
            "SPOTIFY_CLIENT_SECRET": "spotify-secret",
        }
    )


class SpotifyServiceTests(unittest.TestCase):
    def test_parse_track_url(self) -> None:
        parsed = SpotifyService.parse_url("https://open.spotify.com/track/abc123?si=value")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.kind, SpotifyUrlKind.TRACK)
        self.assertEqual(parsed.spotify_id, "abc123")

    def test_parse_internationalized_album_url(self) -> None:
        parsed = SpotifyService.parse_url("https://open.spotify.com/intl-de/album/album123")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.kind, SpotifyUrlKind.ALBUM)
        self.assertEqual(parsed.spotify_id, "album123")

    def test_parse_playlist_url(self) -> None:
        parsed = SpotifyService.parse_url("https://open.spotify.com/playlist/playlist123")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.kind, SpotifyUrlKind.PLAYLIST)
        self.assertEqual(parsed.spotify_id, "playlist123")

    def test_track_from_url_rejects_album_url_clearly(self) -> None:
        service = SpotifyService(settings(), client=FakeSpotifyClient())
        with self.assertRaises(UnsupportedSpotifyUrl) as ctx:
            service.track_from_url("https://open.spotify.com/album/album123")
        self.assertEqual(ctx.exception.kind, SpotifyUrlKind.ALBUM)

    def test_track_from_url_rejects_playlist_url_clearly(self) -> None:
        service = SpotifyService(settings(), client=FakeSpotifyClient())
        with self.assertRaises(UnsupportedSpotifyUrl) as ctx:
            service.track_from_url("https://open.spotify.com/playlist/playlist123")
        self.assertEqual(ctx.exception.kind, SpotifyUrlKind.PLAYLIST)

    def test_track_from_url_converts_spotify_track(self) -> None:
        client = FakeSpotifyClient()
        service = SpotifyService(settings(), client=client)
        track = service.track_from_url("https://open.spotify.com/track/abc123")
        self.assertEqual(track.title, "Song")
        self.assertEqual(track.author, "Artist")
        self.assertEqual(track.duration_ms, 123000)
        self.assertEqual(track.isrc, "USRC17607839")
        self.assertEqual(client.track_calls[0], "https://open.spotify.com/track/abc123")

    def test_track_from_url_uses_parsed_spotify_url_not_surrounding_text(self) -> None:
        client = FakeSpotifyClient()
        service = SpotifyService(settings(), client=client)
        track = service.track_from_url("please play https://open.spotify.com/track/abc123 thanks")
        self.assertEqual(track.title, "Song")
        self.assertEqual(client.track_calls, ["https://open.spotify.com/track/abc123"])

    def test_search_first_track(self) -> None:
        service = SpotifyService(settings(), client=FakeSpotifyClient())
        track = service.search_track("artist song")
        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.title, "Song")

    def test_falsy_injected_client_is_still_used(self) -> None:
        class FalsySpotifyClient(FakeSpotifyClient):
            def __bool__(self) -> bool:
                return False

        client = FalsySpotifyClient()
        service = SpotifyService(settings(), client=client)
        track = service.track_from_url("https://open.spotify.com/track/abc123")
        self.assertEqual(track.title, "Song")
        self.assertEqual(client.track_calls, ["https://open.spotify.com/track/abc123"])

import unittest

from siren.config import Settings
from siren.spotify import SpotifyService


def settings() -> Settings:
    return Settings.from_env(
        {
            "DISCORD_TOKEN": "discord-token",
            "SPOTIFY_CLIENT_ID": "spotify-id",
            "SPOTIFY_CLIENT_SECRET": "spotify-secret",
        }
    )


def spotify_track(name: str, index: int) -> dict[str, object]:
    return {
        "name": name,
        "artists": [{"name": "Artist"}],
        "duration_ms": 1000 + index,
        "external_urls": {"spotify": f"https://open.spotify.com/track/{index}"},
        "external_ids": {"isrc": f"ISRC{index}"},
    }


class FakeSpotifyClient:
    def __init__(self) -> None:
        self.album_calls: list[dict[str, object]] = []
        self.playlist_calls: list[dict[str, object]] = []

    def album_tracks(self, album_id: str, limit: int = 50, offset: int = 0) -> dict[str, object]:
        self.album_calls.append({"album_id": album_id, "limit": limit, "offset": offset})
        if offset == 0:
            return {"items": [spotify_track("A0", 0), spotify_track("A1", 1)], "next": "more"}
        return {"items": [spotify_track("A2", 2)], "next": None}

    def playlist_items(
        self,
        playlist_id: str,
        limit: int = 50,
        offset: int = 0,
        additional_types: tuple[str, ...] = ("track",),
    ) -> dict[str, object]:
        self.playlist_calls.append(
            {"playlist_id": playlist_id, "limit": limit, "offset": offset, "additional_types": additional_types}
        )
        if offset == 0:
            return {
                "items": [
                    {"track": spotify_track("P0", 0)},
                    {"track": None},
                    {"track": spotify_track("P1", 1)},
                ],
                "next": "more",
            }
        return {
            "items": [{"track": spotify_track(f"P{index}", index)} for index in range(2, 62)],
            "next": None,
        }


class SpotifyExpansionTests(unittest.TestCase):
    def test_album_tracks_expands_all_pages_in_order(self) -> None:
        client = FakeSpotifyClient()
        service = SpotifyService(settings(), client=client)

        tracks = service.tracks_from_url("https://open.spotify.com/album/album123")

        self.assertEqual([track.title for track in tracks], ["A0", "A1", "A2"])
        self.assertEqual([call["offset"] for call in client.album_calls], [0, 2])

    def test_album_tracks_captures_album_name_and_artist_metadata(self) -> None:
        class MetadataAlbumClient(FakeSpotifyClient):
            def album(self, album_id: str) -> dict[str, object]:
                return {"name": "Discovery", "artists": [{"name": "Daft Punk"}]}

        service = SpotifyService(settings(), client=MetadataAlbumClient())

        tracks = service.tracks_from_url("https://open.spotify.com/album/album123")

        self.assertEqual(tracks.album_name, "Discovery")
        self.assertEqual(tracks.album_artist, "Daft Punk")

    def test_album_tracks_metadata_lookup_failure_does_not_break_track_list(self) -> None:
        client = FakeSpotifyClient()
        service = SpotifyService(settings(), client=client)

        tracks = service.tracks_from_url("https://open.spotify.com/album/album123")

        self.assertEqual(tracks.album_name, "")
        self.assertEqual(tracks.album_artist, "")
        self.assertEqual([track.title for track in tracks], ["A0", "A1", "A2"])

    def test_album_tracks_skip_malformed_track_objects(self) -> None:
        class MalformedAlbumClient(FakeSpotifyClient):
            def album_tracks(self, album_id: str, limit: int = 50, offset: int = 0) -> dict[str, object]:
                return {
                    "items": [
                        spotify_track("Good", 1),
                        {"name": "Bad"},
                        spotify_track("Also Good", 2),
                    ],
                    "next": None,
                }

        service = SpotifyService(settings(), client=MalformedAlbumClient())

        try:
            tracks = service.tracks_from_url("https://open.spotify.com/album/album123")
        except KeyError as exc:
            self.fail(f"malformed album track should be skipped, not raised: {exc}")

        self.assertEqual([track.title for track in tracks], ["Good", "Also Good"])

    def test_playlist_tracks_skips_invalid_entries_and_caps_default_at_50(self) -> None:
        client = FakeSpotifyClient()
        service = SpotifyService(settings(), client=client)

        tracks = service.tracks_from_url("https://open.spotify.com/playlist/playlist123")

        self.assertEqual(len(tracks), 50)
        self.assertEqual(tracks[0].title, "P0")
        self.assertEqual(tracks[1].title, "P1")
        self.assertEqual(tracks[-1].title, "P49")
        self.assertEqual([call["offset"] for call in client.playlist_calls], [0, 3])
        self.assertEqual(client.playlist_calls[0]["additional_types"], ("track",))
        self.assertTrue(tracks.truncated)

    def test_exactly_50_track_playlist_is_not_marked_truncated(self) -> None:
        class ExactPlaylistClient(FakeSpotifyClient):
            def playlist_items(
                self,
                playlist_id: str,
                limit: int = 50,
                offset: int = 0,
                additional_types: tuple[str, ...] = ("track",),
            ) -> dict[str, object]:
                return {
                    "items": [{"track": spotify_track(f"P{index}", index)} for index in range(50)],
                    "next": None,
                }

        service = SpotifyService(settings(), client=ExactPlaylistClient())

        tracks = service.tracks_from_url("https://open.spotify.com/playlist/playlist123")

        self.assertEqual(len(tracks), 50)
        self.assertFalse(tracks.truncated)

    def test_playlist_tracks_skip_malformed_track_objects(self) -> None:
        class MalformedPlaylistClient(FakeSpotifyClient):
            def playlist_items(
                self,
                playlist_id: str,
                limit: int = 50,
                offset: int = 0,
                additional_types: tuple[str, ...] = ("track",),
            ) -> dict[str, object]:
                return {
                    "items": [
                        {"track": spotify_track("Good", 1)},
                        {"track": {"name": "Bad"}},
                        {"track": spotify_track("Also Good", 2)},
                    ],
                    "next": None,
                }

        service = SpotifyService(settings(), client=MalformedPlaylistClient())

        tracks = service.tracks_from_url("https://open.spotify.com/playlist/playlist123")

        self.assertEqual([track.title for track in tracks], ["Good", "Also Good"])

    def test_track_url_returns_single_track_anchor(self) -> None:
        class TrackClient(FakeSpotifyClient):
            def track(self, url_or_id: str) -> dict[str, object]:
                return spotify_track("Single", 99)

        service = SpotifyService(settings(), client=TrackClient())

        tracks = service.tracks_from_url("https://open.spotify.com/track/track123")

        self.assertEqual([track.title for track in tracks], ["Single"])

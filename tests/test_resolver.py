import asyncio
import time
import unittest

from siren.models import Track
from siren.resolver import TrackResolver, score_candidate
from siren.spotify import SpotifyUrlKind, UnsupportedSpotifyUrl


class FakeSpotify:
    def __init__(
        self,
        anchor: Track | None = None,
        unsupported: SpotifyUrlKind | None = None,
        anchors: list[Track] | None = None,
    ) -> None:
        self.anchor = anchor
        self.unsupported = unsupported
        self.anchors = anchors

    def track_from_url(self, url: str) -> Track | None:
        if self.unsupported:
            raise UnsupportedSpotifyUrl(self.unsupported)
        return self.anchor

    def tracks_from_url(self, url: str) -> list[Track]:
        if self.anchors is not None:
            return self.anchors
        track = self.track_from_url(url)
        return [track] if track else []

    def search_track(self, query: str) -> Track | None:
        return self.anchor

    @staticmethod
    def parse_url(query: str):
        from siren.spotify import SpotifyService

        return SpotifyService.parse_url(query)


class ExpandedTracks(list[Track]):
    def __init__(self, tracks: list[Track], *, truncated: bool = False) -> None:
        super().__init__(tracks)
        self.truncated = truncated


class SlowSpotify(FakeSpotify):
    def __init__(self, anchor: Track | None = None, *, delay_seconds: float = 0.2) -> None:
        super().__init__(anchor=anchor)
        self.delay_seconds = delay_seconds

    def track_from_url(self, url: str) -> Track | None:
        time.sleep(self.delay_seconds)
        return super().track_from_url(url)

    def search_track(self, query: str) -> Track | None:
        time.sleep(self.delay_seconds)
        return super().search_track(query)


class FakeYouTube:
    def __init__(self, candidates: list[Track]) -> None:
        self.candidates = candidates
        self.searches: list[str] = []

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        self.searches.append(query)
        return self.candidates

    async def resolve_url(self, url: str):
        return Track("Resolved", "Uploader", 100000, url), "https://stream.test/audio"


class MappingYouTube:
    def __init__(self, candidates_by_query: dict[str, list[Track]]) -> None:
        self.candidates_by_query = candidates_by_query
        self.searches: list[str] = []

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        self.searches.append(query)
        return self.candidates_by_query.get(query, [])

    async def resolve_url(self, url: str):
        return Track("Resolved", "Uploader", 100000, url), "https://stream.test/audio"


class SlowMappingYouTube(MappingYouTube):
    def __init__(self, candidates_by_query: dict[str, list[Track]], *, delay_seconds: float = 0.05) -> None:
        super().__init__(candidates_by_query)
        self.delay_seconds = delay_seconds
        self.active_searches = 0
        self.max_active_searches = 0

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        self.searches.append(query)
        self.active_searches += 1
        self.max_active_searches = max(self.max_active_searches, self.active_searches)
        try:
            await asyncio.sleep(self.delay_seconds)
            return self.candidates_by_query.get(query, [])
        finally:
            self.active_searches -= 1


ANCHOR = Track("Never Gonna Give You Up", "Rick Astley", 213000, "spotify", "GBARL9300135")


class ResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_spotify_album_with_no_tracks_returns_clear_result(self) -> None:
        resolver = TrackResolver(FakeSpotify(anchors=[]), FakeYouTube([]))
        result = await resolver.resolve("https://open.spotify.com/album/abc123")
        self.assertFalse(result.ok)
        self.assertIsNone(result.track)
        self.assertEqual(result.all_tracks, [])
        self.assertIn("Couldn't resolve", result.message)

    async def test_embedded_spotify_album_with_no_tracks_returns_clear_result(self) -> None:
        resolver = TrackResolver(FakeSpotify(anchors=[]), FakeYouTube([]))
        result = await resolver.resolve("please play https://open.spotify.com/album/abc123 thanks")
        self.assertFalse(result.ok)
        self.assertEqual(result.all_tracks, [])
        self.assertIn("Couldn't resolve", result.message)

    async def test_spotify_playlist_with_no_tracks_returns_clear_result(self) -> None:
        resolver = TrackResolver(FakeSpotify(anchors=[]), FakeYouTube([]))
        result = await resolver.resolve("https://open.spotify.com/playlist/playlist123")
        self.assertFalse(result.ok)
        self.assertIn("Couldn't resolve", result.message)

    async def test_text_query_uses_spotify_anchor_and_picks_best_candidate(self) -> None:
        candidates = [
            Track("Never Gonna Give You Up lyrics", "Someone", 213000, "bad"),
            Track("Rick Astley - Never Gonna Give You Up", "Rick Astley", 213000, "good"),
        ]
        resolver = TrackResolver(FakeSpotify(anchor=ANCHOR), FakeYouTube(candidates))
        result = await resolver.resolve("never gonna give you up")
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.track)
        assert result.track is not None
        self.assertEqual(result.track.webpage_url, "good")
        self.assertEqual(result.track.isrc, "GBARL9300135")

    async def test_text_spotify_lookup_does_not_block_event_loop(self) -> None:
        first = Track("First", "Uploader", 100000, "first-url")
        resolver = TrackResolver(SlowSpotify(anchor=None), FakeYouTube([first]))

        start = time.perf_counter()
        resolve_task = asyncio.create_task(resolver.resolve("plain query"))
        await asyncio.sleep(0.02)

        self.assertLess(time.perf_counter() - start, 0.1)
        result = await resolve_task
        self.assertTrue(result.ok)
        self.assertEqual(result.track, first)

    async def test_spotify_url_lookup_does_not_block_event_loop(self) -> None:
        candidates = [Track("Rick Astley - Never Gonna Give You Up", "Rick Astley", 213000, "good")]
        resolver = TrackResolver(SlowSpotify(anchor=ANCHOR), FakeYouTube(candidates))

        start = time.perf_counter()
        resolve_task = asyncio.create_task(resolver.resolve("https://open.spotify.com/track/abc123"))
        await asyncio.sleep(0.02)

        self.assertLess(time.perf_counter() - start, 0.1)
        result = await resolve_task
        self.assertTrue(result.ok)
        self.assertEqual(result.track.webpage_url if result.track else None, "good")

    async def test_plain_youtube_fallback_when_spotify_has_no_anchor(self) -> None:
        first = Track("First", "Uploader", 100000, "first-url")
        resolver = TrackResolver(FakeSpotify(anchor=None), FakeYouTube([first]))
        result = await resolver.resolve("plain query")
        self.assertTrue(result.ok)
        self.assertEqual(result.track, first)

    async def test_bare_spotify_like_input_is_not_treated_as_direct_url(self) -> None:
        candidates = [Track("Rick Astley - Never Gonna Give You Up", "Rick Astley", 213000, "good")]
        youtube = FakeYouTube(candidates)
        resolver = TrackResolver(FakeSpotify(anchor=ANCHOR), youtube)

        result = await resolver.resolve("open.spotify.com/track/abc123")

        self.assertTrue(result.ok)
        self.assertEqual(result.track.webpage_url if result.track else None, "good")
        self.assertEqual(youtube.searches, ['"GBARL9300135"', "Rick Astley - Never Gonna Give You Up"])

    async def test_spotify_album_resolves_all_expanded_tracks(self) -> None:
        anchors = [Track("Song A", "Artist", 100000, "spotify-a"), Track("Song B", "Artist", 110000, "spotify-b")]
        youtube = MappingYouTube(
            {
                "Artist - Song A": [Track("Song A", "Artist", 100000, "youtube-a")],
                "Artist - Song B": [Track("Song B", "Artist", 110000, "youtube-b")],
            }
        )
        resolver = TrackResolver(FakeSpotify(anchors=anchors), youtube)

        result = await resolver.resolve("https://open.spotify.com/album/album123")

        self.assertTrue(result.ok)
        self.assertEqual([track.webpage_url for track in result.all_tracks], ["youtube-a", "youtube-b"])
        self.assertEqual(result.track.webpage_url if result.track else None, "youtube-a")
        self.assertEqual(result.message, "Queued 2 tracks.")

    async def test_spotify_playlist_partial_resolution_reports_skipped_count(self) -> None:
        anchors = [Track("Song A", "Artist", 100000, "spotify-a"), Track("Song B", "Artist", 110000, "spotify-b")]
        youtube = MappingYouTube({"Artist - Song A": [Track("Song A", "Artist", 100000, "youtube-a")]})
        resolver = TrackResolver(FakeSpotify(anchors=anchors), youtube)

        result = await resolver.resolve("https://open.spotify.com/playlist/playlist123")

        self.assertTrue(result.ok)
        self.assertEqual([track.webpage_url for track in result.all_tracks], ["youtube-a"])
        self.assertEqual(result.message, "Queued 1 track. Skipped 1 track that couldn't be resolved.")

    async def test_exactly_50_track_spotify_playlist_does_not_report_limit(self) -> None:
        anchors = [Track(f"Song {index}", "Artist", 100000, f"spotify-{index}") for index in range(50)]
        youtube = MappingYouTube(
            {
                f"Artist - Song {index}": [Track(f"Song {index}", "Artist", 100000, f"youtube-{index}")]
                for index in range(50)
            }
        )
        resolver = TrackResolver(FakeSpotify(anchors=anchors), youtube)

        result = await resolver.resolve("https://open.spotify.com/playlist/playlist123")

        self.assertTrue(result.ok)
        self.assertEqual(len(result.all_tracks), 50)
        self.assertEqual(result.message, "Queued 50 tracks.")

    async def test_truncated_spotify_playlist_reports_limit_in_message(self) -> None:
        anchors = ExpandedTracks(
            [Track(f"Song {index}", "Artist", 100000, f"spotify-{index}") for index in range(50)],
            truncated=True,
        )
        youtube = MappingYouTube(
            {
                f"Artist - Song {index}": [Track(f"Song {index}", "Artist", 100000, f"youtube-{index}")]
                for index in range(50)
            }
        )
        resolver = TrackResolver(FakeSpotify(anchors=anchors), youtube)

        result = await resolver.resolve("https://open.spotify.com/playlist/playlist123")

        self.assertTrue(result.ok)
        self.assertEqual(len(result.all_tracks), 50)
        self.assertEqual(result.message, "Queued 50 tracks. Playlist limited to first 50 tracks.")

    async def test_expanded_spotify_resolution_overlaps_and_preserves_order(self) -> None:
        anchors = [Track(f"Song {index}", "Artist", 100000, f"spotify-{index}") for index in range(6)]
        youtube = SlowMappingYouTube(
            {
                f"Artist - Song {index}": [Track(f"Song {index}", "Artist", 100000, f"youtube-{index}")]
                for index in range(6)
            }
        )
        resolver = TrackResolver(FakeSpotify(anchors=anchors), youtube)

        result = await resolver.resolve("https://open.spotify.com/album/album123")

        self.assertGreater(youtube.max_active_searches, 1)
        self.assertEqual([track.webpage_url for track in result.all_tracks], [f"youtube-{index}" for index in range(6)])

    async def test_spotify_playlist_total_resolution_failure_returns_no_tracks(self) -> None:
        anchors = [Track("Song A", "Artist", 100000, "spotify-a"), Track("Song B", "Artist", 110000, "spotify-b")]
        resolver = TrackResolver(FakeSpotify(anchors=anchors), MappingYouTube({}))

        result = await resolver.resolve("https://open.spotify.com/playlist/playlist123")

        self.assertFalse(result.ok)
        self.assertEqual(result.all_tracks, [])
        self.assertIn("Couldn't resolve any tracks", result.message)

    async def test_autocomplete_uses_spotify_anchor_for_youtube_candidates(self) -> None:
        youtube = FakeYouTube([Track("Official", "Artist", 180000, "official-url")])
        resolver = TrackResolver(FakeSpotify(anchor=ANCHOR), youtube)

        choices = await resolver.autocomplete("never gonna give you up", limit=25)

        self.assertEqual(choices[0].webpage_url, "official-url")
        self.assertEqual(youtube.searches, ["Rick Astley - Never Gonna Give You Up"])

    async def test_autocomplete_falls_back_to_raw_youtube_search_without_spotify_anchor(self) -> None:
        youtube = FakeYouTube([Track("Raw", "Uploader", 180000, "raw-url")])
        resolver = TrackResolver(FakeSpotify(anchor=None), youtube)

        choices = await resolver.autocomplete("raw query", limit=25)

        self.assertEqual(choices[0].webpage_url, "raw-url")
        self.assertEqual(youtube.searches, ["raw query"])

    async def test_autocomplete_returns_no_candidates_for_empty_or_url_input(self) -> None:
        youtube = FakeYouTube([Track("Ignored", "Uploader", 180000, "ignored-url")])
        resolver = TrackResolver(FakeSpotify(anchor=ANCHOR), youtube)

        self.assertEqual(await resolver.autocomplete("", limit=25), [])
        self.assertEqual(await resolver.autocomplete("   ", limit=25), [])
        self.assertEqual(await resolver.autocomplete("https://www.youtube.com/watch?v=abc", limit=25), [])
        self.assertEqual(await resolver.autocomplete("HTTPS://www.youtube.com/watch?v=abc", limit=25), [])
        self.assertEqual(await resolver.autocomplete("youtube.com/watch?v=abc", limit=25), [])
        self.assertEqual(await resolver.autocomplete("youtu.be/abc", limit=25), [])
        self.assertEqual(await resolver.autocomplete("https://open.spotify.com/track/abc", limit=25), [])
        self.assertEqual(youtube.searches, [])

    def test_score_rejects_large_duration_mismatch(self) -> None:
        candidate = Track("Song", "Artist", 300000, "url")
        target = Track("Song", "Artist", 100000, "target")
        self.assertEqual(score_candidate(candidate, target, has_anchor=True), float("-inf"))

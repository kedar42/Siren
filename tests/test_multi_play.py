import unittest

from siren.commands.play import enqueue_resolved_tracks
from siren.models import Track
from siren.resolver import ResolveResult


class FakePlayer:
    def __init__(self) -> None:
        self.enqueued: list[Track] = []

    async def enqueue(self, track: Track) -> None:
        self.enqueued.append(track)


class MultiPlayTests(unittest.IsolatedAsyncioTestCase):
    async def test_enqueue_resolved_tracks_preserves_single_track_response(self) -> None:
        player = FakePlayer()
        track = Track("Song", "Artist", 100000, "url")

        message = await enqueue_resolved_tracks(player, ResolveResult(track=track))

        self.assertEqual(player.enqueued, [track])
        self.assertEqual(message, "Queued **Song** by *Artist*.")

    async def test_enqueue_resolved_tracks_enqueues_all_tracks_and_uses_summary(self) -> None:
        player = FakePlayer()
        tracks = [Track("Song A", "Artist", 100000, "a"), Track("Song B", "Artist", 110000, "b")]

        message = await enqueue_resolved_tracks(player, ResolveResult(tracks=tracks, message="Queued 2 tracks."))

        self.assertEqual(player.enqueued, tracks)
        self.assertEqual(message, "Queued 2 tracks.")

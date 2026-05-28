import unittest

from siren.config import Settings
from siren.models import Track
from siren.player import GuildPlayer


class FakeBot:
    loop = None


class FakeYouTube:
    pass


def settings() -> Settings:
    return Settings.from_env(
        {
            "DISCORD_TOKEN": "discord-token",
            "SPOTIFY_CLIENT_ID": "spotify-id",
            "SPOTIFY_CLIENT_SECRET": "spotify-secret",
        }
    )


def track(index: int) -> Track:
    return Track(f"Track {index}", "Artist", 1000 * index, f"url-{index}")


class QueueMutationTests(unittest.TestCase):
    def player(self) -> GuildPlayer:
        player = GuildPlayer(FakeBot(), 123, FakeYouTube(), settings())
        player.queue.extend([track(1), track(2), track(3)])
        return player

    def test_remove_queued_uses_one_based_position(self) -> None:
        player = self.player()

        removed = player.remove_queued(2)

        self.assertEqual(removed.title, "Track 2")
        self.assertEqual([item.title for item in player.queue], ["Track 1", "Track 3"])

    def test_remove_queued_rejects_invalid_position(self) -> None:
        player = self.player()

        with self.assertRaises(IndexError):
            player.remove_queued(0)
        with self.assertRaises(IndexError):
            player.remove_queued(4)

    def test_move_queued_uses_one_based_positions(self) -> None:
        player = self.player()

        moved = player.move_queued(3, 1)

        self.assertEqual(moved.title, "Track 3")
        self.assertEqual([item.title for item in player.queue], ["Track 3", "Track 1", "Track 2"])

    def test_move_queued_rejects_invalid_positions(self) -> None:
        player = self.player()

        with self.assertRaises(IndexError):
            player.move_queued(0, 1)
        with self.assertRaises(IndexError):
            player.move_queued(1, 0)
        with self.assertRaises(IndexError):
            player.move_queued(4, 1)
        with self.assertRaises(IndexError):
            player.move_queued(1, 4)

    def test_clear_queue_returns_removed_count(self) -> None:
        player = self.player()

        removed = player.clear_queue()

        self.assertEqual(removed, 3)
        self.assertEqual(list(player.queue), [])

    def test_shuffle_queue_keeps_same_tracks(self) -> None:
        player = self.player()

        shuffled = player.shuffle_queue(seed=1)

        self.assertEqual(shuffled, 3)
        self.assertCountEqual([item.title for item in player.queue], ["Track 1", "Track 2", "Track 3"])
        self.assertNotEqual([item.title for item in player.queue], ["Track 1", "Track 2", "Track 3"])


if __name__ == "__main__":
    unittest.main()

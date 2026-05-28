import unittest
from collections import deque
from datetime import datetime

from siren.commands.queue import format_queue_message
from siren.models import Track


class FakeVoice:
    def __init__(self, playing: bool = False, paused: bool = False) -> None:
        self._playing = playing
        self._paused = paused

    def is_playing(self) -> bool:
        return self._playing

    def is_paused(self) -> bool:
        return self._paused


class FakePlayer:
    def __init__(self) -> None:
        self.current = Track("Current", "Artist", 185000, "current-url")
        self.queue = deque([Track("Next", "Other", 61000, "next-url")])
        self.voice = FakeVoice(playing=True)
        self._elapsed_ms: int | None = 45000
        self._remaining_ms: int | None = 140000

    def current_elapsed_ms(self) -> int | None:
        return self._elapsed_ms

    def current_remaining_ms(self) -> int | None:
        return self._remaining_ms


class QueueCommandTests(unittest.TestCase):
    def test_format_queue_message_includes_current_progress_and_next_estimate(self) -> None:
        now = datetime(2026, 5, 28, 19, 10, 0)
        message = format_queue_message(FakePlayer(), now=now)
        self.assertIn("**Now playing:** Artist — Current `[0:45 / 3:05]`", message)
        self.assertIn("**Up next (1):**", message)
        self.assertIn("`1.` Other — Next `[1:01]` — starts around 7:12 PM", message)

    def test_format_queue_message_uses_paused_state_with_frozen_progress(self) -> None:
        player = FakePlayer()
        player.voice = FakeVoice(paused=True)
        player._elapsed_ms = 90000
        player._remaining_ms = 95000
        now = datetime(2026, 5, 28, 19, 10, 0)

        message = format_queue_message(player, now=now)

        self.assertIn("**Paused:** Artist — Current `[1:30 / 3:05]`", message)
        self.assertIn("starts around 7:11 PM", message)

    def test_format_queue_message_uses_unknown_progress_when_elapsed_missing(self) -> None:
        player = FakePlayer()
        player._elapsed_ms = None
        player._remaining_ms = None
        now = datetime(2026, 5, 28, 19, 10, 0)

        message = format_queue_message(player, now=now)

        self.assertIn("**Now playing:** Artist — Current `[?:?? / 3:05]`", message)
        self.assertIn("starts after unknown time", message)

    def test_format_queue_message_estimates_multiple_items_from_prior_durations(self) -> None:
        player = FakePlayer()
        player.current = None
        player._elapsed_ms = None
        player._remaining_ms = 0
        player.queue = deque(
            [
                Track("First", "Artist", 60000, "first-url"),
                Track("Second", "Artist", 120000, "second-url"),
            ]
        )
        now = datetime(2026, 5, 28, 19, 10, 0)

        message = format_queue_message(player, now=now)

        self.assertIn("`1.` Artist — First `[1:00]` — starts around 7:10 PM", message)
        self.assertIn("`2.` Artist — Second `[2:00]` — starts around 7:11 PM", message)

    def test_format_queue_message_uses_unknown_estimates_after_unknown_duration(self) -> None:
        player = FakePlayer()
        player.current = None
        player._remaining_ms = 0
        player.queue = deque(
            [
                Track("Unknown", "Artist", 0, "unknown-url"),
                Track("Later", "Artist", 120000, "later-url"),
            ]
        )
        now = datetime(2026, 5, 28, 19, 10, 0)

        message = format_queue_message(player, now=now)

        self.assertIn("`1.` Artist — Unknown `[?:??]` — starts around 7:10 PM", message)
        self.assertIn("`2.` Artist — Later `[2:00]` — starts after unknown time", message)

    def test_format_queue_message_uses_original_overflow_text(self) -> None:
        player = FakePlayer()
        player.queue = deque(
            Track(f"Track {index}", "Artist", 60_000, f"url-{index}")
            for index in range(11)
        )
        message = format_queue_message(player, now=datetime(2026, 5, 28, 19, 10, 0))
        self.assertIn("…and 1 more", message)

import asyncio
import unittest
from unittest.mock import patch

from siren.config import Settings
from siren.models import Track
from siren.player import GuildPlayer
from siren.player_registry import PlayerRegistry


class FakeBot:
    loop = None


class FakeYouTube:
    pass


class FakeVoice:
    def __init__(self) -> None:
        self.play_calls = 0
        self.stop_calls = 0
        self.disconnect_calls = 0
        self.disconnected = False

    @property
    def channel(self):
        class Channel:
            members = []

        return Channel()

    def is_connected(self) -> bool:
        return not self.disconnected

    def is_playing(self) -> bool:
        return False

    def is_paused(self) -> bool:
        return False

    def play(self, source, after=None) -> None:
        self.play_calls += 1

    def stop(self) -> None:
        self.stop_calls += 1

    async def disconnect(self) -> None:
        self.disconnected = True
        self.disconnect_calls += 1


class BlockingYouTube:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def resolve_url(self, url: str):
        self.started.set()
        await self.release.wait()
        return Track("Resolved", "Artist", 1000, url), "https://stream.test/audio"


class FailingYouTube:
    async def resolve_url(self, url: str):
        return None


class ImmediateYouTube:
    async def resolve_url(self, url: str):
        return Track(f"Resolved {url}", "Artist", 1000, url), f"stream-{url}"


class StatefulVoice(FakeVoice):
    def __init__(self) -> None:
        super().__init__()
        self.playing = False
        self.after_callbacks = []

    def is_playing(self) -> bool:
        return self.playing

    def play(self, source, after=None) -> None:
        self.playing = True
        self.play_calls += 1
        self.after_callbacks.append(after)


def settings() -> Settings:
    return Settings.from_env(
        {
            "DISCORD_TOKEN": "discord-token",
            "SPOTIFY_CLIENT_ID": "spotify-id",
            "SPOTIFY_CLIENT_SECRET": "spotify-secret",
        }
    )


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class PlayerRegistryTests(unittest.TestCase):
    def test_player_returns_same_instance_for_same_guild(self) -> None:
        registry = PlayerRegistry(FakeBot(), FakeYouTube(), settings())
        first = registry.player(123)
        second = registry.player(123)
        self.assertIs(first, second)
        self.assertIsInstance(first, GuildPlayer)
        self.assertEqual(first.guild_id, 123)

    def test_get_returns_none_for_unknown_guild(self) -> None:
        registry = PlayerRegistry(FakeBot(), FakeYouTube(), settings())
        self.assertIsNone(registry.get(999))


class GuildPlayerTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_elapsed_and_remaining_track_playback_time(self) -> None:
        clock = FakeClock()
        voice = StatefulVoice()
        player = GuildPlayer(FakeBot(), 123, ImmediateYouTube(), settings(), clock=clock)
        player.voice = voice
        player.queue.append(Track("Timed", "Artist", 180000, "timed-url"))

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()):
            await player.play_next()

        clock.advance(42)

        self.assertEqual(player.current_elapsed_ms(), 42000)
        self.assertEqual(player.current_remaining_ms(), 138000)

    async def test_pause_and_resume_freeze_elapsed_time(self) -> None:
        clock = FakeClock()
        voice = StatefulVoice()
        player = GuildPlayer(FakeBot(), 123, ImmediateYouTube(), settings(), clock=clock)
        player.voice = voice
        player.queue.append(Track("Timed", "Artist", 180000, "timed-url"))

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()):
            await player.play_next()

        clock.advance(10)
        player.mark_paused()
        clock.advance(20)
        self.assertEqual(player.current_elapsed_ms(), 10000)

        player.mark_resumed()
        clock.advance(5)
        self.assertEqual(player.current_elapsed_ms(), 15000)

    async def test_timing_is_replaced_for_next_track(self) -> None:
        clock = FakeClock()
        voice = StatefulVoice()
        player = GuildPlayer(FakeBot(), 123, ImmediateYouTube(), settings(), clock=clock)
        player.voice = voice
        player.queue.append(Track("First", "Artist", 180000, "first-url"))

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()):
            await player.play_next()
            clock.advance(30)
            voice.playing = False
            await player.enqueue(Track("Second", "Artist", 90000, "second-url"))

        self.assertEqual(player.current.title, "Second")
        self.assertEqual(player.current_elapsed_ms(), 0)
        clock.advance(3)
        self.assertEqual(player.current_elapsed_ms(), 3000)

    async def test_stop_clears_timing(self) -> None:
        clock = FakeClock()
        voice = StatefulVoice()
        player = GuildPlayer(FakeBot(), 123, ImmediateYouTube(), settings(), clock=clock)
        player.voice = voice
        player.queue.append(Track("Timed", "Artist", 180000, "timed-url"))

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()):
            await player.play_next()

        clock.advance(5)
        await player.stop()

        self.assertIsNone(player.current_elapsed_ms())
        self.assertEqual(player.current_remaining_ms(), 0)

    async def test_stale_after_callback_does_not_clear_new_playback(self) -> None:
        bot = FakeBot()
        bot.loop = asyncio.get_running_loop()
        voice = StatefulVoice()
        player = GuildPlayer(bot, 123, ImmediateYouTube(), settings())
        player.voice = voice

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()):
            player.queue.append(Track("First", "Artist", 1000, "first-url"))
            await player.play_next()
            first_after = voice.after_callbacks[0]

            voice.playing = False
            await player.enqueue(Track("Second", "Artist", 1000, "second-url"))
            self.assertEqual(player.current.title, "Second")
            self.assertEqual(voice.play_calls, 2)

            first_after(None)
            await asyncio.sleep(0.01)

        self.assertEqual(player.current.title, "Second")
        self.assertEqual(voice.play_calls, 2)

    async def test_stop_waits_for_playback_transition_before_clearing_voice(self) -> None:
        youtube = BlockingYouTube()
        voice = FakeVoice()
        player = GuildPlayer(FakeBot(), 123, youtube, settings())
        player.voice = voice
        player.queue.append(Track("Queued", "Artist", 1000, "queued-url"))

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()):
            play_task = asyncio.create_task(player.play_next())
            await youtube.started.wait()

            stop_task = asyncio.create_task(player.stop())
            await asyncio.sleep(0)

            self.assertFalse(stop_task.done())
            self.assertIs(player.voice, voice)
            self.assertFalse(voice.disconnected)

            youtube.release.set()
            await play_task
            await stop_task

        self.assertIsNone(player.voice)
        self.assertTrue(voice.disconnected)

    async def test_failed_tracks_advance_without_recursive_overflow(self) -> None:
        player = GuildPlayer(FakeBot(), 123, FailingYouTube(), settings())
        player.voice = FakeVoice()
        for index in range(1100):
            player.queue.append(Track(f"Track {index}", "Artist", 1000, f"url-{index}"))

        with patch("siren.player.log.warning"):
            await player.play_next()

        self.assertIsNone(player.current)
        self.assertEqual(len(player.queue), 0)

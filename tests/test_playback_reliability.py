import asyncio
import unittest
import warnings
from unittest.mock import patch

from siren.bot import SirenBot
from siren.config import Settings
from siren.models import Track
from siren.player import GuildPlayer
from siren.player_registry import PlayerRegistry


class FakeBot:
    loop = None


class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeVoice:
    def __init__(self) -> None:
        self.play_calls = 0
        self.after_callbacks = []
        self.playing = False
        self.connected = True

    @property
    def channel(self):
        class Channel:
            members = []

        return Channel()

    def is_connected(self) -> bool:
        return self.connected

    def is_playing(self) -> bool:
        return self.playing

    def is_paused(self) -> bool:
        return False

    def play(self, source, after=None) -> None:
        self.play_calls += 1
        self.playing = True
        self.after_callbacks.append(after)

    def stop(self) -> None:
        self.playing = False


class SequencedYouTube:
    def __init__(self, outcomes) -> None:
        self.outcomes = list(outcomes)
        self.urls = []

    async def resolve_url(self, url: str):
        self.urls.append(url)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if outcome is None:
            return None
        return outcome, f"stream-{url}"


class BlockingYouTube:
    def __init__(self, outcome) -> None:
        self.outcome = outcome
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def resolve_url(self, url: str):
        self.started.set()
        await self.release.wait()
        return self.outcome, f"stream-{url}"


def settings() -> Settings:
    return Settings.from_env(
        {
            "DISCORD_TOKEN": "discord-token",
            "SPOTIFY_CLIENT_ID": "spotify-id",
            "SPOTIFY_CLIENT_SECRET": "spotify-secret",
        }
    )


def track(index: int) -> Track:
    return Track(f"Track {index}", "Artist", 180000, f"url-{index}")


class PlaybackReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def _clear_voice_state(self, player: GuildPlayer) -> None:
        result = player.clear_voice_state()
        if asyncio.iscoroutine(result):
            await result

    async def test_failed_extraction_advances_to_next_playable_track(self) -> None:
        voice = FakeVoice()
        player = GuildPlayer(FakeBot(), 123, SequencedYouTube([RuntimeError("yt-dlp failed"), track(2)]), settings())
        player.voice = voice
        player.queue.extend([track(1), track(2)])

        with (
            patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()),
            patch("siren.player.log.exception"),
        ):
            await player.play_next()

        self.assertEqual(player.current, track(2))
        self.assertEqual(voice.play_calls, 1)
        self.assertEqual(list(player.queue), [])

    async def test_ffmpeg_construction_failure_advances_to_next_playable_track(self) -> None:
        voice = FakeVoice()
        player = GuildPlayer(FakeBot(), 123, SequencedYouTube([track(1), track(2)]), settings())
        player.voice = voice
        player.queue.extend([track(1), track(2)])

        with (
            patch("siren.player.discord.FFmpegOpusAudio.from_probe", side_effect=[RuntimeError("probe failed"), object()]),
            patch("siren.player.log.exception"),
        ):
            await player.play_next()

        self.assertEqual(player.current, track(2))
        self.assertEqual(voice.play_calls, 1)
        self.assertEqual(list(player.queue), [])

    async def test_all_failed_queue_clears_current_and_timing(self) -> None:
        clock = FakeClock()
        voice = FakeVoice()
        player = GuildPlayer(
            FakeBot(),
            123,
            SequencedYouTube([None, RuntimeError("yt-dlp failed")]),
            settings(),
            clock=clock,
        )
        player.voice = voice
        player.queue.extend([track(1), track(2)])

        with patch("siren.player.log.exception"), patch("siren.player.log.warning"):
            await player.play_next()

        self.assertIsNone(player.current)
        self.assertIsNone(player.current_elapsed_ms())
        self.assertEqual(player.current_remaining_ms(), 0)
        self.assertFalse(voice.is_playing())

    async def test_bot_voice_disconnect_clears_state_and_ignores_stale_playback_callback(self) -> None:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            bot = SirenBot(settings(), resolver=object())
        bot.loop = asyncio.get_running_loop()
        bot._connection.user = type("User", (), {"id": 42})()
        registry = PlayerRegistry(bot, SequencedYouTube([track(1), track(2)]), settings())
        bot.attach_players(registry)

        player = registry.player(123)
        voice = FakeVoice()
        player.voice = voice
        player.queue.append(track(1))

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()):
            await player.play_next()
            voice.playing = False
            player.mark_paused()
            stale_after = voice.after_callbacks[0]

            guild = type("Guild", (), {"id": 123})()
            member = type("Member", (), {"id": 42, "guild": guild})()
            before = type("VoiceState", (), {"channel": voice.channel})()
            after = type("VoiceState", (), {"channel": None})()

            await bot.on_voice_state_update(member, before, after)

            self.assertIsNone(player.voice)
            self.assertIsNone(player.current)
            self.assertIsNone(player.current_elapsed_ms())
            self.assertEqual(player.current_remaining_ms(), 0)

            player.voice = FakeVoice()
            await player.enqueue(track(2))
            stale_after(None)
            await asyncio.sleep(0.01)

        self.assertEqual(player.current, track(2))
        self.assertEqual(player.voice.play_calls, 1)

    async def test_clear_voice_state_during_extraction_prevents_stale_playback(self) -> None:
        youtube = BlockingYouTube(track(1))
        voice = FakeVoice()
        player = GuildPlayer(FakeBot(), 123, youtube, settings())
        player.voice = voice
        player.queue.append(track(1))

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()):
            play_task = asyncio.create_task(player.play_next())
            await youtube.started.wait()
            cleanup_task = asyncio.create_task(self._clear_voice_state(player))
            await asyncio.sleep(0)
            youtube.release.set()
            await play_task
            await cleanup_task

        self.assertEqual(voice.play_calls, 0)
        self.assertIsNone(player.voice)
        self.assertIsNone(player.current)
        self.assertIsNone(player.current_elapsed_ms())

    async def test_clear_voice_state_during_ffmpeg_probe_prevents_stale_playback(self) -> None:
        voice = FakeVoice()
        probe_started = asyncio.Event()
        release_probe = asyncio.Event()

        async def from_probe(*args, **kwargs):
            probe_started.set()
            await release_probe.wait()
            return object()

        player = GuildPlayer(FakeBot(), 123, SequencedYouTube([track(1)]), settings())
        player.voice = voice
        player.queue.append(track(1))

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", side_effect=from_probe):
            play_task = asyncio.create_task(player.play_next())
            await probe_started.wait()
            cleanup_task = asyncio.create_task(self._clear_voice_state(player))
            await asyncio.sleep(0)
            release_probe.set()
            await play_task
            await cleanup_task

        self.assertEqual(voice.play_calls, 0)
        self.assertIsNone(player.voice)
        self.assertIsNone(player.current)
        self.assertIsNone(player.current_elapsed_ms())


if __name__ == "__main__":
    unittest.main()

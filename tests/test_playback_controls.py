import unittest
from collections import deque

from siren.commands.views import PlaybackControlsView
from siren.commands.nowplaying import NowPlayingCommand
from siren.commands.queue import QueueCommand
from siren.models import Track


class FakePlayers:
    def __init__(self, player=None) -> None:
        self.player = player

    def get(self, guild_id: int):
        return self.player if guild_id == 123 else None


class FakeBot:
    def __init__(self, player=None) -> None:
        self.players = FakePlayers(player)


class FakeVoice:
    def __init__(self, *, playing: bool = False, paused: bool = False, connected: bool = True) -> None:
        self._playing = playing
        self._paused = paused
        self._connected = connected
        self.pause_calls = 0
        self.resume_calls = 0

    def is_playing(self) -> bool:
        return self._playing

    def is_paused(self) -> bool:
        return self._paused

    def is_connected(self) -> bool:
        return self._connected

    def pause(self) -> None:
        self.pause_calls += 1
        self._playing = False
        self._paused = True

    def resume(self) -> None:
        self.resume_calls += 1
        self._playing = True
        self._paused = False


class FakePlayer:
    def __init__(self) -> None:
        self.current = Track("Current", "Artist", 185000, "current-url")
        self.queue = deque([Track("Next", "Other", 61000, "next-url")])
        self.voice = FakeVoice(playing=True)
        self.paused_marks = 0
        self.resumed_marks = 0
        self.skip_calls = 0
        self.stop_calls = 0

    def current_elapsed_ms(self) -> int | None:
        return 45000

    def current_remaining_ms(self) -> int | None:
        return 140000

    def mark_paused(self) -> None:
        self.paused_marks += 1

    def mark_resumed(self) -> None:
        self.resumed_marks += 1

    async def skip(self) -> None:
        self.skip_calls += 1
        self.current = self.queue.popleft() if self.queue else None

    async def stop(self) -> None:
        self.stop_calls += 1
        self.current = None
        self.queue.clear()
        self.voice = None


class FakeMessage:
    def __init__(self) -> None:
        self.edits: list[dict] = []

    async def edit(self, **kwargs) -> None:
        self.edits.append(kwargs)


class FakeResponse:
    def __init__(self) -> None:
        self.messages: list[tuple[str, bool]] = []
        self.sent: list[dict] = []
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def send_message(self, content: str, *, ephemeral: bool = False, **kwargs) -> None:
        self.messages.append((content, ephemeral))
        self.sent.append({"content": content, "ephemeral": ephemeral, **kwargs})
        self._done = True


class FakeInteraction:
    def __init__(self) -> None:
        self.response = FakeResponse()
        self.message = FakeMessage()
        self.guild = None

    async def original_response(self):
        return self.message


class FakeGuild:
    id = 123


class FakeTree:
    def __init__(self) -> None:
        self.commands = {}

    def command(self, *, name: str, description: str):
        def decorator(func):
            self.commands[name] = func
            return func

        return decorator


class FakeCommandPlayers:
    def __init__(self, player) -> None:
        self.player_obj = player

    def player(self, guild_id: int):
        return self.player_obj

    def get(self, guild_id: int):
        return self.player_obj


class FakeCommandBot:
    def __init__(self, player) -> None:
        self.tree = FakeTree()
        self.players = FakeCommandPlayers(player)


class PlaybackControlsTests(unittest.IsolatedAsyncioTestCase):
    async def test_refresh_uses_queue_message_when_not_compact(self) -> None:
        player = FakePlayer()
        view = PlaybackControlsView(FakeBot(player), 123)
        interaction = FakeInteraction()

        await view.handle_refresh(interaction)

        self.assertEqual(interaction.response.messages, [])
        self.assertEqual(len(interaction.message.edits), 1)
        edit = interaction.message.edits[0]
        self.assertIn("**Now playing:** Artist — Current", edit["content"])
        self.assertIn("**Up next (1):**", edit["content"])
        self.assertIs(edit["view"], view)

    async def test_refresh_uses_nowplaying_message_when_compact(self) -> None:
        player = FakePlayer()
        view = PlaybackControlsView(FakeBot(player), 123, compact=True)
        interaction = FakeInteraction()

        await view.handle_refresh(interaction)

        edit = interaction.message.edits[0]
        self.assertEqual(edit["content"], "**Now playing:** Artist — Current `[0:45 / 3:05]`")
        self.assertIs(edit["view"], view)

    async def test_pause_resume_toggles_voice_and_timing_hooks(self) -> None:
        player = FakePlayer()
        view = PlaybackControlsView(FakeBot(player), 123)
        interaction = FakeInteraction()

        await view.handle_pause_resume(interaction)

        self.assertEqual(player.voice.pause_calls, 1)
        self.assertEqual(player.paused_marks, 1)
        self.assertEqual(interaction.response.messages, [])
        self.assertIn("**Paused:** Artist — Current", interaction.message.edits[0]["content"])

        interaction = FakeInteraction()
        await view.handle_pause_resume(interaction)

        self.assertEqual(player.voice.resume_calls, 1)
        self.assertEqual(player.resumed_marks, 1)
        self.assertEqual(interaction.response.messages, [])
        self.assertIn("**Now playing:** Artist — Current", interaction.message.edits[0]["content"])

    async def test_skip_calls_player_skip(self) -> None:
        player = FakePlayer()
        view = PlaybackControlsView(FakeBot(player), 123)
        interaction = FakeInteraction()

        await view.handle_skip(interaction)

        self.assertEqual(player.skip_calls, 1)
        self.assertEqual(interaction.response.messages, [])
        self.assertIn("**Now playing:** Other — Next", interaction.message.edits[0]["content"])
        self.assertNotIn("Current", interaction.message.edits[0]["content"])

    async def test_stop_calls_player_stop(self) -> None:
        player = FakePlayer()
        view = PlaybackControlsView(FakeBot(player), 123)
        interaction = FakeInteraction()

        await view.handle_stop(interaction)

        self.assertEqual(player.stop_calls, 1)
        self.assertEqual(interaction.response.messages, [])
        self.assertEqual(interaction.message.edits[0]["content"], "Queue is empty.")
        self.assertTrue(all(item.disabled for item in view.children))

    async def test_compact_stop_edits_source_message_to_nothing_playing(self) -> None:
        player = FakePlayer()
        view = PlaybackControlsView(FakeBot(player), 123, compact=True)
        interaction = FakeInteraction()

        await view.handle_stop(interaction)

        self.assertEqual(interaction.message.edits[0]["content"], "Nothing playing.")
        self.assertTrue(all(item.disabled for item in view.children))

    async def test_on_timeout_disables_buttons_and_edits_stored_message_view(self) -> None:
        view = PlaybackControlsView(FakeBot(FakePlayer()), 123)
        message = FakeMessage()
        view.message = message

        await view.on_timeout()

        self.assertTrue(all(item.disabled for item in view.children))
        self.assertEqual(message.edits, [{"view": view}])

    async def test_stale_or_invalid_state_sends_ephemeral_error(self) -> None:
        view = PlaybackControlsView(FakeBot(None), 123)
        interaction = FakeInteraction()

        await view.handle_skip(interaction)

        self.assertEqual(interaction.response.messages, [("Nothing playing.", True)])

        player = FakePlayer()
        player.voice = None
        view = PlaybackControlsView(FakeBot(player), 123)
        interaction = FakeInteraction()

        await view.handle_stop(interaction)

        self.assertEqual(player.stop_calls, 0)
        self.assertEqual(interaction.response.messages, [("Not connected.", True)])

    async def test_queue_command_sends_controls_view_when_queue_exists(self) -> None:
        player = FakePlayer()
        bot = FakeCommandBot(player)
        QueueCommand(bot).register()
        interaction = FakeInteraction()
        interaction.guild = FakeGuild()

        await bot.tree.commands["queue"](interaction)

        sent = interaction.response.sent[0]
        self.assertIsInstance(sent["view"], PlaybackControlsView)
        self.assertFalse(sent["view"].compact)
        self.assertIs(sent["view"].message, interaction.message)

    async def test_nowplaying_command_sends_compact_controls_view_when_current_exists(self) -> None:
        player = FakePlayer()
        bot = FakeCommandBot(player)
        NowPlayingCommand(bot).register()
        interaction = FakeInteraction()
        interaction.guild = FakeGuild()

        await bot.tree.commands["nowplaying"](interaction)

        sent = interaction.response.sent[0]
        self.assertIsInstance(sent["view"], PlaybackControlsView)
        self.assertTrue(sent["view"].compact)
        self.assertIs(sent["view"].message, interaction.message)


if __name__ == "__main__":
    unittest.main()

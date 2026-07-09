import asyncio
import unittest

from siren.commands.skip import SkipCommand


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


class FakeVoice:
    def __init__(self, *, playing: bool = False, paused: bool = False) -> None:
        self._playing = playing
        self._paused = paused

    def is_playing(self) -> bool:
        return self._playing

    def is_paused(self) -> bool:
        return self._paused


class BlockingPlayer:
    def __init__(self, response: "FakeResponse", *, active: bool = True) -> None:
        self.voice = FakeVoice(playing=active)
        self.response = response
        self.skip_calls = 0
        self.deferred_before_skip_completed = False

    async def skip(self) -> None:
        self.skip_calls += 1
        await asyncio.sleep(0)
        self.deferred_before_skip_completed = self.response.defer_calls == 1


class FakePlayers:
    def __init__(self, player: BlockingPlayer) -> None:
        self.player_obj = player

    def player(self, guild_id: int) -> BlockingPlayer:
        return self.player_obj


class FakeBot:
    def __init__(self, player: BlockingPlayer) -> None:
        self.tree = FakeTree()
        self.players = FakePlayers(player)


class FakeResponse:
    def __init__(self) -> None:
        self.messages: list[dict] = []
        self.defer_calls = 0
        self._done = False

    def is_done(self) -> bool:
        return self._done

    async def send_message(self, content: str, *, ephemeral: bool = False) -> None:
        self.messages.append({"content": content, "ephemeral": ephemeral})
        self._done = True

    async def defer(self) -> None:
        self.defer_calls += 1
        self._done = True


class FakeFollowup:
    def __init__(self) -> None:
        self.messages: list[dict] = []

    async def send(self, content: str, *, ephemeral: bool = False) -> None:
        self.messages.append({"content": content, "ephemeral": ephemeral})


class FakeInteraction:
    def __init__(self) -> None:
        self.guild = FakeGuild()
        self.response = FakeResponse()
        self.followup = FakeFollowup()


class SkipCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_skip_defers_before_player_skip_completes_and_uses_followup(self) -> None:
        interaction = FakeInteraction()
        player = BlockingPlayer(interaction.response)
        bot = FakeBot(player)
        SkipCommand(bot).register()

        await bot.tree.commands["skip"](interaction)

        self.assertEqual(interaction.response.defer_calls, 1)
        self.assertTrue(player.deferred_before_skip_completed)
        self.assertEqual(interaction.response.messages, [])
        self.assertEqual(interaction.followup.messages, [{"content": "Skipped.", "ephemeral": False}])

    async def test_nothing_playing_remains_ephemeral_and_does_not_defer(self) -> None:
        interaction = FakeInteraction()
        player = BlockingPlayer(interaction.response, active=False)
        bot = FakeBot(player)
        SkipCommand(bot).register()

        await bot.tree.commands["skip"](interaction)

        self.assertEqual(interaction.response.defer_calls, 0)
        self.assertEqual(player.skip_calls, 0)
        self.assertEqual(interaction.response.messages, [{"content": "Nothing playing.", "ephemeral": True}])
        self.assertEqual(interaction.followup.messages, [])


if __name__ == "__main__":
    unittest.main()

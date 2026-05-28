import unittest
import warnings

from siren.bot import SirenBot
from siren.config import Settings


class FakeTree:
    def __init__(self) -> None:
        self.copied_guild_ids = []
        self.synced_guild_ids = []
        self.global_syncs = 0

    def copy_global_to(self, *, guild) -> None:
        self.copied_guild_ids.append(guild.id)

    async def sync(self, *, guild=None):
        if guild is None:
            self.global_syncs += 1
        else:
            self.synced_guild_ids.append(guild.id)


class FakeVoice:
    def __init__(self, channel, *, connected=True, session_id=None) -> None:
        self.channel = channel
        self.connected = connected
        self.session_id = session_id

    def is_connected(self) -> bool:
        return self.connected


class FakePlayer:
    def __init__(self, voice=None, *, current=None) -> None:
        self.voice = voice
        self.current = current
        self.clear_calls = []

    async def clear_voice_state(self, expected_voice=None) -> None:
        self.clear_calls.append(expected_voice)
        self.voice = None
        self.current = None


class FakePlayers:
    def __init__(self, player) -> None:
        self._player = player

    def get(self, guild_id: int):
        return self._player


def make_bot() -> SirenBot:
    settings = Settings(
        discord_token="discord-token",
        guild_ids=[],
        spotify_client_id="spotify-id",
        spotify_client_secret="spotify-secret",
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)
        bot = SirenBot(settings, resolver=object())
    return bot


class BotSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_hook_syncs_globally_when_no_guild_ids_configured(self) -> None:
        settings = Settings(
            discord_token="discord-token",
            guild_ids=[],
            spotify_client_id="spotify-id",
            spotify_client_secret="spotify-secret",
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            bot = SirenBot(settings, resolver=object())
        tree = FakeTree()
        bot._BotBase__tree = tree

        await bot.setup_hook()

        self.assertEqual(tree.global_syncs, 1)
        self.assertEqual(tree.copied_guild_ids, [])
        self.assertEqual(tree.synced_guild_ids, [])

    async def test_setup_hook_syncs_configured_guilds(self) -> None:
        settings = Settings(
            discord_token="discord-token",
            guild_ids=[123, 456],
            spotify_client_id="spotify-id",
            spotify_client_secret="spotify-secret",
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            bot = SirenBot(settings, resolver=object())
        tree = FakeTree()
        bot._BotBase__tree = tree

        await bot.setup_hook()

        self.assertEqual(tree.global_syncs, 0)
        self.assertEqual(tree.copied_guild_ids, [123, 456])
        self.assertEqual(tree.synced_guild_ids, [123, 456])


class BotVoiceStateTests(unittest.IsolatedAsyncioTestCase):
    async def test_bot_self_disconnect_does_not_clear_fresh_voice_in_different_channel(self) -> None:
        bot = make_bot()
        bot._connection.user = type("User", (), {"id": 42})()
        disconnected_channel = object()
        fresh_channel = object()
        fresh_voice = FakeVoice(fresh_channel)
        player = FakePlayer(fresh_voice)
        bot.attach_players(FakePlayers(player))

        guild = type("Guild", (), {"id": 123})()
        member = type("Member", (), {"id": 42, "guild": guild})()
        before = type("VoiceState", (), {"channel": disconnected_channel})()
        after = type("VoiceState", (), {"channel": None})()

        await bot.on_voice_state_update(member, before, after)

        self.assertEqual(player.clear_calls, [])
        self.assertIs(player.voice, fresh_voice)

    async def test_bot_self_disconnect_does_not_clear_connected_fresh_voice_in_same_channel(self) -> None:
        bot = make_bot()
        bot._connection.user = type("User", (), {"id": 42})()
        channel = object()
        fresh_voice = FakeVoice(channel, connected=True)
        player = FakePlayer(fresh_voice)
        bot.attach_players(FakePlayers(player))

        guild = type("Guild", (), {"id": 123})()
        member = type("Member", (), {"id": 42, "guild": guild})()
        before = type("VoiceState", (), {"channel": channel})()
        after = type("VoiceState", (), {"channel": None})()

        await bot.on_voice_state_update(member, before, after)

        self.assertEqual(player.clear_calls, [])
        self.assertIs(player.voice, fresh_voice)

    async def test_bot_self_disconnect_does_not_clear_active_connected_fresh_voice_without_sessions(self) -> None:
        bot = make_bot()
        bot._connection.user = type("User", (), {"id": 42})()
        channel = object()
        fresh_voice = FakeVoice(channel, connected=True)
        current_track = object()
        player = FakePlayer(fresh_voice, current=current_track)
        bot.attach_players(FakePlayers(player))

        guild = type("Guild", (), {"id": 123})()
        member = type("Member", (), {"id": 42, "guild": guild})()
        before = type("VoiceState", (), {"channel": channel})()
        after = type("VoiceState", (), {"channel": None})()

        await bot.on_voice_state_update(member, before, after)

        self.assertEqual(player.clear_calls, [])
        self.assertIs(player.voice, fresh_voice)
        self.assertIs(player.current, current_track)

    async def test_bot_self_disconnect_clears_active_voice_even_if_is_connected_lags(self) -> None:
        bot = make_bot()
        bot._connection.user = type("User", (), {"id": 42})()
        channel = object()
        stale_voice = FakeVoice(channel, connected=True, session_id="old-session")
        current_track = object()
        player = FakePlayer(stale_voice, current=current_track)
        bot.attach_players(FakePlayers(player))

        guild = type("Guild", (), {"id": 123})()
        member = type("Member", (), {"id": 42, "guild": guild})()
        before = type("VoiceState", (), {"channel": channel, "session_id": "old-session"})()
        after = type("VoiceState", (), {"channel": None})()

        await bot.on_voice_state_update(member, before, after)

        self.assertEqual(player.clear_calls, [stale_voice])
        self.assertIsNone(player.voice)
        self.assertIsNone(player.current)

    async def test_bot_self_disconnect_clears_idle_voice_when_session_matches_even_if_connected_lags(self) -> None:
        bot = make_bot()
        bot._connection.user = type("User", (), {"id": 42})()
        channel = object()
        stale_voice = FakeVoice(channel, connected=True, session_id="old-session")
        player = FakePlayer(stale_voice, current=None)
        bot.attach_players(FakePlayers(player))

        guild = type("Guild", (), {"id": 123})()
        member = type("Member", (), {"id": 42, "guild": guild})()
        before = type("VoiceState", (), {"channel": channel, "session_id": "old-session"})()
        after = type("VoiceState", (), {"channel": None})()

        await bot.on_voice_state_update(member, before, after)

        self.assertEqual(player.clear_calls, [stale_voice])
        self.assertIsNone(player.voice)

    async def test_bot_self_disconnect_does_not_clear_active_fresh_voice_with_different_session(self) -> None:
        bot = make_bot()
        bot._connection.user = type("User", (), {"id": 42})()
        channel = object()
        fresh_voice = FakeVoice(channel, connected=True, session_id="fresh-session")
        current_track = object()
        player = FakePlayer(fresh_voice, current=current_track)
        bot.attach_players(FakePlayers(player))

        guild = type("Guild", (), {"id": 123})()
        member = type("Member", (), {"id": 42, "guild": guild})()
        before = type("VoiceState", (), {"channel": channel, "session_id": "old-session"})()
        after = type("VoiceState", (), {"channel": None})()

        await bot.on_voice_state_update(member, before, after)

        self.assertEqual(player.clear_calls, [])
        self.assertIs(player.voice, fresh_voice)
        self.assertIs(player.current, current_track)

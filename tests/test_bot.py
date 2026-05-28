import unittest

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


class BotSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_setup_hook_syncs_globally_when_no_guild_ids_configured(self) -> None:
        settings = Settings(
            discord_token="discord-token",
            guild_ids=[],
            spotify_client_id="spotify-id",
            spotify_client_secret="spotify-secret",
        )
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
        bot = SirenBot(settings, resolver=object())
        tree = FakeTree()
        bot._BotBase__tree = tree

        await bot.setup_hook()

        self.assertEqual(tree.global_syncs, 0)
        self.assertEqual(tree.copied_guild_ids, [123, 456])
        self.assertEqual(tree.synced_guild_ids, [123, 456])

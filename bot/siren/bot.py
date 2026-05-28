from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .config import Settings
from .player_registry import PlayerRegistry
from .resolver import TrackResolver

log = logging.getLogger("siren")


class SirenBot(commands.Bot):
    def __init__(self, settings: Settings, resolver: TrackResolver) -> None:
        intents = discord.Intents.default()
        intents.message_content = False
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.resolver = resolver
        self.players: PlayerRegistry | None = None

    def attach_players(self, players: PlayerRegistry) -> None:
        self.players = players

    async def setup_hook(self) -> None:
        if not self.settings.guild_ids:
            await self.tree.sync()
            log.info("Synced commands globally")
            return

        for guild_id in self.settings.guild_ids:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to guild %s", guild_id)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")

    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if self.user is not None and member.id == self.user.id:
            if before.channel is not None and after.channel is None and self.players is not None:
                player = self.players.get(member.guild.id)
                if player is not None:
                    disconnected_voice = player.voice
                    before_session_id = getattr(before, "session_id", None)
                    voice_session_id = getattr(disconnected_voice, "session_id", None)
                    has_session_identity = before_session_id is not None and voice_session_id is not None
                    session_matches = has_session_identity and before_session_id == voice_session_id
                    should_clear = session_matches or (
                        not has_session_identity
                        and disconnected_voice is not None
                        and (not disconnected_voice.is_connected() or player.current is not None)
                    )
                    if (
                        disconnected_voice is not None
                        and disconnected_voice.channel == before.channel
                        and should_clear
                    ):
                        await player.clear_voice_state(disconnected_voice)
            return
        if self.players is None:
            return
        player = self.players.get(member.guild.id)
        if not player or not player.voice or not player.voice.is_connected():
            return
        bot_channel = player.voice.channel
        if before.channel != bot_channel and after.channel != bot_channel:
            return
        player.reconcile_idle()

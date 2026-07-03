from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from ..player import GuildPlayer

if TYPE_CHECKING:
    from ..bot import SirenBot

log = logging.getLogger("siren")


class CommandBase:
    def __init__(self, bot: "SirenBot") -> None:
        self.bot = bot

    async def guild_or_reply(self, interaction: discord.Interaction) -> discord.Guild | None:
        if interaction.guild is None:
            await self._send(interaction, "DMs aren't supported.", ephemeral=True)
            return None
        return interaction.guild

    def player_for(self, guild_id: int) -> GuildPlayer:
        if self.bot.players is None:
            raise RuntimeError("Player registry is not attached")
        return self.bot.players.player(guild_id)

    async def ensure_voice(self, interaction: discord.Interaction) -> GuildPlayer | None:
        guild = await self.guild_or_reply(interaction)
        if guild is None:
            return None
        if not isinstance(interaction.user, discord.Member):
            await self._send(interaction, "DMs aren't supported.", ephemeral=True)
            return None
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            await self._send(interaction, "Join a voice channel first.", ephemeral=True)
            return None

        channel = interaction.user.voice.channel
        player = self.player_for(guild.id)
        if (player.voice is None or not player.voice.is_connected()) and guild.voice_client is not None:
            player.voice = guild.voice_client  # type: ignore[assignment]
        if player.voice is None or not player.voice.is_connected():
            log.info("[voice guild=%s] connecting to channel=%s", guild.id, channel.id)
            try:
                player.voice = await channel.connect(self_deaf=True, timeout=30.0)
            except Exception as exc:
                log.exception("[voice guild=%s] connect failed: %s", guild.id, exc)
                await self._send(interaction, f"Voice connect failed: `{exc}`")
                return None
            log.info("[voice guild=%s] connected", guild.id)
        elif player.voice.channel.id != channel.id:
            log.info("[voice guild=%s] moving %s -> %s", guild.id, player.voice.channel.id, channel.id)
            await player.voice.move_to(channel)
        return player

    async def _send(self, interaction: discord.Interaction, message: str, *, ephemeral: bool = False) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(message, ephemeral=ephemeral)

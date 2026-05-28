from __future__ import annotations

import logging

import discord

from .base import CommandBase

log = logging.getLogger("siren")


class PauseCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="pause", description="Pause playback.")
        async def pause(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if not player.voice or not player.voice.is_playing():
                await interaction.response.send_message("Nothing playing.", ephemeral=True)
                return
            player.voice.pause()
            player.mark_paused()
            log.info("[player %s] paused", player.tag)
            await interaction.response.send_message("Paused.")

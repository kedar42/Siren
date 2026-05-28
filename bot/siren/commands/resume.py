from __future__ import annotations

import logging

import discord

from .base import CommandBase

log = logging.getLogger("siren")


class ResumeCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="resume", description="Resume paused playback.")
        async def resume(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if not player.voice or not player.voice.is_paused():
                await interaction.response.send_message("Not paused.", ephemeral=True)
                return
            player.voice.resume()
            player.mark_resumed()
            log.info("[player %s] resumed", player.tag)
            await interaction.response.send_message("Resumed.")

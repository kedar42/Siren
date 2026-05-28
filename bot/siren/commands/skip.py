from __future__ import annotations

import discord

from .base import CommandBase


class SkipCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="skip", description="Skip the current track.")
        async def skip(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if not player.voice or not (player.voice.is_playing() or player.voice.is_paused()):
                await interaction.response.send_message("Nothing playing.", ephemeral=True)
                return
            await interaction.response.defer()
            await player.skip()
            await interaction.followup.send("Skipped.")

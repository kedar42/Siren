from __future__ import annotations

import discord

from .base import CommandBase


class StopCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="stop", description="Stop and disconnect.")
        async def stop(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if player.voice is None:
                await interaction.response.send_message("Not connected.", ephemeral=True)
                return
            await player.stop()
            await interaction.response.send_message("Bye.")

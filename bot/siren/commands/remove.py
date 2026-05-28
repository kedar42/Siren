from __future__ import annotations

import discord
from discord import app_commands

from .base import CommandBase


class RemoveCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="remove", description="Remove a queued track by position.")
        @app_commands.describe(position="The 1-based queued position to remove.")
        async def remove(interaction: discord.Interaction, position: int) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if not player.queue:
                await interaction.response.send_message("Queue is empty.", ephemeral=True)
                return
            try:
                track = player.remove_queued(position)
            except IndexError:
                await interaction.response.send_message(
                    f"Position must be between 1 and {len(player.queue)}.", ephemeral=True
                )
                return
            await interaction.response.send_message(f"Removed **{track.title}** by *{track.author}*.")

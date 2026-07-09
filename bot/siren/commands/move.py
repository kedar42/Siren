from __future__ import annotations

import discord
from discord import app_commands

from .base import CommandBase


class MoveCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="move", description="Move a queued track to another position.")
        @app_commands.describe(
            from_position="The 1-based queued position to move from.",
            to_position="The 1-based queued position to move to.",
        )
        async def move(interaction: discord.Interaction, from_position: int, to_position: int) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if not player.queue:
                await interaction.response.send_message("Queue is empty.", ephemeral=True)
                return
            try:
                track = player.move_queued(from_position, to_position)
            except IndexError:
                await interaction.response.send_message(
                    f"Position must be between 1 and {len(player.queue)}.", ephemeral=True
                )
                return
            await interaction.response.send_message(f"Moved **{track.title}** to position {to_position}.")

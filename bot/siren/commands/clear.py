from __future__ import annotations

import discord

from .base import CommandBase


class ClearCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="clear", description="Clear queued tracks without stopping playback.")
        async def clear(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if not player.queue:
                await interaction.response.send_message("Queue is empty.", ephemeral=True)
                return
            count = player.clear_queue()
            await interaction.response.send_message(f"Cleared {count} queued tracks.")

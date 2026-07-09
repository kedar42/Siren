from __future__ import annotations

import discord

from .base import CommandBase


class ShuffleCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="shuffle", description="Shuffle queued tracks.")
        async def shuffle(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if not player.queue:
                await interaction.response.send_message("Queue is empty.", ephemeral=True)
                return
            count = player.shuffle_queue()
            await interaction.response.send_message(f"Shuffled {count} queued tracks.")

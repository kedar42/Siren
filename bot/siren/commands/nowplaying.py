from __future__ import annotations

import discord

from .base import CommandBase
from .queue import format_nowplaying_message


class NowPlayingCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="nowplaying", description="Show the current track.")
        async def nowplaying(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if player.current is None:
                await interaction.response.send_message(format_nowplaying_message(player), ephemeral=True)
                return
            await interaction.response.send_message(format_nowplaying_message(player))

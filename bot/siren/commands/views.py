from __future__ import annotations

from typing import TYPE_CHECKING, Any

import discord

from .queue import format_nowplaying_message, format_queue_message

if TYPE_CHECKING:
    from ..bot import SirenBot
    from ..player import GuildPlayer


class PlaybackControlsView(discord.ui.View):
    def __init__(self, bot: SirenBot, guild_id: int, *, compact: bool = False) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.compact = compact

    def player(self) -> GuildPlayer | None:
        return self.bot.players.get(self.guild_id) if self.bot.players else None

    async def _send_error(self, interaction: discord.Interaction, message: str) -> None:
        await interaction.response.send_message(message, ephemeral=True)

    async def _edit_message(self, interaction: discord.Interaction, content: str) -> None:
        response = interaction.response
        if hasattr(response, "edit_message"):
            await response.edit_message(content=content, view=self)
            return
        message = getattr(interaction, "message", None)
        if message is not None:
            await message.edit(content=content, view=self)

    async def handle_pause_resume(self, interaction: discord.Interaction) -> None:
        player = self.player()
        if player is None or player.current is None or player.voice is None:
            await self._send_error(interaction, "Nothing playing.")
            return
        if player.voice.is_playing():
            player.voice.pause()
            player.mark_paused()
            await interaction.response.send_message("Paused.", ephemeral=True)
            return
        if player.voice.is_paused():
            player.voice.resume()
            player.mark_resumed()
            await interaction.response.send_message("Resumed.", ephemeral=True)
            return
        await self._send_error(interaction, "Nothing playing.")

    async def handle_skip(self, interaction: discord.Interaction) -> None:
        player = self.player()
        if (
            player is None
            or player.current is None
            or player.voice is None
            or not (player.voice.is_playing() or player.voice.is_paused())
        ):
            await self._send_error(interaction, "Nothing playing.")
            return
        await player.skip()
        await interaction.response.send_message("Skipped.", ephemeral=True)

    async def handle_stop(self, interaction: discord.Interaction) -> None:
        player = self.player()
        if player is None or player.voice is None or not player.voice.is_connected():
            await self._send_error(interaction, "Not connected.")
            return
        await player.stop()
        await interaction.response.send_message("Stopped.", ephemeral=True)

    async def handle_refresh(self, interaction: discord.Interaction) -> None:
        player = self.player()
        if player is None:
            await self._send_error(interaction, "Nothing playing." if self.compact else "Queue is empty.")
            return
        if self.compact:
            if player.current is None:
                await self._send_error(interaction, "Nothing playing.")
                return
            content = format_nowplaying_message(player)
        else:
            if player.current is None and not player.queue:
                await self._send_error(interaction, "Queue is empty.")
                return
            content = format_queue_message(player)
        await self._edit_message(interaction, content)

    @discord.ui.button(label="Pause/Resume", style=discord.ButtonStyle.secondary)
    async def pause_resume(self, interaction: discord.Interaction, _button: discord.ui.Button[Any]) -> None:
        await self.handle_pause_resume(interaction)

    @discord.ui.button(label="Skip", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, _button: discord.ui.Button[Any]) -> None:
        await self.handle_skip(interaction)

    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, _button: discord.ui.Button[Any]) -> None:
        await self.handle_stop(interaction)

    @discord.ui.button(label="Refresh", style=discord.ButtonStyle.secondary)
    async def refresh(self, interaction: discord.Interaction, _button: discord.ui.Button[Any]) -> None:
        await self.handle_refresh(interaction)

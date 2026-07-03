from __future__ import annotations

import re
from dataclasses import dataclass

import discord
from discord import app_commands

from .base import CommandBase

_TIMECODE_RE = re.compile(r"^(\d+):(\d{2})(?::(\d{2}))?$")
_RELATIVE_RE = re.compile(r"^([+-])(\d+)$")


@dataclass(frozen=True)
class SeekTarget:
    offset_ms: int
    relative: bool


def parse_seek_input(text: str) -> SeekTarget | None:
    text = text.strip()
    m = _RELATIVE_RE.match(text)
    if m:
        sign = 1 if m.group(1) == "+" else -1
        return SeekTarget(offset_ms=sign * int(m.group(2)) * 1000, relative=True)
    m = _TIMECODE_RE.match(text)
    if m:
        if m.group(3) is not None:
            hours, minutes, seconds = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            hours, minutes, seconds = 0, int(m.group(1)), int(m.group(2))
        return SeekTarget(offset_ms=(hours * 3600 + minutes * 60 + seconds) * 1000, relative=False)
    return None


class SeekCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="seek", description="Seek to a position in the current track.")
        @app_commands.describe(position="Timecode (2:30) or relative offset (+30 / -10 seconds).")
        async def seek(interaction: discord.Interaction, position: str) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if not player.voice or not (player.voice.is_playing() or player.voice.is_paused()):
                await interaction.response.send_message("Nothing playing.", ephemeral=True)
                return

            target = parse_seek_input(position)
            if target is None:
                await interaction.response.send_message(
                    "Invalid position. Use a timecode like `2:30`, or a relative offset like `+30` or `-10`.",
                    ephemeral=True,
                )
                return

            current_track = player.current                                 # C5: snapshot before defer
            current_ms = player.current_elapsed_ms() or 0
            duration_ms = current_track.duration_ms if current_track else 0

            position_ms = (current_ms + target.offset_ms) if target.relative else target.offset_ms
            position_ms = max(0, position_ms)
            if duration_ms > 0:
                position_ms = min(position_ms, duration_ms)

            await interaction.response.defer()
            expected_url = current_track.webpage_url if current_track else None
            ok = await player.seek(position_ms, expected_url=expected_url)
            if not ok:
                await interaction.followup.send("Seek failed.", ephemeral=True)
                return
            total_seconds = position_ms // 1000
            label = f"{total_seconds // 60}:{total_seconds % 60:02d}"
            await interaction.followup.send(f"Seeked to **{label}**.")

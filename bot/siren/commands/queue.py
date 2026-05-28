from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import discord

from ..models import fmt_duration
from .base import CommandBase

QUEUE_PREVIEW_LIMIT = 10
UNKNOWN_START_TEXT = "starts after unknown time"


def fmt_position(ms: int) -> str:
    seconds = max(0, ms) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def fmt_clock(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def current_progress(player: Any) -> str:
    if player.current is None:
        return ""
    elapsed_ms = player.current_elapsed_ms()
    elapsed = fmt_position(elapsed_ms) if elapsed_ms is not None else "?:??"
    return f"{elapsed} / {fmt_duration(player.current.duration_ms)}"


def start_estimate(now: datetime, offset_ms: int | None) -> str:
    if offset_ms is None:
        return UNKNOWN_START_TEXT
    return f"starts around {fmt_clock(now + timedelta(milliseconds=offset_ms))}"


def format_queue_message(player: Any, *, now: datetime | None = None) -> str:
    now = now or datetime.now().astimezone()
    lines: list[str] = []
    if player.current is not None:
        if player.voice and player.voice.is_paused():
            state = "Paused"
        elif player.voice and player.voice.is_playing():
            state = "Now playing"
        else:
            state = "Loading"
        lines.append(
            f"**{state}:** {player.current.author} — {player.current.title} "
            f"`[{current_progress(player)}]`"
        )

    offset_ms: int | None
    if player.current is None:
        offset_ms = 0
    else:
        offset_ms = player.current_remaining_ms()

    if player.queue:
        lines.append("")
        lines.append(f"**Up next ({len(player.queue)}):**")
        for index, track in enumerate(list(player.queue)[:QUEUE_PREVIEW_LIMIT], start=1):
            lines.append(
                f"`{index}.` {track.author} — {track.title} `[{fmt_duration(track.duration_ms)}]` "
                f"— {start_estimate(now, offset_ms)}"
            )
            if offset_ms is not None:
                if track.duration_ms > 0:
                    offset_ms += track.duration_ms
                else:
                    offset_ms = None
        remaining = len(player.queue) - QUEUE_PREVIEW_LIMIT
        if remaining > 0:
            lines.append(f"…and {remaining} more")

    return "\n".join(lines)


def format_nowplaying_message(player: Any) -> str:
    if player.current is None:
        return "Nothing playing."
    if player.voice and player.voice.is_paused():
        state = "Paused"
    elif player.voice and player.voice.is_playing():
        state = "Now playing"
    else:
        state = "Loading"
    return f"**{state}:** {player.current.author} — {player.current.title} `[{current_progress(player)}]`"


class QueueCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="queue", description="Show what's playing and what's queued.")
        async def queue_cmd(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if player.current is None and not player.queue:
                await interaction.response.send_message("Queue is empty.", ephemeral=True)
                return
            await interaction.response.send_message(format_queue_message(player))

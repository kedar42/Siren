from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands

from ..models import Track, fmt_duration
from .base import CommandBase

log = logging.getLogger("siren")

MAX_AUTOCOMPLETE_CHOICES = 25
DISCORD_CHOICE_NAME_LIMIT = 100
DISCORD_CHOICE_VALUE_LIMIT = 100
AUTOCOMPLETE_TIMEOUT_SECONDS = 2.5


def choice_label(track: Track) -> str:
    label = f"{track.author} - {track.title}" if track.author else track.title
    duration = fmt_duration(track.duration_ms)
    if duration != "?:??":
        label = f"{label} [{duration}]"
    if len(label) > DISCORD_CHOICE_NAME_LIMIT:
        label = label[: DISCORD_CHOICE_NAME_LIMIT - 3] + "..."
    return label


def tracks_to_choices(tracks: list[Track]) -> list[app_commands.Choice[str]]:
    choices: list[app_commands.Choice[str]] = []
    seen_values: set[str] = set()
    for track in tracks:
        if not track.webpage_url or len(track.webpage_url) > DISCORD_CHOICE_VALUE_LIMIT:
            continue
        if track.webpage_url in seen_values:
            continue
        seen_values.add(track.webpage_url)
        choices.append(app_commands.Choice(name=choice_label(track), value=track.webpage_url))
        if len(choices) >= MAX_AUTOCOMPLETE_CHOICES:
            break
    return choices


async def autocomplete_tracks(
    resolver: object,
    current: str,
    *,
    limit: int = MAX_AUTOCOMPLETE_CHOICES,
    timeout_seconds: float = AUTOCOMPLETE_TIMEOUT_SECONDS,
) -> list[Track]:
    try:
        return await asyncio.wait_for(resolver.autocomplete(current, limit=limit), timeout=timeout_seconds)
    except TimeoutError:
        log.warning("[autocomplete] timed out for %r", current)
        return []
    except Exception as exc:
        log.warning("[autocomplete] failed for %r: %s", current, exc)
        return []


class PlayCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="play", description="Play a song. URL or 'artist - title'.")
        @app_commands.describe(query="A URL (Spotify/YouTube/SoundCloud) or text search.")
        @app_commands.autocomplete(query=self.autocomplete_query)
        async def play(interaction: discord.Interaction, query: str) -> None:
            await interaction.response.defer()
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            async with player.play_lock:
                if await self.ensure_voice(interaction) is None:
                    return
                result = await self.bot.resolver.resolve(query)
                if not result.ok:
                    await interaction.followup.send(result.message or f"Couldn't resolve `{query}`.")
                    return
                assert result.track is not None
                await player.enqueue(result.track)
                await interaction.followup.send(f"Queued **{result.track.title}** by *{result.track.author}*.")

    async def autocomplete_query(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        del interaction
        tracks = await autocomplete_tracks(self.bot.resolver, current, limit=MAX_AUTOCOMPLETE_CHOICES)
        return tracks_to_choices(tracks)

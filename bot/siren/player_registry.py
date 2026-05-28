from __future__ import annotations

from typing import Any

from .config import Settings
from .player import GuildPlayer
from .youtube import YouTubeService


class PlayerRegistry:
    def __init__(self, bot: Any, youtube: YouTubeService, settings: Settings) -> None:
        self._bot = bot
        self._youtube = youtube
        self._settings = settings
        self._players: dict[int, GuildPlayer] = {}

    def player(self, guild_id: int) -> GuildPlayer:
        player = self._players.get(guild_id)
        if player is None:
            player = GuildPlayer(self._bot, guild_id, self._youtube, self._settings)
            self._players[guild_id] = player
        return player

    def get(self, guild_id: int) -> GuildPlayer | None:
        return self._players.get(guild_id)

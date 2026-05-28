from __future__ import annotations

import logging

from .bot import SirenBot
from .commands import register_commands
from .config import Settings, load_settings
from .player_registry import PlayerRegistry
from .resolver import TrackResolver
from .spotify import SpotifyService
from .youtube import YouTubeService


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)


def create_bot(settings: Settings | None = None) -> SirenBot:
    settings = settings or load_settings()
    spotify = SpotifyService(settings)
    youtube = YouTubeService(settings)
    resolver = TrackResolver(spotify, youtube)
    bot = SirenBot(settings, resolver)
    players = PlayerRegistry(bot, youtube, settings)
    bot.attach_players(players)
    register_commands(bot)
    return bot

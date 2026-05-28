from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

class ConfigError(RuntimeError):
    pass


FFMPEG_BEFORE_OPTIONS = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
    "-nostdin -loglevel warning"
)
FFMPEG_OPTIONS = "-vn"
DEFAULT_IDLE_TIMEOUT_SECONDS = 300
LOG_LEVEL_NAMES = ("CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG", "NOTSET")


@dataclass(frozen=True)
class Settings:
    discord_token: str
    guild_ids: list[int]
    spotify_client_id: str
    spotify_client_secret: str
    yt_cookies_file: str | None = None
    log_level: str = "INFO"
    idle_timeout_seconds: int = DEFAULT_IDLE_TIMEOUT_SECONDS
    ffmpeg_before_options: str = FFMPEG_BEFORE_OPTIONS
    ffmpeg_options: str = FFMPEG_OPTIONS

    def __post_init__(self) -> None:
        log_level = self.log_level.upper()
        if log_level not in LOG_LEVEL_NAMES:
            raise ConfigError(f"LOG_LEVEL must be one of: {', '.join(LOG_LEVEL_NAMES)}")
        object.__setattr__(self, "log_level", log_level)

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        source = os.environ if env is None else env
        required = ["DISCORD_TOKEN", "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"]
        missing = [name for name in required if not source.get(name)]
        if missing:
            raise ConfigError("Missing required environment variables: " + ", ".join(missing))

        guild_ids: list[int] = []
        raw_guild_ids = source.get("DISCORD_GUILD_IDS", "")
        for raw in [part.strip() for part in raw_guild_ids.split(",") if part.strip()]:
            try:
                guild_ids.append(int(raw))
            except ValueError as exc:
                raise ConfigError(f"DISCORD_GUILD_IDS contains a non-integer value: {raw}") from exc

        return cls(
            discord_token=source["DISCORD_TOKEN"],
            guild_ids=guild_ids,
            spotify_client_id=source["SPOTIFY_CLIENT_ID"],
            spotify_client_secret=source["SPOTIFY_CLIENT_SECRET"],
            yt_cookies_file=source.get("YT_COOKIES_FILE") or None,
            log_level=source.get("LOG_LEVEL", "INFO"),
        )

    @property
    def ytdl_base_options(self) -> dict[str, object]:
        options: dict[str, object] = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "noplaylist": True,
            "source_address": "0.0.0.0",
        }
        if self.yt_cookies_file:
            options["cookiefile"] = self.yt_cookies_file
        return options

    @property
    def ytdl_search_options(self) -> dict[str, object]:
        return {**self.ytdl_base_options, "extract_flat": "in_playlist"}

    @property
    def ytdl_resolve_options(self) -> dict[str, object]:
        return {**self.ytdl_base_options, "format": "bestaudio/best"}


def load_settings() -> Settings:
    return Settings.from_env()

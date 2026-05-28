import logging
import unittest
from unittest.mock import Mock, patch

from siren.config import Settings


VALID_SETTINGS = Settings(
    discord_token="discord-token",
    guild_ids=[123],
    spotify_client_id="spotify-id",
    spotify_client_secret="spotify-secret",
    log_level="DEBUG",
)


class AppFactoryTests(unittest.TestCase):
    def test_create_bot_wires_services_players_and_commands(self) -> None:
        with (
            patch("siren.app.SpotifyService") as spotify_cls,
            patch("siren.app.YouTubeService") as youtube_cls,
            patch("siren.app.TrackResolver") as resolver_cls,
            patch("siren.app.SirenBot") as bot_cls,
            patch("siren.app.PlayerRegistry") as registry_cls,
            patch("siren.app.register_commands") as register_commands,
            patch("siren.app.configure_logging") as configure_logging,
        ):
            bot = bot_cls.return_value

            from siren.app import create_bot

            result = create_bot(VALID_SETTINGS)

        spotify_cls.assert_called_once_with(VALID_SETTINGS)
        youtube_cls.assert_called_once_with(VALID_SETTINGS)
        resolver_cls.assert_called_once_with(spotify_cls.return_value, youtube_cls.return_value)
        bot_cls.assert_called_once_with(VALID_SETTINGS, resolver_cls.return_value)
        registry_cls.assert_called_once_with(bot, youtube_cls.return_value, VALID_SETTINGS)
        bot.attach_players.assert_called_once_with(registry_cls.return_value)
        register_commands.assert_called_once_with(bot)
        self.assertIs(result, bot)
        configure_logging.assert_not_called()

    def test_configure_logging_sets_yt_dlp_to_warning(self) -> None:
        from siren.app import configure_logging

        configure_logging(VALID_SETTINGS)

        self.assertEqual(logging.getLogger("yt_dlp").level, logging.WARNING)


if __name__ == "__main__":
    unittest.main()

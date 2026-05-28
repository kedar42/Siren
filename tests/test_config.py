import unittest
from unittest.mock import patch

from siren.config import ConfigError, Settings


VALID_ENV = {
    "DISCORD_TOKEN": "discord-token",
    "DISCORD_GUILD_IDS": "123,456",
    "SPOTIFY_CLIENT_ID": "spotify-id",
    "SPOTIFY_CLIENT_SECRET": "spotify-secret",
    "LOG_LEVEL": "DEBUG",
}


class SettingsTests(unittest.TestCase):
    def test_from_env_parses_required_values(self) -> None:
        settings = Settings.from_env(VALID_ENV)
        self.assertEqual(settings.discord_token, "discord-token")
        self.assertEqual(settings.guild_ids, [123, 456])
        self.assertEqual(settings.spotify_client_id, "spotify-id")
        self.assertEqual(settings.spotify_client_secret, "spotify-secret")
        self.assertEqual(settings.log_level, "DEBUG")
        self.assertIsNone(settings.yt_cookies_file)
        self.assertEqual(settings.idle_timeout_seconds, 300)

    def test_from_env_raises_clear_error_for_missing_required_values(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            Settings.from_env({})
        message = str(ctx.exception)
        self.assertIn("DISCORD_TOKEN", message)
        self.assertIn("SPOTIFY_CLIENT_ID", message)
        self.assertIn("SPOTIFY_CLIENT_SECRET", message)

    def test_from_env_rejects_invalid_guild_id(self) -> None:
        env = {**VALID_ENV, "DISCORD_GUILD_IDS": "123,nope"}
        with self.assertRaises(ConfigError) as ctx:
            Settings.from_env(env)
        self.assertIn("DISCORD_GUILD_IDS", str(ctx.exception))

    def test_from_env_rejects_invalid_log_level(self) -> None:
        env = {**VALID_ENV, "LOG_LEVEL": "NOPE"}
        with self.assertRaises(ConfigError) as ctx:
            Settings.from_env(env)
        self.assertIn("LOG_LEVEL", str(ctx.exception))

    def test_direct_settings_rejects_invalid_log_level(self) -> None:
        with self.assertRaises(ConfigError) as ctx:
            Settings(
                discord_token="discord-token",
                guild_ids=[],
                spotify_client_id="spotify-id",
                spotify_client_secret="spotify-secret",
                log_level="NOPE",
            )
        self.assertIn("LOG_LEVEL", str(ctx.exception))

    def test_ytdl_options_include_cookiefile_only_when_set(self) -> None:
        without_cookie = Settings.from_env(VALID_ENV)
        self.assertNotIn("cookiefile", without_cookie.ytdl_base_options)

        with_cookie = Settings.from_env({**VALID_ENV, "YT_COOKIES_FILE": "/app/data/cookies.txt"})
        self.assertEqual(with_cookie.ytdl_base_options["cookiefile"], "/app/data/cookies.txt")

    def test_load_settings_does_not_read_dotenv(self) -> None:
        from siren.config import load_settings

        with patch.dict("os.environ", {}, clear=True), patch("dotenv.main.load_dotenv") as load_dotenv:
            with self.assertRaises(ConfigError):
                load_settings()

        load_dotenv.assert_not_called()

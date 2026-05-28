from siren.app import configure_logging, create_bot
from siren.config import ConfigError, load_settings


def main() -> None:
    try:
        settings = load_settings()
        configure_logging(settings)
        bot = create_bot(settings)
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc
    bot.run(bot.settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()

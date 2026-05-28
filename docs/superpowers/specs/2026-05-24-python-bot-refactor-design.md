# SirenBot Refactor Design

Date: 2026-05-24

## Goal

Refactor the current single-file Python Discord music bot into SirenBot: a clearer, testable, object-oriented module structure while preserving the existing runtime model of Discord voice playback, Spotify-anchored metadata resolution, yt-dlp extraction, and ffmpeg streaming.

The refactor includes small correctness fixes discovered during assessment, but it does not add new product features such as persistence, embeds, filters, or SQLite caching.

## Current State

The implementation lives almost entirely in `bot/main.py`. It contains configuration loading, Spotify access, YouTube search and extraction, scoring, queue state, Discord command handlers, bot lifecycle hooks, and startup code.

The behavior is understandable, but the boundaries are too broad. This makes future changes harder to reason about and harder to test without running the whole bot.

## Scope

Included:

- Split `bot/main.py` into focused modules under `bot/siren/`.
- Use command-per-module files under `bot/siren/commands/`.
- Make SirenBot the canonical name in code, README branding, loggers, and Docker-visible names.
- Prefer small service classes with explicit dependencies over global clients and free-floating helper clusters.
- Keep `bot/main.py` as a small startup entrypoint.
- Preserve Docker and docker-compose runtime behavior while allowing visible names such as `container_name` to use SirenBot/Siren naming.
- Keep current dependencies unless a direct refactor requires a small adjustment.
- Fix Spotify album/playlist URL handling.
- Replace guild-only `assert` checks in slash commands with user-facing responses.
- Add explicit startup configuration validation.
- Add playback transition locking around queue/playback state changes.
- Update stale README checklist entries.

Excluded:

- TypeScript rewrite.
- SQLite resolution cache.
- Queue persistence across restart.
- Persistent embeds or buttons.
- Seek, volume, filters, or additional playback features.
- Broad production hardening beyond the targeted correctness fixes.

## Target Structure

```text
bot/
  siren/
    __init__.py
    app.py
    bot.py
    commands/
      __init__.py
      base.py
      play.py
      queue.py
      skip.py
      stop.py
      pause.py
      resume.py
    config.py
    models.py
    player.py
    player_registry.py
    resolver.py
    spotify.py
    youtube.py
  main.py
  requirements.txt
  Dockerfile
```

## Object Model

The refactor should move toward object-oriented service boundaries, but avoid over-abstracting simple pure functions.

Core objects:

- `Settings`: immutable runtime configuration loaded from environment.
- `SpotifyService`: owns the Spotipy client and Spotify-specific conversion/parsing.
- `YouTubeService`: owns yt-dlp option construction, search, and stream resolution.
- `TrackResolver`: coordinates Spotify and YouTube services to resolve user queries.
- `GuildPlayer`: owns playback state for one guild.
- `PlayerRegistry`: creates and stores one `GuildPlayer` per guild.
- `SirenBot`: Discord bot subclass that owns settings, services, and player registry.
- Command classes: one class per slash command module, each responsible for registering and handling one command.

Pure helpers should remain functions when that is clearer, such as `fmt_duration()` and candidate scoring helpers.

## Module Responsibilities

### `config.py`

Owns environment loading and validation. Produces a typed settings object containing Discord token, guild IDs, Spotify credentials, optional YouTube cookies file, log level, ffmpeg options, yt-dlp options, and idle timeout.

Missing required configuration should raise a clear startup error that names the missing variables instead of failing with raw `KeyError` exceptions at import time.

### `models.py`

Defines shared domain types and small formatting helpers.

Initial contents:

- `Track`
- `fmt_duration(ms: int) -> str`

### `spotify.py`

Defines `SpotifyService`. Owns Spotify client creation, Spotify URL parsing, track lookup, and text search.

Spotify track URLs should resolve to a `Track` anchor. Spotify album and playlist URLs should be rejected with a clear resolver result or message, because the current bot only accepts single-track playback input.

### `youtube.py`

Defines `YouTubeService`. Owns yt-dlp interaction.

Responsibilities:

- Search YouTube using `ytsearch`.
- Convert yt-dlp entries to `Track` objects.
- Resolve a selected webpage URL into playback metadata and a direct stream URL.
- Keep blocking yt-dlp calls behind `asyncio.to_thread` wrappers.

### `resolver.py`

Defines `TrackResolver`. Owns high-level query resolution.

Responsibilities:

- Identify URL versus text query.
- Use Spotify as an anchor for text and Spotify track URL queries.
- Search by ISRC when available.
- Fall back to artist-title search.
- Score YouTube candidates by duration, title, and artist similarity.
- Apply junk-title rejection for anchored searches.
- Fall back to plain YouTube search when Spotify text search has no result.

`TrackResolver.resolve(query)` should return either a resolved `Track` or a structured failure reason suitable for command responses and logging.

### `player.py`

Defines `GuildPlayer`. Owns per-guild playback state.

Responsibilities:

- Queue management.
- Current track state.
- Voice client reference.
- Per-guild `/play` serialization.
- Playback transition locking so `_play_next()` cannot race between command handlers and the audio-thread callback.
- Idle disconnect watcher.
- Skip, stop, pause, and resume mechanics.

The `after` callback from Discord audio playback still needs to bounce work back onto the bot event loop with `asyncio.run_coroutine_threadsafe`.

### `player_registry.py`

Defines `PlayerRegistry`.

Responsibilities:

- Store players by guild ID.
- Lazily create `GuildPlayer` instances with their required dependencies.
- Keep player lookup out of command modules and out of the bot subclass internals.

### `bot.py`

Defines the `SirenBot` subclass.

Responsibilities:

- Discord intents.
- `PlayerRegistry` ownership.
- Direct attributes for shared services needed by commands, such as `settings`, `resolver`, and `players`.
- Logger naming should use `siren` consistently.
- Slash command sync.
- `on_ready` logging.
- Voice-state updates that trigger idle reconciliation.

### `app.py`

Defines the application composition layer.

Responsibilities:

- Create `Settings`.
- Configure logging.
- Create Spotify, YouTube, resolver, and player-registry services.
- Create `SirenBot`.
- Register command modules.
- Return the fully wired bot to `main.py`.

### `commands/`

Owns slash command registration and interaction handling. Each command should live in its own module and expose a small command class with a `register(bot: SirenBot) -> None` method.

Command modules:

- `commands/base.py`: shared command helpers such as guild validation, voice-channel validation, and common response helpers.
- `commands/play.py`: `/play` only.
- `commands/skip.py`: `/skip` only.
- `commands/stop.py`: `/stop` only.
- `commands/pause.py`: `/pause` only.
- `commands/resume.py`: `/resume` only.
- `commands/queue.py`: `/queue` only.

Commands should avoid guild assertions and handle unsupported DM context consistently.

The command-per-module structure is intentionally more verbose than a single `commands.py`, but it gives each command one clear responsibility and makes new commands easy to add without growing a central file.

### `main.py`

Stays intentionally small.

Responsibilities:

- Call the application factory from `app.py`.
- Run the bot.

## Data Flow

For `/play <query>`:

1. Command handler defers the response.
2. Command handler validates guild and user voice state.
3. `PlayCommand` retrieves the `GuildPlayer` from `PlayerRegistry`.
4. `GuildPlayer.play_lock` serializes concurrent `/play` invocations per guild.
5. `TrackResolver.resolve(query)` returns a `Track` or a clear failure reason.
6. The track is enqueued.
7. `GuildPlayer` starts playback if nothing is currently playing or paused.
8. `YouTubeService.resolve_url(track.webpage_url)` obtains a fresh direct stream URL immediately before playback.
9. `discord.FFmpegOpusAudio.from_probe` builds the audio source.
10. Discord voice playback starts.
11. The audio `after` callback schedules the next transition on the event loop.

## Error Handling

- Configuration errors fail fast at startup with explicit missing variable names.
- Spotify lookup/search failures are logged and degrade to existing fallback behavior when possible.
- Unsupported Spotify album/playlist URLs return a clear user-facing message.
- yt-dlp search failures return no candidates and are logged with the `[resolve]` stage.
- yt-dlp stream extraction failures skip the failed track and continue the queue.
- Discord voice connection failures are reported to the user.
- Slash commands return friendly messages in DMs instead of relying on assertions.

## Testing And Verification

Minimum verification for the refactor:

- Run Python syntax compilation across the bot package.
- Import the package without requiring live Discord startup or environment variables.
- Unit-test pure pieces where practical: duration formatting, Spotify URL parsing, scoring, and candidate rejection.
- Instantiate service classes with fake dependencies where practical.
- Keep live Discord/yt-dlp behavior manually verifiable through Docker because it depends on external services and credentials.

## Migration Strategy

Perform the refactor in small steps:

1. Create package structure and move pure models/config helpers.
2. Introduce service classes for Spotify, YouTube, and resolution.
3. Move resolver and scoring logic behind `TrackResolver`.
4. Move player state into `GuildPlayer` and add playback transition locking.
5. Add `PlayerRegistry`.
6. Move bot lifecycle into `SirenBot`.
7. Split slash commands into command-per-module classes.
8. Shrink `main.py` to startup only via the `app.py` factory.
9. Apply targeted correctness fixes, SirenBot naming updates, and README updates.
10. Run verification.

## Risks

- Discord voice behavior is sensitive to lifecycle timing; playback locking should be minimal and focused on state transitions.
- yt-dlp calls are blocking; all existing async thread offloading must be preserved.
- Moving command registration can accidentally break slash command sync; keep guild-sync behavior equivalent.
- A command-per-module layout creates more files; each file should stay small and avoid unnecessary inheritance or framework abstractions.
- The OOP design should use composition and dependency injection, not a deep class hierarchy.
- Live service behavior cannot be fully proven by local syntax checks alone.

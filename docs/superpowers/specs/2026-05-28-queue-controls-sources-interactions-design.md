# Queue Controls, Source Expansion, And Interactive Playback Design

## Goal

Improve SirenBot's day-to-day music UX by adding queue management, Spotify album and playlist support, stronger playback recovery, and interactive Discord controls.

This work builds on the current in-memory player model. Database persistence, durable Discord component state after process restart, and non-Spotify playlist sources are out of scope.

## Current State

- `GuildPlayer` owns the active voice client, current track, queue, playback timing, and idle disconnect handling.
- Commands are split by file under `bot/siren/commands/` and registered from `commands/__init__.py`.
- `/play` resolves a submitted query into one `Track` and enqueues it.
- Spotify track URLs and text searches are supported; Spotify album and playlist URLs return a clear unsupported message.
- Playback already skips failed extraction or FFmpeg source creation by continuing through the queue loop.
- `/queue` shows current progress and up to 10 upcoming items with start estimates.

## Feature Scope

### Queue Controls

Add slash commands for direct queue management:

- `/remove position`: remove the queued item at a 1-based position.
- `/move from_position to_position`: move a queued item from one 1-based position to another.
- `/clear`: clear queued items without stopping the current track.
- `/shuffle`: shuffle queued items without changing the current track.
- `/nowplaying`: show the current track, progress, and controls without listing the full queue.

Queue mutation will live on `GuildPlayer` rather than command modules mutating `player.queue` directly. Methods will return enough information for user-facing responses, such as the removed or moved `Track`.

Invalid positions, empty queues, and missing playback state will produce short ephemeral error messages.

### Playback Reliability

Keep the existing skip-and-continue loop for failed track preparation, and make the behavior more explicit and testable:

- A failed `yt-dlp` stream extraction skips that track and continues to the next queued item.
- A failed FFmpeg source construction skips that track and continues to the next queued item.
- If the whole queue fails, the player clears current timing state and becomes idle.
- Stale playback callbacks continue to be ignored by generation checks.
- When Discord reports the bot has disconnected from voice, the player clears its voice reference and playback timing so commands do not report stale active playback.

This first pass will not automatically retry alternate YouTube candidates after a chosen URL fails. The resolver still selects one candidate before enqueueing.

### Spotify Albums And Playlists

Extend Spotify support from single-track URLs to URL expansion:

- Track URL: resolve as one Spotify anchor, as today.
- Album URL: fetch all album tracks available from Spotify.
- Playlist URL: fetch playlist tracks up to a maximum of 50 items.

Spotify expansion returns Spotify `Track` anchors. The resolver will then resolve each anchor to a playable YouTube `Track` using the same anchored YouTube search/scoring path already used for single tracks.

For `/play`:

- If the query resolves to one track, keep the current response style.
- If the query resolves to multiple tracks, enqueue every successfully resolved track and respond with a summary, for example `Queued 47 tracks from Spotify playlist. Skipped 3 tracks.`
- If every expanded item fails, respond with a clear failure message and do not enqueue anything.

Playlist expansion is intentionally capped at 50 to keep command latency, API usage, and queue size predictable.

### Interactive Queue UI

Add Discord UI buttons to `/queue` and `/nowplaying` responses:

- `Pause` or `Resume`, depending on current voice state.
- `Skip`.
- `Stop`.
- `Refresh`.

Button handlers will validate current guild and player state every time they run. Errors such as `Nothing playing.` or `Not paused.` will be ephemeral. Successful actions will update the visible message where practical so the queue display stays current.

Views are non-persistent for this version. If the bot restarts, old buttons may stop working; that is acceptable for this scope.

## Components

- `GuildPlayer`: queue mutation methods, playback failure accounting, voice disconnect cleanup, and current-state helpers used by commands and views.
- `SpotifyService`: album and playlist URL expansion with pagination and a 50-track playlist cap.
- `TrackResolver`: multi-track resolution result for Spotify albums/playlists while preserving existing single-track behavior.
- `play.py`: enqueue one or many resolved tracks and summarize partial success.
- Queue command modules: new command files for remove, move, clear, shuffle, and nowplaying.
- `views.py` or a command-local view module: Discord button view for queue and nowplaying controls.
- Tests: focused unit tests for queue mutation, Spotify expansion, multi-track play summaries, playback failure continuation, voice disconnect cleanup, and button callbacks.

## Data Flow

Single-track `/play` keeps the current flow:

1. User submits a URL or search string.
2. `TrackResolver.resolve()` returns one playable `Track`.
3. `/play` enqueues the track and reports it.

Spotify album or playlist `/play` uses a multi-track flow:

1. User submits a Spotify album or playlist URL.
2. `SpotifyService` expands the URL into Spotify track anchors.
3. `TrackResolver` resolves each anchor to a YouTube candidate.
4. `/play` enqueues successful tracks in Spotify order.
5. `/play` reports queued and skipped counts.

Interactive controls use the same player methods as slash commands. Buttons should not duplicate queue or playback mutation logic.

## Error Handling

- Queue command positions are 1-based and validated before mutation.
- Empty queue operations return ephemeral messages.
- Spotify expansion failures return a user-facing message rather than a traceback.
- Playlist tracks without usable track objects are skipped and counted.
- Multi-track resolution logs per-track failures and continues resolving later tracks.
- Button interactions validate guild/player state at click time because messages may be stale.
- Voice disconnect events clear stale player state but do not attempt to reconnect automatically.

## Testing

Unit tests will cover:

- `GuildPlayer.remove_queued()`, `move_queued()`, `clear_queue()`, and `shuffle_queue()` behavior.
- Slash command responses for invalid positions and empty queues.
- Spotify album expansion from fake album payloads.
- Spotify playlist expansion pagination, skipped invalid entries, and the 50-track cap.
- Resolver multi-track behavior for complete success, partial success, and total failure.
- `/play` summary messages for single-track and multi-track inputs.
- Playback failure continuation when extraction or FFmpeg setup fails.
- Bot voice disconnect cleanup on `on_voice_state_update`.
- Queue/nowplaying button callbacks for pause/resume, skip, stop, refresh, and stale-state errors.

Manual verification after tests should include slash-command sync, queue controls in a guild, one Spotify album, one Spotify playlist with more than 50 tracks, and button interactions on `/queue` and `/nowplaying`.

## Deployment

Implementation can happen without touching the live container. After local tests and Docker smoke checks pass, the bot image can be rebuilt and the live Compose service restarted.

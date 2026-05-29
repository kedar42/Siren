# YouTube Playlist Support Design

## Goal

Allow `/play` to accept YouTube playlist URLs and enqueue playlist items in order, matching the new Spotify playlist behavior.

Supported examples include:

- `https://www.youtube.com/playlist?list=...`
- `https://youtube.com/playlist?list=...`
- `https://www.youtube.com/watch?v=...&list=...`
- `https://music.youtube.com/playlist?list=...`

## Current State

- `YouTubeService.resolve_url()` resolves a URL as a single playable track and stream URL.
- `YouTubeService.search()` already converts flat yt-dlp entries into `Track` objects.
- `TrackResolver.resolve()` sends all explicit `http://` or `https://` URLs through the single-track YouTube URL path unless they are Spotify URLs.
- `/play` already supports multi-track `ResolveResult` values, enqueues every returned track, and sends a summary message.
- Spotify playlists are capped at 50 tracks to keep latency and queue size predictable.

## Behavior

When a user runs `/play` with a YouTube playlist URL:

1. The resolver detects the URL as a YouTube playlist before the generic direct-URL path.
2. The YouTube service extracts playlist entries with yt-dlp flat extraction.
3. The service converts usable entries into `Track` objects and preserves playlist order.
4. The resolver returns a multi-track `ResolveResult`.
5. `/play` enqueues all returned tracks and replies with a summary.

The playlist cap is 50 tracks. If more than 50 usable entries are available, the response includes `Playlist limited to first 50 tracks.`

Malformed or unusable playlist entries are skipped. If every playlist entry is unusable, the command responds with a clear failure message and does not enqueue anything.

Single YouTube video URLs continue to resolve as one track. A watch URL that includes a `list=` parameter is treated as playlist input, not only the individual video.

## Components

- `YouTubeService`: add playlist URL detection and a `tracks_from_playlist_url(url, limit=50)` method using flat yt-dlp extraction.
- `TrackResolver`: check for YouTube playlist URLs before generic direct URL resolution and return a multi-track result.
- `/play`: no major change expected because it already enqueues multi-track results.
- Tests: cover playlist extraction, cap/truncation, skipped entries, resolver behavior, and direct-video regression.

## Data Flow

1. User submits `/play https://youtube.com/playlist?list=...`.
2. `TrackResolver.resolve()` identifies it as a YouTube playlist URL.
3. `YouTubeService.tracks_from_playlist_url()` runs yt-dlp with flat extraction and a safe playlist cap.
4. `YouTubeService` converts each usable entry into a `Track` with title, author, duration, and webpage URL.
5. `TrackResolver` returns `ResolveResult(track=first_track, tracks=tracks, message=summary)`.
6. `/play` enqueues each track through the existing multi-track path.

## Error Handling

- yt-dlp playlist extraction failures log a warning and produce an empty result.
- Empty extracted playlists return `Couldn't resolve` rather than raising.
- Missing title, author, duration, or URL fields are handled the same way as existing flat YouTube search entries.
- Entries without a usable URL are skipped.
- The playlist cap applies to enqueued usable tracks, not raw entries.

## Testing

Unit tests will cover:

- YouTube playlist URL detection for `/playlist?list=...`, `watch?v=...&list=...`, and `music.youtube.com` playlist URLs.
- `YouTubeService.tracks_from_playlist_url()` converts flat entries into ordered `Track` objects.
- Playlist expansion caps at 50 usable tracks and marks the result as truncated when additional entries exist.
- Malformed entries are skipped without aborting the playlist.
- `TrackResolver.resolve()` returns a multi-track result and summary for YouTube playlist URLs.
- Direct single-video URL resolution remains unchanged when no playlist parameter is present.
- Existing `/play` multi-track enqueue tests continue to cover queue insertion and summary responses.

## Deployment

This is an incremental change on the existing feature branch. After implementation, run the full unit suite, compileall, Compose config validation with dummy env, Docker build, image smokes, and restart the local bot container with the updated feature image.

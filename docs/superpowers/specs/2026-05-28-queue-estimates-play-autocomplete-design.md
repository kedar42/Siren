# Queue Estimates And Play Autocomplete Design

## Goal

Improve SirenBot's music UX without restarting the currently running bot during implementation:

- `/queue` should show current playback progress as elapsed time versus total duration.
- `/queue` should estimate when each visible queued item will start, using clock time.
- `/play` should provide smart autocomplete suggestions so users can pick a specific version before submitting.

MySQL queue persistence is intentionally out of scope for this spec.

## Current State

- `GuildPlayer` tracks `current`, `queue`, and `voice` in memory.
- `/queue` formats the current item and up to 10 queued tracks with durations.
- `/play` accepts free text or URLs and resolves only after the command is submitted.
- `TrackResolver` uses Spotify as a canonical anchor for text queries, then searches YouTube and chooses the best candidate.
- YouTube search already returns `Track` candidates with title, author, duration, and URL.

## Queue Display

`GuildPlayer` will record when the current FFmpeg playback starts. Queue formatting will use that timestamp to compute elapsed playback time while the voice client is playing or paused.

The current item line will become:

```text
**Now playing:** Artist - Title `[1:24 / 3:22]`
```

If the elapsed position is unavailable, the formatter will fall back to:

```text
**Now playing:** Artist - Title `[?:?? / 3:22]`
```

Queued items will show a clock-time estimate only:

```text
`1.` Artist - Next Song `[3:41]` - starts around 7:16 PM
```

The estimate is calculated from the current local time plus the remaining time in the current track plus the durations of any queued tracks before that item. If there is no current track, the current remaining time is treated as zero. If a duration is unknown, estimates for that item and subsequent items will show `starts after unknown time` rather than pretending to be precise.

## Playback Timing

`GuildPlayer` will add timing state for the current track:

- `started_at_monotonic`: set when `voice.play()` successfully starts.
- `elapsed_before_pause_ms`: accumulated elapsed time before the current pause, initially `0`.
- `paused_at_monotonic`: set when playback is paused, cleared on resume.

The player will expose small methods/properties for queue formatting:

- `current_elapsed_ms()` returns elapsed milliseconds for the current track, capped to the track duration when known.
- `current_remaining_ms()` returns remaining milliseconds when duration is known.

Pause and resume commands will update timing state after calling Discord voice pause/resume. Skip, stop, playback completion, and transition to the next track will reset or replace timing state.

## Play Autocomplete

`/play` will use Discord slash-command autocomplete on the `query` parameter.

The autocomplete behavior will be hybrid:

- If input is empty or URL-like, return no suggestions.
- For normal text, ask Spotify for a canonical anchor candidate first.
- Use the Spotify anchor to form a precise YouTube search query when available.
- Return YouTube candidates as selectable choices so users can choose a specific version.
- If Spotify returns no anchor, fall back to YouTube search using the raw input.

Autocomplete choices will display concise labels such as:

```text
Alestorm - Drink [3:23]
Alestorm - Drink (Official Video) [3:24]
Alestorm - Drink (Live) [4:01]
```

The choice value will be the selected candidate's YouTube URL. Submitting `/play` with that selected value will use the existing direct URL flow and play the chosen version.

Discord limits autocomplete responses to 25 choices, so SirenBot will return at most 25 candidates. Labels will be truncated to Discord's choice-name limit without changing the URL value.

## Components

- `GuildPlayer`: owns playback timing state and elapsed/remaining calculations.
- `queue.py`: formats current progress and start estimates from player timing and queued durations.
- `play.py`: registers autocomplete for the `query` option and sends selected values through the existing play flow.
- `TrackResolver`: exposes an `autocomplete(query)` helper that performs the Spotify/YouTube orchestration and returns candidate `Track` objects.
- Tests: cover timing math, queue formatting, autocomplete fallback behavior, and selected YouTube URL passthrough.

## Error Handling

- Autocomplete failures should log at warning level and return no choices rather than failing the Discord interaction.
- Unknown durations should not produce misleading start times.
- Playback timing should tolerate Discord state mismatches, such as pause called when not playing.
- Existing `/play` error responses remain unchanged for unresolved submitted queries.

## Testing

Unit tests will cover:

- Current progress formatting for playing, paused, and unknown elapsed states.
- Queue start estimates based on current remaining time and previous queued durations.
- Estimate fallback when a duration is unknown.
- `GuildPlayer` timing state on start, pause, resume, skip/stop, and next-track transition.
- Autocomplete returns YouTube URL values with readable labels.
- Autocomplete returns no choices for empty or URL-like input.
- Autocomplete falls back to raw YouTube search when Spotify has no anchor.

Manual verification will avoid restarting the currently running bot until explicitly requested. After implementation, local tests and container-safe smoke checks can be run without touching the live container.

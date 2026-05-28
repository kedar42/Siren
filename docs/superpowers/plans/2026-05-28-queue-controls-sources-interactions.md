# Queue Controls, Source Expansion, And Interactive Playback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add queue management commands, Spotify album/playlist expansion, playback recovery cleanup, and Discord button controls for SirenBot.

**Architecture:** Keep command modules small and put reusable state changes on `GuildPlayer`. Extend `SpotifyService` to return Spotify track anchors for track, album, and playlist URLs, then let `TrackResolver` resolve one or many anchors to playable YouTube tracks. Put Discord component callbacks in a focused view module that calls the same player methods as slash commands.

**Tech Stack:** Python 3.12+, discord.py app commands and UI views, Spotipy, yt-dlp, unittest.

---

## File Structure

- Modify `bot/siren/player.py`: add queue mutation methods, current-state helpers, voice cleanup, and clearer playback failure counters.
- Modify `bot/siren/bot.py`: clear stale player state when Discord reports the bot disconnected from voice.
- Modify `bot/siren/spotify.py`: add `tracks_from_url()`, album expansion, playlist expansion with pagination and 50-track cap.
- Modify `bot/siren/resolver.py`: add multi-track resolution result while preserving existing single-track behavior.
- Modify `bot/siren/commands/play.py`: enqueue one or many resolved tracks and summarize partial success.
- Modify `bot/siren/commands/queue.py`: support optional interactive view and reuse formatting from buttons.
- Create `bot/siren/commands/remove.py`, `move.py`, `clear.py`, `shuffle.py`, `nowplaying.py`: queue control command modules.
- Modify `bot/siren/commands/__init__.py`: register new command modules.
- Create `bot/siren/commands/views.py`: `PlaybackControlsView` with pause/resume, skip, stop, and refresh buttons.
- Create tests `tests/test_queue_controls.py`, `tests/test_spotify_expansion.py`, `tests/test_multi_play.py`, `tests/test_playback_reliability.py`, `tests/test_playback_controls.py`.

## Task 1: Queue Mutation Core And Queue Control Commands

**Files:**
- Modify: `bot/siren/player.py`
- Create: `bot/siren/commands/remove.py`
- Create: `bot/siren/commands/move.py`
- Create: `bot/siren/commands/clear.py`
- Create: `bot/siren/commands/shuffle.py`
- Create: `bot/siren/commands/nowplaying.py`
- Modify: `bot/siren/commands/__init__.py`
- Test: `tests/test_queue_controls.py`

- [ ] **Step 1: Write failing queue mutation tests**

Add `tests/test_queue_controls.py`:

```python
import unittest

from siren.config import Settings
from siren.models import Track
from siren.player import GuildPlayer


class FakeBot:
    loop = None


class FakeYouTube:
    pass


def settings() -> Settings:
    return Settings.from_env(
        {
            "DISCORD_TOKEN": "discord-token",
            "SPOTIFY_CLIENT_ID": "spotify-id",
            "SPOTIFY_CLIENT_SECRET": "spotify-secret",
        }
    )


def track(index: int) -> Track:
    return Track(f"Track {index}", "Artist", 1000 * index, f"url-{index}")


class QueueMutationTests(unittest.TestCase):
    def player(self) -> GuildPlayer:
        player = GuildPlayer(FakeBot(), 123, FakeYouTube(), settings())
        player.queue.extend([track(1), track(2), track(3)])
        return player

    def test_remove_queued_uses_one_based_position(self) -> None:
        player = self.player()

        removed = player.remove_queued(2)

        self.assertEqual(removed.title, "Track 2")
        self.assertEqual([item.title for item in player.queue], ["Track 1", "Track 3"])

    def test_remove_queued_rejects_invalid_position(self) -> None:
        player = self.player()

        with self.assertRaises(IndexError):
            player.remove_queued(0)
        with self.assertRaises(IndexError):
            player.remove_queued(4)

    def test_move_queued_uses_one_based_positions(self) -> None:
        player = self.player()

        moved = player.move_queued(3, 1)

        self.assertEqual(moved.title, "Track 3")
        self.assertEqual([item.title for item in player.queue], ["Track 3", "Track 1", "Track 2"])

    def test_clear_queue_returns_removed_count(self) -> None:
        player = self.player()

        removed = player.clear_queue()

        self.assertEqual(removed, 3)
        self.assertEqual(list(player.queue), [])

    def test_shuffle_queue_keeps_same_tracks(self) -> None:
        player = self.player()

        shuffled = player.shuffle_queue(seed=1)

        self.assertEqual(shuffled, 3)
        self.assertCountEqual([item.title for item in player.queue], ["Track 1", "Track 2", "Track 3"])
        self.assertNotEqual([item.title for item in player.queue], ["Track 1", "Track 2", "Track 3"])
```

- [ ] **Step 2: Verify failing queue mutation tests**

Run: `PYTHONPATH=bot .venv/bin/python -m unittest tests.test_queue_controls -v`

Expected: failures mentioning missing `remove_queued`, `move_queued`, `clear_queue`, or `shuffle_queue`.

- [ ] **Step 3: Implement queue mutation methods**

In `bot/siren/player.py`, import `random` and add methods on `GuildPlayer`:

```python
    def _queue_index(self, position: int) -> int:
        index = position - 1
        if index < 0 or index >= len(self.queue):
            raise IndexError("queue position out of range")
        return index

    def remove_queued(self, position: int) -> Track:
        items = list(self.queue)
        removed = items.pop(self._queue_index(position))
        self.queue = deque(items)
        self.reconcile_idle()
        return removed

    def move_queued(self, from_position: int, to_position: int) -> Track:
        items = list(self.queue)
        from_index = self._queue_index(from_position)
        if to_position < 1 or to_position > len(items):
            raise IndexError("queue position out of range")
        moved = items.pop(from_index)
        items.insert(to_position - 1, moved)
        self.queue = deque(items)
        return moved

    def clear_queue(self) -> int:
        removed = len(self.queue)
        self.queue.clear()
        self.reconcile_idle()
        return removed

    def shuffle_queue(self, *, seed: int | None = None) -> int:
        items = list(self.queue)
        rng = random.Random(seed) if seed is not None else random
        rng.shuffle(items)
        self.queue = deque(items)
        return len(items)
```

- [ ] **Step 4: Verify queue mutation tests pass**

Run: `PYTHONPATH=bot .venv/bin/python -m unittest tests.test_queue_controls -v`

Expected: all tests in `QueueMutationTests` pass.

- [ ] **Step 5: Add queue control command modules**

Create `remove.py`, `move.py`, `clear.py`, `shuffle.py`, and `nowplaying.py` under `bot/siren/commands/`. Use the existing `CommandBase` pattern. Command behavior:

```python
await interaction.response.send_message("Queue is empty.", ephemeral=True)
await interaction.response.send_message("Position must be between 1 and N.", ephemeral=True)
await interaction.response.send_message(f"Removed **{track.title}** by *{track.author}*.")
await interaction.response.send_message(f"Moved **{track.title}** to position {to_position}.")
await interaction.response.send_message(f"Cleared {count} queued tracks.")
await interaction.response.send_message(f"Shuffled {count} queued tracks.")
```

For `/nowplaying`, add `format_nowplaying_message(player)` in `queue.py` and call that helper from the new command and from the compact control view.

- [ ] **Step 6: Register new command modules**

Modify `bot/siren/commands/__init__.py` to import and instantiate `RemoveCommand`, `MoveCommand`, `ClearCommand`, `ShuffleCommand`, and `NowPlayingCommand`.

- [ ] **Step 7: Run command registration smoke test**

Run: `PYTHONPATH=bot .venv/bin/python -m unittest tests.test_app -v`

Expected: app tests pass with the updated command count that includes `/remove`, `/move`, `/clear`, `/shuffle`, and `/nowplaying`.

- [ ] **Step 8: Commit queue controls**

Run:

```bash
git add bot/siren/player.py bot/siren/commands tests/test_queue_controls.py
git commit -m "feat: add queue control commands"
```

## Task 2: Spotify Album And Playlist Expansion

**Files:**
- Modify: `bot/siren/spotify.py`
- Modify: `bot/siren/resolver.py`
- Modify: `bot/siren/commands/play.py`
- Test: `tests/test_spotify_expansion.py`
- Test: `tests/test_multi_play.py`

- [ ] **Step 1: Write failing Spotify expansion tests**

Add `tests/test_spotify_expansion.py` with fake client methods for `album_tracks()` and `playlist_items()`. Verify album tracks convert to `Track`, playlist pagination stops at 50, and playlist items with missing `track` are skipped.

```python
class FakeSpotifyClient:
    def album_tracks(self, album_id, limit=50, offset=0):
        return {"items": [{"name": "A", "artists": [{"name": "Artist"}], "duration_ms": 1000, "external_urls": {"spotify": "album-track"}, "external_ids": {"isrc": "ISRC1"}}], "next": None}

    def playlist_items(self, playlist_id, limit=50, offset=0, additional_types=("track",)):
        return {"items": [{"track": {"name": f"P{offset + i}", "artists": [{"name": "Artist"}], "duration_ms": 1000, "external_urls": {"spotify": f"playlist-track-{offset+i}"}, "external_ids": {"isrc": f"ISRC{offset+i}"}}} for i in range(limit)], "next": "more" if offset == 0 else None}
```

- [ ] **Step 2: Verify failing Spotify expansion tests**

Run: `PYTHONPATH=bot .venv/bin/python -m unittest tests.test_spotify_expansion -v`

Expected: failures mentioning missing `tracks_from_url`.

- [ ] **Step 3: Implement Spotify expansion**

In `bot/siren/spotify.py`:

```python
MAX_PLAYLIST_TRACKS = 50

def tracks_from_url(self, url: str, *, playlist_limit: int = MAX_PLAYLIST_TRACKS) -> list[Track]:
    parsed = self.parse_url(url)
    if parsed is None:
        return []
    if parsed.kind is SpotifyUrlKind.TRACK:
        track = self._track_lookup(parsed.url)
        return [track] if track else []
    if parsed.kind is SpotifyUrlKind.ALBUM:
        return self._album_tracks(parsed.spotify_id)
    if parsed.kind is SpotifyUrlKind.PLAYLIST:
        return self._playlist_tracks(parsed.spotify_id, playlist_limit=playlist_limit)
    return []
```

Add `_album_tracks()` and `_playlist_tracks()` using `_track_from_obj()` and Spotipy pagination. Skip falsy playlist `track` values.

- [ ] **Step 4: Add multi-track resolver result**

Update `ResolveResult` in `resolver.py` to include `tracks: list[Track] | None = None` and keep `track` compatibility:

```python
@dataclass(frozen=True)
class ResolveResult:
    track: Track | None = None
    tracks: list[Track] | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.all_tracks)

    @property
    def all_tracks(self) -> list[Track]:
        if self.tracks is not None:
            return self.tracks
        return [self.track] if self.track is not None else []
```

For Spotify album/playlist URLs, call `spotify.tracks_from_url()` and resolve each anchor through `_resolve_anchored(anchor, query)`. Count failures by comparing anchors to successful playable tracks.

- [ ] **Step 5: Update `/play` for one or many tracks**

In `play.py`, replace single `result.track` enqueue with:

```python
tracks = result.all_tracks
for track in tracks:
    await player.enqueue(track)
if len(tracks) == 1:
    track = tracks[0]
    await interaction.followup.send(f"Queued **{track.title}** by *{track.author}*.")
else:
    await interaction.followup.send(result.message or f"Queued {len(tracks)} tracks.")
```

- [ ] **Step 6: Verify Spotify and play tests**

Run: `PYTHONPATH=bot .venv/bin/python -m unittest tests.test_spotify_expansion tests.test_resolver tests.test_play_command tests.test_multi_play -v`

Expected: all listed tests pass.

- [ ] **Step 7: Commit source expansion**

Run:

```bash
git add bot/siren/spotify.py bot/siren/resolver.py bot/siren/commands/play.py tests/test_spotify_expansion.py tests/test_multi_play.py tests/test_resolver.py tests/test_play_command.py
git commit -m "feat: expand spotify albums and playlists"
```

## Task 3: Playback Reliability And Voice Disconnect Cleanup

**Files:**
- Modify: `bot/siren/player.py`
- Modify: `bot/siren/bot.py`
- Test: `tests/test_playback_reliability.py`
- Modify: `tests/test_bot.py`

- [ ] **Step 1: Write failing reliability tests**

Add tests proving failed extraction advances to the next playable track, FFmpeg construction failure advances to the next playable track, and bot voice disconnect clears `player.voice`, `player.current`, and timing.

Use the existing fake patterns in `tests/test_player_registry.py`.

- [ ] **Step 2: Verify failing reliability tests**

Run: `PYTHONPATH=bot .venv/bin/python -m unittest tests.test_playback_reliability tests.test_bot -v`

Expected: failures for missing cleanup helper or stale state behavior.

- [ ] **Step 3: Add player voice cleanup helper**

In `GuildPlayer`:

```python
    def clear_voice_state(self) -> None:
        self.voice = None
        self.current = None
        self._clear_timing()
        self._playback_generation += 1
        self.reconcile_idle()
```

- [ ] **Step 4: Update bot voice-state event**

In `SirenBot.on_voice_state_update()`, if `member.id == self.user.id` and `before.channel is not None and after.channel is None`, get the player and call `clear_voice_state()`.

- [ ] **Step 5: Verify reliability tests**

Run: `PYTHONPATH=bot .venv/bin/python -m unittest tests.test_playback_reliability tests.test_player_registry tests.test_bot -v`

Expected: all listed tests pass.

- [ ] **Step 6: Commit reliability cleanup**

Run:

```bash
git add bot/siren/player.py bot/siren/bot.py tests/test_playback_reliability.py tests/test_bot.py
git commit -m "fix: clear stale voice playback state"
```

## Task 4: Interactive Queue And Now Playing Controls

**Files:**
- Create: `bot/siren/commands/views.py`
- Modify: `bot/siren/commands/queue.py`
- Modify: `bot/siren/commands/nowplaying.py`
- Test: `tests/test_playback_controls.py`

- [ ] **Step 1: Write failing view tests**

Add `tests/test_playback_controls.py` with fake interaction, response, message, and player objects. Test refresh returns updated queue content, pause/resume toggles voice state and timing methods, skip calls `player.skip()`, stop calls `player.stop()`, and stale state returns ephemeral errors.

- [ ] **Step 2: Verify failing view tests**

Run: `PYTHONPATH=bot .venv/bin/python -m unittest tests.test_playback_controls -v`

Expected: failure because `PlaybackControlsView` is missing.

- [ ] **Step 3: Implement `PlaybackControlsView`**

Create `bot/siren/commands/views.py`:

```python
class PlaybackControlsView(discord.ui.View):
    def __init__(self, bot: SirenBot, guild_id: int, *, compact: bool = False) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.guild_id = guild_id
        self.compact = compact

    def player(self) -> GuildPlayer | None:
        return self.bot.players.get(self.guild_id) if self.bot.players else None
```

Add four buttons using `@discord.ui.button`: pause/resume, skip, stop, refresh. Each callback validates player state and sends ephemeral errors for invalid actions. Refresh edits the existing message with `format_queue_message(player)` or nowplaying text.

- [ ] **Step 4: Attach views to queue and nowplaying responses**

In `/queue`, send `view=PlaybackControlsView(self.bot, guild.id)`. In `/nowplaying`, send `view=PlaybackControlsView(self.bot, guild.id, compact=True)`.

- [ ] **Step 5: Verify view tests and command registration**

Run: `PYTHONPATH=bot .venv/bin/python -m unittest tests.test_playback_controls tests.test_queue_command tests.test_app -v`

Expected: all listed tests pass.

- [ ] **Step 6: Commit interactive controls**

Run:

```bash
git add bot/siren/commands/views.py bot/siren/commands/queue.py bot/siren/commands/nowplaying.py tests/test_playback_controls.py tests/test_queue_command.py tests/test_app.py
git commit -m "feat: add playback control buttons"
```

## Task 5: Full Verification, Review, And Deployment Prep

**Files:**
- Modify only if verification reveals a defect.

- [ ] **Step 1: Run full unit test suite**

Run: `PYTHONPATH=bot .venv/bin/python -m unittest discover -s tests -v`

Expected: all tests pass.

- [ ] **Step 2: Compile source and tests**

Run: `PYTHONPYCACHEPREFIX=/var/folders/z1/hj7cl3756jn651xfjpw3s8lw0000gn/T/opencode/siren-compileall-cache .venv/bin/python -m compileall -q bot tests`

Expected: no output and exit code 0.

- [ ] **Step 3: Validate Compose config without secrets**

Run: `env DISCORD_TOKEN=dummy SPOTIFY_CLIENT_ID=dummy SPOTIFY_CLIENT_SECRET=dummy DISCORD_GUILD_IDS=123456789012345678 LOG_LEVEL=INFO YT_COOKIES_FILE= docker compose --env-file /dev/null config`

Expected: config renders without reading `.env`.

- [ ] **Step 4: Build Docker image**

Run: `docker compose build`

Expected: image builds successfully.

- [ ] **Step 5: Smoke-test image imports and bot construction**

Run:

```bash
docker run --rm siren-bot:latest python -m compileall -q .
docker run --rm siren-bot:latest python -c 'import siren; import siren.app; import siren.config; import main; print(siren.APP_NAME)'
docker run --rm -e DISCORD_TOKEN=dummy -e SPOTIFY_CLIENT_ID=dummy -e SPOTIFY_CLIENT_SECRET=dummy siren-bot:latest python -c 'from siren.app import create_bot; bot = create_bot(); print(type(bot).__name__, len(bot.tree.get_commands()))'
```

Expected: compileall exits 0, imports print `SirenBot`, and bot construction prints `SirenBot` plus the updated command count.

- [ ] **Step 6: Request code review**

Dispatch a focused review for queue controls, Spotify expansion, reliability, interactive views, and tests. Fix critical and important findings before proceeding.

- [ ] **Step 7: Commit final fixes if any**

Run:

```bash
git status --short
git add bot/siren tests docs/superpowers/plans/2026-05-28-queue-controls-sources-interactions.md
git commit -m "fix: address playback control review"
```

Only run this step if review or verification required fixes.

- [ ] **Step 8: Push branch**

Run: `git push`

Expected: local branch is pushed to `origin/main` unless work is moved to a feature branch.

## Self-Review

- Spec coverage: queue controls are covered by Task 1; Spotify albums/playlists by Task 2; reliability and disconnect cleanup by Task 3; interactive queue UI by Task 4; verification and deployment prep by Task 5.
- Placeholder scan: no `TBD`, `TODO`, or incomplete steps remain. Each task has exact files, commands, and expected outcomes.
- Type consistency: `GuildPlayer` queue methods, `ResolveResult.all_tracks`, `SpotifyService.tracks_from_url`, and `PlaybackControlsView` are named consistently across tasks.

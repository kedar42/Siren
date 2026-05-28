# Queue Estimates And Play Autocomplete Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add current playback progress, clock-time queue start estimates, and hybrid Spotify/YouTube `/play` autocomplete.

**Architecture:** `GuildPlayer` owns playback timing state and exposes elapsed/remaining methods. Queue display stays in `bot/siren/commands/queue.py` and reads only player state. `TrackResolver` owns autocomplete search orchestration, while `PlayCommand` only converts candidate tracks into Discord choices.

**Tech Stack:** Python 3.12+, `discord.py` slash commands/autocomplete, existing `spotipy`, existing `yt-dlp`, `unittest`, Docker Compose for packaging checks.

---

## File Structure

- Modify `bot/siren/player.py`: add monotonic playback timing state and methods used by `/queue`; update auto-resume, skip, stop, and next-track transitions to maintain timing state.
- Modify `bot/siren/commands/pause.py`: call player timing hook after pausing.
- Modify `bot/siren/commands/resume.py`: call player timing hook after resuming.
- Modify `bot/siren/commands/queue.py`: format elapsed/total current progress and estimated queue start clock times.
- Modify `bot/siren/resolver.py`: add `autocomplete()` that performs hybrid Spotify anchor + YouTube candidate search.
- Modify `bot/siren/commands/play.py`: register autocomplete and convert `Track` candidates to `app_commands.Choice[str]` values.
- Modify `tests/test_queue_command.py`: cover progress and estimate formatting.
- Modify `tests/test_player_registry.py`: cover timing start, pause, resume, stop, and skip clearing behavior.
- Modify `tests/test_resolver.py`: cover autocomplete source selection and URL/empty skips.
- Create `tests/test_play_command.py`: cover autocomplete choice labels, values, truncation, and URL length filtering.

The user has approved restarting the live bot after implementation and image verification.

---

### Task 1: Queue Formatting With Progress And Start Estimates

**Files:**
- Modify: `tests/test_queue_command.py`
- Modify: `bot/siren/commands/queue.py`

- [ ] **Step 1: Write failing queue formatting tests**

Replace `tests/test_queue_command.py` with:

```python
import unittest
from collections import deque
from datetime import datetime

from siren.commands.queue import format_queue_message
from siren.models import Track


class FakeVoice:
    def __init__(self, playing: bool = False, paused: bool = False) -> None:
        self._playing = playing
        self._paused = paused

    def is_playing(self) -> bool:
        return self._playing

    def is_paused(self) -> bool:
        return self._paused


class FakePlayer:
    def __init__(self) -> None:
        self.current = Track("Current", "Artist", 185000, "current-url")
        self.queue = deque([Track("Next", "Other", 61000, "next-url")])
        self.voice = FakeVoice(playing=True)
        self._elapsed_ms: int | None = 45000
        self._remaining_ms: int | None = 140000

    def current_elapsed_ms(self) -> int | None:
        return self._elapsed_ms

    def current_remaining_ms(self) -> int | None:
        return self._remaining_ms


class QueueCommandTests(unittest.TestCase):
    def test_format_queue_message_includes_current_progress_and_next_estimate(self) -> None:
        now = datetime(2026, 5, 28, 19, 10, 0)
        message = format_queue_message(FakePlayer(), now=now)
        self.assertIn("**Now playing:** Artist — Current `[0:45 / 3:05]`", message)
        self.assertIn("**Up next (1):**", message)
        self.assertIn("`1.` Other — Next `[1:01]` — starts around 7:12 PM", message)

    def test_format_queue_message_uses_paused_state_with_frozen_progress(self) -> None:
        player = FakePlayer()
        player.voice = FakeVoice(paused=True)
        player._elapsed_ms = 90000
        player._remaining_ms = 95000
        now = datetime(2026, 5, 28, 19, 10, 0)

        message = format_queue_message(player, now=now)

        self.assertIn("**Paused:** Artist — Current `[1:30 / 3:05]`", message)
        self.assertIn("starts around 7:11 PM", message)

    def test_format_queue_message_uses_unknown_progress_when_elapsed_missing(self) -> None:
        player = FakePlayer()
        player._elapsed_ms = None
        player._remaining_ms = None
        now = datetime(2026, 5, 28, 19, 10, 0)

        message = format_queue_message(player, now=now)

        self.assertIn("**Now playing:** Artist — Current `[?:?? / 3:05]`", message)
        self.assertIn("starts after unknown time", message)

    def test_format_queue_message_estimates_multiple_items_from_prior_durations(self) -> None:
        player = FakePlayer()
        player.current = None
        player._elapsed_ms = None
        player._remaining_ms = 0
        player.queue = deque(
            [
                Track("First", "Artist", 60000, "first-url"),
                Track("Second", "Artist", 120000, "second-url"),
            ]
        )
        now = datetime(2026, 5, 28, 19, 10, 0)

        message = format_queue_message(player, now=now)

        self.assertIn("`1.` Artist — First `[1:00]` — starts around 7:10 PM", message)
        self.assertIn("`2.` Artist — Second `[2:00]` — starts around 7:11 PM", message)

    def test_format_queue_message_uses_unknown_estimates_after_unknown_duration(self) -> None:
        player = FakePlayer()
        player.current = None
        player._remaining_ms = 0
        player.queue = deque(
            [
                Track("Unknown", "Artist", 0, "unknown-url"),
                Track("Later", "Artist", 120000, "later-url"),
            ]
        )
        now = datetime(2026, 5, 28, 19, 10, 0)

        message = format_queue_message(player, now=now)

        self.assertIn("`1.` Artist — Unknown `[?:??]` — starts around 7:10 PM", message)
        self.assertIn("`2.` Artist — Later `[2:00]` — starts after unknown time", message)

    def test_format_queue_message_uses_original_overflow_text(self) -> None:
        player = FakePlayer()
        player.queue = deque(
            Track(f"Track {index}", "Artist", 60_000, f"url-{index}")
            for index in range(11)
        )
        message = format_queue_message(player, now=datetime(2026, 5, 28, 19, 10, 0))
        self.assertIn("…and 1 more", message)
```

- [ ] **Step 2: Run queue tests and verify they fail**

Run:

```bash
PYTHONPATH=bot .venv/bin/python -m unittest tests.test_queue_command -v
```

Expected: failures because `format_queue_message()` does not accept `now`, does not show elapsed/total progress, and does not show start estimates.

- [ ] **Step 3: Implement queue formatting helpers**

Replace `bot/siren/commands/queue.py` with:

```python
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import discord

from ..models import fmt_duration
from .base import CommandBase

QUEUE_PREVIEW_LIMIT = 10
UNKNOWN_START_TEXT = "starts after unknown time"


def fmt_position(ms: int) -> str:
    seconds = max(0, ms) // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"


def fmt_clock(value: datetime) -> str:
    return value.strftime("%I:%M %p").lstrip("0")


def current_progress(player: Any) -> str:
    if player.current is None:
        return ""
    elapsed_ms = player.current_elapsed_ms()
    elapsed = fmt_position(elapsed_ms) if elapsed_ms is not None else "?:??"
    return f"{elapsed} / {fmt_duration(player.current.duration_ms)}"


def start_estimate(now: datetime, offset_ms: int | None) -> str:
    if offset_ms is None:
        return UNKNOWN_START_TEXT
    return f"starts around {fmt_clock(now + timedelta(milliseconds=offset_ms))}"


def format_queue_message(player: Any, *, now: datetime | None = None) -> str:
    now = now or datetime.now().astimezone()
    lines: list[str] = []
    if player.current is not None:
        if player.voice and player.voice.is_paused():
            state = "Paused"
        elif player.voice and player.voice.is_playing():
            state = "Now playing"
        else:
            state = "Loading"
        lines.append(
            f"**{state}:** {player.current.author} — {player.current.title} "
            f"`[{current_progress(player)}]`"
        )

    offset_ms: int | None
    if player.current is None:
        offset_ms = 0
    else:
        offset_ms = player.current_remaining_ms()

    if player.queue:
        lines.append("")
        lines.append(f"**Up next ({len(player.queue)}):**")
        for index, track in enumerate(list(player.queue)[:QUEUE_PREVIEW_LIMIT], start=1):
            lines.append(
                f"`{index}.` {track.author} — {track.title} `[{fmt_duration(track.duration_ms)}]` "
                f"— {start_estimate(now, offset_ms)}"
            )
            if offset_ms is not None:
                if track.duration_ms > 0:
                    offset_ms += track.duration_ms
                else:
                    offset_ms = None
        remaining = len(player.queue) - QUEUE_PREVIEW_LIMIT
        if remaining > 0:
            lines.append(f"…and {remaining} more")

    return "\n".join(lines)


class QueueCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="queue", description="Show what's playing and what's queued.")
        async def queue_cmd(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if player.current is None and not player.queue:
                await interaction.response.send_message("Queue is empty.", ephemeral=True)
                return
            await interaction.response.send_message(format_queue_message(player))
```

- [ ] **Step 4: Run queue tests and verify they pass**

Run:

```bash
PYTHONPATH=bot .venv/bin/python -m unittest tests.test_queue_command -v
```

Expected: all `QueueCommandTests` pass.

---

### Task 2: Playback Timing State

**Files:**
- Modify: `tests/test_player_registry.py`
- Modify: `bot/siren/player.py`
- Modify: `bot/siren/commands/pause.py`
- Modify: `bot/siren/commands/resume.py`

- [ ] **Step 1: Add failing player timing tests**

Append this helper and tests to `tests/test_player_registry.py`, after `settings()` and inside `GuildPlayerTests`:

```python
class FakeClock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds
```

Add these methods to `GuildPlayerTests`:

```python
    async def test_current_elapsed_and_remaining_track_playback_time(self) -> None:
        clock = FakeClock()
        voice = StatefulVoice()
        player = GuildPlayer(FakeBot(), 123, ImmediateYouTube(), settings(), clock=clock)
        player.voice = voice
        player.queue.append(Track("Timed", "Artist", 180000, "timed-url"))

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()):
            await player.play_next()

        clock.advance(42)

        self.assertEqual(player.current_elapsed_ms(), 42000)
        self.assertEqual(player.current_remaining_ms(), 138000)

    async def test_pause_and_resume_freeze_elapsed_time(self) -> None:
        clock = FakeClock()
        voice = StatefulVoice()
        player = GuildPlayer(FakeBot(), 123, ImmediateYouTube(), settings(), clock=clock)
        player.voice = voice
        player.queue.append(Track("Timed", "Artist", 180000, "timed-url"))

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()):
            await player.play_next()

        clock.advance(10)
        player.mark_paused()
        clock.advance(20)
        self.assertEqual(player.current_elapsed_ms(), 10000)

        player.mark_resumed()
        clock.advance(5)
        self.assertEqual(player.current_elapsed_ms(), 15000)

    async def test_timing_is_replaced_for_next_track(self) -> None:
        clock = FakeClock()
        voice = StatefulVoice()
        player = GuildPlayer(FakeBot(), 123, ImmediateYouTube(), settings(), clock=clock)
        player.voice = voice
        player.queue.append(Track("First", "Artist", 180000, "first-url"))

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()):
            await player.play_next()
            clock.advance(30)
            voice.playing = False
            await player.enqueue(Track("Second", "Artist", 90000, "second-url"))

        self.assertEqual(player.current.title, "Second")
        self.assertEqual(player.current_elapsed_ms(), 0)
        clock.advance(3)
        self.assertEqual(player.current_elapsed_ms(), 3000)

    async def test_stop_clears_timing(self) -> None:
        clock = FakeClock()
        voice = StatefulVoice()
        player = GuildPlayer(FakeBot(), 123, ImmediateYouTube(), settings(), clock=clock)
        player.voice = voice
        player.queue.append(Track("Timed", "Artist", 180000, "timed-url"))

        with patch("siren.player.discord.FFmpegOpusAudio.from_probe", return_value=object()):
            await player.play_next()

        clock.advance(5)
        await player.stop()

        self.assertIsNone(player.current_elapsed_ms())
        self.assertEqual(player.current_remaining_ms(), 0)
```

- [ ] **Step 2: Run player tests and verify they fail**

Run:

```bash
PYTHONPATH=bot .venv/bin/python -m unittest tests.test_player_registry.GuildPlayerTests -v
```

Expected: failures because `GuildPlayer.__init__()` does not accept `clock`, and timing methods do not exist.

- [ ] **Step 3: Implement player timing state**

In `bot/siren/player.py`, add imports:

```python
import time
from collections.abc import Callable
```

Change the constructor signature and add fields:

```python
    def __init__(
        self,
        bot: Any,
        guild_id: int,
        youtube: YouTubeService,
        settings: Settings,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.youtube = youtube
        self.settings = settings
        self.clock = clock
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.voice: discord.VoiceClient | None = None
        self.play_lock = asyncio.Lock()
        self._transition_lock = asyncio.Lock()
        self._idle_task: asyncio.Task | None = None
        self._playback_generation = 0
        self._started_at_monotonic: float | None = None
        self._elapsed_before_pause_ms = 0
        self._paused_at_monotonic: float | None = None
```

Add timing methods to `GuildPlayer` after `tag`:

```python
    def _start_timing(self) -> None:
        self._started_at_monotonic = self.clock()
        self._elapsed_before_pause_ms = 0
        self._paused_at_monotonic = None

    def _clear_timing(self) -> None:
        self._started_at_monotonic = None
        self._elapsed_before_pause_ms = 0
        self._paused_at_monotonic = None

    def mark_paused(self) -> None:
        if self.current is None or self._paused_at_monotonic is not None:
            return
        elapsed = self.current_elapsed_ms()
        self._elapsed_before_pause_ms = elapsed or 0
        self._paused_at_monotonic = self.clock()
        self._started_at_monotonic = None

    def mark_resumed(self) -> None:
        if self.current is None or self._paused_at_monotonic is None:
            return
        self._started_at_monotonic = self.clock()
        self._paused_at_monotonic = None

    def current_elapsed_ms(self) -> int | None:
        if self.current is None:
            return None
        elapsed_ms = self._elapsed_before_pause_ms
        if self._started_at_monotonic is not None and self._paused_at_monotonic is None:
            elapsed_ms += int((self.clock() - self._started_at_monotonic) * 1000)
        elapsed_ms = max(0, elapsed_ms)
        if self.current.duration_ms > 0:
            return min(elapsed_ms, self.current.duration_ms)
        return elapsed_ms

    def current_remaining_ms(self) -> int | None:
        if self.current is None:
            return 0
        if self.current.duration_ms <= 0:
            return None
        elapsed = self.current_elapsed_ms()
        if elapsed is None:
            return None
        return max(0, self.current.duration_ms - elapsed)
```

In `_play_next_unlocked()`, call `self._clear_timing()` immediately before assigning the next track, call `self._start_timing()` after `self.voice.play(...)`, and call `self._clear_timing()` when the queue becomes empty:

```python
            self._clear_timing()
            track = self.queue.popleft()
            self.current = track
```

```python
                self.voice.play(source, after=lambda error: self._after_play(error, generation))
                self._start_timing()
```

```python
        self.current = None
        self._clear_timing()
        log.info("[player %s] queue empty", self.tag)
```

In `enqueue()`, update auto-resume:

```python
            if self.voice and self.voice.is_paused():
                log.info("[player %s] auto-resume on enqueue", self.tag)
                self.voice.resume()
                self.mark_resumed()
```

In `skip()`, clear timing before stopping voice:

```python
            log.info("[player %s] skip requested", self.tag)
            self._clear_timing()
            self.voice.stop()
```

In `_stop_unlocked()`, clear timing after clearing the queue:

```python
        self.queue.clear()
        self._clear_timing()
        self._playback_generation += 1
```

- [ ] **Step 4: Wire pause/resume commands to timing state**

In `bot/siren/commands/pause.py`, after `player.voice.pause()` add:

```python
            player.mark_paused()
```

In `bot/siren/commands/resume.py`, after `player.voice.resume()` add:

```python
            player.mark_resumed()
```

- [ ] **Step 5: Run player and queue tests and verify they pass**

Run:

```bash
PYTHONPATH=bot .venv/bin/python -m unittest tests.test_player_registry tests.test_queue_command -v
```

Expected: all player and queue tests pass.

---

### Task 3: Resolver Autocomplete Candidates

**Files:**
- Modify: `tests/test_resolver.py`
- Modify: `bot/siren/resolver.py`

- [ ] **Step 1: Add failing resolver autocomplete tests**

Append these tests to `ResolverTests` in `tests/test_resolver.py`:

```python
    async def test_autocomplete_uses_spotify_anchor_for_youtube_candidates(self) -> None:
        youtube = FakeYouTube([Track("Official", "Artist", 180000, "official-url")])
        resolver = TrackResolver(FakeSpotify(anchor=ANCHOR), youtube)

        choices = await resolver.autocomplete("never gonna give you up", limit=25)

        self.assertEqual(choices[0].webpage_url, "official-url")
        self.assertEqual(youtube.searches, ["Rick Astley - Never Gonna Give You Up"])

    async def test_autocomplete_falls_back_to_raw_youtube_search_without_spotify_anchor(self) -> None:
        youtube = FakeYouTube([Track("Raw", "Uploader", 180000, "raw-url")])
        resolver = TrackResolver(FakeSpotify(anchor=None), youtube)

        choices = await resolver.autocomplete("raw query", limit=25)

        self.assertEqual(choices[0].webpage_url, "raw-url")
        self.assertEqual(youtube.searches, ["raw query"])

    async def test_autocomplete_returns_no_candidates_for_empty_or_url_input(self) -> None:
        youtube = FakeYouTube([Track("Ignored", "Uploader", 180000, "ignored-url")])
        resolver = TrackResolver(FakeSpotify(anchor=ANCHOR), youtube)

        self.assertEqual(await resolver.autocomplete("", limit=25), [])
        self.assertEqual(await resolver.autocomplete("   ", limit=25), [])
        self.assertEqual(await resolver.autocomplete("https://www.youtube.com/watch?v=abc", limit=25), [])
        self.assertEqual(await resolver.autocomplete("https://open.spotify.com/track/abc", limit=25), [])
        self.assertEqual(youtube.searches, [])
```

- [ ] **Step 2: Run resolver autocomplete tests and verify they fail**

Run:

```bash
PYTHONPATH=bot .venv/bin/python -m unittest tests.test_resolver.ResolverTests.test_autocomplete_uses_spotify_anchor_for_youtube_candidates tests.test_resolver.ResolverTests.test_autocomplete_falls_back_to_raw_youtube_search_without_spotify_anchor tests.test_resolver.ResolverTests.test_autocomplete_returns_no_candidates_for_empty_or_url_input -v
```

Expected: failures because `TrackResolver.autocomplete()` does not exist.

- [ ] **Step 3: Implement `TrackResolver.autocomplete()`**

Add this method to `TrackResolver` in `bot/siren/resolver.py`, after `resolve()` and before `_resolve_anchored()`:

```python
    async def autocomplete(self, query: str, *, limit: int = 25) -> list[Track]:
        query = query.strip()
        if not query or is_url(query) or self.spotify.parse_url(query):
            return []

        try:
            anchor = await asyncio.to_thread(self.spotify.search_track, query)
        except Exception as exc:
            log.warning("[autocomplete] spotify search failed for %r: %s", query, exc)
            anchor = None

        if anchor:
            search_text = f"{anchor.author} - {anchor.title}" if anchor.author else anchor.title
            self._log_anchor(anchor)
        else:
            search_text = query

        try:
            return await self.youtube.search(search_text, limit=limit)
        except Exception as exc:
            log.warning("[autocomplete] youtube search failed for %r: %s", search_text, exc)
            return []
```

- [ ] **Step 4: Run resolver tests and verify they pass**

Run:

```bash
PYTHONPATH=bot .venv/bin/python -m unittest tests.test_resolver -v
```

Expected: all resolver tests pass.

---

### Task 4: `/play` Autocomplete Choices

**Files:**
- Create: `tests/test_play_command.py`
- Modify: `bot/siren/commands/play.py`

- [ ] **Step 1: Add failing play autocomplete helper tests**

Create `tests/test_play_command.py` with:

```python
import unittest

from siren.commands.play import tracks_to_choices
from siren.models import Track


class PlayCommandAutocompleteTests(unittest.TestCase):
    def test_tracks_to_choices_uses_readable_label_and_url_value(self) -> None:
        choices = tracks_to_choices(
            [Track("Drink (Official Video)", "Alestorm", 203000, "https://www.youtube.com/watch?v=pibSHkDG91g")]
        )

        self.assertEqual(len(choices), 1)
        self.assertEqual(choices[0].name, "Alestorm - Drink (Official Video) [3:23]")
        self.assertEqual(choices[0].value, "https://www.youtube.com/watch?v=pibSHkDG91g")

    def test_tracks_to_choices_omits_duration_when_unknown(self) -> None:
        choices = tracks_to_choices([Track("Mystery", "Uploader", 0, "https://www.youtube.com/watch?v=abc")])

        self.assertEqual(choices[0].name, "Uploader - Mystery")

    def test_tracks_to_choices_truncates_long_names(self) -> None:
        title = "A" * 140
        choices = tracks_to_choices([Track(title, "Artist", 60000, "https://www.youtube.com/watch?v=abc")])

        self.assertEqual(len(choices[0].name), 100)
        self.assertTrue(choices[0].name.endswith("..."))

    def test_tracks_to_choices_skips_values_too_long_for_discord(self) -> None:
        choices = tracks_to_choices([Track("Song", "Artist", 60000, "https://example.com/" + "a" * 120)])

        self.assertEqual(choices, [])

    def test_tracks_to_choices_caps_results_at_25(self) -> None:
        tracks = [Track(f"Song {index}", "Artist", 60000, f"https://youtu.be/{index}") for index in range(30)]

        choices = tracks_to_choices(tracks)

        self.assertEqual(len(choices), 25)
```

- [ ] **Step 2: Run play autocomplete tests and verify they fail**

Run:

```bash
PYTHONPATH=bot .venv/bin/python -m unittest tests.test_play_command -v
```

Expected: import failure because `tracks_to_choices` does not exist.

- [ ] **Step 3: Implement autocomplete choice helpers and register autocomplete**

Replace `bot/siren/commands/play.py` with:

```python
from __future__ import annotations

import logging

import discord
from discord import app_commands

from ..models import Track, fmt_duration
from .base import CommandBase

log = logging.getLogger("siren")

MAX_AUTOCOMPLETE_CHOICES = 25
DISCORD_CHOICE_NAME_LIMIT = 100
DISCORD_CHOICE_VALUE_LIMIT = 100


def choice_label(track: Track) -> str:
    label = f"{track.author} - {track.title}" if track.author else track.title
    duration = fmt_duration(track.duration_ms)
    if duration != "?:??":
        label = f"{label} [{duration}]"
    if len(label) > DISCORD_CHOICE_NAME_LIMIT:
        label = label[: DISCORD_CHOICE_NAME_LIMIT - 3] + "..."
    return label


def tracks_to_choices(tracks: list[Track]) -> list[app_commands.Choice[str]]:
    choices: list[app_commands.Choice[str]] = []
    seen_values: set[str] = set()
    for track in tracks:
        if not track.webpage_url or len(track.webpage_url) > DISCORD_CHOICE_VALUE_LIMIT:
            continue
        if track.webpage_url in seen_values:
            continue
        seen_values.add(track.webpage_url)
        choices.append(app_commands.Choice(name=choice_label(track), value=track.webpage_url))
        if len(choices) >= MAX_AUTOCOMPLETE_CHOICES:
            break
    return choices


class PlayCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="play", description="Play a song. URL or 'artist - title'.")
        @app_commands.describe(query="A URL (Spotify/YouTube/SoundCloud) or text search.")
        @app_commands.autocomplete(query=self.autocomplete_query)
        async def play(interaction: discord.Interaction, query: str) -> None:
            await interaction.response.defer()
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            async with player.play_lock:
                if await self.ensure_voice(interaction) is None:
                    return
                result = await self.bot.resolver.resolve(query)
                if not result.ok:
                    await interaction.followup.send(result.message or f"Couldn't resolve `{query}`.")
                    return
                assert result.track is not None
                await player.enqueue(result.track)
                await interaction.followup.send(f"Queued **{result.track.title}** by *{result.track.author}*.")

    async def autocomplete_query(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        del interaction
        try:
            tracks = await self.bot.resolver.autocomplete(current, limit=MAX_AUTOCOMPLETE_CHOICES)
        except Exception as exc:
            log.warning("[autocomplete] failed for %r: %s", current, exc)
            return []
        return tracks_to_choices(tracks)
```

- [ ] **Step 4: Run play autocomplete tests and bot setup tests**

Run:

```bash
PYTHONPATH=bot .venv/bin/python -m unittest tests.test_play_command tests.test_app tests.test_bot -v
```

Expected: all tests pass and app/bot setup still works.

---

### Task 5: Final Verification And Bot Restart

**Files:**
- No code changes.

- [ ] **Step 1: Run full unit suite**

Run:

```bash
PYTHONPATH=bot .venv/bin/python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Compile Python files**

Run:

```bash
PYTHONPYCACHEPREFIX=/var/folders/z1/hj7cl3756jn651xfjpw3s8lw0000gn/T/opencode/pycache-siren .venv/bin/python -m compileall -q bot tests
```

Expected: no output and exit 0.

- [ ] **Step 3: Validate Docker Compose config safely**

Run:

```bash
env DISCORD_TOKEN=dummy SPOTIFY_CLIENT_ID=dummy SPOTIFY_CLIENT_SECRET=dummy DISCORD_GUILD_IDS=123456789012345678 LOG_LEVEL=INFO YT_COOKIES_FILE= docker compose --env-file /dev/null config
```

Expected: config renders with dummy values and no real credential values are printed.

- [ ] **Step 4: Build image**

Run:

```bash
docker compose build
```

Expected: `siren-bot:latest` builds.

- [ ] **Step 5: Run safe image smoke checks**

Run:

```bash
docker run --rm siren-bot:latest python -m compileall -q .
```

Expected: no output and exit 0.

Run:

```bash
docker run --rm siren-bot:latest python -c 'import siren; import siren.app; import siren.config; import main; print(siren.APP_NAME)'
```

Expected: `SirenBot`.

Run:

```bash
docker run --rm siren-bot:latest python -c 'import subprocess, sys; r = subprocess.run([sys.executable, "main.py"], capture_output=True, text=True); output = r.stdout + r.stderr; print(f"exit={r.returncode}"); print(output, end=""); assert r.returncode != 0; assert "Missing required environment variables: DISCORD_TOKEN, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET" in output'
```

Expected: exit code printed as non-zero with the missing-env error.

Run:

```bash
docker run --rm -e DISCORD_TOKEN=dummy -e SPOTIFY_CLIENT_ID=dummy -e SPOTIFY_CLIENT_SECRET=dummy siren-bot:latest python -c 'from siren.app import create_bot; bot = create_bot(); print(type(bot).__name__, len(bot.tree.get_commands()))'
```

Expected: `SirenBot 6`.

- [ ] **Step 6: Restart the live bot with the verified image**

Run:

```bash
docker compose up -d bot
```

Expected: Compose recreates or restarts `siren-bot` with the new image.

- [ ] **Step 7: Confirm the restarted live bot is healthy**

Run:

```bash
docker inspect --format '{{.State.Status}} running={{.State.Running}} restarts={{.RestartCount}} started={{.State.StartedAt}}' siren-bot
```

Expected: status is `running`.

Run:

```bash
docker logs --tail 30 siren-bot
```

Expected: logs show Discord gateway connection and command sync without a startup traceback.

---

## Self-Review Notes

- Spec coverage: queue progress, clock-time estimates, hybrid autocomplete, error handling, and verified restart are covered by Tasks 1-5.
- Scope: MySQL persistence is intentionally excluded.
- Type consistency: `current_elapsed_ms()`, `current_remaining_ms()`, `mark_paused()`, `mark_resumed()`, `TrackResolver.autocomplete()`, and `tracks_to_choices()` are named consistently across tests and implementation steps.
- Verification: final commands avoid printing real credentials before restarting the live bot with the verified image.

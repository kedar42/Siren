# SirenBot Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor the current single-file Discord music bot into a modular, object-oriented Python package named SirenBot while preserving behavior and applying the targeted correctness fixes from the design spec.

**Architecture:** Create a `bot/siren/` package with explicit service objects for configuration, Spotify, YouTube, resolution, playback, bot lifecycle, and command registration. Keep `bot/main.py` as a small entrypoint, move each slash command into `bot/siren/commands/<command>.py`, and use dependency injection instead of global service clients.

**Tech Stack:** Python 3.12, discord.py, yt-dlp, spotipy, rapidfuzz, python-dotenv, unittest, Docker Compose.

---

## File Structure

Create:

- `bot/siren/__init__.py`: package marker and version/name constants.
- `bot/siren/config.py`: immutable `Settings`, environment validation, yt-dlp and ffmpeg option builders.
- `bot/siren/models.py`: shared domain models and formatting helpers.
- `bot/siren/spotify.py`: `SpotifyService`, Spotify URL parsing, Spotify object conversion.
- `bot/siren/youtube.py`: `YouTubeService`, yt-dlp search, yt-dlp stream resolution.
- `bot/siren/resolver.py`: `TrackResolver`, `ResolveResult`, scoring, anchored and fallback resolution.
- `bot/siren/player.py`: `GuildPlayer`, queue state, playback transitions, idle disconnect.
- `bot/siren/player_registry.py`: `PlayerRegistry` for one `GuildPlayer` per guild.
- `bot/siren/bot.py`: `SirenBot` subclass, lifecycle hooks, guild command sync.
- `bot/siren/app.py`: application factory and service wiring.
- `bot/siren/commands/__init__.py`: command registration helper.
- `bot/siren/commands/base.py`: shared command helpers.
- `bot/siren/commands/play.py`: `/play` command.
- `bot/siren/commands/skip.py`: `/skip` command.
- `bot/siren/commands/stop.py`: `/stop` command.
- `bot/siren/commands/pause.py`: `/pause` command.
- `bot/siren/commands/resume.py`: `/resume` command.
- `bot/siren/commands/queue.py`: `/queue` command and queue formatting helper.
- `tests/__init__.py`: test package marker.
- `tests/test_config.py`: settings validation tests.
- `tests/test_models.py`: model helper tests.
- `tests/test_spotify.py`: Spotify URL parsing and conversion tests.
- `tests/test_youtube.py`: YouTube conversion and option tests.
- `tests/test_resolver.py`: resolver scoring and failure-result tests.
- `tests/test_player_registry.py`: player registry tests.
- `tests/test_queue_command.py`: queue formatting tests.

Modify:

- `bot/main.py`: replace monolithic implementation with tiny SirenBot startup.
- `README.md`: rename Aether to SirenBot and update completed command checklist.
- `docker-compose.yml`: rename `container_name` from `aether-bot` to `siren-bot`.

No deletion is needed during the first pass. The old logic in `bot/main.py` will be replaced once the package exists.

The workspace is not currently a git repository. Commit steps below are written as checkpoints. If a git repository is initialized before execution, run the listed commit commands. Otherwise, record the checkpoint in the session and continue.

---

### Task 1: Models And Configuration

**Files:**
- Create: `bot/siren/__init__.py`
- Create: `bot/siren/models.py`
- Create: `bot/siren/config.py`
- Create: `tests/__init__.py`
- Create: `tests/test_models.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing model and config tests**

Create `tests/__init__.py` as an empty file.

Create `tests/test_models.py`:

```python
import unittest

from siren.models import Track, fmt_duration


class ModelTests(unittest.TestCase):
    def test_fmt_duration_formats_positive_milliseconds(self) -> None:
        self.assertEqual(fmt_duration(185_000), "3:05")

    def test_fmt_duration_handles_unknown_or_zero_duration(self) -> None:
        self.assertEqual(fmt_duration(0), "?:??")
        self.assertEqual(fmt_duration(-1), "?:??")

    def test_track_carries_optional_isrc(self) -> None:
        track = Track(
            title="Song",
            author="Artist",
            duration_ms=123_000,
            webpage_url="https://example.test/watch",
            isrc="USRC17607839",
        )
        self.assertEqual(track.isrc, "USRC17607839")
```

Create `tests/test_config.py`:

```python
import unittest

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

    def test_ytdl_options_include_cookiefile_only_when_set(self) -> None:
        without_cookie = Settings.from_env(VALID_ENV)
        self.assertNotIn("cookiefile", without_cookie.ytdl_base_options)

        with_cookie = Settings.from_env({**VALID_ENV, "YT_COOKIES_FILE": "/app/data/cookies.txt"})
        self.assertEqual(with_cookie.ytdl_base_options["cookiefile"], "/app/data/cookies.txt")
```

- [ ] **Step 2: Run tests to verify they fail**

Run from repository root:

```bash
PYTHONPATH=bot python3 -m unittest tests.test_models tests.test_config -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'siren'` or import errors for missing modules.

- [ ] **Step 3: Add package, model, and config implementation**

Create `bot/siren/__init__.py`:

```python
APP_NAME = "SirenBot"
LOGGER_NAME = "siren"
```

Create `bot/siren/models.py`:

```python
from dataclasses import dataclass


@dataclass
class Track:
    title: str
    author: str
    duration_ms: int
    webpage_url: str
    isrc: str | None = None


def fmt_duration(ms: int) -> str:
    if ms <= 0:
        return "?:??"
    seconds = ms // 1000
    return f"{seconds // 60}:{seconds % 60:02d}"
```

Create `bot/siren/config.py`:

```python
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Mapping

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    pass


FFMPEG_BEFORE_OPTIONS = (
    "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5 "
    "-nostdin -loglevel warning"
)
FFMPEG_OPTIONS = "-vn"
DEFAULT_IDLE_TIMEOUT_SECONDS = 300


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
            log_level=source.get("LOG_LEVEL", "INFO").upper(),
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
    load_dotenv()
    return Settings.from_env()
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=bot python3 -m unittest tests.test_models tests.test_config -v
```

Expected: PASS for all tests in `tests.test_models` and `tests.test_config`.

- [ ] **Step 5: Checkpoint**

Run:

```bash
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If git has been initialized before execution, commit with:

```bash
git add bot/siren/__init__.py bot/siren/models.py bot/siren/config.py tests/__init__.py tests/test_models.py tests/test_config.py
git commit -m "refactor: add SirenBot models and config"
```

---

### Task 2: Spotify Service

**Files:**
- Create: `bot/siren/spotify.py`
- Modify: `tests/test_spotify.py`

- [ ] **Step 1: Write failing Spotify tests**

Create `tests/test_spotify.py`:

```python
import unittest

from siren.config import Settings
from siren.spotify import SpotifyService, SpotifyUrlKind, UnsupportedSpotifyUrl


class FakeSpotifyClient:
    def __init__(self) -> None:
        self.track_calls: list[str] = []
        self.search_calls: list[dict[str, object]] = []

    def track(self, url_or_id: str) -> dict[str, object]:
        self.track_calls.append(url_or_id)
        return {
            "name": "Song",
            "artists": [{"name": "Artist"}],
            "duration_ms": 123000,
            "external_urls": {"spotify": "https://open.spotify.com/track/abc123"},
            "external_ids": {"isrc": "USRC17607839"},
        }

    def search(self, q: str, type: str, limit: int) -> dict[str, object]:
        self.search_calls.append({"q": q, "type": type, "limit": limit})
        return {"tracks": {"items": [self.track("from-search")]}}


def settings() -> Settings:
    return Settings.from_env(
        {
            "DISCORD_TOKEN": "discord-token",
            "SPOTIFY_CLIENT_ID": "spotify-id",
            "SPOTIFY_CLIENT_SECRET": "spotify-secret",
        }
    )


class SpotifyServiceTests(unittest.TestCase):
    def test_parse_track_url(self) -> None:
        parsed = SpotifyService.parse_url("https://open.spotify.com/track/abc123?si=value")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.kind, SpotifyUrlKind.TRACK)
        self.assertEqual(parsed.spotify_id, "abc123")

    def test_parse_internationalized_album_url(self) -> None:
        parsed = SpotifyService.parse_url("https://open.spotify.com/intl-de/album/album123")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed.kind, SpotifyUrlKind.ALBUM)
        self.assertEqual(parsed.spotify_id, "album123")

    def test_track_from_url_rejects_album_url_clearly(self) -> None:
        service = SpotifyService(settings(), client=FakeSpotifyClient())
        with self.assertRaises(UnsupportedSpotifyUrl) as ctx:
            service.track_from_url("https://open.spotify.com/album/album123")
        self.assertEqual(ctx.exception.kind, SpotifyUrlKind.ALBUM)

    def test_track_from_url_converts_spotify_track(self) -> None:
        client = FakeSpotifyClient()
        service = SpotifyService(settings(), client=client)
        track = service.track_from_url("https://open.spotify.com/track/abc123")
        self.assertEqual(track.title, "Song")
        self.assertEqual(track.author, "Artist")
        self.assertEqual(track.duration_ms, 123000)
        self.assertEqual(track.isrc, "USRC17607839")
        self.assertEqual(client.track_calls[0], "https://open.spotify.com/track/abc123")

    def test_search_first_track(self) -> None:
        service = SpotifyService(settings(), client=FakeSpotifyClient())
        track = service.search_track("artist song")
        self.assertIsNotNone(track)
        assert track is not None
        self.assertEqual(track.title, "Song")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=bot python3 -m unittest tests.test_spotify -v
```

Expected: FAIL with `ModuleNotFoundError` or missing names from `siren.spotify`.

- [ ] **Step 3: Implement SpotifyService**

Create `bot/siren/spotify.py`:

```python
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials

from .config import Settings
from .models import Track

log = logging.getLogger("siren")


class SpotifyUrlKind(StrEnum):
    TRACK = "track"
    ALBUM = "album"
    PLAYLIST = "playlist"


@dataclass(frozen=True)
class SpotifyUrl:
    kind: SpotifyUrlKind
    spotify_id: str
    url: str


class UnsupportedSpotifyUrl(ValueError):
    def __init__(self, kind: SpotifyUrlKind) -> None:
        self.kind = kind
        super().__init__(f"Spotify {kind.value} URLs are not supported yet. Please use a Spotify track URL.")


SPOTIFY_URL_RE = re.compile(
    r"https?://open\.spotify\.com/(?:intl-[a-z]+/)?(track|album|playlist)/([A-Za-z0-9]+)"
)


class SpotifyService:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._client = client or spotipy.Spotify(
            auth_manager=SpotifyClientCredentials(
                client_id=settings.spotify_client_id,
                client_secret=settings.spotify_client_secret,
            )
        )

    @staticmethod
    def parse_url(query: str) -> SpotifyUrl | None:
        match = SPOTIFY_URL_RE.search(query)
        if not match:
            return None
        return SpotifyUrl(
            kind=SpotifyUrlKind(match.group(1)),
            spotify_id=match.group(2),
            url=match.group(0),
        )

    def track_from_url(self, url: str) -> Track | None:
        parsed = self.parse_url(url)
        if parsed is None:
            return None
        if parsed.kind is not SpotifyUrlKind.TRACK:
            raise UnsupportedSpotifyUrl(parsed.kind)
        return self._track_lookup(url)

    def search_track(self, query: str) -> Track | None:
        try:
            response = self._client.search(q=query, type="track", limit=1)
        except Exception as exc:
            log.warning("[resolve] spotify search failed: %s", exc)
            return None
        items = (response or {}).get("tracks", {}).get("items", [])
        return self._track_from_obj(items[0]) if items else None

    def _track_lookup(self, url_or_id: str) -> Track | None:
        try:
            spotify_track = self._client.track(url_or_id)
        except Exception as exc:
            log.warning("[resolve] spotify track lookup failed: %s", exc)
            return None
        return self._track_from_obj(spotify_track) if spotify_track else None

    @staticmethod
    def _track_from_obj(spotify_track: dict[str, Any]) -> Track:
        return Track(
            title=str(spotify_track["name"]),
            author=", ".join(artist["name"] for artist in spotify_track["artists"]) or "",
            duration_ms=int(spotify_track["duration_ms"]),
            webpage_url=str(spotify_track.get("external_urls", {}).get("spotify", "")),
            isrc=(spotify_track.get("external_ids") or {}).get("isrc"),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=bot python3 -m unittest tests.test_spotify -v
```

Expected: PASS for all tests in `tests.test_spotify`.

- [ ] **Step 5: Checkpoint**

Run:

```bash
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If git has been initialized before execution, commit with:

```bash
git add bot/siren/spotify.py tests/test_spotify.py
git commit -m "refactor: add Spotify service"
```

---

### Task 3: YouTube Service

**Files:**
- Create: `bot/siren/youtube.py`
- Modify: `tests/test_youtube.py`

- [ ] **Step 1: Write failing YouTube tests**

Create `tests/test_youtube.py`:

```python
import unittest

from siren.config import Settings
from siren.youtube import YouTubeService


class FakeYoutubeDL:
    calls: list[dict[str, object]] = []

    def __init__(self, options: dict[str, object]) -> None:
        self.options = options
        FakeYoutubeDL.calls.append(options)

    def __enter__(self) -> "FakeYoutubeDL":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def extract_info(self, target: str, download: bool) -> dict[str, object]:
        if target.startswith("ytsearch"):
            return {
                "entries": [
                    {
                        "title": "Song",
                        "uploader": "Artist",
                        "duration": 123,
                        "webpage_url": "https://youtube.test/watch?v=1",
                    }
                ]
            }
        return {
            "title": "Resolved Song",
            "channel": "Resolved Artist",
            "duration": 124,
            "webpage_url": target,
            "requested_formats": [
                {"acodec": "none", "url": "https://video.invalid"},
                {"acodec": "opus", "url": "https://audio.valid"},
            ],
        }


def settings() -> Settings:
    return Settings.from_env(
        {
            "DISCORD_TOKEN": "discord-token",
            "SPOTIFY_CLIENT_ID": "spotify-id",
            "SPOTIFY_CLIENT_SECRET": "spotify-secret",
            "YT_COOKIES_FILE": "/app/data/cookies.txt",
        }
    )


class YouTubeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_returns_tracks_from_flat_entries(self) -> None:
        service = YouTubeService(settings(), ydl_cls=FakeYoutubeDL)
        tracks = await service.search("artist song", limit=3)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].title, "Song")
        self.assertEqual(tracks[0].author, "Artist")
        self.assertEqual(tracks[0].duration_ms, 123000)
        self.assertEqual(tracks[0].webpage_url, "https://youtube.test/watch?v=1")
        self.assertTrue(FakeYoutubeDL.calls[-1]["extract_flat"])
        self.assertEqual(FakeYoutubeDL.calls[-1]["cookiefile"], "/app/data/cookies.txt")

    async def test_resolve_url_uses_audio_requested_format_when_url_missing(self) -> None:
        service = YouTubeService(settings(), ydl_cls=FakeYoutubeDL)
        resolved = await service.resolve_url("https://youtube.test/watch?v=1")
        self.assertIsNotNone(resolved)
        assert resolved is not None
        track, stream_url = resolved
        self.assertEqual(track.title, "Resolved Song")
        self.assertEqual(track.author, "Resolved Artist")
        self.assertEqual(track.duration_ms, 124000)
        self.assertEqual(stream_url, "https://audio.valid")
        self.assertEqual(FakeYoutubeDL.calls[-1]["format"], "bestaudio/best")
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=bot python3 -m unittest tests.test_youtube -v
```

Expected: FAIL with missing `siren.youtube`.

- [ ] **Step 3: Implement YouTubeService**

Create `bot/siren/youtube.py`:

```python
from __future__ import annotations

import asyncio
import logging
from typing import Any

import yt_dlp

from .config import Settings
from .models import Track

log = logging.getLogger("siren")


class YouTubeService:
    def __init__(self, settings: Settings, ydl_cls: Any = yt_dlp.YoutubeDL) -> None:
        self._settings = settings
        self._ydl_cls = ydl_cls

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        return await asyncio.to_thread(self._search_sync, query, limit)

    async def resolve_url(self, url: str) -> tuple[Track, str] | None:
        return await asyncio.to_thread(self._resolve_url_sync, url)

    def _search_sync(self, query: str, limit: int = 5) -> list[Track]:
        try:
            with self._ydl_cls(self._settings.ytdl_search_options) as ydl:
                info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False)
        except yt_dlp.utils.DownloadError as exc:
            log.warning("[resolve] yt search %r failed: %s", query, exc)
            return []

        tracks: list[Track] = []
        for entry in (info or {}).get("entries") or []:
            track = self._entry_to_track(entry)
            if track:
                tracks.append(track)
        return tracks

    def _resolve_url_sync(self, url: str) -> tuple[Track, str] | None:
        try:
            with self._ydl_cls(self._settings.ytdl_resolve_options) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            log.warning("[stream] extract %r failed: %s", url, exc)
            return None
        if not info:
            return None

        duration = info.get("duration") or 0
        track = Track(
            title=info.get("title") or "?",
            author=info.get("uploader") or info.get("channel") or "",
            duration_ms=int(duration * 1000) if duration else 0,
            webpage_url=info.get("webpage_url") or url,
        )
        stream_url = info.get("url")
        if not stream_url:
            for fmt in info.get("requested_formats") or []:
                if fmt.get("acodec") and fmt["acodec"] != "none":
                    stream_url = fmt.get("url")
                    break
        if not stream_url:
            log.warning("[stream] no playable URL on %s", url)
            return None
        return track, stream_url

    @staticmethod
    def _entry_to_track(entry: dict[str, Any]) -> Track | None:
        if not entry:
            return None
        duration = entry.get("duration") or 0
        url = entry.get("webpage_url") or entry.get("url") or ""
        if not url:
            return None
        return Track(
            title=entry.get("title") or "?",
            author=entry.get("uploader") or entry.get("channel") or "",
            duration_ms=int(duration * 1000) if duration else 0,
            webpage_url=url,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=bot python3 -m unittest tests.test_youtube -v
```

Expected: PASS for all tests in `tests.test_youtube`.

- [ ] **Step 5: Checkpoint**

Run:

```bash
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If git has been initialized before execution, commit with:

```bash
git add bot/siren/youtube.py tests/test_youtube.py
git commit -m "refactor: add YouTube service"
```

---

### Task 4: Track Resolver

**Files:**
- Create: `bot/siren/resolver.py`
- Modify: `tests/test_resolver.py`

- [ ] **Step 1: Write failing resolver tests**

Create `tests/test_resolver.py`:

```python
import unittest

from siren.models import Track
from siren.resolver import TrackResolver, score_candidate
from siren.spotify import SpotifyUrlKind, UnsupportedSpotifyUrl


class FakeSpotify:
    def __init__(self, anchor: Track | None = None, unsupported: SpotifyUrlKind | None = None) -> None:
        self.anchor = anchor
        self.unsupported = unsupported

    def track_from_url(self, url: str) -> Track | None:
        if self.unsupported:
            raise UnsupportedSpotifyUrl(self.unsupported)
        return self.anchor

    def search_track(self, query: str) -> Track | None:
        return self.anchor

    @staticmethod
    def parse_url(query: str):
        from siren.spotify import SpotifyService

        return SpotifyService.parse_url(query)


class FakeYouTube:
    def __init__(self, candidates: list[Track]) -> None:
        self.candidates = candidates
        self.searches: list[str] = []

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        self.searches.append(query)
        return self.candidates

    async def resolve_url(self, url: str):
        return Track("Resolved", "Uploader", 100000, url), "https://stream.test/audio"


ANCHOR = Track("Never Gonna Give You Up", "Rick Astley", 213000, "spotify", "GBARL9300135")


class ResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_unsupported_spotify_album_returns_clear_result(self) -> None:
        resolver = TrackResolver(FakeSpotify(unsupported=SpotifyUrlKind.ALBUM), FakeYouTube([]))
        result = await resolver.resolve("https://open.spotify.com/album/abc123")
        self.assertFalse(result.ok)
        self.assertIsNone(result.track)
        self.assertIn("Spotify album URLs", result.message)

    async def test_text_query_uses_spotify_anchor_and_picks_best_candidate(self) -> None:
        candidates = [
            Track("Never Gonna Give You Up lyrics", "Someone", 213000, "bad"),
            Track("Rick Astley - Never Gonna Give You Up", "Rick Astley", 213000, "good"),
        ]
        resolver = TrackResolver(FakeSpotify(anchor=ANCHOR), FakeYouTube(candidates))
        result = await resolver.resolve("never gonna give you up")
        self.assertTrue(result.ok)
        self.assertIsNotNone(result.track)
        assert result.track is not None
        self.assertEqual(result.track.webpage_url, "good")
        self.assertEqual(result.track.isrc, "GBARL9300135")

    async def test_plain_youtube_fallback_when_spotify_has_no_anchor(self) -> None:
        first = Track("First", "Uploader", 100000, "first-url")
        resolver = TrackResolver(FakeSpotify(anchor=None), FakeYouTube([first]))
        result = await resolver.resolve("plain query")
        self.assertTrue(result.ok)
        self.assertEqual(result.track, first)

    def test_score_rejects_large_duration_mismatch(self) -> None:
        candidate = Track("Song", "Artist", 300000, "url")
        target = Track("Song", "Artist", 100000, "target")
        self.assertEqual(score_candidate(candidate, target, has_anchor=True), float("-inf"))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=bot python3 -m unittest tests.test_resolver -v
```

Expected: FAIL with missing `siren.resolver`.

- [ ] **Step 3: Implement TrackResolver**

Create `bot/siren/resolver.py`:

```python
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .models import Track
from .spotify import SpotifyService, UnsupportedSpotifyUrl
from .youtube import YouTubeService

log = logging.getLogger("siren")

JUNK_PATTERNS = re.compile(
    r"\b(lyric[s]?|sped[- ]?up|slowed|nightcore|8d|"
    r"bass[- ]?boost(?:ed)?|reverb|karaoke|cover|instrumental)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ResolveResult:
    track: Track | None = None
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.track is not None


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def score_candidate(candidate: Track, target: Track, *, has_anchor: bool) -> float:
    if has_anchor and JUNK_PATTERNS.search(candidate.title):
        if not JUNK_PATTERNS.search(target.title):
            return float("-inf")

    if target.duration_ms > 0 and candidate.duration_ms > 0:
        delta_seconds = abs(candidate.duration_ms - target.duration_ms) / 1000
        if delta_seconds > 30:
            return float("-inf")
        duration_score = max(0.0, 1.0 - (delta_seconds / 15.0))
    else:
        duration_score = 0.5

    title_score = fuzz.token_set_ratio(target.title, candidate.title) / 100.0
    artist_score = fuzz.partial_ratio(target.author, candidate.author) / 100.0 if target.author else 0.5
    return duration_score * 2.0 + title_score * 1.5 + artist_score


class TrackResolver:
    def __init__(self, spotify: SpotifyService, youtube: YouTubeService) -> None:
        self.spotify = spotify
        self.youtube = youtube

    async def resolve(self, query: str) -> ResolveResult:
        log.info("[resolve] query=%r", query)

        spotify_url = self.spotify.parse_url(query)
        if is_url(query) and spotify_url:
            try:
                anchor = self.spotify.track_from_url(query)
            except UnsupportedSpotifyUrl as exc:
                return ResolveResult(message=str(exc))
            if not anchor:
                log.warning("[resolve] spotify URL did not resolve: %s", query)
                return ResolveResult(message=f"Couldn't resolve `{query}`.")
            self._log_anchor(anchor)
            return await self._resolve_anchored(anchor, query)

        if is_url(query):
            log.info("[resolve] direct URL -> yt-dlp")
            resolved = await self.youtube.resolve_url(query)
            return ResolveResult(track=resolved[0]) if resolved else ResolveResult(message=f"Couldn't resolve `{query}`.")

        anchor = self.spotify.search_track(query)
        if anchor:
            self._log_anchor(anchor)
            return await self._resolve_anchored(anchor, query)

        log.info("[resolve] no spotify anchor; falling back to plain yt search")
        candidates = await self.youtube.search(query, limit=5)
        if not candidates:
            log.warning("[resolve] no candidates for %r", query)
            return ResolveResult(message=f"Couldn't resolve `{query}`.")
        return ResolveResult(track=candidates[0])

    async def _resolve_anchored(self, anchor: Track, original_query: str) -> ResolveResult:
        candidates: list[Track] = []
        if anchor.isrc:
            isrc_candidates = await self.youtube.search(f'"{anchor.isrc}"', limit=5)
            log.info("[resolve] ISRC search -> %d candidates", len(isrc_candidates))
            candidates.extend(isrc_candidates)

        text = f"{anchor.author} - {anchor.title}" if anchor.author else original_query
        text_candidates = await self.youtube.search(text, limit=5)
        log.info("[resolve] text search %r -> %d candidates", text, len(text_candidates))
        candidates.extend(text_candidates)

        if not candidates:
            log.warning("[resolve] no YT candidates for %s - %s", anchor.author, anchor.title)
            return ResolveResult(message=f"Couldn't resolve `{original_query}`.")

        scored = sorted(
            ((score_candidate(candidate, anchor, has_anchor=True), candidate) for candidate in candidates),
            key=lambda item: item[0],
            reverse=True,
        )
        best_score, best = scored[0]
        if best_score == float("-inf"):
            log.warning("[resolve] all candidates rejected by junk filter / duration")
            return ResolveResult(message=f"Couldn't resolve `{original_query}`.")

        log.info("[resolve] picked: %s - %s (score=%.2f, url=%s)", best.author, best.title, best_score, best.webpage_url)
        best.isrc = anchor.isrc
        return ResolveResult(track=best)

    @staticmethod
    def _log_anchor(anchor: Track) -> None:
        log.info("[resolve] spotify anchor: %s - %s (isrc=%s, %.1fs)", anchor.author, anchor.title, anchor.isrc, anchor.duration_ms / 1000)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=bot python3 -m unittest tests.test_resolver -v
```

Expected: PASS for all tests in `tests.test_resolver`.

- [ ] **Step 5: Checkpoint**

Run:

```bash
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If git has been initialized before execution, commit with:

```bash
git add bot/siren/resolver.py tests/test_resolver.py
git commit -m "refactor: add track resolver"
```

---

### Task 5: Player And Registry

**Files:**
- Create: `bot/siren/player.py`
- Create: `bot/siren/player_registry.py`
- Modify: `tests/test_player_registry.py`

- [ ] **Step 1: Write failing registry tests**

Create `tests/test_player_registry.py`:

```python
import unittest

from siren.config import Settings
from siren.player import GuildPlayer
from siren.player_registry import PlayerRegistry


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


class PlayerRegistryTests(unittest.TestCase):
    def test_player_returns_same_instance_for_same_guild(self) -> None:
        registry = PlayerRegistry(FakeBot(), FakeYouTube(), settings())
        first = registry.player(123)
        second = registry.player(123)
        self.assertIs(first, second)
        self.assertIsInstance(first, GuildPlayer)
        self.assertEqual(first.guild_id, 123)

    def test_get_returns_none_for_unknown_guild(self) -> None:
        registry = PlayerRegistry(FakeBot(), FakeYouTube(), settings())
        self.assertIsNone(registry.get(999))
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=bot python3 -m unittest tests.test_player_registry -v
```

Expected: FAIL with missing `siren.player` or `siren.player_registry`.

- [ ] **Step 3: Implement GuildPlayer and PlayerRegistry**

Create `bot/siren/player.py` by moving the existing `GuildPlayer` behavior from `bot/main.py` and changing dependencies to constructor parameters:

```python
from __future__ import annotations

import asyncio
import logging
from collections import deque
from typing import Any

import discord

from .config import Settings
from .models import Track
from .youtube import YouTubeService

log = logging.getLogger("siren")


class GuildPlayer:
    def __init__(self, bot: Any, guild_id: int, youtube: YouTubeService, settings: Settings) -> None:
        self.bot = bot
        self.guild_id = guild_id
        self.youtube = youtube
        self.settings = settings
        self.queue: deque[Track] = deque()
        self.current: Track | None = None
        self.voice: discord.VoiceClient | None = None
        self.play_lock = asyncio.Lock()
        self._transition_lock = asyncio.Lock()
        self._idle_task: asyncio.Task | None = None

    @property
    def tag(self) -> str:
        return f"guild={self.guild_id}"

    def _alone(self) -> bool:
        if not self.voice or not self.voice.is_connected():
            return False
        return all(member.bot for member in self.voice.channel.members)

    def _is_idle(self) -> bool:
        if not self.voice or not self.voice.is_connected():
            return False
        if self._alone():
            return True
        return not self.voice.is_playing() and not self.voice.is_paused() and not self.queue and self.current is None

    def reconcile_idle(self) -> None:
        if self._is_idle():
            if self._idle_task is None or self._idle_task.done():
                log.info("[player %s] idle -> arming disconnect (%ds)", self.tag, self.settings.idle_timeout_seconds)
                self._idle_task = asyncio.create_task(self._idle_watcher())
        elif self._idle_task is not None and not self._idle_task.done():
            log.info("[player %s] active -> cancelling idle disconnect", self.tag)
            self._idle_task.cancel()
            self._idle_task = None

    async def _idle_watcher(self) -> None:
        try:
            await asyncio.sleep(self.settings.idle_timeout_seconds)
        except asyncio.CancelledError:
            return
        if self._is_idle():
            log.info("[player %s] idle %ds -> disconnecting", self.tag, self.settings.idle_timeout_seconds)
            await self.stop()

    async def enqueue(self, track: Track) -> None:
        async with self._transition_lock:
            self.queue.append(track)
            log.info("[player %s] enqueued: %s - %s (queue=%d)", self.tag, track.author, track.title, len(self.queue))
            if self.voice and self.voice.is_paused():
                log.info("[player %s] auto-resume on enqueue", self.tag)
                self.voice.resume()
            elif self.voice and not self.voice.is_playing():
                await self._play_next_unlocked()
            self.reconcile_idle()

    async def play_next(self) -> None:
        async with self._transition_lock:
            await self._play_next_unlocked()

    async def _play_next_unlocked(self) -> None:
        if not self.queue:
            self.current = None
            log.info("[player %s] queue empty", self.tag)
            self.reconcile_idle()
            return
        if not self.voice or not self.voice.is_connected():
            log.warning("[player %s] no voice client; aborting", self.tag)
            self.current = None
            return

        track = self.queue.popleft()
        self.current = track
        log.info("[player %s] now playing: %s - %s", self.tag, track.author, track.title)

        log.info("[stream %s] extracting %s", self.tag, track.webpage_url)
        resolved = await self.youtube.resolve_url(track.webpage_url)
        if not resolved:
            log.warning("[stream %s] extract returned nothing; skipping track", self.tag)
            await self._play_next_unlocked()
            return
        _metadata, stream_url = resolved
        log.info("[stream %s] direct URL acquired (len=%d)", self.tag, len(stream_url))

        try:
            source = await discord.FFmpegOpusAudio.from_probe(
                stream_url,
                method="fallback",
                before_options=self.settings.ffmpeg_before_options,
                options=self.settings.ffmpeg_options,
            )
        except Exception as exc:
            log.exception("[ffmpeg %s] source construction failed: %s", self.tag, exc)
            await self._play_next_unlocked()
            return

        log.info("[ffmpeg %s] starting playback", self.tag)
        try:
            self.voice.play(source, after=self._after_play)
        except discord.ClientException as exc:
            log.error("[ffmpeg %s] play() rejected: %s", self.tag, exc)
            await self._play_next_unlocked()
            return
        self.reconcile_idle()

    def _after_play(self, error: Exception | None) -> None:
        if error:
            log.error("[ffmpeg %s] playback error: %r", self.tag, error)
        else:
            log.info("[ffmpeg %s] playback finished cleanly", self.tag)
        asyncio.run_coroutine_threadsafe(self.play_next(), self.bot.loop)

    async def skip(self) -> None:
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            log.info("[player %s] skip requested", self.tag)
            self.voice.stop()

    async def stop(self) -> None:
        log.info("[player %s] stop requested", self.tag)
        task = self._idle_task
        self._idle_task = None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self.queue.clear()
        if self.voice:
            try:
                if self.voice.is_playing():
                    self.voice.stop()
                if self.voice.is_connected():
                    await self.voice.disconnect()
            except Exception as exc:
                log.warning("[player %s] disconnect error: %s", self.tag, exc)
        self.voice = None
        self.current = None
```

Create `bot/siren/player_registry.py`:

```python
from __future__ import annotations

from typing import Any

from .config import Settings
from .player import GuildPlayer
from .youtube import YouTubeService


class PlayerRegistry:
    def __init__(self, bot: Any, youtube: YouTubeService, settings: Settings) -> None:
        self._bot = bot
        self._youtube = youtube
        self._settings = settings
        self._players: dict[int, GuildPlayer] = {}

    def player(self, guild_id: int) -> GuildPlayer:
        player = self._players.get(guild_id)
        if player is None:
            player = GuildPlayer(self._bot, guild_id, self._youtube, self._settings)
            self._players[guild_id] = player
        return player

    def get(self, guild_id: int) -> GuildPlayer | None:
        return self._players.get(guild_id)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:

```bash
PYTHONPATH=bot python3 -m unittest tests.test_player_registry -v
```

Expected: PASS for all tests in `tests.test_player_registry`.

- [ ] **Step 5: Checkpoint**

Run:

```bash
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If git has been initialized before execution, commit with:

```bash
git add bot/siren/player.py bot/siren/player_registry.py tests/test_player_registry.py
git commit -m "refactor: add player services"
```

---

### Task 6: SirenBot And Command Modules

**Files:**
- Create: `bot/siren/bot.py`
- Create: `bot/siren/commands/__init__.py`
- Create: `bot/siren/commands/base.py`
- Create: `bot/siren/commands/play.py`
- Create: `bot/siren/commands/skip.py`
- Create: `bot/siren/commands/stop.py`
- Create: `bot/siren/commands/pause.py`
- Create: `bot/siren/commands/resume.py`
- Create: `bot/siren/commands/queue.py`
- Modify: `tests/test_queue_command.py`

- [ ] **Step 1: Write failing queue-format test**

Create `tests/test_queue_command.py`:

```python
import unittest
from collections import deque

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


class QueueCommandTests(unittest.TestCase):
    def test_format_queue_message_includes_current_and_next_track(self) -> None:
        message = format_queue_message(FakePlayer())
        self.assertIn("**Now playing:** Artist - Current `[3:05]`", message)
        self.assertIn("**Up next (1):**", message)
        self.assertIn("`1.` Other - Next `[1:01]`", message)
```

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
PYTHONPATH=bot python3 -m unittest tests.test_queue_command -v
```

Expected: FAIL with missing `siren.commands.queue`.

- [ ] **Step 3: Implement SirenBot and command modules**

Create `bot/siren/bot.py`:

```python
from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .config import Settings
from .player_registry import PlayerRegistry
from .resolver import TrackResolver

log = logging.getLogger("siren")


class SirenBot(commands.Bot):
    def __init__(self, settings: Settings, resolver: TrackResolver) -> None:
        intents = discord.Intents.default()
        intents.message_content = False
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)
        self.settings = settings
        self.resolver = resolver
        self.players: PlayerRegistry | None = None

    def attach_players(self, players: PlayerRegistry) -> None:
        self.players = players

    async def setup_hook(self) -> None:
        for guild_id in self.settings.guild_ids:
            guild = discord.Object(id=guild_id)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            log.info("Synced commands to guild %s", guild_id)

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, self.user.id if self.user else "?")

    async def on_voice_state_update(self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState) -> None:
        if self.user is not None and member.id == self.user.id:
            return
        if self.players is None:
            return
        player = self.players.get(member.guild.id)
        if not player or not player.voice or not player.voice.is_connected():
            return
        bot_channel = player.voice.channel
        if before.channel != bot_channel and after.channel != bot_channel:
            return
        player.reconcile_idle()
```

Create `bot/siren/commands/base.py`:

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord

from ..player import GuildPlayer

if TYPE_CHECKING:
    from ..bot import SirenBot

log = logging.getLogger("siren")


class CommandBase:
    def __init__(self, bot: "SirenBot") -> None:
        self.bot = bot

    async def guild_or_reply(self, interaction: discord.Interaction) -> discord.Guild | None:
        if interaction.guild is None:
            await self._send(interaction, "DMs aren't supported.", ephemeral=True)
            return None
        return interaction.guild

    def player_for(self, guild_id: int) -> GuildPlayer:
        if self.bot.players is None:
            raise RuntimeError("Player registry is not attached")
        return self.bot.players.player(guild_id)

    async def ensure_voice(self, interaction: discord.Interaction) -> GuildPlayer | None:
        guild = await self.guild_or_reply(interaction)
        if guild is None:
            return None
        if not isinstance(interaction.user, discord.Member):
            await self._send(interaction, "DMs aren't supported.", ephemeral=True)
            return None
        if interaction.user.voice is None or interaction.user.voice.channel is None:
            await self._send(interaction, "Join a voice channel first.", ephemeral=True)
            return None

        channel = interaction.user.voice.channel
        player = self.player_for(guild.id)
        if player.voice is None or not player.voice.is_connected():
            log.info("[voice guild=%s] connecting to channel=%s", guild.id, channel.id)
            try:
                player.voice = await channel.connect(self_deaf=True, timeout=30.0)
            except Exception as exc:
                log.exception("[voice guild=%s] connect failed: %s", guild.id, exc)
                await self._send(interaction, f"Voice connect failed: `{exc}`")
                return None
            log.info("[voice guild=%s] connected", guild.id)
        elif player.voice.channel.id != channel.id:
            log.info("[voice guild=%s] moving %s -> %s", guild.id, player.voice.channel.id, channel.id)
            await player.voice.move_to(channel)
        return player

    async def _send(self, interaction: discord.Interaction, message: str, *, ephemeral: bool = False) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=ephemeral)
        else:
            await interaction.response.send_message(message, ephemeral=ephemeral)
```

Create `bot/siren/commands/play.py`:

```python
from __future__ import annotations

import discord
from discord import app_commands

from .base import CommandBase
from ..bot import SirenBot


class PlayCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="play", description="Play a song. URL or 'artist - title'.")
        @app_commands.describe(query="A URL (Spotify/YouTube/SoundCloud) or text search.")
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
```

Create `bot/siren/commands/skip.py`, `stop.py`, `pause.py`, and `resume.py` with one class per file using `CommandBase.guild_or_reply()` instead of assertions. Preserve user-facing responses from `bot/main.py`: `Nothing playing.`, `Skipped.`, `Not connected.`, `Bye.`, `Paused.`, `Not paused.`, `Resumed.`.

Create `bot/siren/commands/queue.py`:

```python
from __future__ import annotations

from typing import Any

import discord

from .base import CommandBase
from ..models import fmt_duration

QUEUE_PREVIEW_LIMIT = 10


def format_queue_message(player: Any) -> str:
    lines: list[str] = []
    if player.current is not None:
        if player.voice and player.voice.is_paused():
            state = "Paused"
        elif player.voice and player.voice.is_playing():
            state = "Now playing"
        else:
            state = "Loading"
        lines.append(f"**{state}:** {player.current.author} - {player.current.title} `[{fmt_duration(player.current.duration_ms)}]`")

    if player.queue:
        lines.append("")
        lines.append(f"**Up next ({len(player.queue)}):**")
        for index, track in enumerate(list(player.queue)[:QUEUE_PREVIEW_LIMIT], start=1):
            lines.append(f"`{index}.` {track.author} - {track.title} `[{fmt_duration(track.duration_ms)}]`")
        remaining = len(player.queue) - QUEUE_PREVIEW_LIMIT
        if remaining > 0:
            lines.append(f"...and {remaining} more")

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

Create `bot/siren/commands/__init__.py`:

```python
from __future__ import annotations

from ..bot import SirenBot
from .pause import PauseCommand
from .play import PlayCommand
from .queue import QueueCommand
from .resume import ResumeCommand
from .skip import SkipCommand
from .stop import StopCommand


def register_commands(bot: SirenBot) -> None:
    for command in (
        PlayCommand(bot),
        SkipCommand(bot),
        StopCommand(bot),
        PauseCommand(bot),
        ResumeCommand(bot),
        QueueCommand(bot),
    ):
        command.register()
```

- [ ] **Step 4: Fill the four simple command modules**

Create `bot/siren/commands/skip.py`:

```python
from __future__ import annotations

import discord

from .base import CommandBase


class SkipCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="skip", description="Skip the current track.")
        async def skip(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if not player.voice or not (player.voice.is_playing() or player.voice.is_paused()):
                await interaction.response.send_message("Nothing playing.", ephemeral=True)
                return
            await player.skip()
            await interaction.response.send_message("Skipped.")
```

Create `bot/siren/commands/stop.py`:

```python
from __future__ import annotations

import discord

from .base import CommandBase



class StopCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="stop", description="Stop and disconnect.")
        async def stop(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if player.voice is None:
                await interaction.response.send_message("Not connected.", ephemeral=True)
                return
            await player.stop()
            await interaction.response.send_message("Bye.")
```

Create `bot/siren/commands/pause.py`:

```python
from __future__ import annotations

import logging

import discord

from .base import CommandBase

log = logging.getLogger("siren")


class PauseCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="pause", description="Pause playback.")
        async def pause(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if not player.voice or not player.voice.is_playing():
                await interaction.response.send_message("Nothing playing.", ephemeral=True)
                return
            player.voice.pause()
            log.info("[player %s] paused", player.tag)
            await interaction.response.send_message("Paused.")
```

Create `bot/siren/commands/resume.py`:

```python
from __future__ import annotations

import logging

import discord

from .base import CommandBase

log = logging.getLogger("siren")


class ResumeCommand(CommandBase):
    def register(self) -> None:
        @self.bot.tree.command(name="resume", description="Resume paused playback.")
        async def resume(interaction: discord.Interaction) -> None:
            guild = await self.guild_or_reply(interaction)
            if guild is None:
                return
            player = self.player_for(guild.id)
            if not player.voice or not player.voice.is_paused():
                await interaction.response.send_message("Not paused.", ephemeral=True)
                return
            player.voice.resume()
            log.info("[player %s] resumed", player.tag)
            await interaction.response.send_message("Resumed.")
```

- [ ] **Step 5: Run queue test and package import checks**

Run:

```bash
PYTHONPATH=bot python3 -m unittest tests.test_queue_command -v
```

Expected: PASS for `tests.test_queue_command`.

Run:

```bash
PYTHONPATH=bot python3 -c "import siren; import siren.bot; import siren.commands"
```

Expected: exit 0 with no output.

- [ ] **Step 6: Checkpoint**

Run:

```bash
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If git has been initialized before execution, commit with:

```bash
git add bot/siren/bot.py bot/siren/commands tests/test_queue_command.py
git commit -m "refactor: split SirenBot commands"
```

---

### Task 7: Application Factory, Entrypoint, Docs, And Full Verification

**Files:**
- Create: `bot/siren/app.py`
- Modify: `bot/main.py`
- Modify: `README.md`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Add the application factory**

Create `bot/siren/app.py`:

```python
from __future__ import annotations

import logging

from .bot import SirenBot
from .commands import register_commands
from .config import Settings, load_settings
from .player_registry import PlayerRegistry
from .resolver import TrackResolver
from .spotify import SpotifyService
from .youtube import YouTubeService


def configure_logging(settings: Settings) -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logging.getLogger("yt_dlp").setLevel(logging.WARNING)


def create_bot(settings: Settings | None = None) -> SirenBot:
    settings = settings or load_settings()
    configure_logging(settings)
    spotify = SpotifyService(settings)
    youtube = YouTubeService(settings)
    resolver = TrackResolver(spotify, youtube)
    bot = SirenBot(settings, resolver)
    players = PlayerRegistry(bot, youtube, settings)
    bot.attach_players(players)
    register_commands(bot)
    return bot
```

- [ ] **Step 2: Replace the monolithic entrypoint**

Replace `bot/main.py` with:

```python
from siren.app import create_bot
from siren.config import ConfigError


def main() -> None:
    try:
        bot = create_bot()
    except ConfigError as exc:
        raise SystemExit(str(exc)) from exc
    bot.run(bot.settings.discord_token, log_handler=None)


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Update README and Docker Compose naming**

Modify `README.md`:

```markdown
# SirenBot - private Discord music bot

discord.py + yt-dlp + Spotify metadata. Built to actually find the track you asked for.
```

In the remaining checklist, keep the existing feature status accurate:

```markdown
- [x] Smart resolver (Spotify-anchored, duration scoring, lyric/sped-up rejection)
- [x] Drop Lavalink - native voice + yt-dlp
- [x] `/queue`, `/pause`, `/resume`
- [x] Auto-leave when channel empty
- [ ] Resolution cache in SQLite
- [ ] `/nowplaying`, `/seek`, `/volume`
- [ ] Persistent now-playing embed with buttons
- [ ] Queue persistence across restart
- [ ] Filters: bassboost, nightcore, slowed (ffmpeg `-af`)
```

Modify `docker-compose.yml`:

```yaml
container_name: siren-bot
```

- [ ] **Step 4: Run unit tests**

Run:

```bash
PYTHONPATH=bot python3 -m unittest discover -s tests -v
```

Expected: PASS for all test modules.

- [ ] **Step 5: Run syntax compilation without workspace pycache**

Run:

```bash
PYTHONPYCACHEPREFIX="/var/folders/z1/hj7cl3756jn651xfjpw3s8lw0000gn/T/opencode/pycache-siren" python3 -m compileall -q bot tests
```

Expected: exit 0 with no output.

- [ ] **Step 6: Verify imports do not require live env until create_bot is called**

Run:

```bash
PYTHONPATH=bot env -u DISCORD_TOKEN -u SPOTIFY_CLIENT_ID -u SPOTIFY_CLIENT_SECRET python3 -c "import siren; import siren.config; import siren.models; print(siren.APP_NAME)"
```

Expected output:

```text
SirenBot
```

- [ ] **Step 7: Verify startup config error is explicit**

Run:

```bash
PYTHONPATH=bot env -u DISCORD_TOKEN -u SPOTIFY_CLIENT_ID -u SPOTIFY_CLIENT_SECRET python3 bot/main.py
```

Expected: exit nonzero with a message that includes `Missing required environment variables: DISCORD_TOKEN, SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET`.

- [ ] **Step 8: Final repository scan**

Run:

```bash
PYTHONPATH=bot python3 -m unittest discover -s tests -v
```

Expected: PASS for all test modules.

Run:

```bash
PYTHONPYCACHEPREFIX="/var/folders/z1/hj7cl3756jn651xfjpw3s8lw0000gn/T/opencode/pycache-siren" python3 -m compileall -q bot tests
```

Expected: exit 0 with no output.

- [ ] **Step 9: Checkpoint**

Run:

```bash
git status --short
```

Expected in the current workspace: `fatal: not a git repository`. If git has been initialized before execution, commit with:

```bash
git add bot/main.py bot/siren/app.py README.md docker-compose.yml
git commit -m "refactor: wire SirenBot application"
```

---

## Self-Review Checklist

Spec coverage:

- `bot/siren/` package split: Tasks 1 through 7.
- Command-per-module layout: Task 6.
- SirenBot naming in code, README, logging, and Docker-visible name: Tasks 1, 6, and 7.
- Small service classes with explicit dependencies: Tasks 2, 3, 4, 5, 6, and 7.
- Tiny `bot/main.py`: Task 7.
- Docker Compose runtime behavior preserved: Task 7 changes only `container_name`.
- Current dependencies preserved: no dependency files are changed.
- Spotify album/playlist URL handling: Tasks 2 and 4.
- Guild assertion removal in commands: Task 6.
- Startup config validation: Tasks 1 and 7.
- Playback transition locking: Task 5.
- README checklist update: Task 7.

Execution notes:

- Use `PYTHONPATH=bot` for local tests because the package lives under `bot/` and is not installed as a wheel.
- If local imports fail because runtime dependencies are missing, install them in a virtual environment with `python3 -m pip install -r bot/requirements.txt`, then rerun the same verification commands.
- Keep live Discord and yt-dlp playback validation manual because credentials and external services are required.

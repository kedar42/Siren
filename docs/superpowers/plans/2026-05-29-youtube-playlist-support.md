# YouTube Playlist Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/play` accept YouTube playlist URLs and enqueue up to 50 playlist tracks in order.

**Architecture:** Add YouTube playlist detection and flat playlist expansion to `YouTubeService`, then have `TrackResolver` return a multi-track `ResolveResult` before the existing direct URL path. Reuse `/play`'s current multi-track enqueue helper.

**Tech Stack:** Python 3.12+, discord.py app commands, yt-dlp flat extraction, unittest.

---

## File Structure

- Modify `bot/siren/youtube.py`: add YouTube playlist URL detection, a playlist result list with metadata, and `tracks_from_playlist_url()`.
- Modify `bot/siren/resolver.py`: detect YouTube playlist URLs before generic direct URL resolution and return a multi-track result with summary text.
- Modify `tests/test_youtube.py`: add unit tests for playlist URL detection, extraction order, skipped entries, and truncation.
- Modify `tests/test_resolver.py`: add resolver tests for YouTube playlist multi-track results and direct single-video regression.

## Task 1: YouTube Playlist Extraction Core

**Files:**
- Modify: `bot/siren/youtube.py`
- Modify: `tests/test_youtube.py`

- [ ] **Step 1: Add failing YouTube playlist extraction tests**

Append these tests to `tests/test_youtube.py` inside `YouTubeServiceTests`:

```python
    async def test_youtube_playlist_url_detection_accepts_playlist_forms(self) -> None:
        from siren.youtube import is_youtube_playlist_url

        self.assertTrue(is_youtube_playlist_url("http://youtube.com/playlist?list=OLAK5uy_example"))
        self.assertTrue(is_youtube_playlist_url("https://www.youtube.com/watch?v=abc123&list=OLAK5uy_example"))
        self.assertTrue(is_youtube_playlist_url("https://music.youtube.com/playlist?list=OLAK5uy_example"))
        self.assertFalse(is_youtube_playlist_url("https://www.youtube.com/watch?v=abc123"))
        self.assertFalse(is_youtube_playlist_url("https://soundcloud.com/artist/playlist?list=abc"))

    async def test_tracks_from_playlist_url_converts_flat_entries_in_order(self) -> None:
        class PlaylistYoutubeDL(FakeYoutubeDL):
            def extract_info(self, target: str, download: bool) -> dict[str, object]:
                return {
                    "entries": [
                        {"title": "First", "uploader": "Artist", "duration": 100, "url": "first-id"},
                        {
                            "title": "Second",
                            "channel": "Channel",
                            "duration": 120,
                            "webpage_url": "https://youtube.test/watch?v=second",
                        },
                    ]
                }

        service = YouTubeService(settings(), ydl_cls=PlaylistYoutubeDL)

        tracks = await service.tracks_from_playlist_url("https://youtube.com/playlist?list=abc")

        self.assertEqual([track.title for track in tracks], ["First", "Second"])
        self.assertEqual([track.author for track in tracks], ["Artist", "Channel"])
        self.assertEqual([track.duration_ms for track in tracks], [100000, 120000])
        self.assertEqual(tracks[0].webpage_url, "https://www.youtube.com/watch?v=first-id")
        self.assertEqual(tracks[1].webpage_url, "https://youtube.test/watch?v=second")
        self.assertFalse(tracks.truncated)
        self.assertEqual(tracks.skipped, 0)
        self.assertFalse(FakeYoutubeDL.calls[-1]["noplaylist"])
        self.assertEqual(FakeYoutubeDL.calls[-1]["extract_flat"], "in_playlist")

    async def test_tracks_from_playlist_url_skips_malformed_entries(self) -> None:
        class MalformedPlaylistYoutubeDL(FakeYoutubeDL):
            def extract_info(self, target: str, download: bool) -> dict[str, object]:
                return {
                    "entries": [
                        {"title": "Good", "uploader": "Artist", "duration": 100, "url": "good-id"},
                        {"title": "Missing URL", "uploader": "Artist", "duration": 100},
                        None,
                        {"title": "Also Good", "uploader": "Artist", "duration": 110, "url": "also-good-id"},
                    ]
                }

        service = YouTubeService(settings(), ydl_cls=MalformedPlaylistYoutubeDL)

        tracks = await service.tracks_from_playlist_url("https://youtube.com/playlist?list=abc")

        self.assertEqual([track.title for track in tracks], ["Good", "Also Good"])
        self.assertEqual(tracks.skipped, 2)

    async def test_tracks_from_playlist_url_caps_usable_tracks_and_marks_truncated(self) -> None:
        class LongPlaylistYoutubeDL(FakeYoutubeDL):
            def extract_info(self, target: str, download: bool) -> dict[str, object]:
                return {
                    "entries": [
                        {"title": f"Track {index}", "uploader": "Artist", "duration": 100, "url": f"id-{index}"}
                        for index in range(52)
                    ]
                }

        service = YouTubeService(settings(), ydl_cls=LongPlaylistYoutubeDL)

        tracks = await service.tracks_from_playlist_url("https://youtube.com/playlist?list=abc")

        self.assertEqual(len(tracks), 50)
        self.assertEqual(tracks[0].title, "Track 0")
        self.assertEqual(tracks[-1].title, "Track 49")
        self.assertTrue(tracks.truncated)
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run: `PYTHONPATH=bot /Users/kedar/Programming/Personal/Siren/.venv/bin/python -m unittest tests.test_youtube -v`

Expected: failures or errors for missing `is_youtube_playlist_url` and missing `tracks_from_playlist_url`.

- [ ] **Step 3: Implement YouTube playlist extraction**

In `bot/siren/youtube.py`, add imports and constants near the top:

```python
from urllib.parse import parse_qs, urlparse

MAX_YOUTUBE_PLAYLIST_TRACKS = 50
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}
```

Add the playlist result class and URL helper above `YouTubeService`:

```python
class YouTubeTrackList(list[Track]):
    def __init__(self, tracks: list[Track] | None = None, *, truncated: bool = False, skipped: int = 0) -> None:
        super().__init__(tracks or [])
        self.truncated = truncated
        self.skipped = skipped


def is_youtube_playlist_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in {"http", "https"}:
        return False
    host = parsed.netloc.lower().split(":", 1)[0]
    if host not in YOUTUBE_HOSTS:
        return False
    return bool((parse_qs(parsed.query).get("list") or [""])[0])
```

Add the async public method to `YouTubeService`:

```python
    async def tracks_from_playlist_url(
        self,
        url: str,
        *,
        limit: int = MAX_YOUTUBE_PLAYLIST_TRACKS,
    ) -> YouTubeTrackList:
        return await asyncio.to_thread(self._playlist_tracks_sync, url, limit)
```

Add the sync extraction method to `YouTubeService`:

```python
    def _playlist_tracks_sync(self, url: str, limit: int = MAX_YOUTUBE_PLAYLIST_TRACKS) -> YouTubeTrackList:
        tracks = YouTubeTrackList()
        if not is_youtube_playlist_url(url):
            return tracks
        options = {
            **self._settings.ytdl_search_options,
            "noplaylist": False,
            "extract_flat": "in_playlist",
        }
        try:
            with self._ydl_cls(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except yt_dlp.utils.DownloadError as exc:
            log.warning("[resolve] yt playlist %r failed: %s", url, exc)
            return tracks

        for entry in (info or {}).get("entries") or []:
            track = self._entry_to_track(entry)
            if track is None:
                tracks.skipped += 1
                continue
            if len(tracks) >= limit:
                tracks.truncated = True
                break
            tracks.append(track)
        return tracks
```

- [ ] **Step 4: Run focused YouTube tests and verify they pass**

Run: `PYTHONPATH=bot /Users/kedar/Programming/Personal/Siren/.venv/bin/python -m unittest tests.test_youtube -v`

Expected: all tests in `tests.test_youtube` pass.

- [ ] **Step 5: Commit YouTube extraction core**

Run:

```bash
git add bot/siren/youtube.py tests/test_youtube.py
git commit -m "feat: expand youtube playlists"
```

## Task 2: Resolver Integration

**Files:**
- Modify: `bot/siren/resolver.py`
- Modify: `tests/test_resolver.py`

- [ ] **Step 1: Add failing resolver tests**

In `tests/test_resolver.py`, add this fake after `MappingYouTube`:

```python
class PlaylistYouTube(FakeYouTube):
    def __init__(self, playlist_tracks: list[Track], *, truncated: bool = False, skipped: int = 0) -> None:
        super().__init__([])
        from siren.youtube import YouTubeTrackList

        self.playlist_tracks = YouTubeTrackList(playlist_tracks, truncated=truncated, skipped=skipped)
        self.playlist_urls: list[str] = []
        self.resolved_urls: list[str] = []

    async def tracks_from_playlist_url(self, url: str):
        self.playlist_urls.append(url)
        return self.playlist_tracks

    async def resolve_url(self, url: str):
        self.resolved_urls.append(url)
        return await super().resolve_url(url)
```

Add these tests inside `ResolverTests`:

```python
    async def test_youtube_playlist_url_returns_multi_track_result(self) -> None:
        tracks = [Track("First", "Artist", 100000, "first-url"), Track("Second", "Artist", 110000, "second-url")]
        youtube = PlaylistYouTube(tracks)
        resolver = TrackResolver(FakeSpotify(anchor=None), youtube)

        result = await resolver.resolve("https://youtube.com/playlist?list=abc")

        self.assertTrue(result.ok)
        self.assertEqual(result.all_tracks, tracks)
        self.assertEqual(result.track, tracks[0])
        self.assertEqual(result.message, "Queued 2 tracks.")
        self.assertEqual(youtube.playlist_urls, ["https://youtube.com/playlist?list=abc"])
        self.assertEqual(youtube.resolved_urls, [])

    async def test_youtube_playlist_summary_reports_cap_and_skipped_entries(self) -> None:
        tracks = [Track(f"Track {index}", "Artist", 100000, f"url-{index}") for index in range(50)]
        resolver = TrackResolver(FakeSpotify(anchor=None), PlaylistYouTube(tracks, truncated=True, skipped=2))

        result = await resolver.resolve("https://music.youtube.com/playlist?list=abc")

        self.assertTrue(result.ok)
        self.assertEqual(len(result.all_tracks), 50)
        self.assertEqual(result.message, "Queued 50 tracks. Playlist limited to first 50 tracks. Skipped 2 tracks that couldn't be resolved.")

    async def test_youtube_playlist_with_no_tracks_returns_clear_result(self) -> None:
        resolver = TrackResolver(FakeSpotify(anchor=None), PlaylistYouTube([]))

        result = await resolver.resolve("https://youtube.com/playlist?list=abc")

        self.assertFalse(result.ok)
        self.assertEqual(result.all_tracks, [])
        self.assertIn("Couldn't resolve", result.message)

    async def test_youtube_direct_video_without_list_stays_single_track_url_resolution(self) -> None:
        youtube = PlaylistYouTube([Track("Playlist", "Artist", 100000, "playlist-url")])
        resolver = TrackResolver(FakeSpotify(anchor=None), youtube)

        result = await resolver.resolve("https://www.youtube.com/watch?v=abc123")

        self.assertTrue(result.ok)
        self.assertEqual(result.track.webpage_url if result.track else None, "https://www.youtube.com/watch?v=abc123")
        self.assertEqual(result.all_tracks, [result.track])
        self.assertEqual(youtube.playlist_urls, [])
        self.assertEqual(youtube.resolved_urls, ["https://www.youtube.com/watch?v=abc123"])
```

- [ ] **Step 2: Run resolver tests and verify they fail**

Run: `PYTHONPATH=bot /Users/kedar/Programming/Personal/Siren/.venv/bin/python -m unittest tests.test_resolver -v`

Expected: failures showing YouTube playlist URLs are going through `resolve_url()` instead of `tracks_from_playlist_url()`.

- [ ] **Step 3: Implement resolver YouTube playlist handling**

Update the import in `bot/siren/resolver.py`:

```python
from .youtube import MAX_YOUTUBE_PLAYLIST_TRACKS, YouTubeService, is_youtube_playlist_url
```

In `TrackResolver.resolve()`, add this branch immediately before the existing `if is_url(query):` branch:

```python
        if is_youtube_playlist_url(query):
            log.info("[resolve] youtube playlist URL -> yt-dlp flat playlist")
            tracks = await self.youtube.tracks_from_playlist_url(query)
            if not tracks:
                log.warning("[resolve] youtube playlist URL did not resolve: %s", query)
                return ResolveResult(message=f"Couldn't resolve `{query}`.")
            message = f"Queued {len(tracks)} {'track' if len(tracks) == 1 else 'tracks'}."
            if getattr(tracks, "truncated", False):
                message += f" Playlist limited to first {MAX_YOUTUBE_PLAYLIST_TRACKS} tracks."
            skipped = int(getattr(tracks, "skipped", 0) or 0)
            if skipped:
                message += f" Skipped {skipped} {'track' if skipped == 1 else 'tracks'} that couldn't be resolved."
            return ResolveResult(track=tracks[0], tracks=list(tracks), message=message)
```

- [ ] **Step 4: Run focused resolver and play tests**

Run: `PYTHONPATH=bot /Users/kedar/Programming/Personal/Siren/.venv/bin/python -m unittest tests.test_resolver tests.test_youtube tests.test_multi_play tests.test_play_command -v`

Expected: all listed tests pass.

- [ ] **Step 5: Commit resolver integration**

Run:

```bash
git add bot/siren/resolver.py tests/test_resolver.py
git commit -m "feat: resolve youtube playlist urls"
```

## Task 3: Full Verification, Review, And Local Deployment

**Files:**
- Modify only if verification or review reveals a defect.

- [ ] **Step 1: Run full unit test suite**

Run: `PYTHONPATH=bot /Users/kedar/Programming/Personal/Siren/.venv/bin/python -m unittest discover -s tests -v`

Expected: output ends with `OK` and reports the full discovered test count.

- [ ] **Step 2: Compile source and tests**

Run: `PYTHONPYCACHEPREFIX=/var/folders/z1/hj7cl3756jn651xfjpw3s8lw0000gn/T/opencode/siren-compileall-cache /Users/kedar/Programming/Personal/Siren/.venv/bin/python -m compileall -q bot tests`

Expected: no output and exit code 0.

- [ ] **Step 3: Validate Compose config without secrets**

Run: `env DISCORD_TOKEN=dummy SPOTIFY_CLIENT_ID=dummy SPOTIFY_CLIENT_SECRET=dummy DISCORD_GUILD_IDS=123456789012345678 LOG_LEVEL=INFO YT_COOKIES_FILE= docker compose --env-file /dev/null config`

Expected: config renders with dummy values and does not read `.env`.

- [ ] **Step 4: Build Docker image**

Run: `docker compose build`

Expected: image builds successfully.

- [ ] **Step 5: Smoke-test Docker image**

Run:

```bash
docker run --rm queue-controls-sources-interactions-bot:latest python -m compileall -q .
docker run --rm queue-controls-sources-interactions-bot:latest python -c 'import siren; import siren.app; import siren.config; import main; print(siren.APP_NAME)'
docker run --rm -e DISCORD_TOKEN=dummy -e SPOTIFY_CLIENT_ID=dummy -e SPOTIFY_CLIENT_SECRET=dummy queue-controls-sources-interactions-bot:latest python -c 'from siren.app import create_bot; bot = create_bot(); print(type(bot).__name__, len(bot.tree.get_commands()))'
sh -c 'if docker run --rm queue-controls-sources-interactions-bot:latest python main.py; then exit 1; else exit 0; fi'
```

Expected: compileall exits 0, imports print `SirenBot`, bot construction prints `SirenBot 11`, and missing-env startup exits nonzero with the missing env message.

- [ ] **Step 6: Request focused code review**

Dispatch a focused review for YouTube playlist URL detection, yt-dlp playlist extraction options, resolver summary messages, direct URL regressions, and tests. Fix Critical and Important findings before continuing.

- [ ] **Step 7: Push branch and update PR**

Run: `git push`

Expected: branch pushes to `origin/feature/queue-controls-sources-interactions` and PR #1 includes the YouTube playlist support commits.

- [ ] **Step 8: Restart local bot with updated feature image**

Run:

```bash
docker stop siren-bot
docker rm siren-bot
docker run -d --name siren-bot --restart unless-stopped --env-file "/Users/kedar/Programming/Personal/Siren/.env" -v "/Users/kedar/Programming/Personal/Siren/bot/data:/app/data" queue-controls-sources-interactions-bot:latest
docker ps --filter name=siren-bot --format '{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.ID}}'
docker inspect siren-bot --format 'container_image_id={{.Image}}\nconfigured_image={{.Config.Image}}\nstarted_at={{.State.StartedAt}}\nrunning={{.State.Running}}'
sleep 5 && docker logs --since 2m --tail 100 siren-bot
```

Expected: container runs `queue-controls-sources-interactions-bot:latest`, image ID matches the latest feature image, logs show command sync, Discord gateway connection, and login as `Siren#8851`.

## Self-Review

- Spec coverage: Task 1 covers YouTube playlist detection, flat extraction, skipped entries, and truncation. Task 2 covers resolver multi-track behavior, summary messages, empty playlists, and direct single-video regression. Task 3 covers verification, review, PR update, and local deployment.
- Placeholder scan: no incomplete markers or vague implementation steps remain. Every code step has concrete code and every verification step has an exact command and expected result.
- Type consistency: `YouTubeTrackList`, `MAX_YOUTUBE_PLAYLIST_TRACKS`, `is_youtube_playlist_url()`, and `tracks_from_playlist_url()` are named consistently across tests, implementation, and resolver integration.

from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import parse_qs, urlparse

import yt_dlp

from .config import Settings
from .models import Track

log = logging.getLogger("siren")

MAX_YOUTUBE_PLAYLIST_TRACKS = 50
YOUTUBE_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}


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


class YouTubeService:
    def __init__(self, settings: Settings, ydl_cls: Any = yt_dlp.YoutubeDL) -> None:
        self._settings = settings
        self._ydl_cls = ydl_cls

    async def search(self, query: str, limit: int = 5) -> list[Track]:
        return await asyncio.to_thread(self._search_sync, query, limit)

    async def resolve_url(self, url: str) -> tuple[Track, str] | None:
        return await asyncio.to_thread(self._resolve_url_sync, url)

    async def tracks_from_playlist_url(
        self,
        url: str,
        *,
        limit: int = MAX_YOUTUBE_PLAYLIST_TRACKS,
    ) -> YouTubeTrackList:
        return await asyncio.to_thread(self._playlist_tracks_sync, url, limit)

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

    def _playlist_tracks_sync(self, url: str, limit: int = MAX_YOUTUBE_PLAYLIST_TRACKS) -> YouTubeTrackList:
        tracks = YouTubeTrackList()
        if not is_youtube_playlist_url(url):
            return tracks
        next_index = 1
        while True:
            remaining = max(limit - len(tracks), 0)
            batch_size = remaining + 1 if remaining else 1
            options = {
                **self._settings.ytdl_search_options,
                "noplaylist": False,
                "extract_flat": "in_playlist",
                "playliststart": next_index,
                "playlistend": next_index + batch_size - 1,
            }
            try:
                with self._ydl_cls(options) as ydl:
                    info = ydl.extract_info(url, download=False)
            except yt_dlp.utils.DownloadError as exc:
                log.warning("[resolve] yt playlist %r failed: %s", url, exc)
                return tracks

            entries = (info or {}).get("entries") or []
            if not entries:
                return tracks
            for entry in entries:
                track = self._entry_to_track(entry)
                if track is None:
                    tracks.skipped += 1
                    continue
                if len(tracks) >= limit:
                    tracks.truncated = True
                    return tracks
                tracks.append(track)
            next_index += len(entries)
            if len(entries) < batch_size:
                return tracks
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
                    if stream_url:
                        break
        if not stream_url:
            log.warning("[stream] no playable URL on %s", url)
            return None
        return track, stream_url

    @staticmethod
    def _entry_to_track(entry: Any) -> Track | None:
        if not entry:
            return None
        duration = entry.get("duration") or 0
        url = YouTubeService._entry_url(entry)
        if not url:
            return None
        return Track(
            title=entry.get("title") or "?",
            author=entry.get("uploader") or entry.get("channel") or "",
            duration_ms=int(duration * 1000) if duration else 0,
            webpage_url=url,
        )

    @staticmethod
    def _entry_url(entry: dict[str, Any]) -> str:
        url = str(entry.get("webpage_url") or entry.get("url") or "")
        if not url:
            return ""
        if url.lower().startswith(("http://", "https://")):
            return url
        return f"https://www.youtube.com/watch?v={url}"

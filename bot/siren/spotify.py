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
MAX_PLAYLIST_TRACKS = 50


class SpotifyTrackList(list[Track]):
    def __init__(self, tracks: list[Track] | None = None, *, truncated: bool = False) -> None:
        super().__init__(tracks or [])
        self.truncated = truncated


class SpotifyService:
    def __init__(self, settings: Settings, client: Any | None = None) -> None:
        self._client = client if client is not None else spotipy.Spotify(
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
        return self._track_lookup(parsed.url)

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

    def _album_tracks(self, album_id: str) -> list[Track]:
        tracks: list[Track] = []
        offset = 0
        while True:
            try:
                response = self._client.album_tracks(album_id, limit=50, offset=offset)
            except Exception as exc:
                log.warning("[resolve] spotify album lookup failed: %s", exc)
                return tracks
            items = (response or {}).get("items", [])
            tracks.extend(self._track_from_obj(item) for item in items if item)
            if not (response or {}).get("next") or not items:
                return tracks
            offset += len(items)

    def _playlist_tracks(self, playlist_id: str, *, playlist_limit: int) -> list[Track]:
        tracks = SpotifyTrackList()
        offset = 0
        while len(tracks) < playlist_limit:
            try:
                response = self._client.playlist_items(
                    playlist_id,
                    limit=min(50, playlist_limit - len(tracks)),
                    offset=offset,
                    additional_types=("track",),
                )
            except Exception as exc:
                log.warning("[resolve] spotify playlist lookup failed: %s", exc)
                return tracks
            items = (response or {}).get("items", [])
            for index, item in enumerate(items):
                spotify_track = (item or {}).get("track")
                if spotify_track:
                    track = self._try_track_from_obj(spotify_track)
                    if track is None:
                        continue
                    tracks.append(track)
                    if len(tracks) >= playlist_limit:
                        tracks.truncated = bool((response or {}).get("next")) or index < len(items) - 1
                        return tracks
            if not (response or {}).get("next") or not items:
                return tracks
            offset += len(items)
        return tracks

    def _try_track_from_obj(self, spotify_track: dict[str, Any]) -> Track | None:
        try:
            return self._track_from_obj(spotify_track)
        except (KeyError, TypeError, ValueError) as exc:
            log.warning("[resolve] skipping malformed spotify playlist track: %s", exc)
            return None

    @staticmethod
    def _track_from_obj(spotify_track: dict[str, Any]) -> Track:
        return Track(
            title=str(spotify_track["name"]),
            author=", ".join(artist["name"] for artist in spotify_track["artists"]) or "",
            duration_ms=int(spotify_track["duration_ms"]),
            webpage_url=str(spotify_track.get("external_urls", {}).get("spotify", "")),
            isrc=(spotify_track.get("external_ids") or {}).get("isrc"),
        )

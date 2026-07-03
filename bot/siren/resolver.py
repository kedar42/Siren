from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .models import Track
from .spotify import MAX_PLAYLIST_TRACKS, SpotifyService, SpotifyUrlKind, UnsupportedSpotifyUrl
from .youtube import MAX_YOUTUBE_PLAYLIST_TRACKS, YouTubeService, is_youtube_playlist_url

log = logging.getLogger("siren")

JUNK_PATTERNS = re.compile(
    r"\b(lyric[s]?|sped[- ]?up|slowed|nightcore|8d|"
    r"bass[- ]?boost(?:ed)?|reverb|karaoke|cover|instrumental)\b",
    re.IGNORECASE,
)
MAX_EXPANDED_RESOLVE_CONCURRENCY = 5


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


URL_LIKE_PREFIXES = (
    "http://",
    "https://",
    "www.",
    "youtube.com/",
    "youtu.be/",
    "m.youtube.com/",
    "music.youtube.com/",
    "open.spotify.com/",
    "spotify.link/",
    "soundcloud.com/",
)


def is_url_like(value: str) -> bool:
    return value.strip().lower().startswith(URL_LIKE_PREFIXES)


def is_url(value: str) -> bool:
    return value.strip().lower().startswith(("http://", "https://"))


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
        if spotify_url:
            try:
                anchors = await asyncio.to_thread(self.spotify.tracks_from_url, query)
            except UnsupportedSpotifyUrl as exc:
                return ResolveResult(message=str(exc))
            if not anchors:
                log.warning("[resolve] spotify URL did not resolve: %s", query)
                return ResolveResult(message=f"Couldn't resolve `{query}`.")
            if len(anchors) == 1:
                self._log_anchor(anchors[0])
                return await self._resolve_anchored(anchors[0], query)

            if spotify_url.kind is SpotifyUrlKind.ALBUM:
                album_result = await self._resolve_album_via_youtube(anchors)
                if album_result is not None:
                    return album_result

            at_playlist_cap = spotify_url.kind is SpotifyUrlKind.PLAYLIST and bool(getattr(anchors, "truncated", False))
            return await self._resolve_anchors(anchors, query, at_playlist_cap=at_playlist_cap)

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

        if is_url(query):
            log.info("[resolve] direct URL -> yt-dlp")
            resolved = await self.youtube.resolve_url(query)
            return ResolveResult(track=resolved[0]) if resolved else ResolveResult(message=f"Couldn't resolve `{query}`.")

        anchor = await asyncio.to_thread(self.spotify.search_track, query)
        if anchor:
            self._log_anchor(anchor)
            return await self._resolve_anchored(anchor, query)

        log.info("[resolve] no spotify anchor; falling back to plain yt search")
        candidates = await self.youtube.search(query, limit=5)
        if not candidates:
            log.warning("[resolve] no candidates for %r", query)
            return ResolveResult(message=f"Couldn't resolve `{query}`.")
        return ResolveResult(track=candidates[0])

    async def autocomplete(self, query: str, *, limit: int = 25) -> list[Track]:
        query = query.strip()
        if not query or is_url_like(query) or self.spotify.parse_url(query):
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
            return ResolveResult(message=f"Found **{anchor.title}** by *{anchor.author}* on Spotify, but couldn't find a matching YouTube video.")

        log.info("[resolve] picked: %s - %s (score=%.2f, url=%s)", best.author, best.title, best_score, best.webpage_url)
        best.isrc = anchor.isrc
        return ResolveResult(track=best)

    async def _resolve_album_via_youtube(self, anchors: list[Track]) -> ResolveResult | None:
        album_name = getattr(anchors, "album_name", "")
        if not album_name:
            return None
        album_artist = getattr(anchors, "album_artist", "")
        search_text = f"{album_artist} {album_name}".strip() if album_artist else album_name

        album_url = await self.youtube.find_album_url(search_text)
        if not album_url:
            log.info("[resolve] no youtube album match for %r", search_text)
            return None

        yt_tracks = await self.youtube.tracks_from_playlist_url(album_url)
        if not yt_tracks:
            log.info("[resolve] youtube album %s had no tracks", album_url)
            return None

        matched, skipped = self._match_album_tracks(anchors, yt_tracks)
        if not matched or len(matched) * 2 < len(anchors):
            log.info(
                "[resolve] youtube album match too weak (%d/%d matched) for %s; falling back to per-track search",
                len(matched),
                len(anchors),
                album_url,
            )
            return None

        log.info("[resolve] matched youtube album %s -> %d/%d tracks", album_url, len(matched), len(anchors))
        message = f"Queued {len(matched)} {'track' if len(matched) == 1 else 'tracks'} from the matching YouTube album."
        if skipped:
            message += f" Skipped {skipped} {'track' if skipped == 1 else 'tracks'} that couldn't be matched."
        return ResolveResult(track=matched[0], tracks=matched, message=message)

    @staticmethod
    def _match_album_tracks(anchors: list[Track], candidates: list[Track]) -> tuple[list[Track], int]:
        used: set[int] = set()
        matched: list[Track] = []
        skipped = 0
        for anchor in anchors:
            best_score = float("-inf")
            best_index = -1
            for index, candidate in enumerate(candidates):
                if index in used:
                    continue
                score = score_candidate(candidate, anchor, has_anchor=True)
                if score > best_score:
                    best_score = score
                    best_index = index
            if best_index == -1 or best_score == float("-inf"):
                skipped += 1
                continue
            used.add(best_index)
            best = candidates[best_index]
            best.isrc = anchor.isrc
            matched.append(best)
        return matched, skipped

    async def _resolve_anchors(
        self,
        anchors: list[Track],
        original_query: str,
        *,
        at_playlist_cap: bool = False,
    ) -> ResolveResult:
        semaphore = asyncio.Semaphore(MAX_EXPANDED_RESOLVE_CONCURRENCY)

        async def resolve_one(anchor: Track) -> ResolveResult:
            self._log_anchor(anchor)
            async with semaphore:
                return await self._resolve_anchored(anchor, original_query)

        results = await asyncio.gather(*(resolve_one(anchor) for anchor in anchors))
        tracks = [result.track for result in results if result.track is not None]

        skipped = len(anchors) - len(tracks)
        if not tracks:
            return ResolveResult(message=f"Couldn't resolve any tracks from `{original_query}`.")

        message = f"Queued {len(tracks)} {'track' if len(tracks) == 1 else 'tracks'}."
        if at_playlist_cap:
            message += f" Playlist limited to first {MAX_PLAYLIST_TRACKS} tracks."
        if skipped:
            message += f" Skipped {skipped} {'track' if skipped == 1 else 'tracks'} that couldn't be resolved."
        return ResolveResult(track=tracks[0], tracks=tracks, message=message)

    @staticmethod
    def _log_anchor(anchor: Track) -> None:
        log.info(
            "[resolve] spotify anchor: %s - %s (isrc=%s, %.1fs)",
            anchor.author,
            anchor.title,
            anchor.isrc,
            anchor.duration_ms / 1000,
        )

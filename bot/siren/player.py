from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque
from collections.abc import Callable
from typing import Any

import discord

from .config import Settings
from .models import Track
from .youtube import YouTubeService

log = logging.getLogger("siren")


class GuildPlayer:
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
        self._voice_clear_requested_for: list[discord.VoiceClient] = []
        self._started_at_monotonic: float | None = None
        self._elapsed_before_pause_ms = 0
        self._paused_at_monotonic: float | None = None

    @property
    def tag(self) -> str:
        return f"guild={self.guild_id}"

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

    async def clear_voice_state(self, expected_voice: discord.VoiceClient | None = None) -> None:
        target_voice = expected_voice if expected_voice is not None else self.voice
        if target_voice is not None and target_voice not in self._voice_clear_requested_for:
            self._voice_clear_requested_for.append(target_voice)
        async with self._transition_lock:
            self._clear_voice_state_unlocked(target_voice)

    def _clear_voice_state_unlocked(self, expected_voice: discord.VoiceClient | None = None) -> None:
        if expected_voice is not None and expected_voice in self._voice_clear_requested_for:
            self._voice_clear_requested_for.remove(expected_voice)
        if expected_voice is not None and self.voice is not expected_voice:
            log.info("[player %s] stale voice cleanup skipped; voice changed", self.tag)
            self.reconcile_idle()
            return
        log.info("[player %s] clearing stale voice state", self.tag)
        self.voice = None
        self.current = None
        self._clear_timing()
        self._playback_generation += 1
        self.reconcile_idle()

    def _voice_changed_during_prepare(self, voice: discord.VoiceClient) -> bool:
        return voice in self._voice_clear_requested_for or self.voice is not voice or not voice.is_connected()

    def _abort_stale_prepare(self) -> None:
        log.info("[player %s] voice changed during playback preparation; aborting track start", self.tag)
        self.current = None
        self._clear_timing()

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
                self.mark_resumed()
            elif self.voice and not self.voice.is_playing():
                await self._play_next_unlocked()
            self.reconcile_idle()

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

    async def play_next(self, completed_generation: int | None = None) -> None:
        async with self._transition_lock:
            if completed_generation is not None and completed_generation != self._playback_generation:
                log.info("[player %s] ignoring stale playback callback", self.tag)
                return
            await self._play_next_unlocked()

    async def _play_next_unlocked(self) -> None:
        while self.queue:
            if not self.voice or not self.voice.is_connected():
                log.warning("[player %s] no voice client; aborting", self.tag)
                self.current = None
                return
            voice = self.voice

            self._clear_timing()
            track = self.queue.popleft()
            self.current = track
            log.info("[player %s] now playing: %s - %s", self.tag, track.author, track.title)

            log.info("[stream %s] extracting %s", self.tag, track.webpage_url)
            try:
                resolved = await self.youtube.resolve_url(track.webpage_url)
            except Exception as exc:
                log.exception("[stream %s] extraction failed: %s", self.tag, exc)
                if self._voice_changed_during_prepare(voice):
                    self._abort_stale_prepare()
                    return
                continue
            if not resolved:
                log.warning("[stream %s] extract returned nothing; skipping track", self.tag)
                if self._voice_changed_during_prepare(voice):
                    self._abort_stale_prepare()
                    return
                continue
            if self._voice_changed_during_prepare(voice):
                self._abort_stale_prepare()
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
                if self._voice_changed_during_prepare(voice):
                    self._abort_stale_prepare()
                    return
                continue
            if self._voice_changed_during_prepare(voice):
                self._abort_stale_prepare()
                return

            log.info("[ffmpeg %s] starting playback", self.tag)
            try:
                self._playback_generation += 1
                generation = self._playback_generation
                voice.play(source, after=lambda error: self._after_play(error, generation))
                self._start_timing()
            except discord.ClientException as exc:
                log.error("[ffmpeg %s] play() rejected: %s", self.tag, exc)
                if self._voice_changed_during_prepare(voice):
                    self._abort_stale_prepare()
                    return
                continue
            self.reconcile_idle()
            return

        self.current = None
        self._clear_timing()
        log.info("[player %s] queue empty", self.tag)
        self.reconcile_idle()

    def _after_play(self, error: Exception | None, generation: int) -> None:
        if error:
            log.error("[ffmpeg %s] playback error: %r", self.tag, error)
            asyncio.run_coroutine_threadsafe(self._handle_playback_error(generation), self.bot.loop)
        else:
            log.info("[ffmpeg %s] playback finished cleanly", self.tag)
            asyncio.run_coroutine_threadsafe(self.play_next(generation), self.bot.loop)

    async def _handle_playback_error(self, completed_generation: int) -> None:
        async with self._transition_lock:
            if completed_generation != self._playback_generation:
                log.info("[player %s] ignoring stale playback error callback", self.tag)
                return
            self.current = None
            self._clear_timing()
            self.reconcile_idle()

    async def skip(self) -> None:
        if self.voice and (self.voice.is_playing() or self.voice.is_paused()):
            log.info("[player %s] skip requested", self.tag)
            self._clear_timing()
            self.voice.stop()

    async def stop(self) -> None:
        async with self._transition_lock:
            await self._stop_unlocked()

    async def _stop_unlocked(self) -> None:
        log.info("[player %s] stop requested", self.tag)
        task = self._idle_task
        self._idle_task = None
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()
        self.queue.clear()
        self._clear_timing()
        self._playback_generation += 1
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

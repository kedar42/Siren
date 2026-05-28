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

import asyncio
import unittest

from siren.commands.play import autocomplete_tracks, tracks_to_choices
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


class SlowResolver:
    async def autocomplete(self, query: str, *, limit: int = 25) -> list[Track]:
        await asyncio.sleep(0.05)
        return [Track("Late", "Artist", 60000, "https://youtu.be/late")]


class PlayCommandAutocompleteAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_autocomplete_tracks_returns_empty_when_timeout_expires(self) -> None:
        tracks = await autocomplete_tracks(SlowResolver(), "query", limit=25, timeout_seconds=0.01)

        self.assertEqual(tracks, [])

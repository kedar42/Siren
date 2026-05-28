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
